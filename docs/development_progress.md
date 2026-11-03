# Energy Planner 개발 진행 기록

최종 갱신: 2026-11-03

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

- XGBoost 의존성 설치 승인과 실제 합성 학습 검증 대기
- Phase 8 운영 보안·job 영속화 후속 설계와 실제 브라우저 QA 준비

## 남은 작업

- job 영속화·재시작 복구
- 인증과 사용자별 artifact 격리
- 서버 재시작·전체 새로고침 후 진행 중 job 재연결
- Danica run의 운영 승격 여부는 PM 검토 후 별도 결정
- 승인된 환경에 `backend/requirements.txt`를 설치한 뒤 XGBoost 결정성·end-to-end 합성 학습 검증

## 사용자 승인 필요

- raw LFS 실파일 확보 또는 외부 다운로드
- 품질 임계값의 장기 운영 정책 확정
- 모델 승격·롤백·보존 기간
- Danica 기존 시간대 manifest 형식 승인 또는 별도 교정 실험 여부
- XGBoost 패키지 설치 승인

## 다음 세션 시작 위치

승인된 환경에 XGBoost 의존성을 설치한 뒤 실제 학습·저장·재로딩·예측 회귀를 검증한다. 이후 PRD·SPEC·PLAN을 기준으로 Phase 8 job 영속화·사용자 격리·보안 설계를 이어서 구현한다. 추가 Office 학습과 운영 승격은 수행하지 않는다.
