import { money, num } from "./ui.js";

export function optionMetrics(option, stockPrice) {
  const strike = option.strike;
  const hasStock = Number.isFinite(stockPrice) && stockPrice > 0;
  const hasStrike = Number.isFinite(strike) && strike > 0;
  const breakeven =
    option.option_type === "PUT" &&
    hasStrike &&
    Number.isFinite(option.mid) &&
    option.mid >= 0
      ? strike - option.mid
      : null;
  return {
    distance:
      hasStock && hasStrike ? ((strike - stockPrice) / stockPrice) * 100 : null,
    breakeven,
    breakevenDistance:
      hasStock && breakeven !== null
        ? ((breakeven - stockPrice) / stockPrice) * 100
        : null,
  };
}

function relativePercent(value) {
  if (value === null) return "—";
  if (Math.abs(value) < 0.005) return "At stock price";
  return `${num(Math.abs(value))}% ${value < 0 ? "below" : "above"}`;
}

export function priceDistanceCells(option, stockPrice) {
  const { distance, breakeven, breakevenDistance } = optionMetrics(
    option,
    stockPrice,
  );
  const description =
    option.option_type === "CALL"
      ? "Move to call strike"
      : "Drop to put strike; not maximum loss";
  const distanceCell = `<td class="number" data-strike-distance title="${description}: (strike − stock price) ÷ stock price × 100">${relativePercent(distance)}</td>`;
  if (option.option_type !== "PUT") return distanceCell;
  return (
    distanceCell +
    `<td class="number" data-put-breakeven title="Short-put breakeven at expiry = strike − premium per share. Uses the quoted midpoint, before fees.">${money(breakeven)}${breakeven !== null && breakevenDistance !== null ? `<span class="subtext">${relativePercent(breakevenDistance)} stock</span>` : ""}</td>`
  );
}

export function hasUsableQuote(option) {
  return (
    Number.isFinite(option.bid) &&
    option.bid >= 0 &&
    Number.isFinite(option.ask) &&
    option.ask > 0 &&
    option.ask >= option.bid &&
    Number.isFinite(option.mid) &&
    option.mid > 0
  );
}
