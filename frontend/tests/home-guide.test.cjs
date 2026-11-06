const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "../..");
const html = fs.readFileSync(path.join(root, "frontend/index.html"), "utf8");
const script = fs.readFileSync(path.join(root, "frontend/app.js"), "utf8");
const css = fs.readFileSync(path.join(root, "frontend/reference-system.css"), "utf8");
const hero = html.match(/<section class="hero[\s\S]*?<\/div><\/section>/)?.[0] || "";

const expectedTabs = ["01 에너지 플래너", "02 데이터 준비", "03 예측 보기", "04 운영에 활용"];
const expectedCopies = [
  "에너지가 언제 얼마나 필요할지 예상하고, 사용 계획을 세우는 도구입니다.",
  "건물 한 곳의 시간별 전력 기록을 올립니다.",
  "앞으로 24시간 중 전기를 가장 많이 쓸 시간을 확인합니다.",
  "전기를 많이 쓰는 작업의 시간을 옮겨봅니다.",
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
assert.ok(css.includes(".home-guide-stage { min-height: 184px; }"));
assert.ok(css.includes(".home-guide-stage, .home-guide-panel { min-height: 300px; }"));

console.log("home-guide: PASS");
