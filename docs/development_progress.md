# Energy Planner 개발 진행 기록

최종 갱신: 2026-11-04

## 완료한 작업

- Phase 6 명세 문서
- Phase 7-1 독립 ML 파이프라인과 기존 자동 검증
- Phase 7-2 Leon 실제 단일 학습 실험
- Phase 7-3 Leon 사후 진단과 Maggie 읽기 전용 점검
- Phase 7-4 장기 상수·상태 전환·Train 0분산·분포 이동·시간대 출처 모드 구현
- Phase 7-5 Office 295개 최신 180일 읽기 전용 재점검과 후보 3개 선정
- Phase 8 로컬 웹 MVP: CSV 품질 진단, 학습 job, 모델 지표 표시, 저장 run 예측 연결
- Phase 8 사용자 흐름 HTTP 검증: PASS/WARNING/FAIL, 합성 학습 job, 저장 run 24시간 예측
- Phase 7-6 Panther_office_Danica 실제 단일 학습 및 Leon 비교
- Phase 8·7-6 후속 감사: HTTP 오류·중복 학습 차단 보완, Danica·Leon run SHA-256 재검증
- 문서 정합화: MVP 갱신 및 PRD → SPEC → PLAN 신규 작성
- 미래 run `feature_timezone` 명시와 기존 manifest 메모리 fallback 호환성 구현
- Phase 9 Landing Hero: Figma 인계 명세 기반 Editorial 레이아웃과 SVG Contour 반응형 구현
- Phase 9 디자인 통일: CSV 입력·품질 판정·예측 대시보드를 Editorial Contour 체계로 정리
- Phase 9 페이지 구조: Home `/`, Workspace `/workspace`, Dashboard `/dashboard` History API 분리
- Phase 9 UX 미반영 항목: 선택 파일 카드·교체·취소, 진단 요청 경합 방지, 상태별 품질 패널, 시간 오류 한국어 안내, 시간대 자동완성 대안 구현
- 신규 학습 모델을 GRU에서 XGBoost로 전환: 168×6 입력 flatten, 24개 horizon 회귀기, 신규 artifact·추론·UI·문서 계약 반영
- 기존 GRU run은 수정하지 않고 읽기 전용 추론 호환 경로로 분리
- Workspace 최종 정리: 세로형 3단계 흐름, 서버 자동 건물 ID·시간대 모드 판별, XGBoost 불확정형 진행 표시·재시도·상태 복원·모델 비교 반영
- Workspace 단계형 UI 마무리: 단일 패널 전환, 이전·다음 탐색, 시간순 분할 결과, Workspace 예측 연결, 키보드 포커스와 모션 감소 대응

## 테스트 결과

- ML 전체: 23/23 PASS
- 기존 Phase 7 사례: 15개 유지
- Phase 7-4 신규 사례: 8개
- 웹 서비스 사례: 13개
- 전체 회귀 테스트: 36/36 PASS
- Landing Hero 실제 Chrome 시각 검증: 1440×880, 390×844, 320×844 PASS(스크린샷 및 수평 오버플로 확인)
- 전체 페이지 Chrome 시각 검증: 1440px, 390px, 320px PASS(수평 오버플로 없음, 최소 버튼 높이 44px)
- 합성 180일 CSV 업로드·품질 판정 브라우저 흐름: PASS
- 브라우저 신규 학습·저장 모델 예측 흐름: 미검증(이번 작업에서 추가 학습 미실행)
- 3개 직접 URL·내비게이션·뒤로 가기·화면 상태 유지: PASS
- 신규 라우팅 3개 포함 전체 회귀 테스트: 39/39 PASS
- UX 실제 Chrome 시나리오: 19/19 PASS(업로드 전후, 교체·취소, PASS/WARNING/FAIL, 오류 복구, 요청 경합, 1440/390/320px)
- UX 변경 후 전체 회귀 테스트: 39/39 PASS, JavaScript 문법·Python compileall PASS
- 실제 건물 학습: Panther_office_Danica 1회 성공, 추가 실행 없음
- XGBoost 전환 회귀 테스트: 38 PASS, 1 SKIP(`xgboost` 패키지 미설치로 실제 결정성 학습 미검증)
- XGBoost 전환 Python compileall·JavaScript 문법 검사: PASS
- 기존 Leon GRU run 읽기 전용 재로딩·24시간 추론 호환: PASS(원본 run 수정 없음)
- Workspace/API 변경 회귀 테스트: 41 PASS, 1 SKIP(`xgboost` 미설치)
- Workspace 실제 Chrome 검증: 9/9 PASS(1440px·390px·320px, 단계 전환·180일 CSV 진단·분할 표시·반응형·모션 감소)
- 최신 전체 회귀: 41 PASS, 1 SKIP(`xgboost` 미설치), Python compileall·JavaScript 문법 검사 PASS

## 발견 및 해결

- Maggie 0.0002kWh 3,504시간과 Train 0분산: 학습 전 차단 구현
- 기존 timezone 검사에서 `UTC` IANA 식별자를 거부: 명시 허용으로 수정
- BDG2와 실서비스 DST 처리 혼용 위험: source timezone mode 분리
- raw electricity는 Git LFS pointer만 존재: 0.0002 upstream 원인은 미확정으로 유지
- Danica manifest는 시간대 의미를 보존하지만 `source_timezone_metadata` 값 형식과 별도 `feature_timezone` 필드가 최신 요청과 완전히 일치하지 않음
- 신규 manifest는 `phase8.1-v1`과 `feature_timezone`을 저장하고 기존 Leon·Danica run은 파일 수정 없이 `building_timezone`으로 호환 로딩

## 현재 진행 중

- 통합 구현과 로컬 실제 브라우저 검증 완료, PM 검토 대기
- 실제 OpenAI API 호출은 사용자 키가 없어 미검증 상태

## 남은 작업

- 인증과 사용자별 artifact 격리
- 영속 실행 queue와 중단 작업 재개(현재는 FAILED 복구)
- Danica run의 운영 승격 여부는 PM 검토 후 별도 결정
- 실제 OpenAI API 성공·거부·rate limit 통합 검증

## 사용자 승인 필요

- raw LFS 실파일 확보 또는 외부 다운로드
- 품질 임계값의 장기 운영 정책 확정
- 모델 승격·롤백·보존 기간
- Danica 기존 시간대 manifest 형식 승인 또는 별도 교정 실험 여부
- 유효한 OpenAI API 키를 사용한 제한적 실제 호출 검증 승인

## 다음 세션 시작 위치

PM 검토 후 유효한 사용자 키가 있는 로컬 환경에서 OpenAI 해석을 제한적으로 검증하거나, 인증·사용자별 artifact 격리 설계를 우선 진행한다. 추가 Office 학습과 운영 승격은 수행하지 않는다.

## 2026-11-03 통합 개발 완료 기록

- 승인된 가상환경에 `xgboost 3.4.1` 설치 후 기본 설정 500 estimators·24 horizon 실제 합성 학습 완료
- XGBoost candidate 저장·24개 모델 재로딩·`[1,24]` 추론과 선택 baseline 재사용 추론 PASS
- 완료 job 메타데이터 영속화, 서버 재시작 복구와 원본 CSV 미저장 구현
- 중단된 QUEUED/RUNNING job은 자동 재학습 없이 FAILED로 복구
- 선택형 OpenAI 해석 API 구현: 최소 집계 전송, strict JSON schema, 키 비노출, timeout·호출 제한
- Wave Halftone 랜딩, Guide, 최근 사용량 분석과 24행 예측표를 포함한 Dashboard 구현
- 실제 Chrome 통합 흐름 1회 실행: 품질 PASS → XGBoost 학습 → 저장 run 예측 → 재시작 복구 PASS
- 모바일 Dashboard 오버플로 수정 후 390px·320px 재검증 16/16 PASS
- 자동 테스트 48/48, targeted 25/25, Python compileall, JavaScript 구문 검사 PASS
- 상세 보고서: `analysis/integrated_mvp_validation/report.md`

### 미검증·승인 필요

- `OPENAI_API_KEY` 미설정으로 실제 OpenAI 외부 성공 호출은 미검증(mock·비활성 상태만 PASS)
- 인증·사용자별 artifact 격리·CSRF·영속 실행 queue는 미구현
- 업로드/run 보존·삭제 및 운영 승격·롤백 정책은 PM 결정 필요
- 추가 Office 학습·외부 배포·운영 승격은 수행하지 않음

## 2026-11-03 첨부 HTML 기반 랜딩 교체

- `energy_planner_landing_reference.html`의 파란색 데이터 시각화 랜딩을 Home에 재현
- 포인터 반응형 dot wave, 3단계 분석 미리보기, 샘플 선 그래프·도넛 인터랙션 구현
- 시안의 수치는 `시연용 예시 데이터`와 실제 결과가 아니라는 안내로 명확히 분리
- 주요 CTA를 실제 `/workspace`, `/dashboard` History API 라우트에 연결
- 기존 Workspace·Dashboard·Guide DOM과 CSV·XGBoost·예측 API는 변경하지 않음
- 실제 Chrome 1440px·390px·320px 검증 29/29 PASS, 가로 오버플로 없음
- 전체 Python 회귀 48/48, JavaScript 문법, Python compileall PASS
- 검증 결과: `analysis/landing_reference_validation/browser_results.json`

## 2026-11-03 통합형 인터랙티브 화면 개편

- `energy_planner_integrated_mockup.html`을 기준으로 Home·Workspace·Dashboard를 하나의 스크롤 페이지로 통합
- Guide 탭을 제거하고 CSV 업로드 → 품질 진단 → XGBoost 학습 → 예측 대시보드의 Sticky 4단계 탐색 구현
- `/`, `/workspace`, `/dashboard` 직접 진입과 History API 이동은 유지하며 해당 통합 섹션으로 이동
- 기존 CSV·시간대·품질·학습·기준 모델·Test·예측·OpenAI API 계약과 저장 run은 변경하지 않음
- 시안의 가상 KPI·학습 시뮬레이션은 화면에서 제거하고 실제 결과가 없으면 빈 상태를 표시
- 파일 선택 취소, 실제 품질 API 결과, 학습 상태, 저장 모델 재사용 UI를 기존 로직으로 연결
- 실제 예측 그래프에 포인터 호버 툴팁을 추가하고 44px 터치 타깃·키보드 포커스·reduced motion 지원
- 실제 Headless Chrome 1440px·390px·320px 검증 7/7 PASS, 수평 오버플로 없음
- 합성 180일 CSV의 실제 품질 API PASS 및 파일 삭제 후 상태 무효화 PASS; 신규 모델 학습은 실행하지 않음
- 전체 Python 회귀 48/48 PASS, JavaScript 문법 검사 PASS
- 검증 결과와 스크린샷: `analysis/integrated_ui_validation/`

## 2026-11-03 아이보리 확정 HTML 디자인 적용

- `energy_planner_ivory_reference.html`을 최종 디자인 기준으로 적용
- 전체 배경 `#F8F7F3`, 카드 `#FFFFFF`, 강조색 `#2855DA`, 텍스트·경계 토큰을 시안과 일치시킴
- 데스크톱 Hero 높이 350px, 44×24 Wave Halftone 점 1,056개와 시안의 배치·크기 적용
- 업로드 영역을 파일 선택 카드와 시간대·CSV 도움말 카드의 2열 구조로 재배치
- 품질 진단·XGBoost 학습·예측 대시보드는 실제 API 상태와 빈 상태만 표시하며 가상 KPI는 노출하지 않음
- 실제 예측 선 그래프에 세로 가이드선·시각·kWh 툴팁, 최근 사용량 막대·도넛에 포인터·키보드 툴팁 추가
- 새 CSV 선택·삭제 시 기존 품질·학습·예측 상태 무효화 로직과 기존 API 계약 유지
- 실제 Headless Chrome 1440px·390px·320px 검증 9/9 PASS, 콘솔 오류 0, 수평 페이지 오버플로 없음
- 전체 Python 회귀 48/48 PASS, JavaScript 문법 검사 PASS
- 검증 결과와 스크린샷: `analysis/ivory_reference_validation/`

## 2026-11-04 아이보리 단일 페이지 구조 정합화

- Home·Workspace·Dashboard용 `data-page` 래퍼와 Guide DOM, 단계 전환용 wizard, 가상 랜딩 KPI 코드를 제거
- `/workspace`, `/dashboard`, `/guide` 서버 라우트를 제거하고 `/`의 `#upload`, `#quality`, `#training`, `#dashboard` 섹션 이동으로 통일
- 기존 CSV 품질 진단·XGBoost 학습·저장 run 예측·OpenAI 해석 API와 상태 ID는 유지
- Headless Chrome 1440px·390px·320px에서 필수 5개 섹션, 중복 ID 없음, 콘솔 오류 0, 수평 페이지 오버플로 없음 확인
- Sticky 단계 이동·URL hash·뒤로 가기와 모바일 44px 이상 주요 CTA를 검증
- 전체 Python 회귀 49/49 PASS, JavaScript 문법·Python compileall PASS
- 검증 스크린샷: `analysis/single_page_validation/`

## 2026-11-04 Forecast Home Hero 적용

- `energy_planner_forecast_home.html`을 기준으로 홈 Hero만 교체하고 CSV 업로드 이후 기존 UI·API 연결은 유지
- 파란 `Energy`, 남색 `Planner`, 작은 `mini`, 한글 설명과 아이보리 배경 적용
- 실선 관측 곡선과 점선 미래 곡선을 장식용으로 명시하고 hover·탭·키보드 토글 및 reduced motion 지원
- 180일 합성 CSV를 실제 브라우저 파일 입력으로 연결해 품질 진단 → XGBoost 학습·baseline 비교 → Test 평가 → 저장 모델 24시간 예측 완료
- 최종 Chrome 1440px·390px·320px Hero/반응형/접근성 16/16 PASS, 콘솔 오류 0
- 전체 Python 테스트 49/49, compileall, JavaScript 문법 검사 PASS
- 검증 결과: `analysis/forecast_home_validation/`
- OpenAI 분석은 서버 키 미설정으로 비활성 상태만 검증했으며 실제 외부 호출은 미검증

## 2026-11-04 Forecast Home 전체 디자인 시스템 적용

- `energy_planner_forecast_home.html`의 아이보리·블루 운영 콘솔 형식을 홈부터 업로드, 품질 진단, XGBoost 학습, 예측 대시보드, AI 해석까지 전체 화면에 적용
- 기존 다중 CSS 레이어 대신 `frontend/reference-system.css` 단일 디자인 시스템으로 색상, 타이포그래피, 직선형 패널, 상태 표시, 반응형 규칙을 통합
- 기존 CSV 품질 진단, 학습 작업, 저장 모델 예측, OpenAI 선택 기능의 DOM ID와 `/api/*` 계약을 유지하고 실제 서버 연결 확인
- 품질 진단 결과를 섹션 헤더 상태에도 동기화하고, 긴 학습 상태 문구가 320px 화면을 넘지 않도록 줄바꿈 처리
- Chrome 1440px·390px·320px 반응형, 키보드, 44px 터치 영역, reduced motion, 대시보드 6개 패널, 콘솔 오류 0을 UI 17/17 PASS로 확인
- 합성 180일 CSV로 실제 품질 진단, XGBoost·baseline 평가, Validation 선택/Test 독립, 저장 모델 24시간 예측과 25개 그래프 점 렌더링을 확인
- 전체 브라우저·백엔드 연결 검증 21/21 PASS
- 검증 결과와 스크린샷: `analysis/forecast_home_validation/browser_results.json`, `analysis/forecast_home_validation/hero_recheck_results.json`, `analysis/forecast_home_validation/reference-dashboard-empty-1440.png`

## 2026-11-04 Forecast HTML 원본 충실도 재구현

- 사용자 제공 Forecast HTML을 최상위 구현 명세로 두고 데스크톱의 `240px 단계 설명 + 작업 영역` 2열 섹션 구조를 복원
- 원본의 아이보리 배경, 블루·잉크 토큰, 직선형 버튼·패널, Sticky 4단계 탐색, Forecast 곡선 Hero를 기준 치수로 재작성
- 업로드·품질 진단·XGBoost 학습·Validation 비교·예측 KPI·차트·사용 패턴·AI 해석을 원본의 `.section`, `.panel`, `.grid2`, `.grid4` 계층에 배치
- 기존 `/api/quality`, 학습 job, 저장 모델 예측, AI 해석 계약은 변경 없이 원본형 DOM에 연결했으며 백엔드 수정은 불필요
- 원본의 42px 버튼은 접근성 최소 조작 영역을 위해 시각 차이 없이 44px로 보정하고 키보드 포커스·reduced motion을 유지
- 실제 Chrome UI 검증 17/17 PASS, 합성 180일 CSV 전체 백엔드 연결과 1440px·390px·320px 실제 예측 대시보드 검증 23/23 PASS, 콘솔 오류 0
- 검증 결과와 스크린샷: `analysis/forecast_home_validation/browser_results.json`, `analysis/forecast_home_validation/hero_recheck_results.json`, `analysis/forecast_home_validation/forecast-dashboard-1440.png`, `forecast-dashboard-390.png`, `forecast-dashboard-320.png`
- 입력 흐름을 건물 시간대 선택 → CSV 업로드 순서로 변경하고 데스크톱 좌측·모바일 상단 배치와 키보드 탐색 순서를 일치시킴
