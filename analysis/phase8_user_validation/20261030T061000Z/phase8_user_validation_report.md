# Energy Planner — Phase 8 사용자 시나리오 검증 보고서

## 최종 판정

- HTTP·통합 사용자 흐름: **PASS**
- 실제 브라우저 시각 검증: **미검증**
- 합성 데이터 학습 실행: **성공**
- 저장 run 재사용 예측: **PASS**

## HTTP와 CSV 품질 처리

| 시나리오 | HTTP | 결과 |
|---|---:|---|
| 상태 확인 | 200 | ok |
| 정상 180일 CSV | 200 | PASS, 학습 가능 True |
| 90일 CSV | 200 | WARNING, 승인 전 학습 가능 False |
| 90일 명시 승인 | 200 | 학습 가능 True |
| 89일 CSV | 200 | FAIL (`FAIL_LESS_THAN_90_DAYS`), 학습 불가 |
| 상수 180일 CSV | 200 | blocker `['FAIL_TRAIN_ZERO_VARIANCE']` |
| 필수 컬럼 오류 | 400 | `DataContractError` |

## 학습 job과 예측

- job ID: `faef3cee62724ad08b0fae38f924bdee`
- 관찰 상태: `RUNNING, COMPLETED`
- 최종 상태: `COMPLETED`
- 선택 모델: `last_168h`
- Validation 지표 제공: True
- 예측 출력 shape: `[1, 24]`
- 예측 개수: 24
- 총사용량: 506.570856 kWh
- 피크: 26.000000 kWh, `2025-06-30T06:00:00+00:00`
- 추론 중 재학습: False

FAILED 상태는 자동 테스트의 의도적 단일 실패 pipeline으로 검증하며 자동 재시도 횟수가 0임을 확인한다.

## 레이아웃과 브라우저 제한

- HTML/CSS/JS 응답: 200/200/200
- 모바일 media query 존재: True
- 데스크톱·모바일 실제 렌더링: 미검증
- 사유: Windows Computer Use가 현재 Chrome URL을 충분히 신뢰성 있게 확인하지 못해 안전상 중단됨
- 스크린샷: 생성하지 않음

시각 검증을 수행하지 않았으므로 데스크톱·모바일 레이아웃을 PASS로 표시하지 않는다.
