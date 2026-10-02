import { friday, icon } from "./ui.js";

const iso = (value) => value.toISOString().slice(0, 10);
const fromISO = (value) => new Date(`${value}T12:00:00Z`);
const format = (value, options) =>
  new Intl.DateTimeFormat("en-US", { ...options, timeZone: "UTC" }).format(
    value,
  );
const comingFriday = () =>
  friday().replace(/^(\d{4})(\d{2})(\d{2})$/, "$1-$2-$3");

export function initExpiryPicker({ allowEmpty = false, initialValue } = {}) {
  const input = document.querySelector("#expiry-select");
  const trigger = document.querySelector("#expiry-trigger");
  const popup = document.createElement("div");
  popup.id = "expiry-calendar";
  popup.className = "expiry-calendar";
  popup.setAttribute("popover", "auto");
  popup.setAttribute("role", "dialog");
  popup.setAttribute("aria-label", "Choose expiration date");
  document.body.append(popup);
  input.value =
    initialValue ?? friday(1).replace(/^(\d{4})(\d{2})(\d{2})$/, "$1-$2-$3");
  let focused = input.value || comingFriday();
  let month = fromISO(focused);
  month.setUTCDate(1);

  function updateLabel() {
    if (!input.value && allowEmpty) {
      trigger.innerHTML = `<span>All expirations</span>${icon("calendar")}`;
      trigger.setAttribute("aria-label", "Expiration: All expirations");
      return;
    }
    trigger.innerHTML = `<span>${format(fromISO(input.value), { month: "short", day: "numeric", year: "numeric" })}</span>${icon("calendar")}`;
    trigger.setAttribute(
      "aria-label",
      `Expiration: ${format(fromISO(input.value), { month: "long", day: "numeric", year: "numeric" })}`,
    );
  }
  function position() {
    const rect = trigger.getBoundingClientRect();
    const width = Math.min(332, window.innerWidth - 24);
    popup.style.width = `${width}px`;
    popup.style.maxHeight = `${window.innerHeight - 24}px`;
    popup.style.left = `${Math.max(12, Math.min(rect.left, window.innerWidth - width - 12))}px`;
    const height = popup.offsetHeight;
    const below = rect.bottom + 8;
    popup.style.top = `${below + height <= window.innerHeight - 12 ? below : Math.max(12, rect.top - height - 8)}px`;
  }
  function render(focus = false) {
    const start = new Date(month);
    start.setUTCDate(1 - ((month.getUTCDay() + 6) % 7));
    const today = new Intl.DateTimeFormat("en-CA", {
      timeZone: "America/New_York",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(new Date());
    const rows = [];
    for (let week = 0; week < 6; week++) {
      const cells = [];
      for (let day = 0; day < 7; day++) {
        const date = new Date(start);
        date.setUTCDate(start.getUTCDate() + week * 7 + day);
        const value = iso(date);
        cells.push(
          `<td role="gridcell" aria-selected="${value === input.value}"><button type="button" data-date="${value}" tabindex="${value === focused ? 0 : -1}" class="calendar-day${date.getUTCMonth() !== month.getUTCMonth() ? " outside-month" : ""}${value === input.value ? " selected" : ""}" aria-label="${format(date, { weekday: "long", month: "long", day: "numeric", year: "numeric" })}"${value === today ? ' aria-current="date"' : ""}>${date.getUTCDate()}</button></td>`,
        );
      }
      rows.push(`<tr role="row">${cells.join("")}</tr>`);
    }
    popup.innerHTML = `<div class="calendar-heading"><button type="button" class="calendar-nav" data-month-step="-1" aria-label="Previous month">‹</button><strong id="calendar-month" data-month="${iso(month).slice(0, 7)}" aria-live="polite">${format(month, { month: "long", year: "numeric" })}</strong><button type="button" class="calendar-nav" data-month-step="1" aria-label="Next month">›</button></div><table class="calendar-grid" role="grid" aria-labelledby="calendar-month"><thead><tr role="row">${["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((day) => `<th scope="col" role="columnheader">${day}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table><div class="calendar-shortcuts">${allowEmpty ? '<button type="button" data-clear-expiry>All expirations</button>' : ""}<button type="button" data-friday="0">Coming Friday</button><button type="button" data-friday="7">Following Friday</button></div>`;
    if (popup.matches(":popover-open")) position();
    if (focus)
      popup
        .querySelector(`[data-date="${focused}"]`)
        ?.focus({ preventScroll: true });
  }
  function close(restore = true) {
    popup.hidePopover();
    trigger.setAttribute("aria-expanded", "false");
    if (restore) trigger.focus({ preventScroll: true });
  }
  function select(value) {
    const changed = input.value !== value;
    input.value = value;
    updateLabel();
    close();
    if (changed) {
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }
  trigger.addEventListener("click", () => {
    if (popup.matches(":popover-open")) return close();
    focused = input.value || comingFriday();
    month = fromISO(focused);
    month.setUTCDate(1);
    render();
    popup.showPopover();
    trigger.setAttribute("aria-expanded", "true");
    position();
    popup
      .querySelector(`[data-date="${focused}"]`)
      ?.focus({ preventScroll: true });
  });
  popup.addEventListener("toggle", () =>
    trigger.setAttribute(
      "aria-expanded",
      String(popup.matches(":popover-open")),
    ),
  );
  popup.addEventListener("click", (event) => {
    if (allowEmpty && event.target.closest("[data-clear-expiry]"))
      return select("");
    const day = event.target.closest("[data-date]");
    if (day) return select(day.dataset.date);
    const shortcut = event.target.closest("[data-friday]");
    if (shortcut) {
      const value = fromISO(comingFriday());
      value.setUTCDate(value.getUTCDate() + Number(shortcut.dataset.friday));
      return select(iso(value));
    }
    const nav = event.target.closest("[data-month-step]");
    if (nav) {
      const step = Number(nav.dataset.monthStep);
      month.setUTCMonth(month.getUTCMonth() + step);
      focused = iso(month);
      render();
      popup
        .querySelector(`[data-month-step="${step}"]`)
        .focus({ preventScroll: true });
    }
  });
  popup.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      return close();
    }
    const day = event.target.closest("[data-date]");
    if (!day) return;
    const value = fromISO(day.dataset.date);
    const shift = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[
      event.key
    ];
    if (shift !== undefined) value.setUTCDate(value.getUTCDate() + shift);
    else if (event.key === "Home")
      value.setUTCDate(value.getUTCDate() - ((value.getUTCDay() + 6) % 7));
    else if (event.key === "End")
      value.setUTCDate(value.getUTCDate() + 6 - ((value.getUTCDay() + 6) % 7));
    else if (["PageUp", "PageDown"].includes(event.key)) {
      const date = value.getUTCDate();
      value.setUTCDate(1);
      value.setUTCMonth(
        value.getUTCMonth() +
          (event.key === "PageUp" ? -1 : 1) * (event.shiftKey ? 12 : 1),
      );
      const last = new Date(
        Date.UTC(value.getUTCFullYear(), value.getUTCMonth() + 1, 0),
      ).getUTCDate();
      value.setUTCDate(Math.min(date, last));
    } else return;
    event.preventDefault();
    focused = iso(value);
    month = new Date(value);
    month.setUTCDate(1);
    render(true);
  });
  document.addEventListener("focusin", (event) => {
    if (
      popup.matches(":popover-open") &&
      !popup.contains(event.target) &&
      event.target !== trigger
    )
      close(false);
  });
  window.addEventListener("resize", () => {
    if (popup.matches(":popover-open")) position();
  });
  window.addEventListener(
    "scroll",
    (event) => {
      if (popup.matches(":popover-open") && !popup.contains(event.target))
        position();
    },
    true,
  );
  updateLabel();
}
