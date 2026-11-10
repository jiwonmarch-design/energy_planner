const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const source = fs.readFileSync(path.join(__dirname, "..", "app.js"), "utf8");
const start = source.indexOf("function apiUrl(");
const end = source.indexOf("\n}", start) + 2;

assert.notEqual(start, -1, "apiUrl must exist in app.js");

let apiBaseUrl = "";
eval(source.slice(start, end));

assert.equal(apiUrl("/api/health"), "/api/health");
apiBaseUrl = "https://api-energy-planner-mini.axworks.site";
assert.equal(
  apiUrl("/api/quality"),
  "https://api-energy-planner-mini.axworks.site/api/quality",
);

assert.match(source, /fetch\(apiUrl\(path\)/);
assert.doesNotMatch(source, /fetch\((?:`|\")\/api\//);

console.log("api-base-url: 4/4 PASS");
