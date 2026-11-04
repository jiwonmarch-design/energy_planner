# Energy Planner 통합 MVP 검증 보고서

검증일: 2026-11-03  
범위: XGBoost 실제 합성 학습, 로컬 웹 전체 흐름, job 복구, 선택형 OpenAI 해석 경계, 반응형 UI

## 1. 최종 상태

| 영역 | 상태 | 근거 |
|---|---|---|
| XGBoost end-to-end | PASS | 기본 설정 500 estimators, 24 horizon 실제 학습·저장·재로딩·추론 |
| 모델 선택 독립성 | PASS | Validation에서 Last-168h 선택, Test로 재선택하지 않음 |
| 로컬 웹 전체 흐름 | PASS | Chrome에서 업로드 → 품질 PASS → 학습 → 저장 run 예측 |
| job 재시작 복구 | PASS | 서버 재시작 후 완료 job 복구, CSV 재업로드·재학습 없이 예측 |
| 반응형 UI | PASS | 1440px, 390px, 320px; 최종 모바일 재검증 16/16 PASS |
| OpenAI 해석 구현 | PARTIAL | mock 4/4 및 키 누락 안전 상태 PASS, 실제 키 호출 미검증 |
| 인증·사용자 격리 | 미구현 | 로컬 단일 사용자 MVP 범위 밖 |

## 2. XGBoost 실제 실행

- 데이터: 생성한 180일 시간별 CSV
- 학습 입력/출력: `[2689,168,6]` → `[2689,24]`
- 학습 시간: 118.79초, 전체 122.37초
- 최대 working set: 약 302.1 MiB
- candidate 저장·24개 모델 재로딩: PASS
- candidate 추론: `[1,24]`, 0.024초, 모두 유한
- 선택 모델 추론: `[1,24]`, 0.030초, `retrained=false`
- 선택 결과: `Last-168h`. 생성 데이터가 정확한 주간 반복 패턴이어서 Validation MAE가 XGBoost보다 작았으며, 승인된 선택 규칙이 정상 적용된 결과입니다.

상세 수치는 [`../xgboost_e2e_validation/results.json`](../xgboost_e2e_validation/results.json)에 보존했습니다.

## 3. 실제 Chrome 사용자 흐름

추가 실제 학습은 1회만 수행했습니다.

- job ID: `fe23f3d76c884a9bb81af29a027179e3`
- run ID: `20261103T060143Z_fe23f3d7`
- 실제 학습 경과: 약 120.2초
- 품질 판정: PASS
- 학습 중 Home/Workspace 이동 후 job 유지: PASS
- 저장 모델 예측: 24개 행, 총 386.6kWh, 최근 7일·시간대·월별 집계 표시 PASS
- 예시 데이터와 실제 예측 결과 구분: PASS
- 서버 재시작 후 완료 job 복구: PASS
- 복구 후 원본 CSV 재전송 없이 `derived_input_utc.csv` 기반 예측: PASS

첫 모바일 캡처에서 Dashboard 작업 버튼과 긴 job 문구가 390px·320px 폭을 넘는 문제를 발견했습니다. 버튼을 단일 열로 배치하고 job chip 줄바꿈을 허용한 뒤 다시 검증했으며 최종 결과는 16/16 PASS입니다. 최초 실패 기록은 수정 이력 보존을 위해 삭제하지 않았습니다.

## 4. OpenAI 해석 안전 경계

- 서버 환경변수 `OPENAI_API_KEY`만 사용하며 health 응답은 enabled 상태와 모델명만 반환합니다.
- 원본 CSV 대신 24개 예측값, 최근 12시간 집계와 기간 통계만 전송합니다.
- Responses API strict JSON schema, `store=false`, timeout, 출력 토큰 상한과 job당 3회 제한을 적용합니다.
- 키 누락, upstream 형식 오류와 호출 제한 테스트는 PASS입니다.
- 현재 키가 설정되지 않아 실제 외부 API 성공 응답은 검증하지 않았습니다. 이 항목은 PASS로 표시하지 않습니다.

## 5. UI·접근성

- Wave Halftone은 코드 기반 SVG이며 기존 Contour SVG는 rollback 자산으로 보존했습니다.
- Guide 직접 URL, 활성 내비게이션, 54px 모바일 터치 대상과 가로 오버플로 없음 확인
- Dashboard 실측 실선/예측 점선, 24행 표, 초점 가능한 예측점과 텍스트 범례 제공
- skip link, 폼 `name`, 이미지 고정 크기, `prefers-reduced-motion` 대응과 명시적 focus outline 보완
- 캡처: `home-wave-1440.png`, `guide-postfix-390.png`, `dashboard-prediction-1440.png`, `dashboard-postfix-390.png`, `dashboard-postfix-320.png`

## 6. 자동 검증

- 웹·AI·route targeted: 25/25 PASS
- 전체 Python 회귀: 48/48 PASS
- Python compileall: PASS
- JavaScript 구문 검사: PASS
- 모바일 수정 후 실제 Chrome: 16/16 PASS
- XGBoost 기본 설정 실제 실행 체크: 12/12 PASS

## 7. 남은 위험과 PM 결정

1. 유효한 사용자 키로 OpenAI 실제 호출·비용·rate limit을 별도 검증해야 합니다.
2. 인증, 사용자별 artifact 접근 통제, CSRF 방어가 없어 외부 배포할 수 없습니다.
3. job 메타데이터는 영속화했지만 실행 queue 자체를 재개하지 않습니다. 중단 job은 의도적으로 FAILED 처리합니다.
4. 업로드·run 보존 기간, 삭제 정책, 운영 승격·롤백 승인이 필요합니다.
5. 실제 고객 데이터와 추가 Office 건물 학습은 별도 승인 전 수행하지 않습니다.

