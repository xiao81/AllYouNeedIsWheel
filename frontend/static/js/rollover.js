import { request, query } from "./api.js";
import {
  esc,
  money,
  num,
  date,
  table,
  empty,
  loading,
  notice,
  busy,
  toast,
  friday,
} from "./ui.js";
import { initOrders, loadOrders } from "./orders.js";
let positions = [],
  selected = null,
  result = null,
  generation = 0;
export function initRollover() {
  initOrders(true);
  document
    .querySelector("#refresh-rollover")
    .addEventListener("click", (event) =>
      busy(event.currentTarget, loadPositions),
    );
  document
    .querySelector("#roll-positions")
    .addEventListener("click", (event) => {
      const button = event.target.closest("[data-roll]");
      if (button)
        busy(button, () => select(positions[Number(button.dataset.roll)]));
    });
  document.querySelector("#roll-editor").addEventListener("click", (event) => {
    const button = event.target.closest("[data-roll-draft]");
    if (button)
      busy(button, () =>
        saveRoll(result.options[Number(button.dataset.rollDraft)]),
      );
  });
  loadPositions();
}
async function loadPositions() {
  const el = document.querySelector("#roll-positions");
  el.innerHTML = loading("Loading short option positions");
  try {
    positions = (await request("/api/portfolio/positions"))
      .filter((p) => p.security_type === "OPT" && p.position < 0)
      .sort((a, b) => a.expiration.localeCompare(b.expiration));
    el.innerHTML = positions.length
      ? table(
          [
            "Contract",
            "Expiry",
            { label: "Contracts", numeric: true },
            { label: "Market / share", numeric: true },
            { label: "Unrealized P&L", numeric: true },
            "",
          ],
          positions
            .map(
              (p, i) =>
                `<tr><td><span class="symbol">${esc(p.symbol)}</span> ${money(p.strike)} <span class="badge neutral">${esc(p.option_type)}</span></td><td>${date(p.expiration)}</td><td class="number">${Math.abs(p.position)}</td><td class="number">${money(p.market_price)}</td><td class="number ${p.unrealized_pnl >= 0 ? "positive" : "negative"}">${money(p.unrealized_pnl)}</td><td><button class="button secondary small" data-roll="${i}">Explore roll →</button></td></tr>`,
            )
            .join(""),
        )
      : empty(
          "No short options to roll.",
          "Your open short calls and puts will appear here.",
        );
  } catch (error) {
    el.innerHTML = notice(error.message);
  }
}
async function select(position) {
  selected = position;
  result = null;
  const revision = ++generation;
  const el = document.querySelector("#roll-editor");
  el.hidden = false;
  el.innerHTML = loading("Finding available expirations");
  el.scrollIntoView({
    behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
      ? "instant"
      : "smooth",
    block: "start",
  });
  try {
    const metadata = await request(
      `/api/options/expirations?${query({ ticker: position.symbol })}`,
    );
    if (revision !== generation) return;
    const expiries = metadata.expirations.filter(
      (e) => e.value > position.expiration,
    );
    let target =
      expiries.find(
        (e) => e.value >= (metadata.default_expiration || friday(1)),
      )?.value || expiries[0]?.value;
    if (!target) {
      el.innerHTML = empty(
        "No later expiration available.",
        "Try again when the broker lists another expiration.",
      );
      return;
    }
    el.innerHTML = `<div class="panel-heading"><div><h2>Find a replacement for ${esc(position.symbol)}</h2></div><span class="badge neutral">STEP 02</span></div><div class="roll-summary">Closing <strong>${Math.abs(position.position)} × ${money(position.strike)} ${esc(position.option_type)}</strong> · ${date(position.expiration)}</div><form id="roll-form" class="roll-controls"><label>New expiration<select id="roll-expiry">${expiries.map((e) => `<option value="${e.value}" ${e.value === target ? "selected" : ""}>${date(e.value)}</option>`).join("")}</select></label><fieldset class="delta-fields"><legend>Absolute delta</legend><input id="roll-delta-min" type="number" min="0.01" max="0.99" step="0.01" value="0.05" aria-label="Minimum delta"><span>—</span><input id="roll-delta-max" type="number" min="0.01" max="0.99" step="0.01" value="0.10" aria-label="Maximum delta"></fieldset><label>Buy-to-close limit / share<input id="close-price" type="number" min="0.01" step="0.01" value="${Number(position.market_price) > 0 ? Number(position.market_price).toFixed(2) : ""}" required><span class="field-help">Portfolio mark; verify before submitting</span></label><button class="button primary">Find replacement</button></form><div id="roll-results"></div>`;
    document.querySelector("#roll-form").addEventListener("submit", (event) => {
      event.preventDefault();
      scan();
    });
    scan();
  } catch (error) {
    el.innerHTML = notice(error.message);
  }
}
async function scan() {
  const el = document.querySelector("#roll-results"),
    button = document.querySelector("#roll-form button");
  const revision = ++generation;
  const position = selected;
  const minimum = Number(document.querySelector("#roll-delta-min").value),
    maximum = Number(document.querySelector("#roll-delta-max").value);
  if (!(minimum > 0 && minimum <= maximum && maximum < 1)) {
    toast("Enter a valid delta range between 0 and 1.", true);
    return;
  }
  button.disabled = true;
  result = null;
  el.innerHTML = loading("Scanning replacement contracts");
  try {
    const data = await request(
      `/api/options/scan?${query({ ticker: position.symbol, type: position.option_type, expiration: document.querySelector("#roll-expiry").value, delta_min: minimum, delta_max: maximum })}`,
    );
    if (revision !== generation) return;
    result = data;
    el.innerHTML = data.options.length
      ? table(
          [
            { label: "Strike", numeric: true },
            "Expiry",
            { label: "Delta", numeric: true },
            { label: "Mid / share", numeric: true },
            { label: "Opening premium", numeric: true },
            "",
          ],
          data.options
            .map(
              (o, i) =>
                `<tr><td class="symbol number">${money(o.strike)}</td><td>${date(o.expiration)}</td><td class="number">${num(o.delta, 3)}</td><td class="number">${money(o.mid)}</td><td class="positive number">${o.mid === null ? "—" : money(o.mid * 100 * Math.abs(position.position))}</td><td><button class="button secondary small" data-roll-draft="${i}" ${o.mid > 0 ? "" : "disabled"}>Add both drafts</button></td></tr>`,
            )
            .join(""),
        )
      : empty(
          "No matching replacement.",
          "Try a later expiration or a wider delta range.",
        );
  } catch (error) {
    if (revision === generation) el.innerHTML = notice(error.message);
  } finally {
    if (revision === generation) button.disabled = false;
  }
}
async function saveRoll(option) {
  const position = selected;
  const buy = Number(document.querySelector("#close-price").value);
  if (!(buy > 0 && Number.isFinite(buy)))
    throw new Error("Enter a valid buy-to-close limit price.");
  const quantity = Math.abs(position.position);
  await request("/api/options/rollover", {
    method: "POST",
    body: {
      ticker: position.symbol,
      current_option_type: position.option_type,
      current_strike: position.strike,
      current_expiration: position.expiration,
      new_strike: option.strike,
      new_expiration: option.expiration,
      quantity,
      current_order_type: "LIMIT",
      new_order_type: "LIMIT",
      current_limit_price: buy,
      new_limit_price: option.mid,
      current_bid: 0,
      current_ask: buy,
      new_bid: option.bid,
      new_ask: option.ask,
    },
  });
  toast("Both rollover drafts saved.");
  await loadOrders(true);
}
