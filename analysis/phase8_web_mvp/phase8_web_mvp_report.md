# Energy Planner — Phase 8 로컬 웹 MVP 구현 보고서

## 구현 상태

| 기능 | 상태 | 비고 |
|---|---|---|
| CSV 선택·업로드 | 정상 작동 | 브라우저에서 읽어 로컬 API로 전달, 25MB 제한 |
| 건물 ID·시간대 입력 | 정상 작동 | IANA 및 explicit offset 지원 |
| PASS/WARNING/FAIL 진단 | 정상 작동 | 기존 ML 품질 모듈 재사용 |
| 학습 자격·사유 표시 | 정상 작동 | 0분산 등 blocker 표시 |
| 학습 작업 생성·상태 | 정상 작동 | 메모리 job registry, 별도 API |
| GRU·baseline 학습 | 구현됨, 실제 Office 미실행 | 사용자 업로드와 명시 요청 시에만 실행 |
| 저장 run 예측 | 정상 작동 구조 | 학습 완료 job에서만 허용, 자동 재학습 없음 |
| 24시간 그래프·총량·피크 | 정상 작동 구조 | 초기에는 예시라고 표시, 실제 예측 후 교체 |
| 모델 비교·버전 정보 | 정상 작동 구조 | 완료 job의 Validation MAE, 선택 모델, run ID 표시 |
| 인증·다중 사용자 격리 | 미구현 | 로컬 단일 사용자 MVP |

## API

- `GET /api/health`
- `POST /api/quality`
- `POST /api/training-jobs`
- `GET /api/training-jobs/{job_id}`
- `POST /api/predictions/{job_id}`

학습과 예측은 별도 endpoint다. 예측 endpoint는 완료된 job의 저장 run만 사용한다.

## 검증

- 전체 Python 테스트 31개 PASS
- Python `compileall` PASS
- JavaScript `node --check` PASS
- 로컬 HTTP: `/`, `/api/health` 200, 잘못된 CSV 계약 `/api/quality` 400 응답 확인
- 합성 180일 CSV 품질 API: PASS, 학습 가능, 168+24 조합 4,129 확인
- 저장된 Last-24h run을 재사용한 24시간 예측: 출력 shape `[1, 24]`, 재학습 없음 확인
- 브라우저 자동 시각 검증: 현재 브라우저 접근 호스트가 없어 미수행. HTTP와 정적 구조 검증으로 대체했으며 시각 QA는 미검증으로 남긴다.

## 보안과 운영 제한

- 서버 기본 bind는 `127.0.0.1`이다.
- CSV는 job 진행 중 프로세스 메모리에만 보관하고 public job 응답에서 제외한다.
- 인증, CSRF 방어, 영구 job DB, 사용자별 artifact 권한은 아직 없다.
- 클라우드 배포, 외부 API, Git 작업은 수행하지 않았다.
- 실제 Maggie 또는 신규 Office 학습은 수행하지 않았다.

## 후속 작업

1. job 영속화와 재시작 복구
2. 사용자별 데이터·artifact 격리와 인증
3. 파일 저장 정책과 보존 기간 확정
4. 브라우저 접근 환경에서 모바일·데스크톱 시각 QA
