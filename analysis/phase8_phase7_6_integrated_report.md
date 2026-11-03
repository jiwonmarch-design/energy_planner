# Energy Planner — Phase 8 사용자 검증 및 Phase 7-6 Danica 실험 통합 보고서

## 1. 최종 판정

- Phase 8 HTTP·통합 사용자 흐름: **PASS**
- 데스크톱·모바일 실제 브라우저 시각 검증: **미검증**
- Panther_office_Danica 사전 품질 게이트: **PASS**
- Danica 실제 GRU 학습: **성공, 정확히 1회**
- Validation 선택 모델: **GRU**
- 저장 run 재사용 추론: **PASS**
- Test 기반 재선택 및 운영 자동 승격: **수행하지 않음**
- 전체 자동 테스트: **32/32 PASS**

## 2. 로컬 웹 사용자 흐름

| 검증 항목 | 결과 |
|---|---|
| 정상 180일 CSV | PASS, 학습 가능 |
| 90일 CSV | WARNING, 명시 승인 전 학습 불가 |
| 90일 명시 승인 | 제한 실험 학습 가능 |
| 89일 CSV | FAIL, `FAIL_LESS_THAN_90_DAYS` |
| 상수 180일 CSV | `FAIL_TRAIN_ZERO_VARIANCE`로 학습 차단 |
| 필수 컬럼 오류 | HTTP 400, `DataContractError` |
| 합성 학습 job | HTTP 202, `RUNNING → COMPLETED` |
| 의도적 pipeline 실패 | `FAILED`, 자동 재시도 없음(자동 테스트) |
| 저장 run 예측 | `[1,24]`, 24개, `retrained=false` |
| 그래프용 총량·피크 | API 응답에서 정상 생성 |

합성 job은 Last-168h를 선택했고 예측 총사용량은 506.570856kWh, 피크는 26.0kWh였다.

HTML, CSS, JavaScript는 모두 HTTP 200으로 제공됐고 모바일 media query도 확인했다. 다만 Windows Computer Use가 현재 Chrome URL을 충분히 신뢰성 있게 확인하지 못해 안전상 중단됐으므로 실제 데스크톱·모바일 렌더링과 스크린샷은 검증하지 않았다.

## 3. Danica 데이터와 품질

- 건물: `Panther_office_Danica` / Office / electricity Yes
- 원본 시간대: `US/Eastern`
- 처리 시간대: `Etc/GMT+5` 고정 표준시(UTC-05:00)
- `source_timezone_mode`: `bdg2_naive_local_grid_fixed_standard`
- 로컬 기간: 2017-07-05 00:00 ~ 2017-12-31 23:00
- UTC 기간: 2017-07-05 05:00 ~ 2018-01-01 04:00
- 관측: 4,320/4,320시간, 결측률 0%, 최대 연속 결측 0시간
- 0값 0개, 최대 상수 구간 2시간, 음수 0개
- IQR 이상치 의심값 7개(제거·보정하지 않음)
- Train/Validation dense/Validation 비중복/Test 비중복: `2689/697/30/30`
- Train 평균·표준편차: 6.012847/2.451178kWh, 0분산 아님

평가 일정은 학습 전에 동결됐으며 제외된 Validation/Test 평가 구간은 없다.

## 4. Danica Validation 성능

| 모델 | MAE | RMSE | WAPE |
|---|---:|---:|---:|
| GRU | 0.954479 | 1.448720 | 0.222758 |
| Last-24h | 1.165822 | 1.908726 | 0.272082 |
| Last-168h | 1.285947 | 1.946766 | 0.300117 |

GRU는 최우수 baseline Last-24h보다 MAE를 18.13% 개선했고 RMSE·WAPE 조건, 비유한·음수 예측 조건을 모두 통과해 Validation 후보로 선택됐다.

## 5. Danica 독립 Test 성능

| 모델 | MAE | RMSE | WAPE |
|---|---:|---:|---:|
| GRU | 1.258125 | 1.807645 | 0.314469 |
| Last-24h | 1.255344 | 2.117003 | 0.313774 |
| Last-168h | 1.788051 | 2.564263 | 0.446925 |

Test MAE는 Last-24h가 GRU보다 약 0.00278kWh 낮았지만, Test 결과로 후보를 바꾸지 않았다. GRU는 Test RMSE가 Last-24h보다 낮다.

## 6. Leon과 Danica 비교

| 건물 | Validation GRU MAE | Test GRU MAE | Test 최저 MAE 모델 |
|---|---:|---:|---|
| Hog_office_Leon | 1.225327 | 1.426505 | Last-168h, 1.313056 |
| Panther_office_Danica | 0.954479 | 1.258125 | Last-24h, 1.255344 |

두 건물 모두 Validation에서는 GRU가 선택됐지만 Test MAE는 baseline이 더 낮았다. 건물별 부하 규모와 분포가 달라 절대 MAE만으로 Danica의 일반화 성능이 더 우수하다고 단정할 수 없다.

## 7. 실행 자원과 저장 run

- Danica 데이터 사전 점검: 3.918초
- 파이프라인 데이터 준비: 3.006초
- GRU 학습: 62.294초
- 전체 실험: 69.493초
- 최대 working set: 474.3MiB
- 최적/종료 epoch: 6/13, early stopping 발생
- 저장 run 예측: 0.035363초
- 재사용 입력/출력: `[1,168,6] → [1,24]`
- 추론 중 재학습: false
- `active_model.json`: 없음

## 8. 회귀 검증

- Python 자동 테스트: 32/32 PASS
- Python compileall: PASS
- JavaScript 구문 검사: PASS
- JSON 산출물 파싱: PASS
- Danica manifest 및 모델·스케일러 재로딩: PASS
- 기존 Leon run 수정: 없음

## 9. 운영 전 필수 위험

1. 실제 브라우저의 데스크톱·모바일 레이아웃과 스크린샷 검증이 남아 있다.
2. 학습 job이 메모리에만 존재해 서버 재시작 시 상태를 복구하지 못한다.
3. 인증, CSRF 방어, 사용자별 데이터·artifact 권한 격리가 없다.
4. BDG2 고정 표준시와 실제 사용자 CSV의 IANA/DST 규칙을 계속 분리해야 한다.
5. Validation 선택과 Test 순위 역전이 Leon과 Danica 모두에서 관찰됐다.
6. 모델 승격·롤백·보존 기간 정책이 확정되지 않았다.

Danica run은 candidate 상태로 유지하며 PM 승인 전 운영 승격 또는 추가 Office 학습을 진행하지 않는다.
