# Energy Planner 건물별 XGBoost 학습 명세

최종 갱신: 2026-11-03

## 1. 목적과 범위

건물 한 곳의 시간별 kWh로 향후 24시간을 예측하는 XGBoost 후보를 새로 학습합니다. 기존 GRU run과 모델 파일은 수정하지 않으며 읽기 전용 호환만 유지합니다. 일반 예측 요청은 저장 run을 재사용하고 자동 재학습하지 않습니다.

## 2. 데이터 계약과 자격

- 입력 계약과 시간대 처리는 `data_contract.md`를 따릅니다.
- 품질·기간·결측·Train 0분산 차단은 `data_quality_policy.md`를 따릅니다.
- 90일 미만은 FAIL, 90~179일은 승인된 제한 실험, 180일 이상은 정규 후보입니다.
- Train/Validation/Test는 시간순으로 분리하며 Test 결과로 모델을 재선택하지 않습니다.

## 3. 입력과 타깃

각 표본은 과거 168시간의 다음 6개 피처를 사용합니다.

1. `kwh`
2. `hour_sin`
3. `hour_cos`
4. `weekday_sin`
5. `weekday_cos`
6. `is_weekend`

원본 입력 shape은 `[N, 168, 6]`이며 시간 우선·피처 순서를 유지해 `[N, 1008]`로 펼칩니다. 타깃은 origin 직후 24시간의 kWh `[N, 24]`입니다. 트리 모델에는 별도 표준화를 적용하지 않습니다.

## 4. 모델 구조

24개 horizon마다 독립 `XGBRegressor` 하나를 학습합니다. 다중 출력 실험 API에 의존하지 않아 모델별 조기 종료와 직렬화 형식을 명확히 유지합니다.

| 설정 | 기본값 |
|---|---:|
| objective | `reg:squarederror` |
| eval metric | `mae` |
| tree method | `hist` |
| n estimators | 500 |
| learning rate | 0.05 |
| max depth | 6 |
| min child weight | 1.0 |
| subsample | 0.9 |
| colsample bytree | 0.9 |
| reg alpha / lambda | 0.0 / 1.0 |
| early stopping rounds | 30 |
| seed / n jobs | 42 / 1 |

CPU와 단일 thread를 사용해 반복 실행의 결정성을 우선합니다. 실제 Office 신규 학습은 별도 승인 후 실행합니다.

## 5. 학습과 조기 종료

- Train dense window로 적합하고 Validation dense window MAE로 조기 종료합니다.
- horizon별 `best_iteration`, `stopped_iteration`, `best_validation_mae`를 기록합니다.
- NaN·Inf 학습 지표 또는 출력은 즉시 실패합니다.
- 실패 시 자동 재시도, 하이퍼파라미터 자동 탐색, 다른 seed 재실행을 하지 않습니다.

## 6. 비교와 선택

XGBoost, Last-24h, Last-168h를 동일한 비중복 Validation origin에서 평가합니다.

- baseline MAE 동률은 더 짧은 이력만 필요한 Last-24h를 선택합니다.
- XGBoost는 최우수 baseline보다 MAE가 5% 이상 개선되어야 합니다.
- RMSE와 WAPE는 각각 최우수 baseline보다 5% 초과 악화되면 안 됩니다.
- 비유한 값 또는 음수 예측이 있으면 XGBoost를 선택하지 않습니다.
- Test는 Validation 선택을 동결한 뒤 보고용으로 한 번 평가합니다.

## 7. 산출물

신규 run은 `{artifact_root}/{building_id}/{run_id}/`에 불변 저장합니다.

- `xgboost_models.joblib`: horizon 순서의 24개 회귀기
- `training_config.json`, `training_history.csv`
- `feature_spec.json`, `split_manifest.json`, `evaluation_schedule.json`
- `quality_report.json`, `distribution_report.json`
- `validation_metrics.json`, `test_metrics.json`
- `derived_input_utc.csv`, `manifest.json`

manifest schema는 `xgboost-v1`이며 source shape `[None,168,6]`, model input shape `[None,1008]`, output shape `[None,24]`, 패키지 버전과 파일별 SHA-256을 기록합니다. 같은 run 경로는 덮어쓰지 않습니다.

## 8. 추론

저장된 XGBoost run은 최신 168시간의 연속성과 피처 계약을 검증한 뒤 입력을 동일한 순서로 펼쳐 24개 모델을 호출합니다. 출력은 `[1,24]`, 유한, 비음수여야 하며 자동 clipping하지 않습니다. baseline이 선택된 run은 기존 baseline 추론을 그대로 사용합니다.

## 9. 호환성과 금지 사항

- 기존 `phase8.1-v1` 이하 GRU run은 파일을 수정하지 않고 읽기 전용으로만 로딩합니다.
- 신규 학습은 GRU state dict나 scaler를 생성하지 않습니다.
- Test 결과 기반 재선택, 예측 중 재학습, 자동 승격은 금지합니다.
- BDG2 원본 데이터, 기존 인턴 모델, Leon·Danica run은 변경하지 않습니다.

## 10. 검증 항목

1. `[N,168,6] → [N,1008]` 순서·shape
2. 24개 horizon 모델과 `[N,24]` 출력
3. 동일 seed·입력의 동일 예측
4. 건물별 run 격리와 hash 검증
5. Validation 선택 후 Test 재선택 금지
6. 음수·비유한 XGBoost 예측 승격 차단
7. 최신 168시간 결측 시 추론 차단
8. Train 0분산 시 학습·산출물 저장 전 차단
