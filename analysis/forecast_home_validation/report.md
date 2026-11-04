# Forecast Home 적용 및 연결 검증

검증일: 2026-11-04  
환경: Chrome 156 headless, `http://127.0.0.1:8765/`

## 적용 범위

- `energy_planner_forecast_home.html`의 홈 Hero만 기존 통합 페이지에 적용
- 파란색 `Energy`, 남색 `Planner`, 작은 `mini`와 아이보리 배경 적용
- 관측 실선과 미래 점선으로 구성된 장식 곡선 적용
- hover, 클릭·탭 고정, 키보드 Enter/Space, `aria-pressed`, reduced motion 지원
- 기존 CSV 업로드 이후 DOM ID와 API 연결은 유지

## 실제 연결 검증

- 브라우저 파일 입력에 180일 합성 CSV 파일을 실제로 연결
- 데이터 품질 진단: `PASS`
- XGBoost와 Last-24h·Last-168h Validation 비교 및 Test 최종 평가: 완료
- 선택 모델: `last_168h` (주간 패턴이 반복되는 합성 fixture 특성)
- 저장 모델 예측: 완료, 24시간 합계 `574 kWh`
- 대시보드 표시: 실제 예측 결과 태그와 24시간 그래프 확인
- OpenAI 해석: 서버 키 미설정으로 비활성 상태만 검증, 실제 외부 호출은 미검증

## 브라우저 검증

- 최종 Hero·반응형·접근성 재검증: 16/16 PASS
- 1440px, 390px, 320px 제목 잘림 없음
- 모바일 문서 가로 스크롤 없음(단계 탐색 자체의 내부 가로 스크롤은 유지)
- 클릭 및 키보드 곡선 토글 PASS
- reduced motion PASS
- 홈 CTA와 상단 분석·대시보드 링크 PASS
- 런타임 콘솔 오류 0

상세 결과는 `hero_recheck_results.json`, 스크린샷은 `forecast-home-recheck-*.png`와 `forecast-dashboard-1440.png`에 저장했다.

## 회귀 검증

- Python 단위 테스트: 49/49 PASS
- Python compileall: PASS
- JavaScript 문법 검사: PASS
- Web Interface Guidelines 변경 범위 검사: 위반 패턴 없음
