# Energy Planner — Phase 8 및 Phase 7-6 후속 검증 보고서

## 1. 실행 판단

- 기존 Danica 불변 run과 Phase 8 합성 학습 결과가 이미 존재하므로 학습을 반복하지 않았다.
- 기존 Danica·Leon run은 읽기 전용으로 무결성만 검증했다.
- 누락됐던 HTTP 입력 오류와 동시 중복 학습 요청을 보완했다.
- 운영 승격, 추가 Office 학습, Git 작업, 패키지 설치는 수행하지 않았다.

## 2. Phase 8 보완 결과

| 항목 | 결과 |
|---|---|
| 잘못된 timestamp | HTTP 400, `DataContractError` |
| 음수 kWh | HTTP 400, `DataContractError` |
| 장기 상수 구간 | HTTP 200, `WARNING_LONG_CONSTANT_RUN_168H` |
| Train 0분산 | 기존 `FAIL_TRAIN_ZERO_VARIANCE` 차단 유지 |
| 최신 168시간 중 1시간 누락 | 품질 응답 200, `prediction_eligible=false` |
| 동일 건물 동시 중복 학습 | `QUEUED/RUNNING` 작업이 있으면 거부 |
| 실패 작업 | `FAILED`, 자동 재시도 없음 |

화면은 API 오류 문자열과 job 상태를 표시하도록 구현돼 있음을 코드에서 확인했다. 실제 브라우저 접근은 이번 후속 검증에서도 수행하지 않았으므로 데스크톱·모바일 시각 QA와 스크린샷은 **미검증**이다.

## 3. Danica 기존 run 감사

- run ID: `20261030T055947Z_phase7-6_a6-v1`
- 학습 호출 기록: 1회
- 모델: GRU candidate
- manifest 등록 파일 13개 SHA-256: 전부 일치
- 모델·스케일러 로딩 및 저장 run 예측: 기존 검증 PASS
- `active_model.json`: 없음
- Test 기반 재선택: 없음

### 시간대 manifest 감사

| 요구 의미 | 기존 run 기록 | 판정 |
|---|---|---|
| source timezone mode | `bdg2_naive_local_grid_fixed_standard` | 일치 |
| source timezone | 설명 문자열 안에 `US/Eastern` 포함 | 의미상 존재, 값 형식 불일치 |
| feature timezone | `building_timezone=Etc/GMT+5` | 의미상 존재, 별도 필드 없음 |
| DST 적용 | `dst_applied=false` | 일치 |

기존 불변 run의 `source_timezone_metadata`는 정확히 `US/Eastern`만 저장하지 않고 고정 오프셋 설명을 함께 저장한다. 또한 별도 `feature_timezone` 필드 없이 `building_timezone` 필드가 그 역할을 한다. 해시와 계산 결과에는 문제가 없지만 요청된 manifest 스키마와는 완전히 동일하지 않다. 불변 run을 수정하거나 재학습하지 않고 PM 판단 사항으로 남긴다.

## 4. Leon 보호 확인

- 기존 Leon manifest 등록 파일 12개 SHA-256: 전부 일치
- Leon run 수정: 없음
- 운영 활성 모델 포인터: 없음

## 5. 테스트

- 관련 웹 테스트: 13/13 PASS
- 전체 자동 테스트: 36/36 PASS
- Python compileall: PASS
- JavaScript 구문 검사: PASS

`docs/training_spec.md`의 과거 Train 상수 처리 문구가 현재 확정 정책과 충돌해 `FAIL_TRAIN_ZERO_VARIANCE` 사전 차단으로 정정했다.

## 6. PM 판단 필요

1. Danica 기존 run의 시간대 필드가 의미상 충분한지 승인할지 결정
2. 향후 manifest 버전에 명시적 `feature_timezone` 필드를 추가할지 결정
3. 정확한 필드 형식을 위해 Danica 재학습이 필요한지는 별도 승인으로 판단

현재 성능 결과만으로 재학습 또는 운영 승격을 권고하지 않는다.
