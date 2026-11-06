const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "../..");
const html = fs.readFileSync(path.join(root, "frontend/index.html"), "utf8");
const script = fs.readFileSync(path.join(root, "frontend/app.js"), "utf8");
const hero = html.match(/<section class="hero[\s\S]*?<\/div><\/section>/)?.[0] || "";

const expectedTabs = ["01 에너지 플래너", "02 데이터 준비", "03 예측 보기", "04 운영에 활용"];
const expectedCopies = [
  "얼마나 많은 에너지가 언제 필요할지 예상하고, 그에 맞춰 사용 계획을 세우는 사람이나 도구를 뜻합니다.",
  "건물의 전력 기록으로 앞으로 24시간의 사용량을 예측하고, 전기를 많이 쓰는 작업의 시간을 옮겨볼 수 있습니다.",
  "건물 한 곳의 시간별 CSV",
  "향후 24시간 전력 사용량",
  "피크 시간에 잡힌 작업을 옮긴다면?",
];

for (const label of expectedTabs) assert.ok(hero.includes(label), `missing tab: ${label}`);
for (const copy of expectedCopies) assert.ok(hero.includes(copy), `missing copy: ${copy}`);
assert.equal((hero.match(/role="tab"/g) || []).length, 4);
assert.equal((hero.match(/role="tabpanel"/g) || []).length, 4);
assert.match(hero, /home-guide-tab-1[\s\S]*?aria-selected="true"/);
assert.match(hero, /home-guide-panel-2[\s\S]*?hidden/);
assert.ok(hero.includes("timestamp") && hero.includes("kwh"));
assert.ok(hero.includes('guide-example-badge">예시'));
assert.ok(hero.includes("15시") && hero.includes("18시"));
assert.ok(!hero.includes("XGBoost") && !hero.includes("PatchTST"));
assert.ok(html.includes("최소 90일 이상 데이터가 필요합니다."));
assert.ok(html.includes("XGBoost · PatchTST"));
assert.ok(html.includes("AI 전력 운영 보고서 생성"));
assert.ok(script.includes("function initHomeGuide()"));
assert.ok(script.includes('event.key === "ArrowRight"'));
assert.ok(script.includes('event.key === "Home"'));
assert.ok(hero.includes("처음 이용하는 분을 위한 미리보기"));
assert.ok(hero.includes("앞으로 24시간,<br>전기를 가장 많이 쓰는 때는?"));
assert.ok(hero.includes("에너지 플래너란?") && hero.includes("이 서비스에서는"));

console.log("home-guide: PASS");
