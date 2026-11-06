# Energy Planner 개발 진행 기록

최종 갱신: 2026-11-04

> 이 문서는 시간순 변경 기록입니다. 현재 웹 구현 기준은 `docs/prd.md`의 PRD-F10·F11과 `docs/spec.md`의 `13. 화면 동작`을 따르며, 아래의 오래된 Phase·날짜별 항목은 당시 상태를 설명하는 이력으로만 사용합니다.

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
- Phase 9 최종 화면: 사용자 제공 Forecast HTML 기반 아이보리·블루 디자인 시스템과 Forecast 곡선 Hero 적용
- Phase 9 단일 페이지 구조: `/`의 Hero → CSV 업로드 → 품질 진단 → 모델 학습 → 예측 대시보드, URL hash 섹션 이동
- Phase 9 UX 미반영 항목: 선택 파일 카드·교체·취소, 진단 요청 경합 방지, 상태별 품질 패널, 시간 오류 한국어 안내, 시간대 자동완성 대안 구현
- 신규 학습 모델을 GRU에서 XGBoost로 전환: 168×6 입력 flatten, 24개 horizon 회귀기, 신규 artifact·추론·UI·문서 계약 반영
- 기존 GRU run은 수정하지 않고 읽기 전용 추론 호환 경로로 분리
- 학습 흐름 최종 정리: 시간순 분할, XGBoost 단일 시작 버튼, 실제 작업 단계 기반 0~100% 진행률, 상태 복원과 모델 비교 반영
- 예측 전 결과 패널을 숨기고 4단계 준비 상태를 표시하며, 실제 예측 성공 후에만 KPI·그래프·AI 선택 기능 공개

## 테스트 결과

- ML 전체: 23/23 PASS
- 기존 Phase 7 사례: 15개 유지
- Phase 7-4 신규 사례: 8개
- 웹 서비스 사례: 13개
- 전체 회귀 테스트: 36/36 PASS
- Landing Hero 실제 Chrome 시각 검증: 1440×880, 390×844, 320×844 PASS(스크린샷 및 수평 오버플로 확인)
- 전체 페이지 Chrome 시각 검증: 1440px, 390px, 320px PASS(수평 오버플로 없음, 최소 버튼 높이 44px)
- 합성 180일 CSV 업로드·품질 판정 브라우저 흐름: PASS
- 단일 페이지 실제 CSV 품질 진단·신규 학습·저장 모델 예측·해시 이동 흐름: Chrome 26/26 PASS
- 과거 3페이지 라우팅 단계 전체 회귀 테스트: 39/39 PASS(후속 단일 페이지 구조로 대체됨)
- UX 실제 Chrome 시나리오: 19/19 PASS(업로드 전후, 교체·취소, PASS/WARNING/FAIL, 오류 복구, 요청 경합, 1440/390/320px)
- UX 변경 후 전체 회귀 테스트: 39/39 PASS, JavaScript 문법·Python compileall PASS
- 실제 건물 학습: Panther_office_Danica 1회 성공, 추가 실행 없음
- XGBoost 전환 회귀 테스트: 38 PASS, 1 SKIP(`xgboost` 패키지 미설치로 실제 결정성 학습 미검증)
- XGBoost 전환 Python compileall·JavaScript 문법 검사: PASS
- 기존 Leon GRU run 읽기 전용 재로딩·24시간 추론 호환: PASS(원본 run 수정 없음)
- Workspace/API 변경 회귀 테스트: 41 PASS, 1 SKIP(`xgboost` 미설치)
- 과거 Workspace 화면 실제 Chrome 검증: 9/9 PASS(후속 단일 페이지 구조로 대체됨)
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
- 데이터 품질 진단 상단을 관측 기간·결측률·시간 연속성·학습 적합성 4개 핵심 지표로 정리하고, 하단에 필수 컬럼 및 형식·최소 관측 기간·입력용 168시간 구간·시간순 Train/Validation/Test 분리 상세 판정을 배치
- 실제 Chrome에서 합성 180일 CSV 품질 진단과 전체 백엔드 흐름 23/23 PASS, 품질 진단 전용 스크린샷 `analysis/forecast_home_validation/forecast-quality-1440.png` 확인
- 상세 진단의 성공 상태를 SVG 체크 아이콘과 `통과` 3개·`가능` 1개로 통일하고, 경고·실패 상태 문구는 기존대로 유지
- XGBoost 학습 영역의 재시도·예측 실행·대시보드 이동 버튼을 제거해 `XGBoost 학습 시작` 단일 버튼으로 정리
- 왕복 애니메이션 진행 막대를 실제 데이터 준비·24개 예측 시점별 학습·Validation·Test·저장 단계 기반 퍼센트 진행률로 교체하고, API에 `progress_percent`를 추가
- 실제 Chrome에서 중간 10%와 완료 100%, 단일 학습 버튼, 전체 백엔드 흐름 24/24 PASS 확인; 스크린샷 `analysis/forecast_home_validation/forecast-training-1440.png`
- 상단 4단계 바의 위·아래 테두리와 완료 단계 밑줄, Hero 파란 장식선, 작업 섹션 경계선을 제거하고 활성 단계 배경·세로 구분만 유지
- 단계 바와 본문을 구분하는 중립색 1px 하단 테두리만 복원해 외곽 경계를 명확히 하고, 중복 상단선·파란 장식선·완료 밑줄은 제외

## 2026-11-04 예측 대시보드 준비 상태 개편

- 예측 실행 전의 빈 KPI·차트·모델 패널을 숨기고 CSV 업로드 → 품질 진단 → 모델 학습 → 24시간 예측의 실제 준비 상태와 다음 행동만 표시
- 품질 진단, 학습 진행·실패, 예측 준비 완료에 따라 안내 제목·상태·이동 버튼이 동적으로 바뀌며 실제 예측 성공 후에만 결과 대시보드를 공개
- XGBoost 학습 진행 바를 학습 전부터 0%로 고정 노출하고 진행 중·실패·완료까지 동일 위치에서 서버 진행률을 유지
- `aria-live`, `aria-busy`, `progressbar` 값을 상태와 동기화하고 1440px·390px·320px 수평 오버플로와 결과 전환을 실제 Chrome에서 확인
- 합성 180일 CSV로 품질 진단 → XGBoost·baseline 평가 → Test 독립 평가 → 저장 모델 예측 전체 흐름 25/25 PASS, 콘솔 오류 0
- 검증 결과와 스크린샷: `analysis/forecast_home_validation/browser_results.json`, `forecast-dashboard-empty-1440.png`, `forecast-training-empty-1440.png`, `forecast-dashboard-1440.png`
- 예측 대시보드 하단의 중복 `모델 성능 비교`·`모델 상세 정보` 패널을 제거하고, 모델 평가는 STEP 03 Validation 결과 표와 선택 모델 KPI에서만 제공
- 상단 단계 바의 완료 상태를 초록색 성공 표현 대신 짙은 본문색·파란 단계 번호로 변경하고, AI 분석 하단에 `CSV 업로드로 돌아가기` 보조 이동 링크 추가

## 2026-11-04 웹 구현 문서 기준 정합화

- `docs/spec.md`의 `13. 화면 동작`을 현재 웹 기술 구현의 단일 기준으로 지정하고 PRD → SPEC → PLAN 문서 우선순위를 명시
- README의 3페이지·Guide·예시 그래프 설명, PRD의 과거 Editorial Wave Halftone 기준, SPEC의 예측 전 예시 그래프 정책과 PLAN의 브라우저 QA 미완료 상태를 현재 단일 페이지 구현에 맞게 수정
- 2026-11-02 UX 지시서는 보관 문서로 표시하고 본문은 당시 의사결정 추적을 위해 유지
- 날짜별 진행 기록은 시간순 이력이며 현재 요구사항으로 사용하지 않는다는 해석 규칙 추가

## 2026-11-04 로컬 OpenAI 키 입력 지원

- Git 제외 루트 `.env`에 `OPENAI_API_KEY`를 붙여 넣을 수 있도록 빈 입력 파일 준비
- 공유용 `.env.example` 추가, 실제 키 커밋 금지와 기본 모델·timeout 형식 명시
- 추가 패키지 없이 서버 시작 시 `.env`를 읽고 기존 프로세스 환경변수를 우선하는 로더와 단위 테스트 추가

## 2026-11-04 의사결정 중심 예측 대시보드 개편

- 대시보드 제목·예측 대상 기간·자연어 요약·핵심 3지표·전체 폭 시간별 차트 순으로 정보 구조 재배치
- 실제 예측 시각과 건물 시간대로 대상 기간·마지막 관측 시각을 표시하고, 직전 24시간 대비 증감률과 선택 모델 Test WAPE를 API 결과에서 계산
- 시간별 차트에 y축 눈금, 날짜·시간 x축, 최고점 상시 라벨, 호버 가이드, 전날 비교 토글, 키보드·터치 시간 선택 슬라이더와 표 대체 표현 적용
- 모델명·Validation 비교·학습 기록은 상세 결과로 이동하고 내부 용어를 사용자 문구로 정리
- 완료 job 복구를 사용한 실제 Chrome 검증에서 초기·완료 상태, 상호작용과 1440px·390px·320px 반응형 19/19 PASS

## 2026-11-04 AI 전력 운영 분석 보고서·다운로드

- 외부 호출 없는 `/api/analysis-report/{job_id}`를 추가하고 24시간 합계·피크·직전 24시간 비교·최근 최대 8주 동일 요일/시간 실측 기준선·모델 품질을 Python에서 계산
- OpenAI 응답을 summary/evidence/peak_analysis/comparison/recommendations/limitations/model_quality 구조로 통합하고, 서버 evidence ID 외 근거 및 숫자 생성 응답을 거부하도록 제한
- 보고서 UI에 실제 동일 요일 비교 그래프, 호버·클릭·터치·키보드 슬라이더, 근거 기반 운영 제안, 가상 단가 시간 이동 시뮬레이터, 신뢰도·한계 표시 구현
- 원본 CSV·API 키·로컬 서버 의존성을 제외한 독립 HTML 다운로드와 A4 브라우저 PDF 저장/인쇄 구현
- 실제 완료 job과 OpenAI 호출 검증 성공, 전체 54/54 및 브라우저 14/14 PASS; 독립 HTML 상호작용·모바일 무가로 스크롤·PDF 3페이지 생성 확인
- 검증 산출물: `analysis/ai_report_validation/`

## 2026-11-04 6단계 페이지 구조·AI 보고서 UI 통합

- 단일 스크롤 페이지를 CSV 업로드·품질 진단·모델 학습·24시간 예측·전력 운영 보고서·시간 변경 시뮬레이터의 STEP 01~06으로 통합하고 동일한 2열 헤더·상태·패널 체계 적용
- STEP 05는 예측 완료 후 사용자가 생성 버튼을 누를 때만 기존 OpenAI 백엔드를 호출하며, 임의 진행률 없이 생성 상태를 표시하고 재생성 중 기존 미리보기를 유지
- STEP 06을 보고서에서 완전히 분리해 AI 호출 없이 현재 24시간 예측으로 동작하도록 변경하고, 이동량 상한·가상 단가 비용·변경 전후 피크·2개 선 비교 그래프 구현
- 독립 HTML 다운로드에서 STEP 06 상태와 원본 CSV·API 키를 제외하고 보고서 수치·본문·인터랙티브 비교 그래프만 포함; A4 인쇄 CSS를 STEP 05 보고서 전용으로 정리
- 실제 완료 job과 OpenAI 호출로 Chrome 12/12 PASS, 1440px·390px·320px 및 오프라인 HTML·2페이지 A4 PDF 확인, 전체 테스트 55 PASS·3 subtests PASS
- 검증 산출물: `analysis/six_step_report_validation/`

## 2026-11-04 데이터 업로드·품질 진단 통합

- CSV 업로드와 데이터 품질 진단을 하나의 `STEP 01 데이터 준비`로 통합하고 전체 탐색을 5단계로 정리
- 건물 시간대·CSV 선택 → 진단 실행 → 4개 핵심 지표·상세 판정·시간순 분할 결과를 같은 작업 영역에서 순차 표시
- 진단 전 큰 빈 결과 카드를 낮은 대기 패널로 축소하고, 진단 완료 시 결과 제목으로 초점을 이동해 비동기 상태 변화를 명확히 처리
- PASS 결과에서만 `XGBoost 모델 학습으로 이동`을 제공하고 파일·시간대 변경 시 기존 진단·예측·보고서 상태 무효화 유지
- 실제 Chrome에서 합성 180일 CSV 품질 API 연결, 1440px·390px·320px 반응형, 44px 조작 영역, 콘솔 오류 0을 6/6 PASS로 확인
- 전체 Python 회귀 55 PASS·3 subtests PASS, JavaScript 문법·Python compileall·Git diff 검사 PASS
- 검증 산출물: `analysis/data_preparation_validation/`

## 2026-11-04 AI 전력 운영 의사결정 보고서 강화

- 동일 요일·시간 평균 대비 시간별 절대/상대 편차와 과거 표본 분산·표준편차·최소/최대 범위를 Python에서 계산
- 예측 상위 사분위 기준 연속 고사용 구간, 피크 구간의 24시간 사용량 비중, 직전 24시간 대비 주요 변화 구간과 Validation/Test MAE·WAPE를 구조화
- Python이 과거 범위 이탈·피크 집중·직전 실측 대비 유의미한 변화만 운영 후보로 만들고 변화가 작으면 일반 절전 권고를 생성하지 않도록 처리
- OpenAI Structured Outputs를 핵심 발견 최대 3개 구조로 변경하고 서버 조치 후보의 evidence ID만 사용할 수 있도록 검증
- 보고서 미리보기·독립 HTML·PDF 인쇄에 정량 근거 태그와 Test MAE를 추가하고 기존 5단계 디자인과 다운로드 보안 유지
- 전체 Python 회귀 59 PASS·3 subtests PASS, JavaScript 문법·Python compileall PASS
- 저장된 실제 XGBoost 완료 run과 `gpt-4o-mini` 연동으로 보고서 버전 2, 핵심 발견 2개, 정량 근거 표시, 1440px·390px 반응형을 Chrome 6/6 PASS로 확인
- 검증 산출물: `analysis/ai_decision_report_validation/`

## 2026-11-05 모델 입력 정보 접기·펼치기

- 모델 학습 화면의 `학습 설정` 안내 아래에 기본 접힘 상태의 `모델 입력 정보 보기` 영역 추가
- 서버가 실제 XGBoost 계약의 `FEATURE_NAMES`와 `LOOKBACK`을 제공하고, 화면이 피처 6개·설명·최근 168시간(7일) 입력 구간을 동적으로 표시하도록 연결
- 최근 168시간 모델 입력 구간과 최소 업로드 기간 90일이 서로 다른 조건임을 명시
- 관련 웹 테스트 23 PASS, JavaScript 문법·Python compileall·Git diff 검사 PASS
- 실제 브라우저 시각 검증은 브라우저 연결 호스트 오류로 미검증

## 2026-11-05 OpenAI 추론 강도 환경설정

- 선택형 OpenAI Responses API 요청에 `OPENAI_REASONING_EFFORT`가 설정된 경우 `reasoning.effort`로 전달하도록 연결
- 설정이 없으면 reasoning 필드를 생략해 기존 모델 호출 호환성을 유지
- 로컬 `.env`에 `gpt-6-sol`·`high`를 적용하고 서버 상태 응답에서 로드된 설정 확인
- 전체 Python 회귀 테스트 62 PASS, JavaScript 문법·Python compileall·Git diff 검사 PASS
- 실제 OpenAI 외부 호출과 `gpt-6-sol` 공개 API 사용 가능 여부는 미검증

## 2026-11-05 조치 후보 없는 보고서의 운영 관찰 개선

- 기존 summary·peak_analysis·comparison을 재사용해 첫 화면에 운영 판단·전일/동일 요일 비교·피크의 과거 표본 근거를 함께 표시
- 관찰 근거는 allowed_evidence_ids, 조치 findings는 actionable_evidence_ids로 검증. 조치 임계값·학습 설정·검증 방식 유지
- 조치 없는 경우 반복되던 이유·빈 조치 영역을 정리하고 HTML 복제·인쇄 경로에도 같은 관찰을 포함
- 저장된 2025-10-01 예측에서 전일 -5.009%·동일 요일 -0.466%, 06시 과거 표본 8개·평균 순위 17위 확인. 반복적 고사용 시간 판단은 보류
- 저장 run 재사용·모의 AI 응답 검증, 전체 Python 66 PASS, 렌더러/내보내기 DOM 모의 검사 두 시나리오 PASS
- 실제 OpenAI 호출 0회. 브라우저 URL 확인 오류로 화면·실제 PDF 배치는 미검증
- 상세 결과: `analysis/report_observation_validation/report.md`

## 2026-11-05 AI 보고서 미완료 응답 실패 진단

- 기존 서버 로그에서 예측 200 후 AI 보고서 502 2회 확인. 화면 문구는 API 응답 status 검사에서 발생하며 신규 관찰 필드/근거 검증 이전에 중단됨
- 기존 코드가 status·incomplete reason·error code를 기록하지 않아 세부 원인은 복구 불가. max_output_tokens 원인 여부는 미확정
- 안전한 HTTP/응답 상태·incomplete 사유·토큰 사용량·실패 stage 로깅 및 오류 응답 추가. 원본 CSV·키·AI 본문은 기록하지 않음
- 실제 원인 확인 전 1200토큰/high/20초 유지, 자동 API 재시도 없음
- Python 전체 71 PASS, 프런트 실패 후 예측/기존 보고서 유지 DOM 모의 검사 8 PASS, compileall·JavaScript 문법·diff 검사 PASS
- 실제 API 호출 0회. 원인 확정을 위한 유료 진단 1회는 승인 응답 대기
- 상세 기록: `analysis/report_failure_validation/report.md`

## 2026-11-05 AI 보고서 출력 한도 부족 확인 및 수정

- 사용자가 승인한 진단 1회로 동일 집계 입력·1200/high에서 HTTP 200, incomplete, reason=max_output_tokens 실제 재현. 출력 1200 중 추론 785토큰 사용
- OPENAI_MAX_OUTPUT_TOKENS 환경설정 지원 추가, 로컬 설정 4096 적용. high·20초 timeout 유지, 미설정 기본1200과 상한16384 적용
- 동일 조건 incomplete 모의 재현, 늘린 예산 전달·정상 모의 응답 처리 및 관찰/조치 근거 검증 유지 확인
- 실제 유료 호출은 승인된 1회만 실행. 변경된 4096 설정의 실제 API 완료 여부는 추가 호출하지 않아 미검증
- 전체 Python 74 PASS, 실패 후 예측/기존 보고서 유지 DOM 모의 검사 8 PASS. 서버 재시작 후 health에서 4096/high/20초 적용 확인
- 안전한 실측 메타데이터: `analysis/report_failure_validation/live-diagnostic-once.json`

## 2026-11-05 연속 결측 학습 적합성 진단 개선

- 최대 연속 결측이 정확히 24시간인 경우와 24시간 초과인 경우를 구분하고, 초과만 `WARNING_MAX_GAP_OVER_24_HOURS`로 기록하도록 변경
- 장기 결측만으로 분할을 차단하지 않고, 결측을 채우지 않은 완전한 168시간 입력+24시간 정답 표본을 Train·Validation·Test별로 계산해 1,000/168/12/12 최소 기준으로 학습 적합성을 별도 판정
- 품질 진단과 실제 학습이 같은 표본 준비 함수를 사용하며, 화면에 구간별 유효·제외 수와 Validation 비중복 평가창 수를 표시. 실제 분할 실패와 유효 표본 부족 문구를 분리
- 최근 업로드된 `유큐브_시간별_전력사용량.csv` 읽기 전용 재진단: 최대 결측 72시간, 전체 유효 192시간 창 3,591개, Train 2,537/제외 2,319, Validation dense 503/제외 194·비중복 22/제외 8, Test 비중복 22/제외 8, 품질 WARNING·학습 적합성 PASS
- 전체 Python 회귀 80 PASS, 프런트 품질 계약 DOM 모의 2시나리오 PASS, JavaScript 문법·Python compileall·Git diff 검사 PASS
- 실제 XGBoost 전체 학습과 실제 브라우저 시각 검증은 실행하지 않음

## 2026-11-05 AI 보고서 transport timeout 대응

- 신규 완료 job의 보고서 요청 3회가 모두 HTTP 응답·파싱 전 `transport` 단계에서 502로 종료된 로그 확인
- OpenAI 엔드포인트 DNS·TLS·443 연결은 정상이며 인증 없는 확인 요청이 약 0.14초 만에 401을 반환해 로컬 네트워크 장애는 배제
- `gpt-6-sol`·high·출력 4,096 설정에서 서버 대기 제한 20초가 가장 유력한 원인으로 판단해 로컬 `OPENAI_TIMEOUT_SECONDS`를 허용 상한 60초로 조정
- transport 실패를 timeout/DNS/TLS/connection으로 안전하게 분류하고 제한 시간만 진단에 남기도록 보완. 예외 원문·API 키·보고서 데이터는 기록하지 않음
- 전체 Python 회귀 81 PASS, JavaScript 문법·Python compileall·Git diff 검사 PASS
- 실제 OpenAI API 재호출은 0회. 60초 설정의 실제 보고서 완료 여부는 사용자의 다음 수동 생성 전까지 미검증

## 2026-11-05 비개발자용 전력 운영 보고서 문장 개선

- 서버 계산 문장을 핵심 판단 → 최고 사용 시간 → 확인 사항 → 예측 정확도 → 참고사항 → 기술 지표 순서의 업무 표현으로 변경하고, 전일·동일 요일 비교에 변화율과 절대 변화량을 함께 표시
- 조치 후보·임계값·수치 계산은 유지하면서 총량 변화가 크지 않고 예상 피크가 평소 범위 안인 경우 제목 강도를 낮추고, 과거 예측은 `과거 데이터 검증 결과`로 분리
- AI 프롬프트에 결론 우선·한 문장 한 판단·쉬운 용어·한계 단일화를 추가하고, 서버 수치 문장은 AI가 대체하지 못하도록 유지. allowed/actionable evidence ID 검증 유지
- 미리보기·독립 HTML·PDF 인쇄가 같은 보고서 DOM을 사용하며 기술 지표는 기본 접힘으로 보존. AI 실패 시 로컬 보고서 API로 전환해 같은 기본 문장을 표시
- 저장된 2025-10-01 예측 재검증: 전일 -5.0%(-9,278.4kWh), 최근 8주 같은 요일 -0.5%(-823.5kWh), 오전 6시 7,852.9kWh·평소 범위 안, 조치 후보 0개, 과거 데이터 검증 결과
- 전체 Python 85 PASS, JavaScript 문법 및 모의 DOM 4시나리오 PASS, Chrome 실제 PDF 생성 확인. PDF 페이지 렌더러 부재로 픽셀 단위 시각 검수는 미검증
- 검증 산출물: `analysis/business_report_validation/`

## 2026-11-05 OpenAI 429 시 로컬 보고서 보장

- 사용자 재시도 3건이 모두 OpenAI HTTP 429로 거절됐으며 요청 전 설정·응답 파싱·근거 ID 검증이 아닌 `http_error` 단계에서 실패한 로그 확인
- 기존 안전 로그 허용 목록에 최신 429 과금·한도·속도 제한 코드를 추가. 기존 요청의 실제 세부 코드는 이미 `unknown`으로 기록돼 사후 복구 불가
- AI 호출이 429·타임아웃·미설정으로 실패하거나 로컬 실행당 3회 호출 한도에 도달해도 같은 `/api/ai-analysis` 요청이 서버 정량 보고서를 200으로 반환하도록 보완
- AI 실패 시에도 예측 결과·운영 후보·근거 검증 결과는 유지하며 추가 유료 API 호출 없이 모의 429와 호출 한도 초과를 검증
- 전체 Python 87 PASS, JavaScript 문법·보고서 DOM 모의 4시나리오 PASS

## 2026-11-05 예측 평가 지표 표시 및 학습 상세 접기

- 기존 저장 지표의 MAE·WAPE·RMSE·피크 크기 오차·피크 시간 오차를 학습 Validation/Test 비교표와 선택 모델 Test 상세에 연결하고, 예측 상단 카드를 총량·피크 시간·피크 사용량으로 정리
- 운영 보고서 서버 응답에 RMSE와 두 피크 오차를 연결하고 과거 Test MAE·피크 오차를 쉬운 문장으로 표시하며, 미리보기·HTML·PDF가 같은 DOM 수치와 문장을 재사용하도록 유지
- 모델 학습 완료 시 `학습 완료 · 선택 모델`만 먼저 표시하고 `상세 평가 지표 보기`를 열면 Validation/Test 표가 함께 나타나는 기본 접힘 구조로 변경
- 최신 저장 작업 `69504acc...`를 재학습 없이 복원해 XGBoost 선택, Test WAPE 29.5%, 피크 크기 오차 1.08kWh, 피크 시간 오차 4.2시간과 기본 접힘을 계약 테스트로 확인. 이전 저장 결과의 누락 필드는 `평가 결과 없음` 처리
- 전체 Python 88 PASS, 프런트 지표·품질 계약 테스트 및 JavaScript 문법 PASS
- 브라우저 접근 호스트 비활성화로 실제 브라우저 시각 검증은 미검증

## 2026-11-06 PatchTST 학습과 예측 방식 자동 선정

- 한 번의 학습 job에서 XGBoost 24개 horizon 회귀기와 `kwh` 단일 채널 168→24 PatchTST를 순차 학습하도록 구현
- 동일한 고정 Validation·Test origin에서 XGBoost, PatchTST, 50:50 평균, Last-24h, Last-168h 다섯 후보를 같은 24시간 실측으로 평가
- 세 학습 기반 후보에 기존 MAE 5% 개선·RMSE/WAPE 5% 악화 제한·유한/비음수 규칙을 동일 적용하고, 통과 후보 중 Validation MAE 최저 방식을 채택하며 Test 재선택은 차단
- PatchTST state dict·config·Train 전용 scaler와 XGBoost bundle을 불변 run에 저장하고 PatchTST·50:50 평균 선택 run의 재로딩 추론 구현; 기존 XGBoost·baseline·GRU 읽기 호환 유지
- 학습 화면을 `모델 학습 및 비교`, `모델 학습 시작`으로 변경하고 현재 학습 모델 진행 문구와 다섯 후보 Validation·Test 표 연결
- 전체 Python 91/91 PASS, JavaScript 문법 PASS. 테스트용 90일 합성 CSV 축소 설정에서 XGBoost 2.92초·PatchTST 2.30초, Last-168h 채택, 저장·재로딩 24시간 예측 PASS
- 실제 Office 신규 학습이나 운영 모델 승격은 실행하지 않음

## 2026-11-06 채택된 예측 방식 결과 카드 강조

- STEP 02 결과 카드에서 `채택된 예측 방식` 라벨 아래 실제 방식명을 가장 크게 표시하고 `학습 완료`를 보조 배지로 이동
- 24시간 예측 요약과 같은 연한 파란 배경·파란 왼쪽 강조선을 재사용하고, 저장된 Validation MAE로 최우수 기준 예측 대비 개선율을 한 줄 설명으로 표시
- Last-24h·Last-168h 채택 시 실제 반복 기준을 구분해 설명하며, 구형 저장 결과처럼 개선율 계산이 불가능하면 숫자 없는 정책 설명으로 대체
- 상세 평가 지표는 기본 접힘을 유지하고 기존 다섯 후보 Validation·Test 표를 그대로 보존
- 최신 완료 저장 job `b7457c03...`에서 XGBoost·25.7% 개선 문구 확인, 합성 표시 데이터로 PatchTST·50:50·두 baseline과 지표 누락 폴백 16/16 PASS
- 실제 Headless Chrome 1440px·390px에서 카드 위계·색상·4px 강조선·기본 접힘·모바일 가로 오버플로·콘솔 오류 없음 10/10 PASS
- 검증 결과: `analysis/training_selection_card_validation/`

## 2026-11-06 timestamp·kWh 계약 유지 PatchTST 성능 개선

- CSV 입력 계약과 168→24 단일 kWh 채널은 유지하면서 신규 PatchTST에 window별 affine RevIN과 길이 24·stride 12의 50% 중첩 patch를 적용
- 최대 80 epoch·patience 12·learning rate 0.0005·gradient clipping 1.0으로 학습 안정성과 수렴 여유를 확대
- RevIN 이전 저장 run은 누락된 config를 legacy 전역 scaler 모드로 복원해 state dict와 추론 호환 유지
- 동일한 90일 테스트용 합성 CSV·고정 Validation 15개 시점 비교에서 기존 MAE 0.226343 → 개선 MAE 0.104527(53.8% 감소), RMSE 0.350039 → 0.182081, WAPE 1.0335% → 0.4773%
- 합성 학습 시간은 기존 4.74초 → 개선 16.10초. 실제 Office 신규 학습·운영 승격은 실행하지 않음

## 2026-11-06 발표용 홈 첫 방문자 안내

- 홈 상단에 `01 에너지 플래너`를 기본 선택한 4개 안내 탭을 추가하고, 클릭·좌우 방향키·Home·End로 같은 영역의 내용만 전환
- 각 탭을 한 문장과 하나의 시각 요소로 제한: 사용량 예상→운영 계획, timestamp·kwh CSV 한 행, `예시` 표시 24시간 곡선·피크, 15시→18시 작업 이동
- 기존 홈의 XGBoost 설명과 장식용 예측 곡선을 제거하고 최소 90일·모델명·보고서 생성 안내는 실제 데이터 준비·학습·보고서 화면에 유지
- 데스크톱 네 문구 모두 한 줄, 네 패널 높이 184px 동일. 모바일 네 패널 높이 300px 동일, 가로 넘침 없음
- 실제 Chrome 1440×900·390×844·844×390에서 탭 순차 전환, 키보드 이동, 줄바꿈, 터치 높이, reduced motion, 콘솔 오류 없음 21/21 PASS

## 2026-11-06 첨부 HTML 기준 홈 미리보기 적용

- `energy-planner-intro.html`을 기준으로 홈을 왼쪽 질문형 제목·소개와 오른쪽 서비스 흐름 탭으로 재배치하고 `처음 이용하는 분을 위한 미리보기` 라벨 표시
- `에너지 플래너란?` 정의와 `이 서비스에서는` 설명을 첨부 원문 그대로 적용. CSV·예측 곡선·작업 이동 내용을 반영하고 곡선·작업 이동에 `예시` 표시
- 첫 진입 01 선택·기존 키보드 탭 전환을 유지하고, 모든 패널의 공간을 함께 확보해 탭 전환 높이 변화 0px. 700px 이하에서는 소개와 탭을 위아래 배치
- 로컬 홈 실제 Chrome 1440px·390px·320px·가로 화면 기본 선택/네 탭/원문 대조/높이/넘침/키보드/예시 표시 27/27 PASS. 프런트 홈 검사·결과 카드 16/16·라우트 4/4·JS 문법 PASS
- 검증 산출물: `analysis/home_intro_reference_validation/`. 변경 범위는 홈 소개 UI와 관련 검사·기록이며 학습·예측 로직은 변경하지 않음

## 2026-11-06 홈 소개 이전 버전 복원

- 사용자 요청으로 첨부 HTML 적용 전 `16c8e41`의 홈 UI(큰 Energy Planner 제목·가로 4개 안내 탭)와 관련 검사를 복원
- 첨부 시안 적용 이력과 검증 산출물은 보존. 학습·예측 코드는 변경하지 않음
- 로컬 Chrome 기본 01 선택·네 탭 순차 전환·반응형·높이 유지 21/21 PASS, 홈 계약 검사·JS 문법 PASS
- 복원 검증 산출물: `analysis/home_rollback_validation/`

## 2026-11-06 발표용 안내 추가 전 홈 복원

- 사용자 요청으로 홈 HTML·CSS·JS를 `45c1ac4` 상태로 복원. 발표용 4개 안내 탭을 제거하고 기존 제목·소개 문장·Energy 클릭 곡선 동작을 복원
- 제거된 안내 전용 계약 테스트를 정리. 이전 작업 기록과 검증 산출물, PatchTST 개선 및 결과 카드 기능은 보존
- 실제 로컬 Chrome 1440px·390px·320px 반응형, 안내 탭 없음, 곡선 클릭·키보드 조작·콘솔 오류 없음 15/15 PASS. 결과 카드 16/16·JS 문법 PASS
- 검증 산출물: `analysis/home_without_guide_validation/`

## 2026-11-06 기존 홈 아래 접이식 서비스 소개 추가

- 기존 히어로 타이틀·설명·CTA·곡선 마크업과 인터랙션을 유지하고, 곡선 아래와 분석 단계 메뉴 사이에 기본 접힘 `처음 이용하시나요? 서비스 미리보기 ▾` 추가
- native details/summary로 같은 컨트롤의 열기·닫기를 제공. 펼치면 첨부 HTML의 왼쪽 질문·소개와 오른쪽 4개 탭을 표시하고 첫 진입 01 선택 및 방향키/Home/End 지원
- 패널 공간을 함께 확보해 탭 전환 높이를 유지하고 700px 이하에서 소개·탭을 위아래 배치. 예측 곡선·작업 이동 예시 표시 및 보고서 인쇄 시 홈 소개 제외
- 실제 로컬 Chrome 접힌 홈·열기/닫기/다시 열기·네 탭·기존 곡선 클릭/키보드·1440/390/320px·보고서 인쇄 제외 37/37 PASS. 결과 카드 16/16 및 JS 문법 PASS
- 검증 산출물: `analysis/collapsible_preview_validation/`

## 2026-11-06 서비스 미리보기 모델 학습·비교 단계 추가

- 접이식 소개 내부에 `03 모델 학습·비교`를 추가하고 기존 예측/운영 탭을 04/05로 변경. 기본 접힘과 첫 펼침 01 선택 유지
- 요청한 건물별 신규 학습·Validation 오차 선택 문장과 3단계 흐름만 표시. 데스크톱은 가로 흐름, 작은 화면은 세로 흐름으로 배치
- 기존 히어로·학습 로직은 변경하지 않고 사용자가 직접 수정한 02 제목은 작업 트리에 보존
- 실제 Chrome 5개 탭 순서·새 문장/흐름·열기/닫기·첫 01 선택·키보드 End/05 선택·1440/390/320px·기존 곡선·인쇄 제외 43/43 PASS. 결과 카드 16/16·JS 문법 PASS
- 검증 산출물: `analysis/service_preview_training_validation/`
