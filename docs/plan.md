# Energy Planner 구현 계획(PLAN)

## 1. 목적

이 계획은 `docs/spec.md`를 기준으로 현재 구현을 유지·검증하고 남은 MVP 작업을 순서대로 수행합니다. 이미 완료된 학습이나 불변 run은 반복하지 않습니다.

## 2. 실행 원칙

- 변경 전 관련 코드와 미커밋 상태를 확인합니다.
- 관련 테스트를 먼저 실행하고 필요할 때 전체 회귀 테스트를 수행합니다.
- BDG2 원본, 기존 인턴 모델, Leon·Danica 불변 run을 수정하지 않습니다.
- 실제 Office 학습, 운영 승격, 패키지 설치, Git 작업과 배포는 별도 승인 후 진행합니다.
- 실제 브라우저에서 보지 않은 UI는 미검증으로 유지합니다.

## 3. 완료된 기반 작업

### PLAN-01 데이터·학습 명세 — 완료

- MVP, CSV 계약, 품질, 피처, 분할, 학습 설정 정의
- 시간순 분할과 Train 전용 scaler 정책 확정
- Validation 선택과 Test 독립성 정의

### PLAN-02 ML 파이프라인 — 완료

- 계약·품질·분할·피처·시퀀스·스케일링
- GRU 학습과 Last-24h·Last-168h 비교
- Validation 선택, Test 보고, 불변 run 저장과 재사용 추론

### PLAN-03 품질 고도화 — 완료

- 장기 상수·지배값·상태 전환 경고
- Train 0분산 차단
- 분할별 분포 이동 진단
- IANA·explicit offset·BDG2 고정 표준시 분리

### PLAN-04 실제 Office 실험 — 완료

- Leon 단일 학습과 사후 진단
- Maggie 학습 차단
- Danica 단일 학습과 Leon 비교
- 추가 Office 학습 및 운영 승격 없음

### PLAN-05 로컬 웹 MVP — 부분 완료

- CSV 품질 API, 학습 job, 상태 조회, 저장 run 예측
- 품질·모델·예측 화면과 오류 표시
- HTTP·통합·정적 검사 완료
- 실제 브라우저 데스크톱·모바일 QA 미완료

## 4. 현재 작업

### PLAN-06 문서 정합화 — 완료

1. MVP를 기준으로 PRD 작성
2. PRD를 기준으로 SPEC 작성
3. SPEC을 기준으로 PLAN 작성
4. 확정 정책, 현재 구현과 미구현 상태 구분
5. 문서 간 용어·상태 충돌 점검

완료 조건:

- `docs/prd.md`, `docs/spec.md`, `docs/plan.md` 존재
- 구현되지 않은 기능이 완료로 표시되지 않음
- 기존 ML 명세를 불필요하게 복제하지 않음

### PLAN-07 manifest 시간대 명시와 호환성 — 완료

1. 미래 신규 run에 `feature_timezone` 저장
2. 기존 `building_timezone` 호환 별칭 유지
3. loader에 `feature_timezone → building_timezone` fallback 적용
4. 추론 피처 시간대가 명시 필드를 우선 사용하도록 변경
5. 신규 run 필드 저장 테스트
6. Leon·Danica 기존 run 로딩 및 원본 불변 테스트
7. 시간대 계산 결과가 변경되지 않는 회귀 테스트

완료 조건:

- 신규 manifest에 `feature_timezone`이 존재
- 기존 run 파일 수정 없이 로딩 성공
- 기존과 신규 시간대 경로의 피처 값 동일
- 관련 테스트와 전체 회귀 테스트 PASS

## 5. 다음 구현 후보

아래 항목은 현재 승인 범위에서 구현하지 않으며 PM 우선순위 결정 후 진행합니다.

### PLAN-08 job 영속화와 재시작 복구 — 미구현

- 메모리 job registry의 저장 방식 결정
- 중단·재시작 상태 전이와 실패 기록 정의
- 동일 건물 동시 작업 제한 유지

### PLAN-09 사용자·artifact 격리 — 미구현

- 사용자·건물 식별 방식 결정
- 업로드와 run 접근 권한 경계 정의
- 인증·CSRF와 비밀정보 처리 설계

### PLAN-10 보존·승격 정책 — 미확정

- 업로드·run 보존 기간과 삭제 정책
- candidate 승격·롤백 승인 절차
- `active_model.json` 갱신 권한과 감사 기록

### PLAN-11 실제 브라우저 QA — 미검증

- 데스크톱 업로드·진단·학습·예측 흐름
- 모바일 세로 레이아웃과 조작성
- 오류·로딩·완료 상태 및 예시/실제 데이터 구분
- 스크린샷과 미검증 항목 기록

## 6. 검증 순서

1. 변경 모듈 단위 테스트
2. 기존 manifest 호환성·불변성 테스트
3. 전체 Python 회귀 테스트
4. Python compileall
5. JavaScript 구문 검사
6. 필요한 경우 로컬 HTTP 확인
7. 별도 실제 브라우저 환경에서 시각 QA

## 7. 이번 단계 산출물

- `docs/prd.md`
- `docs/spec.md`
- `docs/plan.md`
- manifest 시간대 필드 코드와 테스트
- 갱신된 `docs/development_progress.md`

## 8. PM 승인 필요 사항

- job 영속화와 인증 중 다음 우선순위
- 업로드·run 보존 기간
- 운영 모델 승격·롤백 정책
- 실제 브라우저 QA 실행 환경
- 추가 실제 Office 학습 여부
