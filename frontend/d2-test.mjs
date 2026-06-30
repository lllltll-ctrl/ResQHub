import { chromium } from "@playwright/test";
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1600, height: 900 } });
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push("[pageerror] " + e.message));

await page.goto("http://localhost:3000/operations", { waitUntil: "networkidle" });
await page.waitForSelector(".leaflet-marker-icon", { timeout: 15000 });
await page.waitForTimeout(4000);
await page.screenshot({ path: "C:/Users/maksy/OneDrive/Робочий стіл/Orbit/d2-anomaly.png", fullPage: true });
const markerCount = await page.locator(".leaflet-marker-icon").count();
const resqMarkers = await page.locator(".resq-marker").count();
console.log(JSON.stringify({ markerCount, resqMarkers, errors }, null, 2));
await browser.close();
