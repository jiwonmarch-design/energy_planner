# Energy Planner — Phase 7-5 Office 건물 검증 준비 보고서

## 범위

BDG2 metadata의 electricity `Yes`, primary use `Office` 296개 중 cleaned electricity에 존재하고 최신 180일을 구성할 수 있는 295개를 읽기 전용으로 점검했다. Phase 7-4 기준을 적용했으며 실제 모델 학습·Test 추론·모델 선택은 수행하지 않았다.

## 전체 결과

- 분석 가능한 Office: 295개
- 결측률 5% 이하, 최대 결측 24시간 이하, 장기 상수 168시간 미만, 지배값 50% 미만, Train 비상수, Validation/Test 비중복 각 12개 이상을 모두 충족: 201개
- Maggie: 장기 상수 및 Train 0분산으로 제외
- Callie: 3,119시간 상수, 0.0007kWh 지배율 72.57%로 제외
- Leon: 기존 실행 건물이므로 신규 후보에서 제외

## 권장 사전 실험 순서

| 순위 | 건물 | 사이트 / 원본 timezone | 180일 평균·최대 | 품질 | 선정 이유 |
|---:|---|---|---:|---|---|
| 1 | `Panther_office_Danica` | Panther / US/Eastern | 5.3895 / 15.2919kWh | 결측 0, 30/30 평가창, Train std 2.4512 | Leon과 비슷한 규모지만 Train→평가 평균이 하락해 다른 변화 방향 검증 가능 |
| 2 | `Hog_office_Alisha` | Hog / US/Central | 12.7181 / 22.9kWh | 결측 0, 30/30, Train std 1.4427 | Leon의 약 2배 평균이고 상대적으로 평탄한 부하 패턴 |
| 3 | `Rat_office_Adele` | Rat / US/Eastern | 437.7509 / 1,161.01kWh | 결측 0, 30/30, Train std 199.7265 | 절대 규모가 크게 다른 대형 Office에서 건물별 scaler·수치 안정성 검증 가능 |

첫 실제 실험은 `Panther_office_Danica`를 권장한다. 데이터 품질이 완전하고 Leon과 규모가 유사해 파이프라인 비교가 해석하기 쉽다. Alisha와 Adele은 후속 확장성 검증 후보로 유지한다.

## 후보별 고정 계획

세 후보 모두 최신 180일 원본 라벨은 2017-07-05 00:00부터 2017-12-31 23:00이다. BDG2 모드로 다음 feature timezone을 사용한다.

- Danica: `US/Eastern` metadata + `Etc/GMT+5` feature timezone
- Alisha: `US/Central` metadata + `Etc/GMT+6` feature timezone
- Adele: `US/Eastern` metadata + `Etc/GMT+5` feature timezone

모든 run은 `source_timezone_mode=bdg2_naive_local_grid_fixed_standard`를 기록해야 한다. 평가 일정은 학습 전에 30일 Validation과 30일 Test의 24시간 비중복 창으로 고정한다.

## 학습 승인 전 체크리스트

1. 후보 ID·Office 용도·electricity 단위 재확인
2. 신규 Phase 7-4 코드와 23개 테스트 통과 상태 확인
3. 원본 파일과 metadata SHA-256 기록
4. 고정표준시 모드와 feature timezone 기록
5. Train/Validation/Test 분포 보고서 저장
6. 모델·scaler·run 디렉터리 불변 저장 및 active model 미변경
7. 단일 건물·단일 학습만 별도 PM 승인 후 실행

## 보류 사항

Maggie와 Callie는 상수값 의미가 확인되고 90일 이상의 실제 변동 Train 구간이 확보되기 전까지 학습 후보로 사용하지 않는다.
