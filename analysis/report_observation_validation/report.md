# 운영 관찰 표시 개선 검증

검증일: 2026-11-05. 실제 OpenAI 호출 0회, 신규 학습 0회.

## 기존 필드 추적

- `summary`: 미리보기의 `report-summary`에 표시되고 HTML 내보내기의 `ai-report` DOM 복제로 보존됨.
- `peak_analysis.ai_interpretation`, `comparison.ai_interpretation`: 서버 결과에는 있었으나 기존 화면 렌더러가 읽지 않아 미리보기·내보내기·인쇄에서 빠졌음.
- 기존 `no_action_reason`: 수치 하단 `report-priority-action`과 발견 목록의 추가 조치 없음 항목에 반복 표시됐음.
- 변경 후 같은 세 문장 필드를 유지하고 `observation_evidence_ids`로 관찰 근거를 연결함. 관찰은 allowed, findings는 actionable 목록으로 각각 서버 검증함.

## 저장된 10월 1일 사례

- run: `20261105T003114Z_b7a92ed0`
- 예측: 2025-10-01 00:00~23:00 Asia/Seoul
- 직전 24시간: -5.0094048069%, 동일 요일: -0.4658650774%
- 예상 최고 시각: 06시, 7,852.8501kWh
- 과거 동일 요일·06시: 8개 표본, 평균 7,067.85kWh, 최소 1,505.76kWh, 최대 8,599.92kWh
- 동일 요일 24개 시간 평균 중 17위. 따라서 반복적인 고사용 시간으로 단정하지 않고 판단을 보류함.
- 기존·변경 후 조치 후보 모두 0개, quantitative 결과 동일.

이 자료는 기존 불변 run의 입력·모델을 읽어 한 번 재현한 예측을 `before.json`에 보존했다. 원본 CSV, API 키와 run 파일은 수정하지 않았다. 이후 검증은 이 스냅샷과 모의 AI transport만 사용한다.

## 전후 예시

| 사례 | 기존 표시 | 변경 표시(모의 AI 문장은 예시) |
|---|---|---|
| 후보 없음 | 합계·최고 사용량 요약 + 뚜렷한 변화가 없다는 동일 사유를 수치 하단과 발견 목록에서 반복 | 상단 판단 `현재 기준에서 추가 조치 권고 없음`. 이유: `전일보다 낮게 예측되지만 동일 요일 기준과의 차이는 작습니다. 계산된 운영 신호가 기존 조치 기준에 이르지 않아 현재 계획을 바꿀 근거가 충분하지 않습니다.` 서버 수치로 `직전 24시간 대비 5.0% 감소; 과거 동일 요일·시간 평균 대비 0.5% 감소`를 함께 표시 |
| 피크 관찰 | 예상 최고 시각·수치만 표시 | `과거 동일 요일·시간 8개 표본의 평균은 7,067.9kWh, 범위는 1,505.8~8,599.9kWh입니다. 동일 요일 24개 시간 평균 중 17위입니다.` 반복적 고사용 여부는 보류 |
| 후보 있음 | 기존 기준을 충족한 조치 권고 | 같은 후보 3개를 보존. 상단 판단과 운영 관찰을 추가하고 허용된 후보 근거의 모의 AI 권고를 기존 조치 영역에 표시 |

조치 후보 없는 경우에 별도 빈 조치 영역과 우선 확인 사유를 숨긴다. 후보 있는 경우에는 기존 조치 기준과 fallback을 유지한다. 새로운 관찰 값은 후보 선별에 사용하지 않는다.

## 검증

- 전체 Python 회귀: 66 PASS. 관찰의 일반 근거 허용, 알 수 없는 근거 거부, 무근거 문장 로컬 fallback, 조치 후보 없는 finding 제한, 피크 표본 부족 시 보류 포함.
- 저장 스냅샷·모의 AI: 후보 없음/있음 PASS. `results.json` 참조.
- 실제 `renderAnalysisReport`와 `buildStandaloneReportHtml` 함수를 DOM test double로 실행: 두 시나리오 PASS. `render-results.json` 참조. 차트 geometry는 이 검사 대상에서 제외.
- 두 시나리오의 요약·비교 AI 문장·피크 AI 문장·서버 근거가 HTML에 보존됨. `no_action-export.html`, `action-export.html`은 이 DOM 모의 검사로 생성한 산출물.
- PDF 경로는 동일 `ai-report`를 인쇄하며, 새 관찰 영역은 인쇄 숨김 대상이 아님을 코드로 확인. 내보내기의 `[hidden]` 규칙으로 빈 조치 영역 숨김 유지.
- 실제 Chrome 조작은 브라우저 URL 확인 실패로 중단. 화면 배치·모바일 overflow·실제 PDF 렌더링은 미검증.

재현 명령:

```powershell
& 'C:/Users/aicam/Desktop/energy_planner_project/analysis/energy-planner-mvp/.venv-phase4-gru/Scripts/python.exe' -m analysis.report_observation_validation.validate
node analysis/report_observation_validation/render_test.mjs
```

격리된 브라우저 검증 서버는 `python -m analysis.report_observation_validation.serve`로 실행할 수 있다. `http://127.0.0.1:8767/qa.html?scenario=no_action` 또는 `scenario=action`은 저장 모의 응답만 렌더링하며, `&export=1`은 같은 내보내기 HTML을 연다. 이 서버는 학습·실제 AI 호출 API를 제공하지 않는다.
