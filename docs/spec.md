# Energy Planner 기술 명세(SPEC)

## 1. 범위와 기준

이 문서는 `docs/prd.md`를 구현하는 현재 로컬 MVP의 기술 구조와 인터페이스를 정의합니다. 데이터 임계값과 XGBoost 상세 정책은 기존 `data_contract.md`, `data_quality_policy.md`, `training_spec.md`를 재정의하지 않고 참조합니다.

## 2. 시스템 구성

| 영역 | 경로 | 상태 |
|---|---|---|
| 데이터 계약·품질 | `backend/app/ml/contracts.py`, `quality.py` | 구현됨 |
| 피처·분할·시퀀스 | `features.py`, `split.py`, `sequences.py` | 구현됨 |
| XGBoost 변환·학습 | `model.py`, `train.py` | 구현됨 |
| baseline·평가 | `baselines.py`, `evaluate.py` | 구현됨 |
| 산출물·추론 | `artifacts.py`, `inference.py` | 구현됨 |
| 웹 서비스 | `backend/app/web/service.py`, `server.py` | 로컬 MVP 구현 |
| 화면 | `frontend/` | 구현됨, 실제 Chrome QA 완료 |
| job 메타데이터 영속화 | `backend/app/web/service.py` | 구현됨 |
| 선택형 AI 해석 | `backend/app/web/ai_analysis.py` | 구현됨, 실제 외부 호출 미검증 |
| 인증·사용자 격리 | 없음 | 미구현 |

## 3. 입력 계약

- 필수 컬럼: `timestamp`, `kwh`
- 한 파일당 건물 한 곳
- `kwh`: 유한한 0 이상 시간 구간 소비량
- 시간축: UTC 환산 후 오름차순, 중복 없음, 1시간 격자
- 결측·원본값 자동 보간 또는 보정 금지
- 웹 업로드 최대 크기: 25MB

입력 계약 실패는 `DataContractError`, 학습·예측 자격 실패는 `EligibilityError`, 산출물 실패는 `ArtifactError`로 구분합니다.

## 4. 시간대 처리

### 4.1 source timezone mode

| 모드 | 입력 | 변환 |
|---|---|---|
| `iana_civil_time` | offset 없는 일반 현지시각 | IANA DST 규칙으로 현지화 후 UTC 변환 |
| `explicit_offset` | ISO 8601 offset 포함 | 입력 offset으로 UTC 변환 |
| `bdg2_naive_local_grid_fixed_standard` | BDG2 offset 없는 연속 격자 | `Etc/GMT±N` 고정 offset으로 UTC 변환 |

BDG2 모드는 실제 민간시각의 DST를 복원하지 않습니다.

### 4.2 시간대 필드

향후 신규 run manifest는 다음 필드를 저장합니다.

- `source_timezone_mode`: 원본 timestamp 해석 방식
- `source_timezone_metadata`: 원본이 선언한 IANA 이름 또는 offset 출처
- `feature_timezone`: 시간·요일 피처를 계산한 시간대
- `building_timezone`: 기존 소비자를 위한 `feature_timezone` 호환 별칭
- `dst_applied`: IANA 민간시각 규칙 적용 여부

신규 저장 시 `feature_timezone == building_timezone`이어야 합니다. 기존 run에 `feature_timezone`이 없으면 loader는 `building_timezone`을 메모리상 fallback으로 사용하며 manifest 파일을 수정하지 않습니다.

## 5. 품질과 학습 자격

1. `validate_and_normalize_frame`이 계약을 검증하고 UTC index를 생성합니다.
2. `diagnose_quality`가 기간·결측·상수·이상치·최신 입력을 계산합니다.
3. `make_split_plan`이 기간별 정책에 따라 시간순 분할을 결정합니다.
4. `diagnose_split_distribution`이 분할별 분포 이동과 Train 0분산을 검사합니다.
5. Train 0분산은 XGBoost 학습 전에 차단합니다.
6. `validate_minimum_samples`가 1,000/168/12/12 기준을 검사합니다.

## 6. 피처와 시퀀스

피처 순서는 고정입니다.

1. `kwh`
2. `hour_sin`
3. `hour_cos`
4. `weekday_sin`
5. `weekday_cos`
6. `is_weekend`

- 입력 shape: `[B,168,6]`
- 출력 shape: `[B,24]`
- 입력: `T-167 ... T`
- 정답: `T+1 ... T+24`
- 미래 실제값을 피처에 포함하지 않습니다.

## 7. 분할과 스케일링

- 90일 미만: FAIL
- 90~179일: 60/15/15일 상당의 제한 실험, 명시 승인 필요
- 180일 이상: 마지막 30일 Test, 직전 30일 Validation, 나머지 Train
- Validation/Test 주요 비교는 24시간 간격의 비중복 평가창을 사용합니다.
- 168×6 입력창은 시간·피처 순서를 보존한 1,008개 열로 펼칩니다.
- 트리 모델에는 별도 입력·타깃 스케일링을 적용하지 않습니다.

## 8. XGBoost 학습

| 설정 | 값 |
|---|---:|
| source/model input | 168×6 / 1,008 |
| output | 24개 독립 horizon 회귀기 |
| objective/eval metric | reg:squarederror / MAE |
| estimators/learning rate | 500 / 0.05 |
| max depth/min child weight | 6 / 1.0 |
| subsample/column sample | 0.9 / 0.9 |
| L1/L2 regularization | 0.0 / 1.0 |
| early stopping | 30 rounds |
| tree method/seed/threads | hist / 42 / 1 |

학습 실패 시 자동 재시도하지 않으며 일반 예측은 학습 함수를 호출하지 않습니다.

## 9. 모델 평가와 선택

- 지표: MAE, RMSE, WAPE, MAPE, peak MAE, peak time error
- 비교 모델: XGBoost, Last-24h, Last-168h
- 선택 입력: Validation 지표만 허용
- XGBoost MAE가 최우수 baseline보다 5% 이상 개선돼야 합니다.
- XGBoost RMSE·WAPE는 최우수 baseline보다 각각 5% 초과 악화되면 안 됩니다.
- 비유한 또는 음수 XGBoost 예측은 후보에서 제외합니다.
- 조건 미충족 시 Validation MAE 최저 baseline을 선택합니다.
- Test는 선택 후 한 번 평가하며 재선택 API에 전달하지 않습니다.

## 10. 산출물 명세

경로: `{artifact_root}/{building_id}/{run_id}/`

주요 파일:

- `manifest.json`
- `training_config.json`, `feature_spec.json`
- `split_manifest.json`, `evaluation_schedule.json`
- `quality_report.json`, `distribution_report.json`
- `validation_metrics.json`, `test_metrics.json`
- `xgboost_models.joblib`
- `training_history.csv`, `derived_input_utc.csv`

manifest는 건물·run·모델·shape·피처·시간대·데이터 해시·파일별 SHA-256·선택 근거·환경·candidate 상태를 기록합니다. 기존 경로가 있으면 저장을 거부합니다.

### 10.1 manifest 버전과 호환성

- 신규 저장 버전: `xgboost-v1`
- 기존 `phase8.1-v1` GRU run은 읽기 전용 추론 호환을 유지합니다.
- 기존 `phase7.4-v1` 및 그 이전 run은 읽기 호환을 유지합니다.
- 기존 파일에 없는 `feature_timezone`은 `building_timezone`으로 fallback합니다.
- fallback은 반환 객체에만 적용하고 원본 manifest를 쓰지 않습니다.
- hash 검증은 fallback보다 먼저 원본 파일 기준으로 유지합니다.

## 11. 추론

1. building ID와 manifest hash를 검증합니다.
2. 최신 168시간의 실제 시간 연속성을 확인합니다.
3. `feature_timezone` 또는 호환 fallback 시간대로 피처를 생성합니다.
4. XGBoost이면 저장된 24개 horizon 모델을 사용하고, baseline이면 과거 관측값을 사용합니다.
5. `[1,24]`, 유한, 비음수 출력을 검사합니다.
6. retrained는 항상 false입니다.

## 12. 로컬 HTTP API

| 메서드·경로 | 기능 |
|---|---|
| `GET /api/health` | 상태 확인 |
| `POST /api/quality` | 계약·품질·학습/예측 자격 |
| `POST /api/training-jobs` | 별도 학습 작업 생성 |
| `GET /api/training-jobs/{job_id}` | 작업 상태·단계 기반 `progress_percent`·지표 조회 |
| `POST /api/predictions/{job_id}` | 완료 run 재사용 예측 |
| `POST /api/analysis-report/{job_id}` | 외부 호출 없는 로컬 정량 분석 보고서 |
| `POST /api/ai-analysis/{job_id}` | 정량 보고서의 선택형 OpenAI 운영 해석 보강 |

동일 건물에 QUEUED/RUNNING 작업이 있으면 중복 학습 요청을 거부합니다. `progress_percent`는 데이터 준비, 24개 예측 시점별 XGBoost 학습, Validation, Test, 산출물 저장의 실제 완료 단계를 0~100 정수로 제공합니다. 공개 job 메타데이터는 `artifacts/web_jobs/_jobs/`에 저장하며 원본 CSV는 저장하지 않습니다. 완료 job은 재시작 후 복구하고, 중단된 QUEUED/RUNNING job은 자동 재학습 없이 FAILED로 복구합니다.

## 13. 화면 동작

이 절은 현재 웹 화면의 단일 기술 구현 기준입니다. 날짜가 붙은 UX 지시서와 `development_progress.md`의 과거 항목이 이 절과 충돌하면 이 절을 우선합니다.

- 프론트엔드는 정적 HTML/CSS/JavaScript 단일 페이지 `/`로 제공합니다.
- `/workspace`, `/dashboard`, `/guide` 별도 화면은 제공하지 않으며 `#upload`, `#quality`, `#training`, `#dashboard` 해시로 섹션을 직접 연결합니다.
- 사용자 제공 Forecast HTML의 아이보리·블루 시각 체계를 따르되, 실제 API 계약·상태 정확성·접근성·반응형 요구사항을 우선합니다.
- 상단 Sticky 4단계 탐색은 현재 섹션을 남색 배경으로, 완료 단계는 짙은 글자와 파란 단계 번호로 구분합니다.

- API의 PASS/WARNING/FAIL, 사유와 학습 자격을 표시합니다.
- 완료 job의 Validation·Test 지표와 선택 모델은 모델 학습 단계에서 표시합니다. 결과 대시보드 상단은 24시간 예상 사용량, 예상 피크, 선택 모델의 과거 Test WAPE를 우선하며 모델명·Validation 비교·학습 기록은 접을 수 있는 상세 결과에서 제공합니다.
- 예측 전에는 빈 KPI·그래프·예시 수치를 숨기고 4단계 준비 상태와 다음 행동을 표시합니다. 실제 예측 성공 후에만 결과 영역을 공개합니다.
- 예측 응답은 건물 시간대, 미래 24개 시각·값과 직전 24개 실측 시각·값을 제공하며 화면은 예측 대상 기간과 데이터 마지막 시점을 건물 시간대로 표시합니다.
- 예측 대시보드는 미래 예측을 파란 점선으로 표시하고, 사용자가 비교를 켜면 직전 24시간 실측을 같은 시간축의 회색 실선으로 겹칩니다. 호버 가이드, 최고점 라벨, 키보드·터치용 시간 선택 슬라이더와 24행 표 대체 표현을 함께 제공합니다.
- 전력 운영 분석 보고서는 로컬 Python이 24시간 합계·피크·직전 24시간 비교·최근 최대 8주 동일 요일·시간 평균·Validation/Test 지표를 계산합니다. 동일 요일 기준선은 시간대별 실제 표본이 2개 미만이면 미확인으로 표시합니다.
- 보고서 그래프는 예측과 동일 요일 실제 기준선을 비교하고 호버·클릭·터치·키보드 슬라이더를 제공합니다. 시간 이동 시뮬레이터는 사용자가 입력한 가상 단가만 사용하며 시간당 kWh와 청구용 최대수요전력 kW를 구분합니다.
- 보고서는 원본 CSV와 API 키를 제외한 독립 실행 HTML로 다운로드할 수 있고, 인쇄 CSS를 적용한 브라우저 PDF 저장을 제공합니다. HTML에는 생성 당시 수치·문장과 작동하는 그래프·시뮬레이터를 포함합니다.
- 홈의 주요 버튼은 예측 전 `CSV로 예측 시작하기`, 결과 생성 후 `예측 결과 보기`로 실제 이동 위치와 문구를 일치시키며 결과 화면에는 `새 CSV로 예측하기` 이동 링크를 제공합니다.
- 별도 Guide 화면 없이 CSV 계약, 품질 진단, 학습·예측과 선택형 AI 해석을 각 단계의 도움말로 제공합니다.
- AI 분석 하단에서 `#upload`로 돌아가 새 CSV 분석을 시작할 수 있습니다.
- 오류는 임의 복구하지 않고 API 사유를 사용자에게 표시합니다.
- 실제 Chrome에서 1440px·390px·320px 단일 페이지 섹션 이동, 학습 중 이동, 완료 job 복구와 저장 예측을 검증했습니다.

### 13.1 OpenAI 해석 경계

- `OPENAI_API_KEY`는 서버 환경변수에서만 읽고 public 응답에는 enabled 상태와 모델명만 제공합니다.
- 로컬 서버 시작 시 Git에서 제외된 루트 `.env`를 선택적으로 읽으며, 프로세스 환경변수가 같은 이름의 `.env` 값보다 우선합니다. `.env.example`에는 형식만 유지하고 실제 키를 저장하지 않습니다.
- Responses API의 strict JSON schema 출력만 허용하며 거부·불완전·비정상 JSON을 실패로 분리합니다. AI는 서버가 만든 evidence ID만 인용하고 문장에 숫자를 생성할 수 없으며, 실제 수치는 로컬 계산 결과만 표시합니다.
- 한 로컬 프로세스에서 job당 최대 3회, 동시 중복 호출은 1회로 제한합니다.
- `store: false`, timeout, 출력 토큰 상한을 적용하며 원본 CSV는 전송하지 않습니다. OpenAI에는 보고서 메타데이터·정량 근거·24개 예측과 실제 동일 요일 기준선만 구조화해 전송합니다.
- 해석 실패는 XGBoost·baseline 수치와 저장 run을 변경하지 않습니다.

## 14. 보안·운영 제한

- 서버 기본 bind: `127.0.0.1`
- public job 응답에서 CSV와 내부 시간대 상태를 제외합니다.
- 인증, CSRF, 영속 실행 queue, 사용자별 권한은 미구현입니다.
- 운영 승격, 배포와 외부 데이터 전송은 별도 승인 대상입니다.

## 15. 검증 요구사항

- 기존 run 로딩과 파일 hash 검증
- 신규 manifest의 `feature_timezone` 저장
- 구 manifest의 fallback 로딩 및 원본 불변 확인
- 시간대 필드 추가 전후 피처·예측 계산 결과 동일성
- 전체 ML·웹 회귀 테스트
- Python compileall과 JavaScript 구문 검사
- 실제 브라우저 QA 결과와 스크린샷 보존
