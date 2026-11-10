const fs = require("node:fs");
const path = require("node:path");

const rawApiBaseUrl = String(process.env.API_BASE_URL || "").trim();

if (!rawApiBaseUrl) {
  throw new Error("API_BASE_URL environment variable is required.");
}

const apiBaseUrl = rawApiBaseUrl.replace(/\/+$/, "");
const parsedUrl = new URL(apiBaseUrl);

if (parsedUrl.protocol !== "https:") {
  throw new Error("API_BASE_URL must use HTTPS.");
}

const config = `window.ENERGY_PLANNER_CONFIG = Object.freeze(${JSON.stringify({ API_BASE_URL: apiBaseUrl })});\n`;
fs.writeFileSync(path.join(__dirname, "config.js"), config, "utf8");
console.log("Generated frontend runtime configuration.");
