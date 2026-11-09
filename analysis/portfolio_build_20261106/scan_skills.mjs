import fs from 'node:fs';
import path from 'node:path';
const root='C:/Users/aicam/.codex/sessions';
const matches=[];
function walk(dir){for(const d of fs.readdirSync(dir,{withFileTypes:true})){const f=path.join(dir,d.name);if(d.isDirectory())walk(f);else if(d.name.endsWith('.jsonl')){
  const data=fs.readFileSync(f,'utf8');if(!data.includes('energy-planner-mini'))continue;
  for(const line of data.split('\n')){let x;try{x=JSON.parse(line);}catch{continue;}const p=x.payload;if(!['function_call','custom_tool_call'].includes(p?.type))continue;const args=p.arguments||p.input||'';
    if(!/SKILL\.md/.test(args)||!/(Get-Content|read_file|cat |read.*skill)/i.test(args))continue;
    const skills=['frontend-design','ui-ux-pro-max','web-design-guidelines','portfolio-build','Presentations','presentations','computer-use','imagegen'].filter(s=>args.includes(s));
    if(skills.length)matches.push({session:path.basename(f),timestamp:x.timestamp,skills});
  }
}}}
walk(root);
fs.writeFileSync('analysis/portfolio_build_20261106/skill-evidence.json',JSON.stringify(matches,null,2));
console.log(JSON.stringify(matches,null,2));
