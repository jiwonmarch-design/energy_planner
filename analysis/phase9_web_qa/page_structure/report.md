# Phase 9 Home / Workspace / Dashboard 구조 개편 보고서

검증일: 2026-11-02

## 라우팅 구조

| 경로 | 역할 | 직접 진입 |
|---|---|---|
| `/` | 브랜드 소개와 Editorial Contour Hero | PASS |
| `/workspace` | CSV 업로드, 품질 진단, 명시적 모델 학습 | PASS |
| `/dashboard` | 예측 요약, 그래프, Validation 성능, 저장 모델 정보 | PASS |

프론트엔드는 Vanilla JavaScript와 History API를 사용한다. 세 경로만 서버의 `index.html`로 연결하며 알 수 없는 경로와 상위 경로 접근은 404로 유지한다.

## 상태와 이동

- Home CTA, 공통 내비게이션, 완료 후 Dashboard 버튼은 문서 재로딩 없이 이동한다.
- Workspace → Dashboard → 브라우저 뒤로 가기에서 입력값이 유지됨을 확인했다.
- 화면 이동 중 동일 JavaScript 상태와 학습 polling이 유지되므로 백엔드 학습 작업을 중단하지 않는다.
- 업로드 완료, 품질 진단 완료, 모델 학습 현재/완료 상태를 단계 표시로 구분한다.
- 전체 새로고침 뒤에는 브라우저 보안상 선택한 로컬 파일과 클라이언트 상태가 복원되지 않는다.

## Dashboard 빈 상태

- 저장 모델이 없으면 총사용량, 최대 시간당 사용량, 피크 시간은 `—`로 표시한다.
- 그래프는 예시 수치 대신 학습·예측 안내를 표시한다.
- 모델 비교는 MAE와 WAPE를 함께 표시하며 Test는 선택에 사용하지 않는다는 정책 문구를 유지한다.
- 학습 완료 후 저장 모델 예측 버튼과 Dashboard 이동 버튼을 표시한다.

## 브라우저 검증

- Chrome DevTools Protocol 실제 렌더링
- Home, Workspace, Dashboard 각각 1440px, 390px, 320px 캡처
- 9개 화면 모두 수평 오버플로 없음
- 활성 내비게이션, 직접 URL, 페이지 제목, 표시 화면 일치
- 합성 180일 CSV 업로드와 품질 판정 PASS
- 단계 전환: `업로드 완료 → 품질 진단 완료 → 모델 학습 현재` PASS
- 실제 신규 모델 학습은 실행하지 않음

## 자동 테스트

- 웹 서비스와 라우팅: 16/16 PASS
- 전체 회귀 테스트: 39/39 PASS
- 신규 라우팅 테스트: 3/3 PASS
- Python 컴파일, JavaScript 문법, 필수 DOM ID 검사 PASS

## 스크린샷

- `home-1440px.png`, `home-390px.png`, `home-320px.png`
- `workspace-1440px.png`, `workspace-390px.png`, `workspace-320px.png`
- `dashboard-1440px.png`, `dashboard-390px.png`, `dashboard-320px.png`

## 알려진 제한

- 서버 재시작 또는 브라우저 전체 새로고침 뒤 진행 중 job에 자동 재연결하는 클라이언트 영속화는 구현되지 않았다.
- Dashboard 직접 진입은 현재 브라우저 세션에서 완료된 job이 없으면 의도적으로 빈 상태를 표시한다.
- 실제 학습 완료 후 예측 화면은 기존 자동 테스트와 모의 완료 상태로 UI 회귀를 확인했으며, 이번 작업에서 추가 학습은 수행하지 않았다.
