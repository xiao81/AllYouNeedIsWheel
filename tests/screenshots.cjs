/* Public screenshots: invented data only, isolated browser, all APIs intercepted.
   Run tests/preview.py first. This script refuses any other server or network. */
const { chromium } = require(process.env.WHEEL_NODE_MODULES + "/playwright");
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const origin = "http://127.0.0.1:8123";
const output = path.resolve(__dirname, "../docs/images");
const symbols = ["ALFA", "NOVA", "ORBT"]; // Fictional demo instruments.
const expiry = "20261009";
const profile = {
  host: "127.0.0.1",
  port: 7497,
  client_id: 1,
  account_id: "",
  platform: "tws",
  readonly: false,
};
const settings = {
  mode: "paper",
  revision: "fictional-demo",
  paper: profile,
  live: { ...profile, port: 7496, readonly: true },
};
const positions = symbols.flatMap((symbol, i) => [
  {
    symbol,
    security_type: "STK",
    position: 200 + i * 100,
    market_price: 80 + i * 40,
    market_value: (200 + i * 100) * (80 + i * 40),
    avg_cost: 72 + i * 40,
    unrealized_pnl: 1600 + i * 800,
  },
  {
    symbol,
    security_type: "OPT",
    option_type: i === 1 ? "CALL" : "PUT",
    expiration: expiry,
    strike: i === 1 ? 130 : 75 + i * 40,
    con_id: 100 + i,
    position: -(i + 1),
    market_price: 0.3 + i * 0.1,
    avg_cost: 55 + i * 15,
    market_value: -(30 + i * 10) * (i + 1),
    unrealized_pnl: 25 * (i + 1),
  },
]);
const orders = symbols.map((ticker, i) => ({
  id: i + 1,
  ticker,
  option_type: "PUT",
  action: "SELL",
  strike: 75 + i * 40,
  expiration: expiry,
  quantity: i + 1,
  premium: 0.4 + i * 0.1,
  limit_price: 0.4 + i * 0.1,
  order_type: "LIMIT",
  status: "pending",
}));
function scan(symbol, type = "PUT") {
  const i = symbols.indexOf(symbol),
    price = 80 + i * 40;
  const options = [0, 1].map((n) => ({
    symbol,
    option_type: type,
    expiration: expiry,
    strike: price + (type === "CALL" ? 5 + n * 5 : -10 + n * 5),
    bid: 0.24 + n * 0.16,
    ask: 0.3 + n * 0.2,
    mid: 0.27 + n * 0.18,
    delta: (type === "CALL" ? 1 : -1) * (n ? 0.075 : 0.056),
    implied_volatility: 0.25 + i * 0.04 + n * 0.01,
  }));
  return {
    symbol,
    stock_price: price,
    expiration: expiry,
    option_type: type,
    options,
    candidate: options[1],
    scanned: 24,
    elapsed_ms: 620,
    is_frozen: false,
  };
}
(async () => {
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({
    headless: true,
    channel: process.env.WHEEL_BROWSER_CHANNEL || undefined,
  });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1100 },
    deviceScaleFactor: 1,
  });
  await context.addInitScript(() => {
    localStorage.setItem(
      "wheel.watchlists.v2",
      JSON.stringify({
        PUT: ["ALFA", "NOVA", "ORBT"],
        CALL: ["ALFA", "NOVA", "ORBT"],
      }),
    );
    localStorage.setItem(
      "wheel.put-quantities.v1",
      JSON.stringify({ ALFA: 2, NOVA: 1, ORBT: 3 }),
    );
  });
  const blocked = [],
    errors = [];
  await context.route("**/*", async (route) => {
    const req = route.request(),
      url = new URL(req.url());
    if (url.origin !== origin) {
      blocked.push(req.url());
      return route.abort();
    }
    if (!url.pathname.startsWith("/api/")) {
      if (
        ["/", "/portfolio", "/settings", "/rollover"].includes(url.pathname) ||
        url.pathname.startsWith("/static/")
      )
        return route.continue();
      blocked.push(url.pathname);
      return route.abort();
    }
    const send = (data) =>
      route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(data),
      });
    if (req.method() !== "GET")
      throw new Error("Screenshot generation cannot mutate data");
    switch (url.pathname) {
      case "/api/settings":
        return send(settings);
      case "/api/portfolio/":
        return send({
          account_value: 250000,
          cash_balance: 45000,
          excess_liquidity: 125000,
          initial_margin: 75000,
          is_frozen: false,
        });
      case "/api/portfolio/positions":
        return send(positions);
      case "/api/portfolio/position-deltas":
        return send({
          deltas: [
            { con_id: 100, delta: -0.072 },
            { con_id: 101, delta: 0.083 },
            { con_id: 102, delta: -0.065 },
          ],
        });
      case "/api/portfolio/weekly-income":
        return send({
          total_income: 450,
          positions_count: 3,
          this_friday: "2026-10-09",
          positions: positions
            .filter((p) => p.security_type === "OPT")
            .map((p, i) => ({ ...p, income: 100 + i * 50 })),
        });
      case "/api/options/pending-orders":
        return send({ orders });
      case "/api/options/scan-batch":
        return send({
          results: url.searchParams
            .get("tickers")
            .split(",")
            .map((s) => scan(s, url.searchParams.get("type"))),
          target_delta: 0.075,
          target_friday: expiry,
          expirations: [expiry],
        });
      case "/api/options/expirations":
        return send({
          default_expiration: expiry,
          target_friday: expiry,
          expirations: [{ value: expiry }, { value: "20261016" }],
        });
      case "/api/options/scan":
        return send(
          scan(url.searchParams.get("ticker"), url.searchParams.get("type")),
        );
      default:
        throw new Error(`Unmocked screenshot endpoint: ${url.pathname}`);
    }
  });
  const page = await context.newPage();
  page.on("pageerror", (error) => errors.push(error.message));
  await page.clock.setFixedTime(new Date("2026-10-01T14:00:00Z"));
  async function label() {
    await page.evaluate(() => {
      const label = document.createElement("span");
      label.className = "badge neutral";
      label.textContent = "DEMO · FICTIONAL DATA";
      label.id = "demo-label";
      document.querySelector(".page-heading > div").append(label);
    });
  }
  async function capture(name) {
    assert.equal(await page.locator("#demo-label").count(), 1);
    await page.screenshot({ path: path.join(output, name), fullPage: true });
  }
  await page.goto(origin);
  await page.locator("[data-board-row]").first().waitFor();
  await page.locator("[data-assignment-cost]").first().waitFor();
  await label();
  await capture("overview-dark.png");
  await page.getByRole("button", { name: "Switch to light theme" }).click();
  await capture("overview-light.png");
  await page.getByRole("button", { name: "Switch to dark theme" }).click();
  await page.goto(origin + "/portfolio");
  await page
    .locator("[data-position-delta]")
    .filter({ hasText: "-0.072" })
    .waitFor();
  await label();
  await capture("portfolio-dark.png");
  await page.goto(origin + "/settings");
  await page.locator("#settings-form").waitFor();
  await page.getByRole("button", { name: "Switch to light theme" }).click();
  await label();
  await capture("settings-light.png");
  assert.deepEqual(blocked, []);
  assert.deepEqual(errors, []);
  await browser.close();
  console.log(
    "Created 4 screenshots using only fictional fixtures; no external network or account access.",
  );
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
