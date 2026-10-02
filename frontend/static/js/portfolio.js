import { request } from "./api.js";
import { initExpiryPicker } from "./expiry-picker.js";
import {
  esc,
  money,
  date,
  num,
  table,
  empty,
  notice,
  loading,
  busy,
} from "./ui.js";

let positions = [];
let loaded = false;
let revision = 0;
export function initPortfolio() {
  document.querySelector("#portfolio-content").innerHTML =
    ["STK", "OPT"]
      .map(
        (type) => `
    <section class="panel" data-position-section="${type}">
      <div class="panel-heading portfolio-position-heading">
        <h2>${type === "STK" ? "Stock positions" : "Option positions"} <span class="count" data-position-count="${type}">0</span></h2>
        ${type === "OPT" ? `<div class="portfolio-expiry-filter"><label for="expiry-trigger">Expiration</label><input type="hidden" id="expiry-select"><button id="expiry-trigger" class="expiry-trigger" type="button" aria-haspopup="dialog" aria-controls="expiry-calendar" aria-expanded="false">All expirations</button></div>` : '<span class="badge neutral">BROKER SNAPSHOT</span>'}
      </div>
      <div data-position-body="${type}"></div>
    </section>`,
      )
      .join("") + '<div id="other-holdings"></div>';
  initExpiryPicker({ allowEmpty: true, initialValue: "" });
  document.querySelector("#expiry-select").addEventListener("change", () => {
    if (loaded) renderPositions("OPT");
  });
  document
    .querySelector("#refresh-portfolio")
    .addEventListener("click", (event) => busy(event.currentTarget, load));
  load();
}

function renderPositions(type) {
  const expiry = document
    .querySelector("#expiry-select")
    .value.replaceAll("-", "");
  const list = positions
    .filter(
      (p) =>
        p.security_type === type &&
        (type !== "OPT" ||
          !expiry ||
          p.expiration?.replaceAll("-", "") === expiry),
    )
    .sort((a, b) => b.market_value - a.market_value);
  document.querySelector(`[data-position-count="${type}"]`).textContent =
    list.length;
  const headers =
    type === "STK"
      ? [
          "Symbol",
          { label: "Shares", numeric: true },
          { label: "Average cost / share", numeric: true },
          { label: "Market / share", numeric: true },
          { label: "Market value", numeric: true },
          { label: "Unrealized P&L", numeric: true },
        ]
      : [
          "Contract",
          { label: "Contracts", numeric: true },
          { label: "Delta", numeric: true },
          { label: "Average cost / contract", numeric: true },
          { label: "Market / contract", numeric: true },
          { label: "Market value", numeric: true },
          { label: "Unrealized P&L", numeric: true },
        ];

  document.querySelector(`[data-position-body="${type}"]`).innerHTML =
    list.length
      ? table(
          headers,
          list
            .map(
              (p) =>
                `<tr><td><div class="symbol-cell"><div><span class="symbol">${esc(p.symbol)}</span>${type === "OPT" ? `<span class="subtext">${money(p.strike)} ${esc(p.option_type)} · ${date(p.expiration)}</span>` : ""}</div></div></td><td class="number">${num(p.position, 0)}</td>${type === "OPT" ? `<td class="number" data-position-delta title="${Number.isFinite(p.delta) ? "Contract delta" : "Delta unavailable"}">${num(p.delta, 3)}</td>` : ""}<td class="number">${money(p.avg_cost)}</td><td class="number">${money(p.market_price * (type === "OPT" ? 100 : 1))}</td><td class="number">${money(p.market_value)}</td><td class="number ${p.unrealized_pnl >= 0 ? "positive" : "negative"}">${money(p.unrealized_pnl)}</td></tr>`,
            )
            .join(""),
        )
      : empty(
          type === "OPT" && expiry
            ? `No options expiring ${date(expiry)}.`
            : `No ${type === "STK" ? "stock" : "option"} positions.`,
          type === "OPT" && expiry
            ? "Choose another date or All expirations."
            : "Your positions will appear here when available.",
        );
}

async function loadDeltas(currentRevision) {
  if (!positions.some((position) => position.security_type === "OPT")) return;
  try {
    const data = await request("/api/portfolio/position-deltas");
    if (revision !== currentRevision) return;
    const deltas = new Map(
      data.deltas.map((item) => [item.con_id, item.delta]),
    );
    positions = positions.map((position) => ({
      ...position,
      delta: deltas.get(position.con_id) ?? null,
    }));
    renderPositions("OPT");
  } catch {
    // Keep the portfolio usable when market-data permissions or Greeks are missing.
  }
}

async function load() {
  const currentRevision = ++revision;
  if (!loaded)
    document
      .querySelectorAll("[data-position-body]")
      .forEach((el) => (el.innerHTML = loading("Loading your positions")));
  try {
    positions = await request("/api/portfolio/positions");
    loaded = true;
    void loadDeltas(currentRevision);
    renderPositions("STK");
    renderPositions("OPT");
    const other = positions.filter(
      (p) => !["STK", "OPT"].includes(p.security_type),
    );
    document.querySelector("#other-holdings").innerHTML = other.length
      ? `<section class="panel"><div class="panel-heading"><h2>Other holdings</h2></div>${table(["Symbol", "Type", { label: "Quantity", numeric: true }, { label: "Market value", numeric: true }], other.map((p) => `<tr><td>${esc(p.symbol)}</td><td>${esc(p.security_type)}</td><td class="number">${num(p.position)}</td><td class="number">${money(p.market_value)}</td></tr>`).join(""))}</section>`
      : "";
  } catch (error) {
    if (loaded) throw error;
    document
      .querySelectorAll("[data-position-body]")
      .forEach((el) => (el.innerHTML = notice(error.message)));
  }
}
