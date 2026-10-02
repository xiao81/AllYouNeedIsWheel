import { putQuantity } from "./put-quantities.js";
import { initExpiryPicker } from "./expiry-picker.js";
import { loadWatchlists, saveWatchlists, parseSymbols } from "./watchlists.js";
import { priceDistanceCells, hasUsableQuote } from "./option-metrics.js";
import { request, query, streamScan } from "./api.js";
import {
  esc,
  money,
  num,
  date,
  table,
  empty,
  loading,
  notice,
  toast,
  busy,
  icon,
} from "./ui.js";
import { renderBoard } from "./scan-board.js";
import { initOrders, saveDraft } from "./orders.js";
let positions = [],
  positionsLoaded = false,
  account = null,
  strategy = "PUT",
  generation = 0,
  result = null;
let scanController = null;
let watchlists = loadWatchlists();
let storageWarning = false;
const $ = (selector) => document.querySelector(selector);
export async function initDashboard() {
  initOrders();
  persistWatchlists();
  window.addEventListener("pagehide", () => scanController?.abort());
  $("#refresh-workspace").addEventListener("click", (event) =>
    busy(event.currentTarget, () => loadAccount()),
  );
  $("#scan-form").addEventListener("submit", (event) => {
    event.preventDefault();
    scan(true);
  });
  function updateTargetDelta() {
    const minimum = Number($("#delta-min").value);
    const maximum = Number($("#delta-max").value);
    $("#target-delta").value =
      $("#delta-min").value &&
      $("#delta-max").value &&
      minimum > 0 &&
      maximum < 1 &&
      minimum <= maximum
        ? num((minimum + maximum) / 2, 3)
        : "—";
  }
  updateTargetDelta();
  function invalidate() {
    updateTargetDelta();
    generation++;
    scanController?.abort();
    result = null;
    $("#scan-result").onchange = null;
    $("#scan-result").innerHTML = empty(
      "Filters changed",
      "Select Find options to scan with these preferences.",
    );
    $("#scan-button").disabled = false;
    $("#scan-button").removeAttribute("aria-busy");
  }
  ["#ticker-input", "#expiry-select", "#delta-min", "#delta-max"].forEach(
    (selector) => $(selector).addEventListener("input", invalidate),
  );
  $("#scan-scope").addEventListener("change", () => {
    invalidate();
    renderWatchlist();
    scan();
  });
  $(".strategy-tabs").addEventListener("click", (event) => {
    const button = event.target.closest("[data-strategy]");
    if (!button) return;
    strategy = button.dataset.strategy;
    document.querySelectorAll("[data-strategy]").forEach((el) => {
      el.classList.toggle("active", el === button);
      el.setAttribute("aria-selected", String(el === button));
    });
    invalidate();
    $("#ticker-input").value = watchSymbols()[0] || "";
    renderWatchlist();
    if (watchSymbols().length) scan();
  });
  $(".strategy-tabs").addEventListener("keydown", (event) => {
    if (["ArrowLeft", "ArrowRight"].includes(event.key)) {
      event.preventDefault();
      const tabs = [...document.querySelectorAll("[data-strategy]")];
      const next = tabs.find((el) => el !== document.activeElement);
      next?.focus();
      next?.click();
    }
  });
  $("#watchlist").addEventListener("click", (event) => {
    const symbol = event.target.closest("[data-ticker]");
    if (symbol) {
      $("#ticker-input").value = symbol.dataset.ticker;
      if ($("#scan-scope").value === "single") scan();
      else {
        const group = [
          ...document.querySelectorAll("[data-symbol-group]"),
        ].find((el) => el.dataset.symbol === symbol.dataset.ticker);
        if (group)
          group.scrollIntoView({
            behavior: window.matchMedia("(prefers-reduced-motion: reduce)")
              .matches
              ? "instant"
              : "smooth",
            block: "center",
          });
        else
          toast(
            "Select Find options to load this watchlist’s contracts.",
            true,
            $("#scan-result"),
          );
      }
      renderWatchlist();
    }
    const remove = event.target.closest("[data-remove]");
    if (remove) {
      watchlists[strategy] = watchSymbols().filter(
        (s) => s !== remove.dataset.remove,
      );
      persistWatchlists();
      if ($("#ticker-input").value === remove.dataset.remove)
        $("#ticker-input").value = watchSymbols()[0] || "";
      renderWatchlist();
      invalidate();
    }
  });
  $("#watchlist-add-form").addEventListener("submit", (event) => {
    event.preventDefault();
    try {
      const added = parseSymbols($("#watchlist-input").value);
      if (!added.length) return;
      const merged = [...new Set([...watchSymbols(), ...added])];
      if (merged.length > 20)
        throw new Error("Keep up to 20 symbols in each watchlist.");
      watchlists[strategy] = merged;
      persistWatchlists();
      $("#watchlist-input").value = "";
      $("#ticker-input").value = watchSymbols()[0] || "";
      renderWatchlist();
      invalidate();
    } catch (error) {
      toast(error.message, true, $("#scan-result"));
    }
  });
  $("#watchlist-holdings").addEventListener("click", () => {
    const held = heldSymbols();
    if (!held.length) {
      toast("No stock holdings loaded. Refresh your account first.", true);
      return;
    }
    if (held.length > 20) {
      toast(
        "More than 20 holdings loaded. Add the symbols you want manually.",
        true,
      );
      return;
    }
    watchlists[strategy] = held;
    persistWatchlists();
    $("#ticker-input").value = held[0];
    renderWatchlist();
    invalidate();
  });
  $("#scan-result").addEventListener("click", (event) => {
    const button = event.target.closest("[data-save-option]");
    if (button && result) {
      const option = result.options[Number(button.dataset.saveOption)];
      busy(button, () =>
        saveDraft(
          option,
          result.symbol,
          defaultQuantity(result.symbol, option.option_type),
        ),
      );
    }
    const retry = event.target.closest("[data-scan-retry]");
    if (retry) scan(true);
  });
  initExpiryPicker();
  renderWatchlist();
  await loadAccount();
  const first = watchSymbols()[0];
  if (first) {
    $("#ticker-input").value = first;
    scan();
  }
}
async function loadAccount() {
  const outcomes = await Promise.allSettled([
    request("/api/portfolio/"),
    request("/api/portfolio/positions"),
    request("/api/portfolio/weekly-income"),
  ]);
  $("#account-error").innerHTML = "";
  if (outcomes[0].status === "fulfilled" && outcomes[0].value) {
    account = outcomes[0].value;
    $("#net-value").textContent = money(account.account_value);
    $("#cash-value").textContent = money(account.cash_balance);
    $("#liquidity-value").textContent = money(account.excess_liquidity);
    $("#account-context").textContent =
      `${account.is_frozen ? "Frozen session" : "Broker snapshot"} · ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
    $("#margin-context").textContent =
      `Initial margin ${money(account.initial_margin)}`;
    $("#connection-dot").classList.add("connected");
  } else {
    ["#net-value", "#cash-value", "#liquidity-value"].forEach(
      (id) => ($(id).textContent = "—"),
    );
    $("#account-context").textContent = "Broker unavailable";
    $("#connection-dot").classList.remove("connected");
    $("#account-error").innerHTML =
      notice(outcomes[0].reason?.message || "No account data available.") +
      `<p style="margin:-9px 0 20px"><a class="text-link" href="/settings">Open connection settings ↗</a></p>`;
  }
  positionsLoaded = outcomes[1].status === "fulfilled";
  if (positionsLoaded) {
    positions = outcomes[1].value || [];
    if (watchlists.CALL === null && heldSymbols().length) {
      watchlists.CALL = heldSymbols();
      persistWatchlists();
    }
    renderWatchlist();
  }
  if (outcomes[2].status === "fulfilled") {
    const income = outcomes[2].value;
    $("#income-value").textContent = money(income.total_income);
    $("#income-context").textContent =
      `${income.positions_count} short positions · Entry premium`;
    $("#income-content").innerHTML = income.positions?.length
      ? `<div class="income-total"><strong>${money(income.total_income)}</strong><p>Entry premium · Expiring through ${esc(income.this_friday)}</p></div>${income.positions
          .slice(0, 4)
          .map(
            (p) =>
              `<div class="income-item"><div><b>${esc(p.symbol)}</b><small>${money(p.strike)} ${esc(p.option_type)} · ${Math.abs(p.position)} contracts</small></div><span>${money(p.income)}</span></div>`,
          )
          .join("")}`
      : empty(
          "Nothing expiring soon.",
          "Short positions expiring this week will appear here.",
        );
  } else {
    $("#income-value").textContent = "—";
    $("#income-content").innerHTML = empty(
      "Income unavailable.",
      "Reconnect to load expiring positions.",
    );
  }
}
function heldSymbols() {
  return [
    ...new Set(
      positions
        .filter((p) => p.security_type === "STK" && p.position > 0)
        .map((p) => p.symbol),
    ),
  ];
}
function watchSymbols() {
  return watchlists[strategy] || [];
}
function persistWatchlists() {
  try {
    saveWatchlists(watchlists);
    storageWarning = false;
  } catch {
    storageWarning = true;
    toast(
      "Browser storage is unavailable. Watchlist changes will last only for this page session.",
      true,
    );
  }
}
function renderWatchlist() {
  const all = watchSymbols();
  $("#watchlist-title").textContent =
    `${strategy === "PUT" ? "Sell-put" : "Covered-call"} watchlist · ${all.length} symbols`;
  $("#watchlist-storage").textContent = storageWarning
    ? "Not saved: browser storage unavailable"
    : "Saved in this browser · Separate lists for puts and calls";
  $("#watchlist").innerHTML = all.length
    ? table(
        [
          "Symbol",
          strategy === "CALL" ? "Shares / default contracts" : "Stock position",
          "",
        ],
        all
          .map((s) => {
            const shares = positions
              .filter((p) => p.symbol === s && p.security_type === "STK")
              .reduce((total, p) => total + p.position, 0);
            const position = !positionsLoaded
              ? "Holdings unavailable"
              : shares > 0
                ? `${num(shares, Number.isInteger(shares) ? 0 : 2)} shares${strategy === "CALL" ? ` · ${defaultQuantity(s, "CALL")} contracts` : " held"}`
                : "Not currently held";
            return `<tr><td><button type="button" class="watchlist-symbol" data-ticker="${esc(s)}" title="View options for ${esc(s)}">${esc(s)}</button></td><td class="watchlist-position">${esc(position)}</td><td class="number"><button type="button" class="watchlist-remove" data-remove="${esc(s)}" aria-label="Remove ${esc(s)} from ${strategy === "PUT" ? "put" : "call"} watchlist">Remove</button></td></tr>`;
          })
          .join(""),
      )
    : `<div class="watchlist-empty"><strong>Your ${strategy === "PUT" ? "put" : "call"} watchlist is empty</strong><p>Add a ticker above, or paste several separated by commas.</p></div>`;
  $("#ticker-input").disabled = $("#scan-scope").value === "watchlist";
}
async function scan(refresh = false) {
  const ticker = $("#ticker-input").value.trim().toUpperCase();
  const isBatch = $("#scan-scope").value === "watchlist";
  const tickers = watchSymbols();
  if ((isBatch && !tickers.length) || (!isBatch && !ticker)) {
    toast("Add symbols to your watchlist or enter a single ticker.", true);
    return;
  }
  if (isBatch && tickers.length > 20) {
    toast("Choose at most 20 symbols per scan.", true);
    return;
  }
  const minimum = Number($("#delta-min").value),
    maximum = Number($("#delta-max").value);
  if (!(minimum > 0 && minimum <= maximum && maximum < 1)) {
    toast(
      "Choose a delta range between 0 and 1, with minimum ≤ maximum.",
      true,
    );
    return;
  }
  scanController?.abort();
  scanController = new AbortController();
  const revision = ++generation;
  const requestedExpiry = $("#expiry-select").value.replaceAll("-", "");
  const scanType = strategy;
  result = null;
  $("#scan-result").onchange = null;
  $("#scan-result").innerHTML = loading(
    `Finding ${isBatch ? `${tickers.length} symbols’` : ticker} ${scanType === "CALL" ? "calls" : "puts"} in your delta range…`,
  );
  $("#scan-button").disabled = true;
  $("#scan-button").setAttribute("aria-busy", "true");
  let board;
  try {
    const params = query({
      ...(isBatch ? { tickers: tickers.join(","), stream: true } : { ticker }),
      type: scanType,
      expiration: requestedExpiry,
      delta_min: minimum,
      delta_max: maximum,
      refresh,
    });
    if (isBatch)
      board = renderBoard($("#scan-result"), {
        results: tickers.map((symbol) => ({ symbol, loading: true })),
        option_type: scanType,
        target_delta: (minimum + maximum) / 2,
        quantities: Object.fromEntries(
          tickers.map((symbol) => [symbol, defaultQuantity(symbol, scanType)]),
        ),
      });
    const data = isBatch
      ? await streamScan(
          `/api/options/scan-batch?${params}`,
          (row) => {
            if (revision === generation) board.add(row);
          },
          scanController.signal,
        )
      : await request(`/api/options/scan?${params}`, {
          signal: scanController.signal,
        });
    if (revision !== generation) return;
    result = isBatch ? null : data;
    renderWatchlist();
    if (isBatch) data.results.forEach((row) => board.add(row));
    else renderScan(data);
  } catch (error) {
    if (revision !== generation) return;
    if (board) {
      board.fail(error.message);
      toast(error.message, true, $("#scan-result"));
      return;
    }
    $("#scan-result").innerHTML =
      notice(error.message) +
      empty(
        "The scan couldn’t complete.",
        "Check your broker connection and market-data subscriptions.",
        `<button class="button secondary" data-scan-retry>Try again</button>`,
      );
  } finally {
    if (revision === generation) {
      $("#scan-button").disabled = false;
      $("#scan-button").removeAttribute("aria-busy");
    }
  }
}
function defaultQuantity(symbol, type) {
  const shares = positions
    .filter((p) => p.symbol === symbol && p.security_type === "STK")
    .reduce((n, p) => n + p.position, 0);
  return type === "CALL"
    ? Math.max(1, Math.floor(shares / 100))
    : putQuantity(symbol);
}
function renderScan(data) {
  const excluded = data.options.filter((o) => !hasUsableQuote(o)).length;
  data.options = data.options.filter(hasUsableQuote);
  const best = data.options.find((o) => o.mid > 0) || data.options[0];
  data.options.sort((a, b) => a.strike - b.strike);
  const shares = positions
    .filter((p) => p.symbol === data.symbol && p.security_type === "STK")
    .reduce((n, p) => n + p.position, 0);
  const shortCalls = positions
    .filter(
      (p) =>
        p.symbol === data.symbol &&
        p.security_type === "OPT" &&
        p.option_type === "CALL" &&
        p.position < 0,
    )
    .reduce((n, p) => n + Math.abs(p.position), 0);
  const coveredAvailable = Math.max(0, Math.floor(shares / 100) - shortCalls);
  let content = `<div class="scan-meta"><div><b>${esc(data.symbol)} <span style="font-weight:400">${money(data.stock_price)}</span></b><span>${date(data.expiration)} · ${data.options.length} matches${excluded ? ` · ${excluded} incomplete quotes hidden` : ""}</span></div><span>${data.cached ? "Cached · " : ""}${data.is_frozen ? "Frozen data" : "Live quotes"} · ${data.scanned} contracts checked · ${(data.elapsed_ms / 1000).toFixed(1)}s</span></div>`;
  if (data.expiration_adjusted)
    content += notice(
      `Friday ${date(data.target_friday)} is not listed. Showing ${date(data.expiration)}.`,
      "info",
    );
  if (data.option_type === "CALL")
    content += notice(
      `${shares} shares · ${shortCalls} short ${shortCalls === 1 ? "call" : "calls"} · Spare coverage: ${coveredAvailable} ${coveredAvailable === 1 ? "contract" : "contracts"}. Drafts unrestricted; queue excluded.`,
      "info",
    );
  if (!data.options.length) {
    content += empty(
      excluded
        ? "Matching contracts are missing usable quotes."
        : "No matches in this range.",
      `Checked ${data.scanned} contracts. ${data.missing_greeks} quotes had no usable delta. Try another expiry or widen the range.`,
    );
    $("#scan-result").innerHTML = content;
    return;
  }
  content += table(
    [
      "Contract",
      { label: "Strike vs stock", numeric: true },
      ...(data.option_type === "PUT"
        ? [{ label: "Put breakeven", numeric: true }]
        : []),
      { label: "Bid", numeric: true },
      { label: "Ask", numeric: true },
      { label: "Mid / share", numeric: true },
      { label: "Delta", numeric: true },
      { label: "IV", numeric: true },
      { label: "Premium / contract", numeric: true },
      "",
    ],
    data.options
      .map((o, i) => {
        const hasQuote = o.mid !== null && o.mid > 0;
        return `<tr><td><span class="symbol contract-strike">${money(o.strike)}</span> <span class="badge neutral">${esc(o.option_type)}</span>${o === best ? '<span class="subtext">Closest to target delta</span>' : ""}</td>${priceDistanceCells(o, data.stock_price)}<td class="number">${money(o.bid)}</td><td class="number">${money(o.ask)}</td><td class="number">${money(o.mid)}</td><td class="number">${num(o.delta, 3)}</td><td class="number">${o.implied_volatility === null ? "—" : `${num(o.implied_volatility * 100, 1)}%`}</td><td class="positive number">${o.mid === null ? "—" : money(o.mid * 100)}</td><td><button class="button secondary small" data-save-option="${i}" ${hasQuote ? "" : "disabled"} title="${!hasQuote ? "A valid two-sided quote is required" : "Review and save a draft"}">+ Add to queue</button></td></tr>`;
      })
      .join(""),
  );
  $("#scan-result").innerHTML = content;
}
