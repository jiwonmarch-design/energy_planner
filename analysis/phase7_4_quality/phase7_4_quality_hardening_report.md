# Energy Planner — Phase 7-4 데이터 품질 고도화 보고서

## 완료 결과

장기 상수 구간, 지배값, 상태 전환, Train 0분산, 분할별 분포 이동 및 시간대 출처 모드를 ML 파이프라인에 구현했다. 기존 실제 run과 원본 데이터는 변경하지 않았다.

## Maggie 0.0002 조사

- `data/meters/raw/electricity.csv`는 134바이트 Git LFS 포인터이며 실데이터 SHA-256 포인터는 `039d909d...a66418`, 원본 크기 표시는 174,239,039바이트다. 현재 로컬 파일만으로 raw와 cleaned 값을 직접 대조할 수 없다.
- 공식 cleaning notebook `10_Cleaned-dataset.ipynb`는 electricity의 정확한 0값을 NaN으로 바꾸고, 탐지된 이상치를 NaN으로 바꾼다고 명시한다.
- cleaning 코드에서 `0.0002`를 생성하거나 0을 `0.0002`로 대체하는 로직은 발견되지 않았다.
- 따라서 `0.0002`의 최종 원인은 **확인되지 않음**이다. 확인 가능한 범위에서는 cleaning 단계가 새로 만든 값이라는 증거가 없으며, raw 실파일 또는 upstream 수집값 확인이 필요하다.

## 구현 정책

| 진단 | 기준 | 처리 |
|---|---|---|
| 장기 상수 | 동일 kWh 168시간 이상 연속 | WARNING |
| 지배값 | 정확히 같은 값이 유효 관측의 50% 이상 | WARNING |
| 상태 전환 의심 | 장기 상수·지배값 이후 다른 값 존재 | WARNING |
| Train 0분산 | Train kWh가 모두 동일 | 학습 전 FAIL |
| 분포 이동 | 평가 평균이 Train 평균에서 Train 표준편차 1배 이상 | WARNING |
| 최신 입력 | 마지막 168시간 중 하나라도 누락 | 최신 예측 FAIL |

값을 결측으로 바꾸거나 보간·제거하지 않는다.

## 시간대 모드

- `iana_civil_time`: 일반 naive CSV와 IANA DST 규칙
- `explicit_offset`: timestamp 자체의 offset 필수
- `bdg2_naive_local_grid_fixed_standard`: BDG2 naive 격자와 `Etc/GMT±N` 고정 offset

신규 manifest schema `phase7.4-v1`은 `source_timezone_mode`, `source_timezone_metadata`, `dst_applied`를 저장한다. 기존 Phase 7-2 manifest는 수정하지 않으며, 로더는 해당 필드가 없는 기존 run을 호환 처리한다.

## Maggie 재판정

| 항목 | 결과 |
|---|---|
| 전체 품질 | WARNING |
| 장기 상수 | 3,504시간 |
| 지배값 | 0.0002kWh, 81.13% |
| 상태 전환 | 의심 |
| Train 평균 / 분산 | 0.0002kWh / 0분산 |
| Validation 평균 | 0.9099kWh |
| Test 평균 | 4.8499kWh |
| 표본 최소 기준 | PASS, 2,689 / 697 / 30 / 23 |
| 신규 GRU 학습 자격 | **FAIL_TRAIN_ZERO_VARIANCE** |
| 최신 168시간 | FAIL, 1시간 결측 영향 |

표본 수가 충분해도 학습 정보가 없는 Train이므로 Maggie 학습은 차단된다.

## 검증

- 기존 Phase 7 사례 15개를 유지했다. 기존 상수 데이터 사례는 새 정책에 맞춰 정상 차단을 검증하도록 기대 결과를 갱신했다.
- Phase 7-4 신규 사례 8개를 추가했다.
- 전체 23개 테스트: PASS 23, FAIL 0
- 실행: Python 3.12 CPU 환경, `unittest discover`
- 신규 검증: 장기 상수, 상태 전환, 분포 이동, 0분산 선차단, 학습 미호출, explicit offset, BDG2 고정표준시, manifest 출처 보존

## 남은 한계

- raw LFS 실파일이 없어 `0.0002`의 upstream 원인은 확정하지 못했다.
- 분포 이동 1표준편차와 168시간 상수 기준은 MVP 잠정값이다.
- 신규 manifest 필드는 다음 신규 run부터 적용되며 과거 run을 소급 변경하지 않는다.
