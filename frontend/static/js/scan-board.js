import { putQuantity, rememberPutQuantity } from "./put-quantities.js";
import { priceDistanceCells, hasUsableQuote } from "./option-metrics.js";
import { esc, money, num, date, table, busy, toast } from "./ui.js";
import { saveDrafts, saveDraft } from "./orders.js";

export function renderBoard(root, data) {
  const selections = [];
  const showPutBreakeven =
    (data.option_type ||
      data.results.find((r) => r.options?.length)?.options[0].option_type ||
      "PUT") === "PUT";
  const columns = showPutBreakeven ? 12 : 11;
  const usable = hasUsableQuote;
  const completed = new Set(
    data.results.filter((r) => !r.loading).map((r) => r.symbol),
  );
  function symbolRows(result) {
    if (result.loading)
      return `<tr class="symbol-group symbol-loading" aria-busy="true" aria-label="Loading options for ${esc(result.symbol)}"><td colspan="${columns}"><div class="symbol-loading-content"><span class="symbol-loading-ring" aria-hidden="true"></span><b class="symbol">${esc(result.symbol)}</b></div></td></tr>`;
    const options = (result.options || []).filter(usable);
    const excluded = (result.options?.length || 0) - options.length;
    const group = `<tr class="symbol-group"><td colspan="${columns}"><span class="symbol">${esc(result.symbol)}</span>${result.stock_price ? `<span>${money(result.stock_price)}</span>` : ""}<span>${result.expiration ? date(result.expiration) : ""}${result.expiration_adjusted ? " · Adjusted expiry" : ""}</span><span>${options.length} matches${excluded ? ` · ${excluded} incomplete quotes hidden` : ""}${result.scanned !== undefined ? ` · ${result.scanned} checked · ${result.cached ? "Cached · " : ""}${result.is_frozen ? "Frozen" : "Live"}` : ""}</span></td></tr>`;
    if (result.error || !options.length)
      return (
        group +
        `<tr><td colspan="${columns}" class="symbol-empty">${esc(result.error || (excluded ? "Matching contracts have no usable bid and ask yet. Refresh quotes to try again." : "No matching contracts in this delta range."))}</td></tr>`
      );
    return (
      group +
      [...options]
        .sort((a, b) => a.strike - b.strike)
        .map((option) => {
          const best = Boolean(
            result.candidate &&
              option.strike === result.candidate.strike &&
              option.expiration === result.candidate.expiration,
          );
          const available = usable(option);
          const index = selections.length;
          const quantity =
            option.option_type === "PUT"
              ? putQuantity(result.symbol)
              : data.quantities?.[result.symbol] || 1;
          selections.push({
            option,
            ticker: result.symbol,
            selected: best && available,
            quantity,
            best,
            available,
          });
          const description = `${result.symbol} ${option.strike} ${option.option_type}`;
          return `<tr data-board-row="${index}" class="${best ? "best-candidate" : ""}"><td><input type="checkbox" data-board-select="${index}" ${best && available ? "checked" : ""} ${available ? "" : "disabled"} aria-label="Select ${esc(description)}"></td><td><span class="contract-stack"><b class="symbol contract-strike">${money(option.strike)}</b>${best ? '<span class="best-label">Best match</span>' : ""}</span> <span class="badge neutral">${esc(option.option_type)}</span>${!available ? '<span class="subtext">Two-sided quote unavailable</span>' : ""}</td>${priceDistanceCells(option, result.stock_price)}<td class="number">${money(option.bid)}</td><td class="number">${money(option.ask)}</td><td class="number">${money(option.mid)}</td><td class="number">${num(option.delta, 3)}</td><td class="number" data-board-iv>${Number.isFinite(option.implied_volatility) ? `${num(option.implied_volatility * 100, 1)}%` : "—"}</td><td class="number"><input class="qty-input" data-board-quantity="${index}" type="number" min="1" step="1" value="${quantity}" ${available ? "" : "disabled"} aria-label="Quantity for ${esc(description)}"></td><td data-board-premium class="positive number">${available ? money(option.mid * 100 * quantity) : "—"}</td><td><button class="button secondary small" data-board-add="${index}" ${available ? "" : "disabled"}>+ Add to queue</button></td></tr>`;
        })
        .join("")
    );
  }
  const rows = data.results
    .map(
      (r, i) =>
        `<tbody data-symbol-group="${i}" data-symbol="${esc(r.symbol)}">${symbolRows(r)}</tbody>`,
    )
    .join("");
  root.innerHTML =
    `<div class="scan-meta"><div><b data-scan-progress role="status" aria-live="polite"></b></div></div>` +
    table(
      [
        "Select",
        "Contract",
        { label: "Strike vs stock", numeric: true },
        ...(showPutBreakeven
          ? [{ label: "Put breakeven", numeric: true }]
          : []),
        { label: "Bid", numeric: true },
        { label: "Ask", numeric: true },
        { label: "Mid / share", numeric: true },
        { label: "Delta", numeric: true },
        { label: "IV", numeric: true },
        { label: "Qty", numeric: true },
        { label: "Premium", numeric: true },
        "",
      ],
      "",
    ).replace("<tbody></tbody>", rows) +
    `<div class="board-actions"><span data-board-count></span><div class="row-actions"><button class="button secondary" data-board-best>Select best matches</button><button class="button primary" data-board-save>Add selected to queue</button></div></div>`;
  root.onclick = (event) => {
    const button = event.target.closest("[data-board-add]");
    if (!button) return;
    busy(button, async () => {
      const entry = selections[Number(button.dataset.boardAdd)];
      if (await saveDraft(entry.option, entry.ticker, entry.quantity)) {
        entry.selected = false;
        root.querySelector(
          `[data-board-select="${button.dataset.boardAdd}"]`,
        ).checked = false;
        update();
      }
    });
  };
  const button = root.querySelector("[data-board-save]");
  const update = () => {
    root.querySelector("[data-scan-progress]").textContent =
      `${completed.size} / ${data.results.length} symbols complete · ${selections.length} matching contracts`;
    const count = selections.filter((s) => s.selected).length;
    root.querySelector("[data-board-count]").textContent = `${count} selected`;
    button.disabled = !count || count > 20;
    if (count > 20)
      root.querySelector("[data-board-count]").textContent =
        `${count} selected · Save up to 20 drafts per batch`;
  };
  root.onchange = (event) => {
    const input = event.target;
    const index = input.dataset.boardSelect ?? input.dataset.boardQuantity;
    if (index === undefined) return;
    const selection = selections[Number(index)];
    if (input.hasAttribute("data-board-select"))
      selection.selected = input.checked;
    if (input.hasAttribute("data-board-quantity")) {
      const quantity = Number(input.value);
      if (!Number.isInteger(quantity) || quantity < 1) {
        input.value = selection.quantity;
        toast("Enter a positive whole number of contracts.", true);
        return;
      }
      selection.quantity = quantity;
      if (selection.option.option_type === "PUT")
        rememberPutQuantity(selection.ticker, quantity);
    }
    root.querySelector(
      `[data-board-row="${index}"] [data-board-premium]`,
    ).textContent = money(selection.option.mid * 100 * selection.quantity);
    update();
  };
  root.querySelector("[data-board-best]").addEventListener("click", () => {
    selections.forEach((s, i) => {
      s.selected = s.best && s.available;
      root.querySelector(`[data-board-select="${i}"]`).checked = s.selected;
    });
    update();
  });
  button.addEventListener("click", () =>
    busy(button, async () => {
      const selected = selections.filter((s) => s.selected);
      if (await saveDrafts(selected)) {
        selected.forEach((s) => (s.selected = false));
        root
          .querySelectorAll("[data-board-select]")
          .forEach(
            (input) =>
              (input.checked =
                selections[Number(input.dataset.boardSelect)].selected),
          );
      }
    }).finally(update),
  );
  update();
  return {
    add(result) {
      if (completed.has(result.symbol)) return;
      const index = data.results.findIndex((r) => r.symbol === result.symbol);
      if (index < 0) return;
      data.results[index] = result;
      completed.add(result.symbol);
      root.querySelector(`[data-symbol-group="${index}"]`).innerHTML =
        symbolRows(result);
      update();
    },
    fail(message) {
      data.results
        .filter((r) => r.loading)
        .forEach((r) => this.add({ symbol: r.symbol, error: message }));
    },
  };
}
