/* Offline browser regression: every API response is intercepted test data. */
const { chromium } = require(process.env.WHEEL_NODE_MODULES + "/playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
(async () => {
  const browser = await chromium.launch({
    headless: true,
    channel: process.env.WHEEL_BROWSER_CHANNEL || undefined,
  });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1100 },
  });
  await context.addInitScript(() => {
    if (!localStorage.getItem("customTickers"))
      localStorage.setItem(
        "customTickers",
        JSON.stringify(["AAPL", "NVDA", "MSFT"]),
      );
  });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  let failExecuteId = null,
    failCancelId = null;
  let failSubmit = false,
    failPortfolio = false;
  let settings = {
    mode: "paper",
    paper: {
      platform: "tws",
      host: "127.0.0.1",
      port: 7497,
      client_id: 1,
      readonly: false,
      account_id: "DEMOACCOUNT",
    },
    live: {
      platform: "tws",
      host: "127.0.0.1",
      port: 7496,
      client_id: 2,
      readonly: true,
      account_id: "",
    },
  };
  const positions = [
    {
      symbol: "AAPL",
      position: 200,
      market_price: 228.5,
      market_value: 45700,
      avg_cost: 201.3,
      unrealized_pnl: 5440,
      security_type: "STK",
    },
    {
      symbol: "NVDA",
      position: 100,
      market_price: 143.7,
      market_value: 14370,
      avg_cost: 112,
      unrealized_pnl: 3170,
      security_type: "STK",
    },
    {
      symbol: "MSFT",
      position: 100,
      market_price: 432.2,
      market_value: 43220,
      avg_cost: 415,
      unrealized_pnl: 1720,
      security_type: "STK",
    },
    {
      symbol: "AAPL",
      position: -2,
      market_price: 0.42,
      market_value: -84,
      avg_cost: 97,
      unrealized_pnl: 110,
      security_type: "OPT",
      option_type: "PUT",
      con_id: 777,
      strike: 210,
      expiration: "20260918",
    },
  ];
  let orders = [
    {
      id: 1,
      ticker: "AAPL",
      option_type: "PUT",
      action: "SELL",
      strike: 210,
      expiration: "20260918",
      quantity: 2,
      premium: 0.97,
      limit_price: 0.97,
      order_type: "LIMIT",
      status: "pending",
    },
    {
      id: 2,
      ticker: "NVDA",
      option_type: "CALL",
      action: "SELL",
      strike: 155,
      expiration: "20260918",
      quantity: 1,
      premium: 0.38,
      limit_price: 0.38,
      order_type: "LIMIT",
      status: "processing",
      ib_order_id: 4021,
    },
  ];
  const requests = [];
  await page.route("**/api/**", async (route) => {
    const req = route.request(),
      url = new URL(req.url());
    requests.push({
      path: url.pathname,
      query: Object.fromEntries(url.searchParams),
      method: req.method(),
      body: req.postDataJSON(),
    });
    const send = (data, status = 200) =>
      route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(data),
      });
    if (url.pathname === "/api/settings") {
      if (req.method() === "PUT") settings = req.postDataJSON();
      return send(settings);
    }
    if (url.pathname === "/api/settings/test")
      return send({
        success: true,
        message: "Connection verified. No orders were placed.",
        accounts: ["DEMOACCOUNT"],
      });
    if (url.pathname === "/api/portfolio/")
      return failPortfolio
        ? send({ error: "Broker unavailable" }, 503)
        : send({
            account_value: 148920.45,
            cash_balance: 42630.12,
            excess_liquidity: 68240.3,
            initial_margin: 25150,
            is_frozen: true,
          });
    if (url.pathname === "/api/portfolio/positions") return send(positions);
    if (url.pathname === "/api/portfolio/position-deltas")
      return send({ deltas: [{ con_id: 777, delta: -0.074 }] });
    if (url.pathname === "/api/portfolio/weekly-income")
      return send({
        total_income: 386,
        positions_count: 3,
        this_friday: "2026-09-18",
        positions: [
          {
            symbol: "AAPL",
            option_type: "PUT",
            strike: 210,
            position: -2,
            income: 194,
          },
          {
            symbol: "NVDA",
            option_type: "CALL",
            strike: 155,
            position: -1,
            income: 72,
          },
          {
            symbol: "MSFT",
            option_type: "PUT",
            strike: 400,
            position: -1,
            income: 120,
          },
        ],
      });
    if (url.pathname === "/api/options/expirations")
      return send({
        ticker: url.searchParams.get("ticker"),
        default_expiration: "20260918",
        target_friday: "20260918",
        expirations: [
          { value: "20260918" },
          { value: "20260925" },
          { value: "20261002" },
        ],
      });
    if (url.pathname === "/api/options/scan-batch") {
      const results = url.searchParams
        .get("tickers")
        .split(",")
        .map((symbol) => {
          if (symbol === "MSFT")
            return {
              symbol,
              error: "No listed contracts for the selected expiration",
            };
          const candidate = {
            symbol,
            strike: 210,
            expiration: url.searchParams.get("expiration") || "20260918",
            option_type: url.searchParams.get("type"),
            bid: 0.9,
            ask: 1.04,
            mid: 0.97,
            delta: -0.074,
            implied_volatility: 0.284,
          };
          return {
            symbol,
            stock_price: 228.5,
            candidate,
            options: [
              candidate,
              {
                ...candidate,
                strike: 205,
                delta: -0.06,
                mid: 0.7,
                implied_volatility: null,
              },
              { ...candidate, strike: 190, ask: null, mid: null },
            ],
            expiration: candidate.expiration,
            scanned: 24,
            is_frozen: true,
          };
        });
      return send({
        results,
        target_delta: 0.075,
        target_friday: "20260918",
        expirations: ["20260918", "20260925"],
      });
    }
    if (url.pathname === "/api/options/orders/batch") {
      const saved = req.postDataJSON().orders.map((order) => {
        const entry = { ...order, id: orders.length + 1, status: "pending" };
        orders.push(entry);
        return entry.id;
      });
      return send({ success: true, order_ids: saved }, 201);
    }
    if (url.pathname === "/api/options/scan") {
      const ticker = url.searchParams.get("ticker"),
        type = url.searchParams.get("type"),
        expiry = url.searchParams.get("expiration") || "20260918";
      return send({
        symbol: ticker,
        stock_price: 228.5,
        option_type: type,
        expiration: expiry,
        target_friday: "20260918",
        scanned: 24,
        missing_greeks: 0,
        elapsed_ms: 1840,
        is_frozen: true,
        options: [
          {
            strike: 210,
            expiration: expiry,
            option_type: type,
            bid: 0.9,
            ask: 1.04,
            mid: 0.97,
            delta: type === "CALL" ? 0.074 : -0.074,
            implied_volatility: 0.284,
          },
          {
            strike: 207.5,
            expiration: expiry,
            option_type: type,
            bid: 0.66,
            ask: 0.76,
            mid: 0.71,
            delta: type === "CALL" ? 0.061 : -0.061,
            implied_volatility: 0.291,
          },
          {
            strike: 212.5,
            expiration: expiry,
            option_type: type,
            bid: 1.14,
            ask: 1.3,
            mid: 1.22,
            delta: type === "CALL" ? 0.093 : -0.093,
            implied_volatility: 0.279,
          },
        ],
      });
    }
    if (url.pathname === "/api/options/pending-orders")
      return send({
        orders: url.searchParams.has("isRollover")
          ? orders.filter((o) => o.isRollover)
          : orders,
      });
    if (url.pathname === "/api/options/orders/prepare-submission")
      return send({
        orders: req
          .postDataJSON()
          .order_ids.map((id) => orders.find((o) => o.id === id)),
      });
    if (url.pathname === "/api/options/check-orders")
      return send({ success: true, updated_orders: [] });
    if (url.pathname === "/api/options/order") {
      const order = {
        id: orders.length + 1,
        ...req.postDataJSON(),
        status: "pending",
      };
      orders.push(order);
      return send({ success: true, order_id: order.id }, 201);
    }
    if (url.pathname.startsWith("/api/options/execute/")) {
      if (Number(url.pathname.split("/").pop()) === failExecuteId)
        return send({ error: "Test broker failure" }, 502);
      if (failSubmit) return send({ error: "Read-only connection" }, 403);
      orders.find(
        (o) => o.id === Number(url.pathname.split("/").pop()),
      ).status = "processing";
      return send({ success: true, ib_order_id: 99 });
    }
    if (url.pathname.endsWith("/local") && req.method() === "DELETE") {
      assert.equal(req.postDataJSON().confirm_local_only, true);
      orders = orders.filter(
        (o) => o.id !== Number(url.pathname.split("/").at(-2)),
      );
      return send({ success: true });
    }
    if (url.pathname.endsWith("/draft") && req.method() === "DELETE") {
      const id = Number(url.pathname.split("/").at(-2));
      if (id === failCancelId)
        return send({ error: "Test cancellation failure" }, 502);
      const order = orders.find((o) => o.id === id);
      assert.equal(order.status, "pending");
      orders = orders.filter((o) => o.id !== id);
      return send({ success: true, status: "canceled" });
    }
    if (url.pathname.startsWith("/api/options/cancel/")) {
      const id = Number(url.pathname.split("/").pop());
      if (id === failCancelId)
        return send({ error: "Test cancellation failure" }, 502);
      const order = orders.find((o) => o.id === id);
      if (order.status !== "pending") {
        order.status = "canceling";
        return send({ success: true, status: "canceling" });
      }
      orders = orders.filter(
        (o) => o.id !== Number(url.pathname.split("/").pop()),
      );
      return send({ success: true });
    }
    if (url.pathname === "/api/options/rollover") {
      const data = req.postDataJSON();
      assert.equal(data.current_limit_price, 0.42);
      assert.equal(data.new_limit_price, 0.97);
      return send({ success: true, buy_order_id: 10, sell_order_id: 11 }, 201);
    }
    if (url.pathname.endsWith("/quantity")) return send({ success: true });
    return send({ error: "Unexpected test request: " + url.pathname }, 500);
  });
  async function chooseExpiry(value) {
    await page.locator("#expiry-trigger").click();
    const target = value.slice(0, 7);
    for (let i = 0; i < 120; i++) {
      const month = await page
        .locator("#calendar-month")
        .getAttribute("data-month");
      if (month === target) break;
      await page
        .getByRole("button", {
          name: month < target ? "Next month" : "Previous month",
          exact: true,
        })
        .click();
    }
    await page.locator('#expiry-calendar [data-date="' + value + '"]').click();
  }
  await page.goto("http://127.0.0.1:8123/");
  await page.getByRole("button", { name: "Add selected to queue" }).waitFor();
  const defaultExpiry = await page.evaluate(async () =>
    (await import("/static/js/ui.js")).friday(1),
  );
  assert.equal(
    (await page.locator("#expiry-select").inputValue()).replaceAll("-", ""),
    defaultExpiry,
  );
  await page.locator("[data-assignment-cost]").first().waitFor();
  assert.equal(
    await page.locator("[data-assignment-cost]").first().textContent(),
    "$42,000.00",
  );
  assert.equal(
    await page.locator("[data-assignment-cost]").nth(1).textContent(),
    "—",
  );

  assert.equal(
    await page.getByRole("columnheader", { name: "IV", exact: true }).count(),
    1,
  );
  assert.deepEqual(await page.locator("[data-board-iv]").allTextContents(), [
    "—",
    "28.4%",
    "—",
    "28.4%",
  ]);
  assert.equal(await page.locator("[data-board-select]:checked").count(), 2);
  await page
    .getByText("No listed contracts for the selected expiration", {
      exact: true,
    })
    .waitFor();
  assert.equal(await page.locator("#put-price-note").count(), 0);
  const batch = requests.find((r) => r.path === "/api/options/scan-batch");
  assert.equal(batch.query.tickers, "AAPL,NVDA,MSFT");
  assert.equal(batch.query.delta_min, "0.05");
  assert.equal(batch.query.delta_max, "0.1");
  await chooseExpiry("2026-09-25");
  assert.equal(await page.locator("[data-board-save]").count(), 0);
  await page.getByRole("button", { name: "Find options", exact: true }).click();
  await page.locator("[data-board-row]").first().waitFor();
  assert.equal(await page.locator("[data-board-row]").count(), 4);
  assert.equal(await page.locator(".best-label").count(), 2);
  assert.equal(await page.getByText(/1 incomplete quotes hidden/).count(), 2);
  assert.equal(
    await page
      .getByText("Two-sided quote unavailable", { exact: true })
      .count(),
    0,
  );
  await page.locator('[data-board-select="1"]').uncheck();
  await page.locator('[data-board-select="0"]').check();
  await page.locator('[data-board-quantity="0"]').fill("2");
  await page.locator('[data-board-quantity="0"]').blur();
  fs.mkdirSync("/tmp/wheel-ui", { recursive: true });
  await page.screenshot({
    path: "/tmp/wheel-ui/watchlist-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  assert.ok(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  );
  await page.screenshot({
    path: "/tmp/wheel-ui/watchlist-mobile.png",
    fullPage: false,
  });
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.getByRole("button", { name: "Add selected to queue" }).click();
  await page.locator('[data-quantity="4"]').waitFor();
  const bulk = requests.find((r) => r.path === "/api/options/orders/batch").body
    .orders;
  assert.equal(bulk.length, 2);
  assert.equal(bulk[0].strike, 205);
  assert.equal(bulk[0].quantity, 2);
  assert.equal(bulk[0].expiration, "20260925");
  assert.equal(bulk[0].limit_price, 0.7);
  assert.equal(
    requests.some((r) => r.path.startsWith("/api/options/execute/")),
    false,
  );
  await chooseExpiry("2026-09-18");
  await page.locator("#scan-scope").selectOption("single");
  await page.getByRole("button", { name: "+ Add to queue" }).first().waitFor();
  const scan = requests.find((r) => r.path === "/api/options/scan");
  assert.equal(scan.query.delta_min, "0.05");
  assert.equal(scan.query.delta_max, "0.1");
  assert.equal(scan.query.expiration, "20260918");

  fs.mkdirSync("/tmp/wheel-ui", { recursive: true });
  await page.screenshot({
    path: "/tmp/wheel-ui/dashboard-desktop.png",
    fullPage: true,
  });
  await chooseExpiry("2026-09-25");
  await page.getByRole("button", { name: "Find options", exact: true }).click();
  await page.getByRole("button", { name: "+ Add to queue" }).first().waitFor();
  assert.equal(
    requests.filter((r) => r.path === "/api/options/scan").at(-1).query
      .expiration,
    "20260925",
  );
  await page.locator('[data-save-option="1"]').click();
  await page.locator('[data-quantity="5"]').waitFor();
  assert.equal(orders.at(-1).limit_price, 0.97);
  assert.equal(orders.at(-1).quantity, 2);
  failSubmit = true;
  await page.locator('[data-submit="1"]').click();
  await page.getByRole("button", { name: "Submit paper order" }).waitFor();
  assert.match(
    await page.locator("#dialog-content").innerText(),
    /Assignment cost[\s\S]*\$42,000.00/,
  );
  await page.getByRole("button", { name: "Submit paper order" }).click();
  await page.getByText("Read-only connection", { exact: true }).waitFor();
  assert.equal(orders[0].status, "pending");
  assert.equal(
    await page
      .locator("#orders-content")
      .locator("..")
      .locator(":scope > .inline-error")
      .count(),
    1,
  );
  assert.equal(await page.locator(".toast, #notifications").count(), 0);
  assert.equal(
    await page.getByText("Order submitted. Tracking broker status.").count(),
    0,
  );
  // Existing calls can use all shares without preventing a new call draft.
  positions.push({
    ...positions[3],
    option_type: "CALL",
    strike: 240,
  });
  await page.locator("#refresh-workspace").click();
  await page.locator("#refresh-workspace:not([disabled])").waitFor();
  await page.locator('[data-strategy="CALL"]').click();
  await page.getByText(/Spare coverage: 0 contracts/).waitFor();
  assert.equal(
    await page
      .getByRole("columnheader", { name: "Put breakeven", exact: true })
      .count(),
    0,
  );
  assert.equal(await page.locator("[data-put-breakeven]").count(), 0);
  const callDraft = page.locator('[data-save-option="1"]');
  assert.equal(await callDraft.isEnabled(), true);
  const callSaved = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/options/order") &&
      response.request().method() === "POST",
  );
  await callDraft.click();
  await callSaved;
  assert.equal(orders.at(-1).quantity, 2);
  assert.equal(orders.at(-1).option_type, "CALL");
  assert.equal(orders.at(-1).limit_price, 0.97);
  positions.pop();
  assert.equal(await page.locator('[data-cancel="2"]').count(), 0);
  await page
    .getByText("Manage cancellation in IBKR", { exact: true })
    .first()
    .waitFor();
  await page.locator('[data-remove-local="2"]').click();
  await page.getByText(/This does not cancel the order at IBKR/).waitFor();
  await page
    .getByRole("button", { name: "Remove local record", exact: true })
    .click();
  await page.locator('[data-remove-local="2"]').waitFor({ state: "detached" });
  assert.equal(
    orders.some((o) => o.id === 2),
    false,
  );
  assert.equal(
    requests.some((r) => r.path === "/api/options/cancel/2"),
    false,
  );
  failPortfolio = true;
  await page.locator("#refresh-workspace").click();
  await page.getByText("Broker unavailable", { exact: true }).first().waitFor();
  assert.equal(await page.locator("#net-value").textContent(), "—");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "/tmp/wheel-ui/dashboard-mobile.png",
    fullPage: true,
  });
  assert.ok(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  );
  await page.goto("http://127.0.0.1:8123/settings");
  await page.getByRole("button", { name: "Save settings" }).waitFor();
  await page.screenshot({
    path: "/tmp/wheel-ui/settings-mobile.png",
    fullPage: true,
  });
  assert.ok(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  );
  await page
    .getByRole("button", { name: "Live trading Your real brokerage account" })
    .click();
  await page.locator('select[name="platform"]').selectOption("gateway");
  assert.equal(await page.locator('input[name="port"]').inputValue(), "4001");
  await page.getByRole("button", { name: "Save settings" }).click();
  await page
    .locator("#save-hint")
    .filter({ hasText: /^Saved$/ })
    .waitFor();
  assert.equal(settings.mode, "live");
  assert.ok((await page.locator("#mode-badge").textContent()).includes("LIVE"));
  await page.getByRole("button", { name: "Test connection" }).click();
  await page.getByText(/Connection verified/).waitFor();
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.screenshot({
    path: "/tmp/wheel-ui/settings-desktop.png",
    fullPage: true,
  });
  await page.goto("http://127.0.0.1:8123/portfolio");
  await page.locator('[data-position-body="OPT"] tbody tr').first().waitFor();
  await page
    .locator("[data-position-delta]")
    .filter({ hasText: "-0.074" })
    .waitFor();
  assert.equal(
    await page
      .locator('[data-position-body="STK"] [data-position-delta]')
      .count(),
    0,
  );
  const positionReads = requests.filter(
    (r) => r.path === "/api/portfolio/positions",
  ).length;
  const stockRows = await page
    .locator('[data-position-body="STK"] tbody tr')
    .count();
  const optionRows = await page
    .locator('[data-position-body="OPT"] tbody tr')
    .count();
  assert.equal(await page.locator("#expiry-select").inputValue(), "");
  await chooseExpiry("2026-09-18");
  assert.equal(
    await page.locator('[data-position-body="OPT"] tbody tr').count(),
    optionRows,
  );
  await chooseExpiry("2026-09-25");
  await page
    .getByText("No options expiring Sep 25, 2026.", { exact: true })
    .waitFor();
  assert.equal(
    await page.locator('[data-position-body="STK"] tbody tr').count(),
    stockRows,
  );
  assert.equal(
    requests.filter((r) => r.path === "/api/portfolio/positions").length,
    positionReads,
  );
  await page.locator("#refresh-portfolio").click();
  await page.locator("#refresh-portfolio:not([disabled])").waitFor();
  assert.equal(await page.locator("#expiry-select").inputValue(), "2026-09-25");
  await page.locator("#expiry-trigger").click();
  await page.locator("[data-clear-expiry]").click();
  assert.equal(
    await page.locator('[data-position-body="OPT"] tbody tr').count(),
    optionRows,
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator("#expiry-trigger").click();
  const portfolioCalendar = await page
    .locator("#expiry-calendar")
    .boundingBox();
  assert(
    portfolioCalendar.x >= 0 &&
      portfolioCalendar.x + portfolioCalendar.width <= 390,
  );
  await page.screenshot({
    path: "/tmp/wheel-ui/portfolio-calendar-mobile.png",
  });
  await page.keyboard.press("Escape");
  await page.setViewportSize({ width: 1440, height: 1100 });

  await page.getByText("Stock positions", { exact: false }).first().waitFor();
  await page.screenshot({
    path: "/tmp/wheel-ui/portfolio-desktop.png",
    fullPage: true,
  });
  await page.goto("http://127.0.0.1:8123/rollover");
  await page.getByRole("button", { name: "Explore roll →" }).click();
  await page.getByRole("button", { name: "Add both drafts" }).first().waitFor();
  assert.equal(await page.locator("#roll-expiry").inputValue(), "20260925");
  const rolloverSaved = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/options/rollover") &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Add both drafts" }).first().click();
  await rolloverSaved;
  await page.screenshot({
    path: "/tmp/wheel-ui/rollover-desktop.png",
    fullPage: true,
  });
  // Exercise progressive NDJSON delivery, including a split network chunk.
  await page.goto("http://127.0.0.1:8123/");
  await page.locator("[data-board-row]").first().waitFor();
  await page.locator("#scan-button:not([disabled])").waitFor();
  await page.evaluate(async () => {
    const { streamScan } = await import("/static/js/api.js");
    const { renderBoard } = await import("/static/js/scan-board.js");
    const root = document.querySelector("#scan-result");
    const board = renderBoard(root, {
      option_type: "CALL",
      results: [
        { symbol: "AAPL", loading: true },
        { symbol: "MSFT", loading: true },
      ],
      target_delta: 0.075,
      quantities: { AAPL: 3, MSFT: 1 },
    });
    const option = {
      strike: 100,
      expiration: "20990116",
      option_type: "CALL",
      mid: 1,
      bid: 0.9,
      ask: 1.1,
      delta: 0.075,
    };
    const first = {
      symbol: "AAPL",
      expiration: "20990116",
      options: [option, { ...option, strike: 95, delta: 0.09 }],
      candidate: option,
    };
    const second = { ...first, symbol: "MSFT" };
    const original = window.fetch;
    const encoder = new TextEncoder();
    let stream;
    window.fetch = (url, ...args) =>
      url === "/__stream-fixture"
        ? Promise.resolve(
            new Response(
              new ReadableStream({
                start(controller) {
                  stream = controller;
                },
              }),
              { headers: { "Content-Type": "application/x-ndjson" } },
            ),
          )
        : original(url, ...args);
    window.progressiveDone = streamScan("/__stream-fixture", (row) =>
      board.add(row),
    )
      .then((data) => data.results.forEach((row) => board.add(row)))
      .finally(() => (window.fetch = original));
    await Promise.resolve();
    const firstLine = encoder.encode(
      JSON.stringify({ type: "result", result: first }) + "\n",
    );
    stream.enqueue(firstLine.slice(0, 20));
    stream.enqueue(firstLine.slice(20));
    window.finishProgressive = () => {
      stream.enqueue(
        encoder.encode(
          JSON.stringify({ type: "result", result: second }) + "\n",
        ),
      );
      stream.enqueue(
        encoder.encode(
          JSON.stringify({
            type: "complete",
            data: { results: [first, second] },
          }) + "\n",
        ),
      );
      stream.close();
    };
  });
  await page
    .getByText("1 / 2 symbols complete · 2 matching contracts", { exact: true })
    .waitFor();
  await page
    .locator('[aria-label="Loading options for MSFT"] .symbol-loading-ring')
    .waitFor();
  assert.equal(
    await page.locator('[data-board-quantity="0"]').inputValue(),
    "3",
  );
  assert.match(await page.locator('[data-board-row="0"]').innerText(), /95.00/);
  assert.match(
    await page.locator('[data-board-row="1"]').innerText(),
    /100.00/,
  );
  await page.locator('[data-board-quantity="0"]').fill("4");
  await page.locator('[data-board-quantity="0"]').blur();
  await page.locator('[data-board-select="0"]').check();
  await page.evaluate(
    () =>
      (window.earlierInput = document.querySelector(
        '[data-board-quantity="0"]',
      )),
  );
  await page.screenshot({
    path: "/tmp/wheel-ui/progressive-scan.png",
    fullPage: true,
  });
  await page.evaluate(() => window.finishProgressive());
  await page.evaluate(() => window.progressiveDone);
  await page
    .getByText("2 / 2 symbols complete · 4 matching contracts", { exact: true })
    .waitFor();
  assert.equal(
    await page.locator('[data-board-quantity="0"]').inputValue(),
    "4",
  );
  assert.equal(await page.locator('[data-board-select="0"]').isChecked(), true);
  assert.equal(
    await page.evaluate(
      () =>
        window.earlierInput ===
        document.querySelector('[data-board-quantity="0"]'),
    ),
    true,
  );
  const metrics = await page.evaluate(async () => {
    const { optionMetrics, priceDistanceCells, hasUsableQuote } = await import(
      "/static/js/option-metrics.js"
    );
    return {
      missingBid: hasUsableQuote({ bid: null, ask: 1, mid: 0.5 }),
      crossed: hasUsableQuote({ bid: 2, ask: 1, mid: 1.5 }),
      valid: hasUsableQuote({ bid: 0, ask: 1, mid: 0.5 }),
      call: optionMetrics({ strike: 110, option_type: "CALL", mid: 2 }, 100),
      put: optionMetrics({ strike: 90, option_type: "PUT", mid: 2 }, 100),
      missing: optionMetrics(
        { strike: 90, option_type: "PUT", mid: null },
        null,
      ),
      noStock: optionMetrics({ strike: 90, option_type: "PUT", mid: 2 }, 0),
      callText: priceDistanceCells(
        { strike: 110, option_type: "CALL", mid: 2 },
        100,
      ),
      putText: priceDistanceCells(
        { strike: 90, option_type: "PUT", mid: 2 },
        100,
      ),
    };
  });
  assert.equal(metrics.missingBid, false);
  assert.equal(metrics.crossed, false);
  assert.equal(metrics.valid, true);
  assert.equal(metrics.call.distance, 10);
  assert.equal(metrics.call.breakeven, null);
  assert.equal(metrics.put.distance, -10);
  assert.equal(metrics.put.breakeven, 88);
  assert.equal(metrics.put.breakevenDistance, -12);
  assert.equal(metrics.missing.distance, null);
  assert.equal(metrics.missing.breakeven, null);
  assert.equal(metrics.noStock.distance, null);
  assert.equal(metrics.noStock.breakeven, 88);
  assert.match(metrics.callText, /10.00% above/);
  assert.doesNotMatch(metrics.callText, /data-put-breakeven/);
  assert.match(metrics.putText, /10.00% below/);
  assert.match(metrics.putText, /12.00% below stock/);
  // Watchlist stays compact by default and expands with native keyboard support.
  assert.equal(
    await page.locator(".watchlist-editor").evaluate((el) => el.open),
    false,
  );
  await page.locator(".watchlist-heading").focus();
  await page.keyboard.press("Enter");
  assert.equal(
    await page.locator(".watchlist-editor").evaluate((el) => el.open),
    true,
  );
  // Separate editable lists survive reloads without re-adding held stocks.
  await page.locator("#watchlist-input").fill("TSLA, amd TSLA");
  await page.getByRole("button", { name: "Add symbols", exact: true }).click();
  await page
    .getByRole("button", {
      name: "Remove MSFT from put watchlist",
      exact: true,
    })
    .click();
  assert.equal(await page.locator('#watchlist [data-ticker="AMD"]').count(), 1);
  await page.reload();
  await page.locator("[data-board-row]").first().waitFor();
  assert.equal(
    await page.locator('#watchlist [data-ticker="MSFT"]').count(),
    0,
  );
  assert.deepEqual(
    await page.locator("#watchlist [data-ticker]").allTextContents(),
    ["AAPL", "NVDA", "TSLA", "AMD"],
  );
  assert.equal(
    requests.filter((r) => r.path === "/api/options/scan-batch").at(-1).query
      .tickers,
    "AAPL,NVDA,TSLA,AMD",
  );
  assert.equal(
    await page.locator(".watchlist-editor").evaluate((el) => el.open),
    false,
  );
  await page.locator(".watchlist-heading").click();
  await page.locator('[data-strategy="CALL"]').click();
  assert.deepEqual(
    await page.locator("#watchlist [data-ticker]").allTextContents(),
    ["AAPL", "NVDA", "MSFT"],
  );
  await page
    .getByRole("button", {
      name: "Remove NVDA from call watchlist",
      exact: true,
    })
    .click();
  await page.locator('[data-strategy="PUT"]').click();
  assert.deepEqual(
    await page.locator("#watchlist [data-ticker]").allTextContents(),
    ["AAPL", "NVDA", "TSLA", "AMD"],
  );
  const migration = await page.evaluate(async () => {
    const { loadWatchlists, parseSymbols, WATCHLIST_KEY } = await import(
      "/static/js/watchlists.js"
    );
    const storage = (values) => ({ getItem: (key) => values[key] ?? null });
    return {
      original: loadWatchlists(
        storage({
          customTickers: '["tsla","AMD","TSLA"]',
          "wheel.watchlist": '["AAPL"]',
        }),
      ),
      recent: loadWatchlists(storage({ "wheel.watchlist": '["AAPL"]' })),
      empty: loadWatchlists(
        storage({
          [WATCHLIST_KEY]: '{"PUT":[],"CALL":["MSFT"]}',
          customTickers: '["TSLA"]',
        }),
      ),
      parsed: parseSymbols("tsla, AMD TSLA"),
    };
  });
  assert.deepEqual(migration.original.PUT, ["TSLA", "AMD"]);
  assert.deepEqual(migration.recent.PUT, ["AAPL"]);
  assert.deepEqual(migration.empty, { PUT: [], CALL: ["MSFT"] });
  assert.deepEqual(migration.parsed, ["TSLA", "AMD"]);
  await page.locator("#scan-button:not([disabled])").waitFor();
  await page.screenshot({
    path: "/tmp/wheel-ui/watchlist-editor.png",
    fullPage: true,
  });
  // Bulk actions use one review, stop submission after failure, and keep failed cancellations.
  failSubmit = false;
  settings.mode = "paper";
  settings.paper.readonly = false;
  const template = { ...orders[0], isRollover: false, status: "pending" };
  orders = [101, 102, 103].map((id) => ({ ...template, id }));
  orders.push({ ...template, id: 104, isRollover: true });
  failExecuteId = 102;
  await page.reload();
  await page.locator("[data-submit-all]:not([disabled])").waitFor();
  const beforeBulk = requests.filter((r) =>
    r.path.startsWith("/api/options/execute/"),
  ).length;
  await page.locator("[data-submit-all]").click();
  assert.equal(
    requests.filter((r) => r.path.startsWith("/api/options/execute/")).length,
    beforeBulk,
  );
  await page
    .getByRole("button", { name: "Submit 3 paper orders", exact: true })
    .click();
  await page
    .getByText("Not attempted after earlier failure", { exact: true })
    .waitFor();
  assert.equal(
    requests.filter((r) => r.path.startsWith("/api/options/execute/")).length,
    beforeBulk + 2,
  );
  assert.deepEqual(
    orders.map((o) => o.status),
    ["processing", "pending", "pending", "pending"],
  );
  const brokerCancelsBefore = requests.filter((r) =>
    r.path.startsWith("/api/options/cancel/"),
  ).length;
  failCancelId = 102;
  await page.locator("[data-cancel-all]:not([disabled])").waitFor();
  await page.locator("[data-cancel-all]").click();
  await page
    .getByRole("button", { name: "Remove 3 drafts", exact: true })
    .click();
  await page.getByText("Test cancellation failure", { exact: true }).waitFor();
  await page.locator("[data-cancel-all]:not([disabled])").waitFor();
  assert.deepEqual(
    orders.map((o) => [o.id, o.status]),
    [
      [101, "processing"],
      [102, "pending"],
    ],
  );
  assert.equal(
    await page.locator(".watchlist-editor").evaluate((el) => el.open),
    false,
  );
  await page.screenshot({
    path: "/tmp/wheel-ui/compact-watchlist-bulk-queue.png",
    fullPage: true,
  });
  assert.equal(
    requests.filter((r) => r.path.startsWith("/api/options/cancel/")).length,
    brokerCancelsBefore,
  );
  assert.equal(
    await page.getByText("Draft removed from queue", { exact: true }).count(),
    0,
  );
  assert.equal(await page.locator(".bulk-report tbody tr").count(), 1);
  assert.match(await page.locator(".bulk-report").innerText(), /#102/);
  // Expiration remains editable even before the first scan returns.
  let releaseScan;
  const heldScan = new Promise((resolve) => {
    releaseScan = resolve;
  });
  await page.route("**/api/options/scan-batch?**", async (route) => {
    await heldScan;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ results: [], expirations: [] }),
    });
  });
  await page.reload();
  await page.locator("#scan-button[disabled]").waitFor();
  assert.match(
    await page.locator("#expiry-select").inputValue(),
    /^\d{4}-\d{2}-\d{2}$/,
  );
  await chooseExpiry("2026-10-16");
  await page.locator("#scan-button:not([disabled])").waitFor();
  releaseScan();
  assert.equal(await page.locator("#expiry-select").inputValue(), "2026-10-16");
  // Single draft cancellation uses the local endpoint and removes the row.
  failCancelId = null;
  await page.locator('[data-cancel="102"]').click();
  await page.locator('[data-cancel="102"]').waitFor({ state: "detached" });
  assert.equal(
    orders.some((o) => o.id === 102),
    false,
  );
  assert.equal(
    requests.filter((r) => r.path === "/api/options/order/102/draft").at(-1)
      .method,
    "DELETE",
  );
  await page.locator("[data-cancel-all][disabled]").waitFor();
  orders.push({ ...template, id: 105 });
  await page.locator("#refresh-orders").click();
  await page.locator("[data-cancel-all]:not([disabled])").waitFor();
  await page.locator("[data-cancel-all]").click();
  await page
    .getByRole("button", { name: "Remove 1 drafts", exact: true })
    .click();
  await page.locator("[data-cancel-all][disabled]").waitFor();
  assert.equal(await page.locator(".bulk-report").innerText(), "");
  // Appearance is keyboard-accessible and persists across reloads.
  failPortfolio = false;
  await page.unroute("**/api/options/scan-batch?**");
  assert.equal(await page.locator("html").getAttribute("data-theme"), "dark");
  await page.getByRole("button", { name: "Switch to light theme" }).click();
  await page.getByRole("button", { name: "Switch to dark theme" }).click();
  assert.equal(await page.locator("html").getAttribute("data-theme"), "dark");
  await page.reload();
  await page.locator("[data-board-row]").first().waitFor();
  assert.equal(await page.locator("html").getAttribute("data-theme"), "dark");
  assert.equal(
    await page.evaluate(() => getComputedStyle(document.body).backgroundColor),
    "rgb(0, 0, 0)",
  );
  await page.screenshot({
    path: "/tmp/wheel-ui/dark-theme.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  assert.ok(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  );
  await page.screenshot({
    path: "/tmp/wheel-ui/dark-mobile.png",
    fullPage: false,
  });
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.getByRole("button", { name: "Switch to light theme" }).focus();
  await page.keyboard.press("Enter");
  assert.equal(await page.locator("html").getAttribute("data-theme"), "light");
  assert.equal(
    await page.evaluate(() => getComputedStyle(document.body).backgroundColor),
    "rgb(255, 255, 255)",
  );
  await page.screenshot({
    path: "/tmp/wheel-ui/light-theme.png",
    fullPage: true,
  });
  assert.equal(await page.locator(".toast, #notifications").count(), 0);
  const selectedExpiry = await page.locator("#expiry-select").inputValue();
  await page.locator("#expiry-trigger").click();
  await page.screenshot({
    path: "/tmp/wheel-ui/calendar-light.png",
    fullPage: false,
  });
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Enter");
  const nextDay = new Date(selectedExpiry + "T12:00:00Z");
  nextDay.setUTCDate(nextDay.getUTCDate() + 1);
  assert.equal(
    await page.locator("#expiry-select").inputValue(),
    nextDay.toISOString().slice(0, 10),
  );
  assert.equal(
    await page.locator("#expiry-trigger").getAttribute("aria-expanded"),
    "false",
  );
  await chooseExpiry("2028-02-29");
  await page.locator("#expiry-trigger").click();
  await page.keyboard.press("PageDown");
  await page.keyboard.press("Enter");
  assert.equal(await page.locator("#expiry-select").inputValue(), "2028-03-29");
  await page.locator("#expiry-trigger").click();
  await page
    .getByRole("button", { name: "Following Friday", exact: true })
    .click();
  const followingFriday = await page.evaluate(async () => {
    const { friday } = await import("/static/js/ui.js");
    const date = new Date(
      friday().replace(/^(\d{4})(\d{2})(\d{2})$/, "$1-$2-$3") + "T12:00:00Z",
    );
    date.setUTCDate(date.getUTCDate() + 7);
    return date.toISOString().slice(0, 10);
  });
  assert.equal(
    await page.locator("#expiry-select").inputValue(),
    followingFriday,
  );
  await page.getByRole("button", { name: "Switch to dark theme" }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator("#expiry-trigger").click();
  const calendarRect = await page.locator("#expiry-calendar").boundingBox();
  assert.ok(
    calendarRect.x >= 0 &&
      calendarRect.x + calendarRect.width <= 390 &&
      calendarRect.y >= 0 &&
      calendarRect.y + calendarRect.height <= 844,
  );
  await page.screenshot({
    path: "/tmp/wheel-ui/calendar-dark-mobile.png",
    fullPage: false,
  });
  await page.keyboard.press("Escape");
  assert.equal(
    await page.locator("#expiry-trigger").getAttribute("aria-expanded"),
    "false",
  );
  assert.equal(
    await page.locator("#expiry-select").inputValue(),
    followingFriday,
  );
  assert.equal(
    await page
      .locator("#expiry-trigger")
      .evaluate((el) => el === document.activeElement),
    true,
  );

  const cachedQuantity = await page.evaluate(async () =>
    (await import("/static/js/put-quantities.js")).putQuantity("AAPL"),
  );
  assert(cachedQuantity > 1);
  await page.reload();
  await page.locator("[data-board-quantity]").first().waitFor();
  assert.equal(
    await page.locator("[data-board-quantity]").first().inputValue(),
    String(cachedQuantity),
  );
  assert.deepEqual(errors, []);
  console.log(
    "PASS: parallel watchlist, partial failures, alternative candidates, bulk drafts, default delta/Friday, expiry changes, drafts, failed submission, offline state, settings persistence/test, rollover price units, mobile overflow; no browser errors.",
  );
  await browser.close();
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
