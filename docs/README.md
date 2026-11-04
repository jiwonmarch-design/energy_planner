# Energy Planner Mini

Energy Planner는 사용자가 업로드한 건물별 시간당 kWh CSV를 진단하고, 건물 전용 XGBoost와 Last-24h·Last-168h 기준 모델을 비교해 향후 24시간 수요를 예측하는 로컬 웹 MVP입니다.

## 현재 구현 상태

웹 화면의 현재 요구사항은 `docs/prd.md`의 PRD-F10·F11, 기술 구현 기준은 `docs/spec.md`의 `13. 화면 동작`을 따릅니다. `docs/development_progress.md`의 날짜별 항목과 `Energy_Planner_Codex_UX_Implementation_2026-11-02.md`는 변경 이력·보관 자료이며 현재 기준과 충돌할 때 PRD와 SPEC을 우선합니다.

- CSV 계약 및 품질 진단
- 장기 상수·상태 전환·Train 0분산·분포 이동 검사
- IANA, explicit offset, BDG2 고정표준시 모드 분리
- 건물별 XGBoost 학습과 기준 모델 비교 파이프라인
- 불변 run 저장과 저장 모델 재사용 추론
- 단일 페이지 `/`의 Home → CSV 업로드 → 품질 진단 → 모델 학습 → 예측 대시보드 흐름
- `#upload`, `#quality`, `#training`, `#dashboard` 해시 기반 섹션 이동과 Sticky 4단계 탐색
- 로컬 CSV 업로드, 품질 결과, 영속 학습 상태, 모델·예측 대시보드
- 완료된 학습의 Validation MAE·선택 모델·run ID 표시
- 저장 run을 재사용한 24시간 예측, 최근 사용량 분석과 그래프 갱신
- 선택형 OpenAI 예측 해석(API 키가 없으면 안전하게 비활성화)

예측 전에는 빈 KPI·그래프나 예시 수치를 노출하지 않고 CSV 업로드부터 예측까지의 준비 상태와 다음 행동만 표시합니다. 저장 모델 예측이 성공한 뒤에만 실제 KPI·그래프·사용 패턴을 공개합니다. 일반 예측 요청은 자동으로 재학습하지 않습니다.

## 로컬 실행

프로젝트 루트에서 기존 ML 가상환경의 Python으로 실행합니다.

XGBoost 전환 후 의존성은 승인된 가상환경에서 다음 파일로 설치합니다.

```powershell
python -m pip install -r backend/requirements.txt
```

```powershell
& 'C:\Users\aicam\Desktop\energy_planner_project\analysis\energy-planner-mvp\.venv-phase4-gru\Scripts\python.exe' -m backend.app.web.server --host 127.0.0.1 --port 8765
```

브라우저에서 `http://127.0.0.1:8765`를 엽니다. 이 서버는 로컬 프로토타입이며 인증·다중 사용자 격리·운영 배포 기능을 제공하지 않습니다.

사용방법은 통합 페이지의 CSV 업로드·품질 진단·학습·예측 단계별 도움말에서 확인할 수 있습니다. OpenAI 해석을 실제로 사용하려면 서버 실행 전에 키를 환경변수로만 설정합니다. 키를 코드·문서·브라우저에 넣지 않습니다.

```powershell
$env:OPENAI_API_KEY = '<your-api-key>'
$env:OPENAI_MODEL = 'gpt-4o-mini' # 선택 사항
```

## 테스트

```powershell
& 'C:\Users\aicam\Desktop\energy_planner_project\analysis\energy-planner-mvp\.venv-phase4-gru\Scripts\python.exe' -m unittest discover -s backend/tests -p 'test*.py' -v
```

실제 Office 건물 학습과 운영 모델 승격은 별도 승인 작업입니다.
