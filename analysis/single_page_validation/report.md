# Energy Planner 단일 페이지 구조 검증

- 검증일: 2026-11-04
- 기준: `energy_planner_ivory_reference.html`
- 실행 환경: 로컬 서버, Headless Chrome, CPU Python 가상환경

## 결과

- `/` 응답: PASS(200)
- 제거 경로 `/workspace`, `/dashboard`, `/guide`: PASS(404)
- 필수 섹션 `landing-home`, `upload`, `quality`, `training`, `dashboard`: PASS
- 레거시 `data-page`, Guide, wizard DOM: 없음
- 중복 DOM ID: 없음
- 1440px·390px·320px 수평 페이지 오버플로: 없음
- 주요 표시 버튼 최소 높이: 44px
- Sticky 단계 이동: `#dashboard` 이동 및 활성 단계 표시 PASS
- 브라우저 뒤로 가기: 루트 hash와 상단 위치 복원 PASS
- 브라우저 런타임 예외: 0
- Python 회귀: 49/49 PASS
- JavaScript 문법 및 Python compileall: PASS

## 스크린샷

- `1440x900-cdp.png`
- `390x844-cdp.png`
- `320x844-cdp.png`
- `390x844-dashboard.png`

실제 모델 학습은 수행하지 않았으며 CSV·XGBoost·예측 API 계약과 기존 run은 변경하지 않았다.
