# 378af21 이후 보고서 실패 조사

날짜: 2026-11-05. 이번 작업의 실제 OpenAI 호출: 0회.

## 실제로 확인한 실패 위치

기존 서버 세션 로그에는 다음 순서가 남아 있었다.

```text
POST /api/predictions/[job] 200
POST /api/ai-analysis/[job] 502
POST /api/ai-analysis/[job] 502
```

사용자가 확인한 `OpenAI API가 분석을 완료하지 못했습니다.`는 `_parse_structured_response` 맨 앞의 `response.status not in {None, completed}` 분기에서만 발생한다. 따라서 이번 요청은 인증/설정 차단·HTTPError·JSON 응답 텍스트 파싱·신규 관찰 필드/근거 ID 검증에 도달한 실패가 아니라, API 최상위 응답 상태 확인 단계에서 중단됐다. 해당 분기는 `incomplete` 외 `failed` 등도 같은 문구로 처리했다.

| 조사 항목 | 당시 로그로 확인되는 값 |
|---|---|
| 로컬 HTTP 상태 | 502, 2회 |
| OpenAI HTTP 상태 | 미기록. HTTPError 경로가 아닌 성공 HTTP 응답을 디코딩한 뒤 실패했다는 것은 코드로 추론 가능하나 정확한 상태 코드는 복구 불가 |
| API 응답 status | completed 외 상태. 정확한 값 미기록 |
| incomplete_details.reason | 미기록, 복구 불가 |
| API error.code | 미기록, 복구 불가 |
| 신규 필드/근거 ID 거부값 | 해당 단계 이전 중단이므로 이번 실패의 원인 아님 |

응답 본문을 보존하는 별도 작업공간 로그는 발견되지 않았으며 요청은 `store:false`였다. 기존 오류 처리에서 사유를 버렸으므로 토큰 부족을 확정할 수 없다. 불완전 결과를 완료 보고서로 받아들이도록 완화하지 않았다.

## 전후 요청과 적용 설정

`git diff 378af21^ 378af21 -- backend/app/web/ai_analysis.py`로 비교했다.

- 변경: 관찰 프롬프트·입력 근거 메타데이터 확대, 응답 schema에 observation_evidence_ids 추가.
- 유지: Responses endpoint, model 환경변수 참조, `max_output_tokens=1200`, reasoning 환경변수 전달, timeout 처리, store:false.
- 현재 서버 health 확인: 모델 gpt-6-sol, reasoning high, 출력 한도 1200, timeout 20초. 키 값은 조회·출력하지 않음.
- 과거 서버의 timeout과 토큰 사용량은 기록되지 않아 재시작 전후 실측 비교는 불가. 현재 `.env`의 비밀이 아닌 설정과 전후 코드에는 변경 없음.

공식 [Reasoning 문서](https://developers.openai.com/api/docs/guides/reasoning)에 따르면 출력 한도에는 추론 토큰이 포함되며 한도 도달 시 `status=incomplete`, `incomplete_details.reason=max_output_tokens`가 반환될 수 있다. 이번에도 이 조건일 가능성은 있지만 아직 가설이다. 실제 reason 확인 전 출력 한도나 사용자의 high 설정을 변경하지 않았다.

## 수정 내용

- `ai_analysis.py`: 오류 stage와 allowlist 기반 상태·사유·에러 코드·토큰 사용량·HTTP 상태 보존. 키·헤더·프롬프트·원본 데이터·AI 응답 텍스트는 진단에 포함하지 않음.
- 토큰 한도 도달 응답은 원인 문구를 구체화하며 미완료 응답을 계속 거부. content_filter 등과 구분하며 자동 유료 재시도 없음.
- HTTP 오류·응답 디코딩·상태 실패·응답 파싱·관찰 근거·조치 근거 오류를 각각 stage로 구분.
- `server.py`: 안전한 진단만 서버 로그 및 로컬 502 JSON에 포함.
- health: 실제 출력 한도·timeout을 비밀이 아닌 진단 설정으로 노출.
- 관찰의 allowed 검증과 조치의 actionable 검증, 프런트 예측 상태 처리 유지.

## 검증

- Python 전체 71 PASS. HTTP 401/invalid_api_key, incomplete/max_output_tokens, incomplete/content_filter, 완료 응답 파싱 오류, 관찰 및 조치 근거 검증을 모의 응답으로 확인.
- 정상처럼 보이는 JSON을 포함해도 status=incomplete이면 거부하는 것을 확인. status 게이트를 우회하지 않음.
- 프런트 실제 `generateAIReport`와 `updateNextAction`을 DOM 모의 환경에서 실행: 4종 실패 × 기존 보고서 유/무, 8 PASS. 10월 1일 예측 객체·KPI·차트·기존 보고서가 유지되고 재시도 버튼이 활성화됨.
- JavaScript 문법, Python compileall, Git diff 검사 PASS.
- 브라우저 시각 검증/실제 API 성공 검증은 수행하지 않음.
- 로컬 서버 재시작 및 health ok 확인.

## 남은 원인 확정 단계

진단 필드가 누락된 이전 응답의 상세 사유는 복구할 수 없다. 저장된 10월 1일 예측의 기존 집계 정보로 동일 설정(1200/high)의 실제 API 요청을 1회 수행하면 정확한 status·incomplete reason·error code·출력/추론 토큰 수를 확인할 수 있다. 유료 진단 1회 허용 여부를 사용자에게 질문했으며, 승인 응답 전에는 실행하지 않는다.

`reason=max_output_tokens`가 확인되면 그때 출력 한도와 추론 예산을 검토한다. 다른 사유면 해당 HTTP 오류/상태/파싱/근거 거부 조건을 대상으로 수정한다.
