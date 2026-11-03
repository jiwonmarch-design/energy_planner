# Energy Planner 기술 명세(SPEC)

## 1. 범위와 기준

이 문서는 `docs/prd.md`를 구현하는 현재 로컬 MVP의 기술 구조와 인터페이스를 정의합니다. 데이터 임계값과 GRU 상세 정책은 기존 `data_contract.md`, `data_quality_policy.md`, `training_spec.md`를 재정의하지 않고 참조합니다.

## 2. 시스템 구성

| 영역 | 경로 | 상태 |
|---|---|---|
| 데이터 계약·품질 | `backend/app/ml/contracts.py`, `quality.py` | 구현됨 |
| 피처·분할·시퀀스 | `features.py`, `split.py`, `sequences.py` | 구현됨 |
| 스케일링·GRU | `scaling.py`, `model.py`, `train.py` | 구현됨 |
| baseline·평가 | `baselines.py`, `evaluate.py` | 구현됨 |
| 산출물·추론 | `artifacts.py`, `inference.py` | 구현됨 |
| 웹 서비스 | `backend/app/web/service.py`, `server.py` | 로컬 MVP 구현 |
| 화면 | `frontend/` | 구현됨, 실제 브라우저 QA 미검증 |
| 영속 job·인증 | 없음 | 미구현 |

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
5. Train 0분산은 scaler·GRU 전에 차단합니다.
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
- 입력·타깃 scaler는 Train 기간의 고유 timestamp만으로 적합합니다.
- Validation/Test는 저장 scaler의 transform만 사용합니다.

## 8. GRU 학습

| 설정 | 값 |
|---|---:|
| input/output | 6 / 24 |
| lookback | 168 |
| hidden size/layers/dropout | 64 / 2 / 0.1 |
| batch size | 64 |
| optimizer/lr | Adam / 0.001 |
| loss | L1Loss |
| max epoch/patience/min delta | 50 / 7 / 0.0001 |
| gradient clipping | 1.0 |
| seed/device | 42 / CPU |

학습 실패 시 자동 재시도하지 않으며 일반 예측은 학습 함수를 호출하지 않습니다.

## 9. 모델 평가와 선택

- 지표: MAE, RMSE, WAPE, MAPE, peak MAE, peak time error
- 비교 모델: GRU, Last-24h, Last-168h
- 선택 입력: Validation 지표만 허용
- GRU MAE가 최우수 baseline보다 5% 이상 개선돼야 합니다.
- GRU RMSE·WAPE는 최우수 baseline보다 각각 5% 초과 악화되면 안 됩니다.
- 비유한 또는 음수 GRU 예측은 후보에서 제외합니다.
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
- `model_state_dict.pth`, `input_scaler.pkl`, `target_scaler.pkl`
- `training_history.csv`, `derived_input_utc.csv`

manifest는 건물·run·모델·shape·피처·시간대·데이터 해시·파일별 SHA-256·선택 근거·환경·candidate 상태를 기록합니다. 기존 경로가 있으면 저장을 거부합니다.

### 10.1 manifest 버전과 호환성

- 신규 저장 버전: `phase8.1-v1`
- 기존 `phase7.4-v1` 및 그 이전 run은 읽기 호환을 유지합니다.
- 기존 파일에 없는 `feature_timezone`은 `building_timezone`으로 fallback합니다.
- fallback은 반환 객체에만 적용하고 원본 manifest를 쓰지 않습니다.
- hash 검증은 fallback보다 먼저 원본 파일 기준으로 유지합니다.

## 11. 추론

1. building ID와 manifest hash를 검증합니다.
2. 최신 168시간의 실제 시간 연속성을 확인합니다.
3. `feature_timezone` 또는 호환 fallback 시간대로 피처를 생성합니다.
4. GRU이면 저장 scaler와 가중치를 사용하고, baseline이면 과거 관측값을 사용합니다.
5. `[1,24]`, 유한, 비음수 출력을 검사합니다.
6. retrained는 항상 false입니다.

## 12. 로컬 HTTP API

| 메서드·경로 | 기능 |
|---|---|
| `GET /api/health` | 상태 확인 |
| `POST /api/quality` | 계약·품질·학습/예측 자격 |
| `POST /api/training-jobs` | 별도 학습 작업 생성 |
| `GET /api/training-jobs/{job_id}` | 작업 상태·지표 조회 |
| `POST /api/predictions/{job_id}` | 완료 run 재사용 예측 |

동일 건물에 QUEUED/RUNNING 작업이 있으면 중복 학습 요청을 거부합니다. job registry는 메모리 전용입니다.

## 13. 화면 동작

- API의 PASS/WARNING/FAIL, 사유와 학습 자격을 표시합니다.
- 완료 job에서 Validation MAE, 선택 모델과 run ID를 표시합니다.
- 예측 전 그래프는 예시임을 표시하고 실제 예측 후 결과로 교체합니다.
- 오류는 임의 복구하지 않고 API 사유를 사용자에게 표시합니다.
- 실제 브라우저 반응형 QA는 미검증입니다.

## 14. 보안·운영 제한

- 서버 기본 bind: `127.0.0.1`
- public job 응답에서 CSV와 내부 시간대 상태를 제외합니다.
- 인증, CSRF, 영속 queue, 사용자별 권한은 미구현입니다.
- 운영 승격, 배포와 외부 데이터 전송은 별도 승인 대상입니다.

## 15. 검증 요구사항

- 기존 run 로딩과 파일 hash 검증
- 신규 manifest의 `feature_timezone` 저장
- 구 manifest의 fallback 로딩 및 원본 불변 확인
- 시간대 필드 추가 전후 피처·예측 계산 결과 동일성
- 전체 ML·웹 회귀 테스트
- Python compileall과 JavaScript 구문 검사
- 실제 브라우저 QA는 별도 환경에서 수행
