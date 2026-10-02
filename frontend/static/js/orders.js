import { rememberPutQuantity } from "./put-quantities.js";
import { request } from "./api.js";
import {
  esc,
  money,
  date,
  table,
  empty,
  loading,
  notice,
  toast,
  busy,
  review,
  icon,
} from "./ui.js";
let orders = [],
  isRoll = false,
  mode = null,
  timer = null,
  loadingOrders = false,
  reconcilingOrders = false,
  reloadOrders = false,
  bulkRunning = false,
  bulkReport = "",
  editingQuantity = 0;
const assignmentCost = (order) =>
  order.action === "SELL" && order.option_type === "PUT"
    ? order.strike * 100 * order.quantity
    : null;
const assignmentCell = (order) =>
  `<td class="number" data-assignment-cost title="Cash required if assigned; before premium received">${money(assignmentCost(order))}</td>`;
const states = {
  pending: ["neutral", "Draft"],
  submitting: ["warn", "Submitting"],
  processing: ["warn", "Working"],
  canceling: ["warn", "Cancel requested"],
  submission_unknown: ["danger", "Verify in TWS"],
  executed: ["good", "Filled"],
  canceled: ["neutral", "Canceled"],
  rejected: ["danger", "Rejected"],
};
export function setMode(value) {
  mode = value;
}
export async function loadOrders(roll = isRoll, reconcile = false) {
  isRoll = roll;
  if (loadingOrders) {
    reloadOrders = true;
    return false;
  }
  loadingOrders = true;
  const el = document.querySelector("#orders-content");
  if (!el) {
    loadingOrders = false;
    return;
  }
  if (!orders.length) el.innerHTML = loading("Loading order queue");
  try {
    const data = await request(
      `/api/options/pending-orders?executed=false${roll ? "&isRollover=true" : ""}`,
    );
    orders = data.orders || [];
    render();
    if (reconcile) void reconcileBrokerOrders();
    return true;
  } catch (error) {
    el.innerHTML =
      notice(error.message) +
      `<div class="empty-state"><button class="button secondary" data-order-retry>Try again</button></div>`;
  } finally {
    loadingOrders = false;
    if (reloadOrders) {
      reloadOrders = false;
      await loadOrders();
    }
    schedule();
  }
}
async function reconcileBrokerOrders() {
  if (
    reconcilingOrders ||
    !orders.some((o) =>
      ["processing", "canceling", "submission_unknown"].includes(o.status),
    )
  )
    return;
  reconcilingOrders = true;
  try {
    await request("/api/options/check-orders", { method: "POST" });
    await loadOrders();
  } catch (error) {
    toast(error.message, true, document.querySelector("#orders-content"));
  } finally {
    reconcilingOrders = false;
  }
}
async function prepareSubmission(selected) {
  const data = await request("/api/options/orders/prepare-submission", {
    method: "POST",
    body: { order_ids: selected.map((order) => order.id) },
  });
  await loadOrders();
  return data.orders;
}
function schedule() {
  clearTimeout(timer);
  if (
    !bulkRunning &&
    orders.some((o) => ["processing", "canceling"].includes(o.status))
  )
    timer = setTimeout(() => {
      if (!document.hidden) loadOrders(isRoll, true);
      else schedule();
    }, 15000);
}
function render() {
  const el = document.querySelector("#orders-content");
  const count = document.querySelector("#order-count");
  if (count) count.textContent = orders.length;
  if (!orders.length) {
    el.innerHTML =
      `<div class="bulk-report" role="status">${bulkReport}</div>` +
      empty(
        "A clean slate.",
        "Options you save will appear here for review before submission.",
      );
    return;
  }
  const drafts = orders.filter((o) => o.status === "pending" && !o.isRollover);
  const cancelable = orders.filter((o) => o.status === "pending");
  const readonly = !mode || mode[mode.mode]?.readonly;
  const showAssignment = orders.some((o) => assignmentCost(o) !== null);
  el.innerHTML =
    `<div class="queue-bulk-actions"><span>${drafts.length} drafts ready · ${cancelable.length} unsubmitted</span><div class="row-actions"><button class="button primary small" data-submit-all ${!drafts.length || readonly ? "disabled" : ""}>Submit all drafts</button><button class="button secondary small" data-cancel-all ${!cancelable.length ? "disabled" : ""}>Cancel all</button></div></div>${readonly ? '<p class="queue-bulk-note">Read-only connection: broker submissions are disabled.</p>' : ""}${orders.some((o) => o.status === "pending" && o.isRollover) ? '<p class="queue-bulk-note">Rollover drafts require individual submission so the closing leg can be confirmed first.</p>' : ""}<div class="bulk-report" role="status">${bulkReport}</div>` +
    table(
      [
        "Contract",
        { label: "Limit / share", numeric: true },
        { label: "Qty", numeric: true },
        ...(showAssignment
          ? [{ label: "Assignment cost", numeric: true }]
          : []),
        "Status",
        "",
      ],
      orders
        .map((o) => {
          const [color, label] = states[o.status] || ["neutral", o.status];
          return `<tr><td><span class="symbol">${esc(o.ticker)}</span> <span class="badge neutral">${esc(o.action)} ${esc(o.option_type)}</span><span class="subtext">${money(o.strike)} · ${date(o.expiration)}${o.isRollover ? " · Roll" : ""}</span></td><td class="number">${o.order_type === "MARKET" ? "Market" : money(o.limit_price ?? o.premium)}</td><td class="number">${o.status === "pending" ? `<input class="qty-input" data-quantity="${o.id}" type="number" min="1" step="1" value="${o.quantity}" aria-label="Quantity for ${esc(o.ticker)} order ${o.id}">` : o.quantity}</td>${showAssignment ? assignmentCell(o) : ""}<td><span class="badge ${color}">${esc(label)}</span>${o.ib_order_id ? `<span class="subtext">IB ${esc(o.ib_order_id)}</span>` : ""}${["processing", "canceling", "submission_unknown"].includes(o.status) ? '<span class="subtext">Manage cancellation in IBKR</span>' : ""}</td><td><div class="row-actions">${o.status === "pending" ? `<button class="button primary small" data-submit="${o.id}">Submit</button>` : ""}${["processing", "canceling", "submission_unknown"].includes(o.status) ? `<button class="button secondary small" data-remove-local="${o.id}" aria-label="Remove local record for ${esc(o.ticker)} order ${o.id}">Remove local record</button>` : ""}${o.status === "pending" ? `<button class="icon-button" data-cancel="${o.id}" aria-label="Cancel ${esc(o.ticker)} order ${o.id}">×</button>` : ""}</div></td></tr>`;
        })
        .join(""),
    );
  lockQueue();
}
function lockQueue() {
  const root = document.querySelector("#orders-content");
  if (bulkRunning)
    root
      .querySelectorAll("button, input")
      .forEach((el) => (el.disabled = true));
  if (editingQuantity)
    root
      .querySelectorAll("[data-submit-all], [data-cancel-all]")
      .forEach((el) => (el.disabled = true));
  const refresh = document.querySelector("#refresh-orders");
  if (refresh) refresh.disabled = bulkRunning;
}
function reportBulk(action, selected, outcomes, finished = false) {
  if (action === "cancel") {
    const failures = outcomes
      .map((item, i) => ({ ...item, order: selected[i] }))
      .filter((item) => !item.ok);
    bulkReport = finished
      ? failures.length
        ? table(
            ["Draft", "Needs attention"],
            failures
              .map(
                ({ order, message }) =>
                  `<tr><td>#${order.id} ${esc(order.ticker)} ${money(order.strike)} ${esc(order.option_type)}</td><td>${esc(message)}</td></tr>`,
              )
              .join(""),
          )
        : ""
      : `<p>Removing drafts ${outcomes.length} / ${selected.length}…</p>`;
    const el = document.querySelector(".bulk-report");
    if (el) el.innerHTML = bulkReport;
    return;
  }
  const succeeded = outcomes.filter((o) => o.ok).length;
  bulkReport =
    `<p><b>${finished ? "Batch finished" : `${action === "submit" ? "Submitting" : "Canceling"} ${outcomes.length} / ${selected.length}`}</b> · ${succeeded} successful · ${outcomes.filter((o) => !o.ok && !o.skipped).length} failed${outcomes.some((o) => o.skipped) ? ` · ${outcomes.filter((o) => o.skipped).length} not attempted` : ""}</p>` +
    table(
      ["Order", "Result"],
      outcomes
        .map(
          (item, i) =>
            `<tr><td>#${selected[i].id} ${esc(selected[i].ticker)} ${money(selected[i].strike)} ${esc(selected[i].option_type)}</td><td>${esc(item.message)}</td></tr>`,
        )
        .join(""),
    );
  const el = document.querySelector(".bulk-report");
  if (el) el.innerHTML = bulkReport;
}
async function runBulk(action) {
  if (bulkRunning || editingQuantity) return;
  bulkRunning = true;
  clearTimeout(timer);
  lockQueue();
  try {
    if (!(await loadOrders()))
      throw new Error(
        "Could not refresh the queue. Try again before submitting or canceling orders.",
      );
    let selected = orders
      .filter((o) =>
        action === "submit"
          ? o.status === "pending" && !o.isRollover
          : o.status === "pending",
      )
      .map((o) => ({ ...o }));
    if (!selected.length) return;
    const live = mode?.mode === "live";
    if (action === "submit" && (!mode || mode[mode.mode]?.readonly))
      throw new Error("Broker connection is read-only.");
    if (action === "submit") selected = await prepareSubmission(selected);
    const showAssignment =
      action === "submit" && selected.some((o) => assignmentCost(o) !== null);
    const detail =
      action === "submit"
        ? `Send ${selected.length} separate ${live ? "LIVE" : "paper"} orders to IBKR at the quantities and prices below. Submission stops at the first failure; completed submissions are not rolled back. No failed request is automatically retried.`
        : `Remove ${selected.length} unsubmitted drafts from the queue, including rollover drafts. Submitted and working IBKR orders are left unchanged.`;
    if (
      !(await review(
        action === "submit"
          ? `Submit all ${live ? "live" : "paper"} drafts`
          : "Cancel all drafts",
        `<p class="dialog-note">${detail}</p>` +
          table(
            [
              "Contract / expiry",
              "Action",
              { label: "Qty", numeric: true },
              { label: "Limit / share", numeric: true },
              ...(showAssignment
                ? [{ label: "Assignment cost", numeric: true }]
                : []),
            ],
            selected
              .map(
                (o) =>
                  `<tr><td>${esc(o.ticker)} ${money(o.strike)} ${esc(o.option_type)}<span class="subtext">${date(o.expiration)}</span></td><td>${esc(o.action)}</td><td class="number">${o.quantity}</td><td class="number">${o.order_type === "MARKET" ? "Market" : money(o.limit_price ?? o.premium)}</td>${showAssignment ? assignmentCell(o) : ""}</tr>`,
              )
              .join(""),
          ),
        action === "submit"
          ? `Submit ${selected.length} ${live ? "live" : "paper"} orders`
          : `Remove ${selected.length} drafts`,
      ))
    )
      return;
    const outcomes = [];
    reportBulk(action, selected, outcomes);
    for (const order of selected) {
      try {
        const data = await request(
          action === "cancel"
            ? `/api/options/order/${order.id}/draft`
            : `/api/options/execute/${order.id}`,
          {
            method: action === "cancel" ? "DELETE" : "POST",
            ...(action === "submit"
              ? { body: { expected_order: order, bulk: true } }
              : {}),
          },
        );
        const rejected =
          action === "submit" &&
          ["rejected", "canceled", "submission_unknown"].includes(data.status);
        outcomes.push({
          ok: !rejected,
          message: rejected
            ? `Broker status: ${data.status}`
            : action === "submit"
              ? data.status === "executed"
                ? "Filled"
                : "Sent to broker"
              : "Draft removed from queue",
        });
        if (rejected) break;
      } catch (error) {
        outcomes.push({ ok: false, message: error.message });
        if (
          action === "submit" ||
          error.message.includes("Connection settings changed")
        )
          break;
      }
      reportBulk(action, selected, outcomes);
    }
    while (outcomes.length < selected.length)
      outcomes.push({
        ok: false,
        skipped: true,
        message: "Not attempted after earlier failure",
      });
    reportBulk(action, selected, outcomes, true);
  } catch (error) {
    toast(error.message, true, document.querySelector("#orders-content"));
  } finally {
    bulkRunning = false;
    await loadOrders();
    lockQueue();
    schedule();
  }
}
export function initOrders(roll = false) {
  isRoll = roll;
  const root = document.querySelector("#orders-content");
  if (!root) return;
  root.addEventListener("click", async (event) => {
    if (bulkRunning) return;
    if (event.target.closest("[data-submit-all]")) return runBulk("submit");
    if (event.target.closest("[data-cancel-all]")) return runBulk("cancel");
    const submit = event.target.closest("[data-submit]");
    const cancel = event.target.closest("[data-cancel]");
    const retry = event.target.closest("[data-order-retry]");
    if (retry) return loadOrders();
    const remove = event.target.closest("[data-remove-local]");
    if (remove)
      return busy(remove, async () => {
        const order = orders.find(
          (o) => o.id === Number(remove.dataset.removeLocal),
        );
        if (
          !(await review(
            "Remove local order record",
            `<p class="dialog-note">Remove ${esc(order.ticker)} ${money(order.strike)} ${esc(order.option_type)} · ${date(order.expiration)} (local #${order.id}, IB ${esc(order.ib_order_id || "unknown")}) from this database? This does not cancel the order at IBKR. It may still be working there, and this dashboard will stop tracking it.</p>`,
            "Remove local record",
          ))
        )
          return;
        await request(`/api/options/order/${order.id}/local`, {
          method: "DELETE",
          body: { confirm_local_only: true },
        });
        toast("Local record removed. The broker order was not canceled.");
        await loadOrders();
      });
    if (submit)
      await busy(submit, async () => {
        const selected = orders.find(
          (o) => o.id === Number(submit.dataset.submit),
        );
        const [o] = await prepareSubmission([selected]);
        const live = mode?.mode === "live";
        const price = o.limit_price ?? o.premium;
        const yes = await review(
          `${live ? "Live" : "Paper"} order submission`,
          `<p class="dialog-note">This sends the order to Interactive Brokers.</p><dl class="review-grid"><div><dt>Contract</dt><dd>${esc(o.ticker)} ${money(o.strike)} ${esc(o.option_type)}</dd></div><div><dt>Action</dt><dd>${esc(o.action)} ${o.quantity}</dd></div><div><dt>Expiration</dt><dd>${date(o.expiration)}</dd></div><div><dt>Limit / share</dt><dd>${o.order_type === "MARKET" ? "Market" : money(price)}</dd></div>${assignmentCost(o) !== null ? `<div><dt>Assignment cost</dt><dd>${money(assignmentCost(o))}</dd></div>` : ""}</dl><p class="dialog-note">${o.order_type === "MARKET" ? "A market order has no guaranteed execution price." : `Gross premium at limit: ${money(price * 100 * o.quantity)}, before fees.`}${o.isRollover ? " This submits one leg only. Confirm the closing leg is filled before submitting the opening leg." : ""}</p>`,
          live ? "Submit live order" : "Submit paper order",
        );
        if (!yes) return;
        await request(`/api/options/execute/${o.id}`, {
          method: "POST",
          body: { expected_order: o },
        });
        toast("Order submitted. Tracking broker status.");
        await loadOrders();
      });
    if (cancel)
      await busy(cancel, async () => {
        const o = orders.find((o) => o.id === Number(cancel.dataset.cancel));
        if (!o || o.status !== "pending") return;
        await request(`/api/options/order/${o.id}/draft`, { method: "DELETE" });
        toast("Draft removed from queue.");
        await loadOrders();
      });
  });
  root.addEventListener("change", async (event) => {
    const input = event.target.closest("[data-quantity]");
    if (!input) return;
    const o = orders.find((o) => o.id === Number(input.dataset.quantity));
    const quantity = Number(input.value);
    if (!Number.isInteger(quantity) || quantity < 1) {
      input.value = o.quantity;
      return;
    }
    input.disabled = true;
    editingQuantity++;
    lockQueue();
    try {
      await request(`/api/options/order/${o.id}/quantity`, {
        method: "PUT",
        body: { quantity },
      });
      o.quantity = quantity;
      if (o.action === "SELL" && o.option_type === "PUT")
        rememberPutQuantity(o.ticker, quantity);
    } catch (error) {
      input.value = o.quantity;
      toast(error.message, true, document.querySelector("#orders-content"));
    } finally {
      input.disabled = false;
      editingQuantity--;
      render();
    }
  });
  document
    .querySelector("#refresh-orders")
    ?.addEventListener("click", (event) =>
      busy(event.currentTarget, () => loadOrders(roll, true)),
    );
  loadOrders(roll);
  window.addEventListener("pagehide", () => clearTimeout(timer));
}
export async function saveDraft(option, ticker, quantity = 1) {
  if (!Number.isInteger(quantity) || quantity < 1)
    throw new Error("Enter a whole number of contracts greater than zero.");
  await request("/api/options/order", {
    method: "POST",
    body: {
      ticker,
      option_type: option.option_type,
      strike: option.strike,
      expiration: option.expiration,
      quantity,
      action: "SELL",
      order_type: "LIMIT",
      limit_price: option.mid,
      premium: option.mid,
      bid: option.bid,
      ask: option.ask,
      delta: option.delta,
    },
  });
  toast("Draft saved to your order queue.");
  await loadOrders();
  return true;
}

export async function saveDrafts(candidates) {
  if (!candidates.length) return false;
  const orders = candidates.map(({ option, ticker, quantity }) => {
    if (!Number.isInteger(quantity) || quantity < 1)
      throw new Error(`Enter a positive whole quantity for ${ticker}.`);
    return {
      ticker,
      option_type: option.option_type,
      strike: option.strike,
      expiration: option.expiration,
      quantity,
      action: "SELL",
      order_type: "LIMIT",
      limit_price: option.mid,
      bid: option.bid,
      ask: option.ask,
      delta: option.delta,
    };
  });
  await request("/api/options/orders/batch", {
    method: "POST",
    body: { orders },
  });
  toast(`${orders.length} drafts saved to your order queue.`);
  await loadOrders();
  return true;
}
