# Energy Planner 개발 진행 기록

최종 갱신: 2026-10-30

## 완료한 작업

- Phase 6 명세 문서
- Phase 7-1 독립 ML 파이프라인과 기존 자동 검증
- Phase 7-2 Leon 실제 단일 학습 실험
- Phase 7-3 Leon 사후 진단과 Maggie 읽기 전용 점검
- Phase 7-4 장기 상수·상태 전환·Train 0분산·분포 이동·시간대 출처 모드 구현
- Phase 7-5 Office 295개 최신 180일 읽기 전용 재점검과 후보 3개 선정
- Phase 8 로컬 웹 MVP: CSV 품질 진단, 학습 job, 모델 지표 표시, 저장 run 예측 연결

## 테스트 결과

- ML 전체: 23/23 PASS
- 기존 Phase 7 사례: 15개 유지
- Phase 7-4 신규 사례: 8개
- 웹 서비스 사례: 8개
- 전체 회귀 테스트: 31/31 PASS
- 실제 건물 학습: 이번 세션에서 실행하지 않음

## 발견 및 해결

- Maggie 0.0002kWh 3,504시간과 Train 0분산: 학습 전 차단 구현
- 기존 timezone 검사에서 `UTC` IANA 식별자를 거부: 명시 허용으로 수정
- BDG2와 실서비스 DST 처리 혼용 위험: source timezone mode 분리
- raw electricity는 Git LFS pointer만 존재: 0.0002 upstream 원인은 미확정으로 유지

## 현재 진행 중

- Phase 8 운영 보안·job 영속화 후속 설계

## 남은 작업

- job 영속화·재시작 복구
- 인증과 사용자별 artifact 격리
- 브라우저 접근 환경의 시각 QA
- 실제 학습은 별도 승인 후 Danica 단일 후보부터 실행

## 사용자 승인 필요

- `Panther_office_Danica` 실제 GRU 학습
- raw LFS 실파일 확보 또는 외부 다운로드
- 품질 임계값의 장기 운영 정책 확정
- 모델 승격·롤백·보존 기간

## 다음 세션 시작 위치

Phase 8 웹 MVP의 job 영속화·사용자 격리·보안 설계를 이어서 구현한다. 브라우저 시각 QA 환경이 있으면 반응형 화면을 검증한다. 실제 Office 학습은 수행하지 않는다.
