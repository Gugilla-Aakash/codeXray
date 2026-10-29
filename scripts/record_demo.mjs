#!/usr/bin/env node
/**
 * CodeXRay — demo recording (Phase 2).
 *
 * Plays the jury story end-to-end against a running stack and records it:
 * landing → gate → one-click demo → live pulse → evidence → ⚡inject → AI.
 *
 * Usage:
 *   node scripts/record_demo.mjs           # headless
 *   node scripts/record_demo.mjs --headed  # watch it live
 *
 * Requires: ./start.sh running (API :3101, web :3100).
 * Output:   docs/assets/*.png + a .webm next to them (git-ignored).
 */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(here, "..");
const require = createRequire(path.join(ROOT, "apps", "web", "package.json"));
const { chromium } = require("playwright-core");

const OUT = path.join(ROOT, "docs", "assets");
const BASE = process.env.DEMO_BASE_URL ?? "http://localhost:3100";
const headed = process.argv.includes("--headed");

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  await mkdir(OUT, { recursive: true });
  const browser = await chromium.launch({ headless: !headed });
  const context = await browser.newContext({
    viewport: { width: 1500, height: 950 },
    recordVideo: { dir: OUT, size: { width: 1500, height: 950 } },
  });
  const page = await context.newPage();
  const video = page.video();
  const done = [];
  const shot = async (name) => page.screenshot({ path: path.join(OUT, `${name}.png`) });
  const step = async (label, fn) => {
    console.log(`▶ ${label}`);
    await fn();
    done.push(label);
  };

  await step("landing", async () => {
    await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" });
    await wait(1800);
    await shot("01-landing");
  });

  await step("dashboard gate", async () => {
    await page.goto(`${BASE}/dashboard`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(".gate__demo", { timeout: 30000 });
    await wait(700);
    await shot("02-gate");
  });

  await step("one-click demo load", async () => {
    await page.click(".gate__demo");
    await page.waitForFunction(
      () => !!sessionStorage.getItem("codexray_project_id"),
      { timeout: 30000 }
    );
    await page.waitForSelector(".react-flow__node", { timeout: 30000 });
    await wait(1800);
    await shot("03-graph");
  });

  await step("live traffic pulse", async () => {
    await page.waitForSelector(".feed__row", { timeout: 30000 });
    await wait(4000);
    await shot("04-live-feed");
  });

  await step("incident evidence (span + signals)", async () => {
    await page.locator('section[aria-label="Incidents"] button.inc').first().click();
    await page.waitForSelector(".rc-box", { timeout: 15000 });
    await wait(900);
    await shot("05-evidence");
  });

  await step("inject failure", async () => {
    await page.click(".dash-inject");
    await page.waitForFunction(() => {
      const el = document.querySelector('section[aria-label="Incidents"]');
      return el && /2 open/.test(el.textContent || "");
    }, { timeout: 30000 });
    await wait(1200);
    await shot("06-injected");
  });

  await step("AI summary drawer", async () => {
    const btn = page.locator('button:has-text("AI Summary")');
    if ((await btn.count()) > 0) {
      await btn.first().click();
      await wait(1500);
    }
    await shot("07-ai-drawer");
  });

  await step("close on landing", async () => {
    await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" });
    await wait(1200);
    await shot("08-landing-close");
  });

  await context.close(); // finalizes the video file
  await browser.close();

  console.log("\n✓ demo recording complete");
  done.forEach((s, i) => console.log(`  ${i + 1}. ${s}`));
  if (video) {
    const file = await video.path();
    console.log(`  video:  ${path.relative(ROOT, file)}`);
  }
  console.log("  stills: docs/assets/0*.png");
}

main().catch((e) => {
  console.error("✗", e.message);
  process.exit(1);
});
