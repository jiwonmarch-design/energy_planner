const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const frontend = path.join(__dirname, "..");
const html = fs.readFileSync(path.join(frontend, "index.html"), "utf8");
const source = fs.readFileSync(path.join(frontend, "app.js"), "utf8");
const css = fs.readFileSync(path.join(frontend, "reference-system.css"), "utf8");

assert.match(html, /id="sample-file"[^>]*aria-controls="sample-picker"/);
assert.match(html, /data-sample-id="synthetic"/);
assert.match(html, /data-sample-id="samdasoo"/);
assert.match(source, /synthetic-power-202604-202610\.csv/);
assert.match(source, /jeju-samdasoo-factory-2025\.csv/);
assert.match(source, /\$\("timezone"\)\.value = "Asia\/Seoul"/);
assert.match(source, /await readFile\(file, \{ sourceLabel: "샘플 CSV · Asia\/Seoul" \}\)/);
assert.doesNotMatch(source, /loadSampleCsv[\s\S]{0,1000}\$\("train"\)\.click/);
assert.match(css, /\.upload-choice-actions[^}]*grid-template-columns:\s*repeat\(2/);
assert.match(css, /\.upload-choice-actions[^}]*margin-top:\s*16px/);
assert.match(html, /reference-system\.css\?v=20261110-sample-spacing/);
assert.match(source, /fileInput\.onchange = \(\) =>/);
assert.match(source, /drop\.addEventListener\("drop"/);

for (const sample of ["synthetic-power-202604-202610.csv", "jeju-samdasoo-factory-2025.csv"]) {
  const csv = fs.readFileSync(path.join(frontend, "samples", sample), "utf8");
  assert.match(csv, /^\uFEFF?timestamp,kwh\r?\n/);
}

console.log("sample-loader: 15/15 PASS");
