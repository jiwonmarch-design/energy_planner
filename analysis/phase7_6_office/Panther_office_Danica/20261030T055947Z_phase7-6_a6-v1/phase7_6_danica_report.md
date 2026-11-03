# Energy Planner — Phase 7-6 Panther_office_Danica 최초 학습 보고서

## 최종 판정

- 사전 품질 게이트: **PASS**
- GRU 학습: **성공, 정확히 1회 실행**
- Validation 선택 모델: **gru**
- Test에 의한 재선택: **없음**
- 저장 run 재사용 추론: **PASS**
- 운영 자동 승격: **수행하지 않음**

## 데이터와 시간대

- 건물: `Panther_office_Danica` / Panther / Office
- 메타데이터 시간대: `US/Eastern`
- 원본 로컬 기간: `2017-07-05T00:00:00` ~ `2017-12-31T23:00:00`
- UTC 기간: `2017-07-05T05:00:00+00:00` ~ `2018-01-01T04:00:00+00:00`
- source_timezone_mode: `bdg2_naive_local_grid_fixed_standard`
- 고정 표준시 피처 시간대: `Etc/GMT+5` (UTC-05:00)
- 단위: BDG2 electricity meter_reading 정의에 따른 시간별 구간 kWh

BDG2 원본의 DST 미반영 로컬 격자를 보존하기 위해 실제 IANA DST 변환과 분리했다.

## 품질과 분할

- 예상/관측 시간: 4320 / 4320
- 결측률·최대 연속 결측: 0.000000% / 0시간
- 0값·최대 상수 구간: 0 / 2시간
- IQR 이상치 의심값: 7
- Train: `2017-07-05T05:00:00+00:00` ~ `2017-11-02T05:00:00+00:00`, 2689조합
- Validation: `2017-11-02T05:00:00+00:00` ~ `2017-12-02T05:00:00+00:00`, dense 697 / 비중복 30
- Test: `2017-12-02T05:00:00+00:00` ~ `2018-01-01T05:00:00+00:00`, 비중복 30
- 동결 평가 일정 제외 구간: Validation 0 / Test 0

## Validation 비교

| 모델 | MAE | RMSE | WAPE | 음수 | 비유한 |
|---|---:|---:|---:|---:|---:|
| gru | 0.954479 | 1.448720 | 0.222758 | 0 | 0 |
| last_24h | 1.165822 | 1.908726 | 0.272082 | 0 | 0 |
| last_168h | 1.285947 | 1.946766 | 0.300117 | 0 | 0 |

선택 사유: `GRU_VALIDATION_PROMOTION_RULES_MET`

## 독립 Test 비교

후보는 Validation에서 고정했으며 Test 결과는 보고 및 진단에만 사용했다.

| 모델 | MAE | RMSE | WAPE | 음수 | 비유한 |
|---|---:|---:|---:|---:|---:|
| gru | 1.258125 | 1.807645 | 0.314469 | 0 | 0 |
| last_24h | 1.255344 | 2.117003 | 0.313774 | 0 | 0 |
| last_168h | 1.788051 | 2.564263 | 0.446925 | 0 | 0 |

## 실행 자원과 재사용

- 데이터 사전 점검: 3.918초
- 파이프라인 데이터 준비: 3.006초
- GRU 학습: 62.294초
- 전체 실험: 69.493초
- 최대 working set: 474.3 MiB
- 최적/종료 epoch: 6 / 13
- Early stopping: True
- 저장 run 예측 시간: 0.035363초
- 출력 shape: `[1, 24]`
- 추론 중 재학습: False

## Leon과의 비교

| 건물 | Validation GRU MAE | Test GRU MAE | Test 최저 MAE 모델 |
|---|---:|---:|---|
| Hog_office_Leon | 1.225327 | 1.426505 | Last-168h, 1.313056 |
| Panther_office_Danica | 0.954479 | 1.258125 | Last-24h, 1.255344 |

Danica는 Leon보다 GRU의 절대 MAE가 낮았지만 건물 부하 규모와 분포가 달라 절대 오차만으로 일반화 우위를 단정할 수 없다. 두 건물 모두 Validation에서 GRU가 선택됐으나 Test에서는 baseline의 MAE가 더 낮았다. Danica의 GRU와 Last-24h Test MAE 차이는 약 0.00278kWh로 사실상 매우 작다.

## 제한과 경고

1. 최신 180일 단일 구간·단일 건물 실험이므로 일반화 성능을 입증하지 않는다.
2. IQR 이상치 의심값은 제거하거나 보정하지 않았다.
3. BDG2 고정 표준시 규칙은 일반 사용자 CSV의 IANA/DST 규칙과 다르다.
4. 이 run은 candidate이며 `active_model.json`은 생성하거나 변경하지 않았다.
