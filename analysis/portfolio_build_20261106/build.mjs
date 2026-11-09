import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';

const workspaceDir=path.resolve('.');
const buildDir=path.resolve('analysis/portfolio_build_20261106');
const runtime='C:/Users/aicam/.cache/codex-runtimes/codex-primary-runtime/dependencies';
const modules=runtime+'/node/node_modules';
const SKILL_DIR='C:/Users/aicam/.codex/plugins/cache/openai-primary-runtime/presentations/26.1104.12130/skills/presentations';
process.env.RUNTIME_NODE_MODULES=modules;
const require=createRequire(import.meta.url);
const {FontLibrary}=require(modules+'/@oai/artifact-tool/node_modules/skia-canvas');
FontLibrary.use('Malgun Gothic',['C:/Windows/Fonts/malgun.ttf','C:/Windows/Fonts/malgunbd.ttf']);
FontLibrary.use('Arial Black','C:/Windows/Fonts/ariblk.ttf');
const {Presentation,PresentationFile}=await import(pathToFileURL(modules+'/@oai/artifact-tool/dist/artifact_tool.mjs').href);
const {finalizePresentation}=await import(pathToFileURL(SKILL_DIR+'/container_tools/artifact_tool_utils.mjs').href);
await fs.mkdir(path.join(buildDir,'renders'),{recursive:true});
await fs.mkdir(path.join(buildDir,'draft'),{recursive:true});
const cap=JSON.parse(await fs.readFile(path.join(buildDir,'capture-evidence.json'),'utf8'));
const p=Presentation.create({slideSize:{width:1280,height:720}});
const C={bg:'#F3F0E8',paper:'#FFFDF8',blue:'#1F4FDB',deep:'#143AA8',ink:'#10213D',sub:'#596579',line:'#D8D5CD',green:'#087A55',red:'#A93434'};
p.theme.defaultFont='Malgun Gothic';
p.theme.colorScheme={name:'Energy Planner Web',themeColors:{accent1:C.blue,accent2:C.green,accent3:'#8DA9FF',accent4:C.red,accent5:C.deep,accent6:'#737E8D',bg1:C.bg,bg2:C.paper,tx1:C.ink,tx2:C.sub,dk1:C.ink,dk2:C.deep,lt1:C.paper,lt2:C.bg,hlink:C.blue,folHlink:C.deep}};
let counter=0;
function text(s,value,x,y,w,h,size=24,color=C.ink,bold=false,font='Malgun Gothic'){
  const t=s.shapes.add({geometry:'textbox',name:'text-'+(++counter),position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
  t.text=value;t.text.style={typeface:font,fontSize:size,color,bold,verticalAlignment:'top',alignment:'left',wrap:'square',autoFit:'none',insets:0};return t;
}
function page(n,title,subtitle){const s=p.slides.add();s.background.fill=C.bg;text(s,title,64,48,1152,65,43,C.ink,true);if(subtitle)text(s,subtitle,64,118,1152,45,23,C.sub);text(s,String(n).padStart(2,'0')+' / 07',1138,678,90,25,16,C.sub);return s;}
async function image(s,file,x,y,w,h){const bytes=await fs.readFile(path.join(buildDir,file));s.images.add({blob:bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength),contentType:'image/png',alt:file,fit:'contain',position:{left:x,top:y,width:w,height:h}});}
function table(s,values,x,y,w,h,widths,font=22){
  const t=s.tables.add({rows:values.length,columns:values[0].length,left:x,top:y,width:w,height:h,columnWidths:widths,values});
  t.styleOptions={headerRow:false,bandedRows:false};
  t.borders.assign({style:'solid',fill:C.line,width:1});
  values.forEach((row,r)=>{t.rows[r].height=h/values.length;row.forEach((v,c)=>{const cell=t.getCell(r,c);cell.fill=r===0?C.ink:C.paper;cell.text.style={typeface:'Malgun Gothic',fontSize:font,color:r===0?'#FFFFFF':C.ink,bold:r===0,verticalAlignment:'middle',alignment:'left',autoFit:'none',insets:{left:12,right:10,top:7,bottom:7}};});});
  return t;
}
const commonNotes='검토 기준: Git HEAD a0743a2 및 2026-11-06 작업 트리. 사용자가 수정한 frontend/index.html 문구를 포함해 현재 로컬 화면을 참고했다. 소스 수정과 모델 재학습, 외부 AI 호출은 수행하지 않았다. 아래의 파일 경로는 저장소 루트 기준이다.\n디자인 근거: frontend/reference-system.css :root. 배경 #F3F0E8, 패널 #FFFDF8, 버튼·예측선 #1F4FDB, 본문 #10213D, 보조 글자 #596579, 경계 #D8D5CD. 차트 변경 전 #737E8D, 변경 후 #1F4FDB, 감소 #A93434, 증가 #087A55. 웹 body 폰트 Bahnschrift/Pretendard/Malgun Gothic, 홈 제목 Arial Black. 슬라이드는 Arial Black과 설치된 Malgun Gothic으로 구성했다.\n';
function notes(s,value){s.speakerNotes.text=commonNotes+'\n'+value;}

// 1. Motivation and cover, using the website's typography and open space.
{
const s=p.slides.add();s.background.fill=C.bg;
text(s,'LG AX SCHOOL  7일 바이브코딩 사이드프로젝트',64,56,1100,36,23,C.sub);
text(s,'Energy',60,178,435,146,112,C.blue,true,'Arial Black');
text(s,'Planner',480,178,600,146,112,C.ink,true,'Arial Black');
text(s,'mini',1080,172,140,72,42,C.ink,true,'Arial Black');
text(s,'기획 계기',64,362,300,36,23,C.blue,true);
text(s,'인턴 과제에서 개발한 전력 예측 모델을\n웹서비스에 연결해 배포와 운영까지 경험하고 싶었습니다.',64,416,1152,112,31,C.ink,true);
text(s,'전력 기록으로 다음 24시간을 예측하고, 사용 계획을 살펴보는 도구',64,574,1140,45,25,C.sub);
text(s,'01 / 07',1138,678,90,25,16,C.sub);
notes(s,'기획 계기와 7일 사이드프로젝트라는 맥락은 사용자 제공 설명에 근거한다. 인턴 과제에서 전력 예측 모델을 개발했고 웹서비스 연결과 배포·운영 경험을 목표로 확장했다. 배포 목표가 공개 배포 완료를 의미하지 않는다. 현재 server.py는 로컬 HTTP 서버이며 docs/README.md와 docs/mvp.md도 로컬 MVP로 명시한다.\n홈 디자인 참고: http://127.0.0.1:8765/의 실제 캡처 analysis/portfolio_build_20261106/home-current.png. 현재 홈 제목은 Arial Black 계열의 Energy Planner mini이며, 타이틀 색·큰 크기·넓은 좌우 여백을 재구성했다. 커밋 이력의 전체 날짜 범위를 정확히 7일이라고 주장하지 않는다.');
}
// 2. Actual product screenshot and the real user workflow.
{
const s=page(2,'서비스 개요와 실제 사용자 흐름','계량기 하나의 시간별 기록으로 24시간 예측과 운영 실험을 연결합니다');
const rows=[['01','CSV 업로드','timestamp, kwh'],['02','품질 진단','기간·결측·유효 표본'],['03','모델 학습·비교','Validation으로 방식 선택'],['04','24시간 예측','총량·피크 시간 확인'],['05','운영에 활용','보고서와 시간 변경 실험']];
rows.forEach((r,i)=>{const y=190+i*88;text(s,r[0],64,y,48,38,28,C.blue,true);text(s,r[1],124,y,245,35,25,C.ink,true);text(s,r[2],124,y+39,255,30,19,C.sub);});
text(s,'로컬 저장 run으로 생성한 예측 화면',418,168,760,30,19,C.sub);
await image(s,'forecast-core.png',412,205,805,438);
notes(s,'현재 사용자 흐름: frontend/index.html의 #upload, #training, #dashboard, #report, #simulator. JS startTraining/runPrediction/setupSimulatorOptions 및 backend/app/web/server.py의 API 경로 확인. 사용자는 CSV와 시간대를 입력하고 품질 진단 후 학습한다. 신규 학습은 XGBoost와 PatchTST를 함께 적합하며 두 모델·50:50 평균·Last-24h·Last-168h의 5후보를 같은 고정 평가 시점으로 비교한다. MAE 5% 개선, RMSE/WAPE 5% 악화 제한, 출력 유효성을 통과한 후보 중 Validation MAE 최저를 채택하며 모두 탈락하면 기준 예측을 쓴다. Test는 선택 확정 후 보고용으로 평가한다.\n실제 캡처 파일: analysis/portfolio_build_20261106/forecast-core.png. 캡처 URL http://127.0.0.1:8765/. 저장 job '+cap.job.job_id+', run '+cap.prediction.run_id+'. 새 학습 없이 기존 job 복원 후 저장 모델로 24시간 추론했다. 캡처에서 보이는 108.3kWh와 13시 피크는 이 저장 run의 예시이며 실건물 운영 성능의 일반화 지표가 아니다. 입력 CSV의 실측 출처는 이 캡처만으로 확정하지 않는다. 90일 미만 차단 및 90~179일 제한 실험 규칙은 docs/data_contract.md, docs/data_quality_policy.md, docs/training_spec.md에 있다.');
}
// 3. Actual simulator screenshot with hypothetical-rate provenance on-slide.
{
const s=page(3,'시간 변경 시뮬레이터','예측을 확인한 뒤, 작업 시간을 바꾸었을 때의 부하와 가상 비용을 비교합니다');
await image(s,'simulator-controls.png',64,180,806,226);
await image(s,'simulator-chart-current.png',64,422,806,230);
text(s,'작업 이동 예시',914,185,300,35,23,C.blue,true);
text(s,'1 kWh',914,231,300,60,46,C.ink,true);
text(s,'13시에서 18시로',914,302,300,40,26,C.ink,true);
text(s,'가상 단가 180원 / 110원',914,367,300,38,20,C.sub);
text(s,'70원 차이',914,419,300,60,40,C.green,true);
text(s,'입력 단가로 계산한 예시입니다.\n실제 요금·절감액은 아닙니다.',914,510,300,100,21,C.sub);
notes(s,'실제 화면 캡처: analysis/portfolio_build_20261106/simulator-controls.png 및 simulator-chart-current.png. 같은 저장 run의 예측을 브라우저에서 선택해 현재 simulator 계산 함수를 실행했다. 임의 HTML로 재현한 화면이 아니다. 웹 소스나 예측 원본을 수정하지 않고 브라우저의 입력값만 바꿨다.\n입력 예시: 2026-11-01 13시의 1kWh를 같은 날 18시로 이동. 기존 단가 180원/kWh, 변경 단가 110원/kWh. 이동 사용량에 대한 예시 비용 1×180=180원, 1×110=110원, 차이 70원. 수치는 가상 입력값의 산술 결과이며 실제 계약 요금제 또는 요금 절감을 검증한 결과가 아니다. 구현 근거 frontend/app.js: setupSimulatorOptions, updateSimulator, drawSimulatorChart. 원본 forecast 배열을 복사해 조정하고 원본 예측은 유지한다. 시간당 kWh 피크를 청구용 최대수요전력 kW와 같다고 취급하지 않는다. 관련 커밋 fb652db와 docs/spec.md 13절.');
}
// 4. Two source-backed modelling and data lessons, with synthetic-only metric.
{
const s=page(4,'시행착오 01  데이터와 모델 검증','데이터 품질과 학습 가능성을 나누고, 같은 평가 시점에서 개선을 확인했습니다');
text(s,'장기 결측으로 학습까지 차단',64,180,540,50,28,C.ink,true);
text(s,'문제',64,250,100,30,20,C.blue,true);
text(s,'연속 72시간 누락 때문에\n사용 가능한 기록까지 막혔습니다.',64,287,540,72,24);
text(s,'판단과 변경',64,382,200,30,20,C.blue,true);
text(s,'값을 채우지 않고 완전한 192시간\n표본만 남겨 학습 적합성을 판정했습니다.',64,419,540,90,24);
text(s,'확인',64,539,100,30,20,C.blue,true);
text(s,'Train 2,537개\nValidation·Test 평가창 각 22개',64,576,540,75,24,C.ink,true);
text(s,'초기 PatchTST의 수렴 한계',690,180,530,50,28,C.ink,true);
text(s,'문제',690,250,100,30,20,C.blue,true);
text(s,'최대 20 epoch에서 학습을 끝내\n추가 개선 여지가 남았습니다.',690,287,530,72,24);
text(s,'판단과 변경',690,382,200,30,20,C.blue,true);
text(s,'RevIN과 중첩 패치를 적용하고\n최대 80 epoch로 학습 여유를 늘렸습니다.',690,419,530,90,24);
text(s,'합성 Validation MAE 53.8% 감소',690,539,530,40,27,C.blue,true);
text(s,'0.2263에서 0.1045 kWh로 감소',690,583,530,32,23,C.ink,true);
text(s,'90일 합성 데이터 / 동일 평가 15시점\n실건물의 개선 효과는 별도 검증 필요',690,624,520,48,17,C.sub);
notes(s,'결측 사례 근거: 커밋 db8ce5e, backend/app/ml/sequences.py prepare_sequence_data/minimum_sample_reason_codes, backend/tests/web/test_missing_window_quality.py, docs/development_progress.md 2026-11-05 연속 결측 학습 적합성 진단 개선. 해당 기록은 최근 업로드 CSV의 최대 결측 72시간, Train 유효 2,537개, Validation dense 503개와 비중복 22개, Test 비중복 22개를 보고한다. 이 수치는 해당 데이터의 표본 수로, 모델 정확도 수치가 아니다.\nPatchTST 사례 근거: 커밋 45c1ac4, backend/app/ml/patchtst.py와 contracts.py, analysis/patchtst_performance_validation/results.json, backend/tests/ml/test_patchtst_pipeline.py. 비교 데이터는 backend/tests/ml/synthetic.py의 결정적 90일 합성 CSV, 동일 고정 Validation 비중복 15개 시점이다. 기존 설정은 patch24/stride24, RevIN 없음, 20epoch, lr0.001. 개선은 patch24/stride12, affine RevIN, 80epoch, patience12, lr0.0005, gradient clipping1.0. MAE 0.2263430198에서 0.1045272297kWh, 상대 감소53.8191%. RMSE0.350039에서0.182081, WAPE1.0335%에서0.4773%. 학습4.74초에서16.10초. 여러 설정을 함께 바꾼 결과이므로 RevIN만의 효과라고 주장하지 않는다. 합성 Validation 결과이며 Test 또는 실제 건물 성능을 보장하지 않는다. 이번 자료 제작 중 재학습은 하지 않았다. 당시 전체 회귀94/94 기록이 있다.');
}
// 5. Report reliability, distinct live diagnostic versus mock regression.
{
const s=page(5,'시행착오 02  AI 보고서 실패 복구','HTTP 200 응답만으로 보고서 완료를 판단하지 않았습니다');
const steps=[
['문제','화면에는 보고서가 없는데, API 응답은 HTTP 200이었습니다.'],
['판단','전송 성공과 보고서 완성을 나눠 실패 단계와 원인을 기록했습니다.'],
['변경','출력 한도·대기시간을 설정화하고, 429·timeout은 로컬 보고서로 복구했습니다.'],
['확인','실제 1회 진단으로 출력 한도 부족을 재현하고, 실패 재현 테스트로 예측 보존을 확인했습니다.']];
steps.forEach((r,i)=>{text(s,r[0],64,190+i*98,150,38,25,C.blue,true);text(s,r[1],244,190+i*98,962,70,25,C.ink,i===0);});
text(s,'1,200 출력 토큰 중 785 토큰을 추론에 사용',64,602,1140,43,31,C.ink,true);
text(s,'AI 문장 생성에 실패해도 기본 예측과 서버 정량 보고서를 제공합니다.',64,652,1080,30,21,C.sub);
notes(s,'근거 커밋 a1f6b5d(실패 단계/미완료 사유), 0b0fd0e(실측 출력 한도 원인), f19545d(transport timeout 진단), 2da216e(429 로컬 보고서 fallback). analysis/report_failure_validation/live-diagnostic-once.json의 승인된 실제1회: HTTP200, response_status incomplete, reason max_output_tokens, 출력1,200중 추론785토큰, stage response_status, validation failed. 출력한도4,096 설정과 timeout60초 조정은 docs/development_progress.md에 기록돼 있다. 이 설정을 적용한 모든 실제 호출이 성공했다고 주장하지 않는다.\nbackend/app/web/ai_analysis.py는 structured outputs와 근거 검증, timeout/오류 진단을 구현한다. backend/app/web/service.py analyze_prediction과 backend/tests/web/test_ai_analysis.py는 429,호출 한도,timeout 등에서 local report를 반환하도록 검증한다. 429 재현 검증은 모의 응답 테스트이며 실제 유료 API를 추가 호출하지 않았다. 과거 실제 성공 기록과 이후 실패 기록을 함께 확인했다. 자료 제작 시 외부 AI 호출0회. 프롬프트에 원본CSV 전체를 보내지 않고 서버집계·예측·근거만 보낸다.');
}
// 6. Editable native technology catalogue.
{
const s=page(6,'기술 스택과 구현 범위','최종 구현은 로컬 웹 MVP이며, 모델과 평가 결과를 저장해 다시 사용합니다');
table(s,[
['영역','확인한 기술','활용한 작업'],
['화면','HTML / CSS / JavaScript / SVG','단일 페이지, 예측 차트, 시간 변경 계산'],
['서버','Python http.server / threading','REST API, 학습 job 상태, 저장 run 추론'],
['데이터','pandas / NumPy / scikit-learn','시간대 정규화, 표본 생성, 구형 scaler 호환'],
['학습','XGBoost / PyTorch PatchTST','24개 horizon 회귀와 단일 채널 168→24 예측'],
['저장','joblib / .pth / JSON / SHA-256','재시작 복구, 파일 무결성, 구형 run 호환'],
['AI','OpenAI Responses / urllib','집계 근거 검증, 선택형 해석, 로컬 fallback'],
['검증','unittest / Chrome CDP / Git','ML·API·브라우저 회귀와 버전 관리'],
],64,178,1152,448,[120,420,612],21);
text(s,'초기 실험: PyTorch GRU, 현재는 읽기 호환 유지    실행: 로컬 완료 / 공개 배포 근거 없음',64,646,1140,32,19,C.sub);
notes(s,'최종 기술 근거 backend/requirements.txt, backend/app/web/server.py(ThreadingHTTPServer), service.py(threading.Thread/TrainingJobManager), backend/app/ml/model.py, patchtst.py, quality.py, sequences.py, artifacts.py, inference.py, legacy_gru.py, scaling.py 및 frontend/index.html/app.js/reference-system.css. XGBoost는24개 독립 horizon 회귀기이고 PatchTST는 kwh1채널168→24 direct 예측이다. scikit-learn StandardScaler는 주로 초기 GRU의 scaler/호환 경로에 사용하며, 신규 PatchTST scaler를 sklearn이라고 표현하지 않는다. SHA-256은 모델 run 불변 산출물 확인에 사용한다. OpenAI는 직접 urllib.request로 Responses API를 호출하며 OpenAI Python SDK를 쓰는 구현으로 표현하지 않는다. 실제 최종 서버는 FastAPI/Flask가 아니다.\n초기 실험 근거 backend/experiments/phase7_2_leon.py, phase7_6_danica.py, backend/app/ml/legacy_gru.py와 docs/development_progress.md. GRU를 현재 신규 학습 모델로 표현하지 않는다.\n로컬 실행·배포 구분: docs/README.md(127.0.0.1:8765 로컬 프로토타입), server.py 모듈 설명, docs/mvp.md 176행 부근. 인증·CSRF·사용자별 권한 격리·영속 실행 큐·운영 배포는 미완료/미확정이다. 사용자 기획 목표인 배포·운영 경험과 현재 공개 배포 완료를 구분한다.');
}
// 7. Tools and skill catalogue, separating install/reference/use.
{
const s=page(7,'바이브코딩 도구와 스킬 카탈로그','요구사항을 작게 나누고, 생성한 결과를 코드·테스트·실제 화면으로 확인했습니다');
table(s,[
['도구 / 스킬','어느 작업에 활용했나','확인 범위'],
['Codex','요구사항 정리, 코드 구현, 테스트와 수정 반복','개발 사용'],
['VS Code / PowerShell / Git','로컬 편집, 명령 실행, 커밋과 화면 원복','개발 사용'],
['Chrome CDP','실제 화면 캡처, 탭 전환과 반응형 검증','개발 사용'],
['frontend-design','아이보리·블루 화면의 시각 설계 지침 참조','설치·참조'],
['ui-ux-pro-max','탭·키보드·모바일 배치 기준 적용','설치·사용'],
['web-design-guidelines','웹 접근성과 레이아웃 점검 기준 참조','설치·참조'],
['computer-use','브라우저 점검·조작 관련 지침 참조','플러그인 참조'],
['presentations','편집 가능한 PPTX 제작과 렌더링 확인','자료 제작 사용'],
],64,178,1152,441,[300,632,220],21);
text(s,'내 역할: 문제 정의·변경 판단·결과 확인     AI의 역할: 구현과 반복 검증 지원',64,644,1140,34,21,C.ink,true);
notes(s,'개발 도구 근거: Git 커밋 이력, 사용자 IDE 컨텍스트(VS Code), Codex saved sessions의 실제 custom_tool_call, analysis/*/browser_qa.mjs와 backend/tests. 이 자료 제작도 Codex와 로컬 PowerShell/Node 실행을 사용했다.\n스킬 설치 근거: skills-lock.json에는 frontend-design(anthropics/skills), ui-ux-pro-max(nextlevelbuilder/ui-ux-pro-max-skill), web-design-guidelines(vercel-labs/agent-skills)3개가 고정돼 있다. 단순히 설치돼 있다는 사실과 실제 참조를 구분했다. 실제 참조 근거는 analysis/portfolio_build_20261106/skill-evidence.json에 session basename/시각/스킬명만 안전하게 추출했다. saved session rollout-2026-11-04T09-52-03-01a1a40a-a676-7e50-86f8-d4ba55bab30e.jsonl의 2026-11-04T00:53:07Z frontend-design/ui-ux-pro-max, 03:22:51Z 세 스킬, 06:15:13Z ui-ux/computer-use 지침 읽기 기록 등이 있다. frontend-design/web-design-guidelines/computer-use는 지침 참조가 확인된 범위로 기재하고, 해당 스킬의 모든 권장 작업을 실행했다고 주장하지 않는다. ui-ux-pro-max는 접이식 소개/탭/키보드/모바일 UI 작업에서 실제 적용된 대화·구현·검증이 있다.\ncomputer-use와 presentations는 프로젝트 skills-lock의 설치3개와 달리 세션 플러그인 스킬이다. presentations는 현재 포트폴리오 제작 단계에서 사용했으며 프로젝트 웹 개발 단계에서 사용했다고 주장하지 않는다. Replit/Cursor/v0/Figma/공개 배포 등은 현재 저장소에서 실사용 근거를 확보하지 못해 카탈로그에 넣지 않았다.');
}

if(p.slides.items.length!==7)throw new Error('Expected exactly seven slides');
for(let i=0;i<7;i++){
  const slide=p.slides.items[i];
  const png=await p.export({slide,format:'png',scale:1});
  await fs.writeFile(path.join(buildDir,'renders','slide-'+(i+1)+'.png'),new Uint8Array(await png.arrayBuffer()));
  await fs.writeFile(path.join(buildDir,'renders','slide-'+(i+1)+'.layout.json'),await (await slide.export({format:'layout'})).text());
}
await fs.writeFile(path.join(buildDir,'design-tokens.json'),JSON.stringify({source:'frontend/reference-system.css and live computed styles',colors:C,webFonts:cap.design,presentationFonts:['Malgun Gothic','Arial Black'],canvas:{width:1280,height:720}},null,2));
const candidatePath=path.join(buildDir,'draft','candidate.pptx');
await (await PresentationFile.exportPptx(p)).save(candidatePath);
console.log('Exported draft '+candidatePath);
await fs.mkdir(path.join(workspaceDir,'output'),{recursive:true});
const finalPath=path.join(workspaceDir,'output','energy-planner-portfolio.pptx');
const result=await finalizePresentation({workspaceDir,candidatePath,finalPath,
  explicitTotalSlideCount:7,requiredNativeTableOwnerSlides:[6,7],requiredNativeChartOwnerSlides:[],
  pythonExecutable:runtime+'/python/python.exe',
  integrityValidatorPath:SKILL_DIR+'/container_tools/inspect_presentation_package_integrity.py',
  layoutValidatorPath:SKILL_DIR+'/container_tools/inspect_presentation_layout_geometry.py',
  layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit','--require-native-table-slide','6','--require-native-table-slide','7'],
  fontPolicy:{basis:'design',families:['Malgun Gothic','Arial Black']},verifyArtifactToolImport:true,
  receiptPath:path.join(buildDir,'validation.json')});
console.log(JSON.stringify(result,null,2));
