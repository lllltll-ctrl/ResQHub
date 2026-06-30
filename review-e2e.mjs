import { chromium } from "@playwright/test";
import * as fs from "node:fs";

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1600, height: 900 } });
const page = await ctx.newPage();

const consoleErrors = [];
page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
page.on("pageerror", (e) => consoleErrors.push("[pageerror] " + e.message));

// 1. Operations
await page.goto("http://localhost:3000/operations", { waitUntil: "networkidle" });
await page.waitForSelector(".leaflet-marker-icon", { timeout: 15000 });
await page.screenshot({ path: "C:/Users/maksy/OneDrive/Робочий стіл/Orbit/review-ops.png", fullPage: true });
const opsMarkers = await page.locator(".leaflet-marker-icon").count();

await page.locator("main table tbody tr").first().click();
await page.waitForTimeout(500);
const drawerVisible = await page.getByText("Деталі об'єкта").isVisible();
const assignBtnVisible = await page.getByText("Направити ресурс").isVisible();

await page.getByRole("button", { name: /Симулювати блекаут/ }).click();
await page.waitForTimeout(2500);
const activeBanner = await page.locator("text=/Active scenario/i").first().isVisible();

// 2. Analytics
await page.goto("http://localhost:3000/analytics", { waitUntil: "networkidle" });
await page.waitForTimeout(1500);
await page.screenshot({ path: "C:/Users/maksy/OneDrive/Робочий стіл/Orbit/review-analytics.png", fullPage: true });
const analyticsHeadings = await page.locator("h1, h2, h3").allInnerTexts();
const hasForecastByDistrict = await page.getByText("Прогноз автономності по районах").isVisible();
const hasKpi1 = await page.getByText("Average Resilience Index").isVisible();
const trendSvg = await page.locator("svg:has(path)").count();

// 3. Resident
await page.goto("http://localhost:3000/resident", { waitUntil: "networkidle" });
await page.waitForTimeout(2000);
await page.screenshot({ path: "C:/Users/maksy/OneDrive/Робочий стіл/Orbit/review-resident.png", fullPage: true });
const resMarkers = await page.locator(".leaflet-marker-icon").count();
const nearestCard = await page.getByText(/Найближчий пункт до вас/).isVisible();

const filterAllCount = await page.locator("button:has-text('Всі')").count();
await page.getByRole("button", { name: /Світло/ }).click();
await page.waitForTimeout(800);
const afterFilterMarkers = await page.locator(".leaflet-marker-icon").count();

// 4. WS sanity
const wsOk = await page.evaluate(() => new Promise((res) => {
  const ws = new WebSocket("ws://localhost:8000/api/ws/stream");
  let got = 0;
  ws.onmessage = () => {
    got += 1;
    if (got >= 2) { ws.close(); res(true); }
  };
  ws.onerror = () => res(false);
  setTimeout(() => res(got > 0), 8000);
}));

// 5. Assignment flow
await page.goto("http://localhost:3000/operations", { waitUntil: "networkidle" });
await page.waitForTimeout(2000);
await page.locator("main table tbody tr").first().click();
await page.waitForTimeout(500);
const firstAssignBtn = page.getByRole("button", { name: /Генератор/ }).first();
const assignDisabled = await firstAssignBtn.isDisabled();
await firstAssignBtn.click().catch(() => {});
await page.waitForTimeout(1000);
const toastVisible = await page.locator("text=/Направлено/").first().isVisible().catch(() => false);
const drawerAfterAssign = await page.getByText("Деталі об'єкта").isVisible();

// Dashboard after assignment
const dashAfter = await (await fetch("http://localhost:8000/api/dashboard")).json();
const assignments = await (await fetch("http://localhost:8000/api/assignments")).json();
const events = await (await fetch("http://localhost:8000/api/events?limit=5")).json();

await browser.close();

const report = {
  ops_markers_count: opsMarkers,
  drawer_visible: drawerVisible,
  assign_section_visible: assignBtnVisible,
  active_scenario_banner: activeBanner,
  analytics_headings: analyticsHeadings,
  has_kpi_average_resilience: hasKpi1,
  has_forecast_by_district: hasForecastByDistrict,
  trend_svgs: trendSvg,
  res_markers_count: resMarkers,
  nearest_card_visible: nearestCard,
  filter_all_button_count: filterAllCount,
  markers_after_light_filter: afterFilterMarkers,
  ws_works: wsOk,
  assign_btn_disabled_in_drawer: assignDisabled,
  toast_after_assign: toastVisible,
  drawer_still_open_after_assign: drawerAfterAssign,
  dashboard_after: dashAfter,
  assignments_count: assignments.length,
  last_assignments: assignments.slice(0, 2),
  events_count: events.length,
  last_events: events.slice(0, 3),
  console_errors: consoleErrors,
};
fs.writeFileSync(
  "C:/Users/maksy/OneDrive/Робочий стіл/Orbit/review-report.json",
  JSON.stringify(report, null, 2),
);
console.log(JSON.stringify(report, null, 2));
