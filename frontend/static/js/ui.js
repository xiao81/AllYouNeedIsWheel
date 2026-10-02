const paths = {
  grid: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
  layers: "m12 3 10 5-10 5L2 8z M2 12l10 5 10-5 M2 16l10 5 10-5",
  repeat:
    "m17 2 4 4-4 4 M3 11V8a2 2 0 0 1 2-2h16 M7 22l-4-4 4-4 M21 13v3a2 2 0 0 1-2 2H3",
  settings:
    "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M9 3h6l1 3 3 1 2 5-2 5-3 1-1 3H9l-1-3-3-1-2-5 2-5 3-1z",
  refresh:
    "M20 7a9 9 0 0 0-15-2L2 8 M2 2v6h6 M4 17a9 9 0 0 0 15 2l3-3 M22 22v-6h-6",
  search: "M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14 M15 15l6 6",
  compass: "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20 m4 6-2 6-6 2 2-6z",
  calendar:
    "M5 4h14a2 2 0 0 1 2 2v14H3V6a2 2 0 0 1 2-2 M7 2v4 M17 2v4 M3 10h18 M7 14h2 M13 14h2",
  wallet: "M3 6h17v14H3V6l14-3v3 M20 11h-6v5h6 M16 13.5h1",
  shield: "m12 2 9 4v6c0 5-9 10-9 10S3 17 3 12V6z m-4 10 3 3 5-6",
  info: "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20 M12 11v6 M12 7v.1",
  "arrow-up-right": "M5 19 19 5 M5 5h14v14",
  check: "m4 12 5 5L20 6",
};
export const icon = (name) =>
  `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name] || paths.info}"/></svg>`;
export function icons(root = document) {
  root
    .querySelectorAll("[data-icon]")
    .forEach((el) => (el.innerHTML = icon(el.dataset.icon)));
}
export const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
export const money = (value) =>
  value === null || value === undefined || !Number.isFinite(Number(value))
    ? "—"
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 2,
      }).format(value);
export const num = (value, digits = 2) =>
  value === null || value === undefined || !Number.isFinite(Number(value))
    ? "—"
    : Number(value).toFixed(digits);
export const date = (value) =>
  /^\d{8}$/.test(value)
    ? new Date(
        `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}T12:00:00`,
      ).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
      })
    : esc(value || "—");
export function empty(title, description, action = "") {
  return `<div class="empty-state"><span class="empty-icon">${icon("compass")}</span><h3>${esc(title)}</h3><p>${esc(description)}</p>${action}</div>`;
}
export const loading = (text) =>
  `<div class="loading-state"><span class="spinner"></span><span>${esc(text)}</span></div>`;
export const notice = (text, type = "error") =>
  `<div class="notice ${type}" role="status">${icon("info")}<span>${esc(text)}</span></div>`;
export function toast(message, error = false, source = document.activeElement) {
  if (!error) return;
  const section = source?.closest?.(".panel") || document.querySelector("main");
  section.querySelector(":scope > .inline-error")?.remove();
  const el = document.createElement("div");
  el.className = "inline-error";
  el.setAttribute("role", "alert");
  const text = document.createElement("span");
  text.textContent = message;
  const close = document.createElement("button");
  close.type = "button";
  close.className = "text-link";
  close.textContent = "Dismiss";
  close.setAttribute("aria-label", "Dismiss error");
  close.onclick = () => el.remove();
  el.append(text, close);
  const heading = section.querySelector(
    ":scope > .panel-heading, :scope > .page-heading",
  );
  if (heading) heading.after(el);
  else section.prepend(el);
  const rect = el.getBoundingClientRect();
  if (rect.top < 0 || rect.bottom > window.innerHeight)
    el.scrollIntoView({ block: "center", behavior: "instant" });
}
export async function busy(button, task) {
  if (button.disabled) return;
  const errorAnchor = button.closest(".panel") || button;
  errorAnchor.querySelector(":scope > .inline-error")?.remove();
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  try {
    return await task();
  } catch (error) {
    toast(error.message, true, errorAnchor);
  } finally {
    button.disabled = false;
    button.removeAttribute("aria-busy");
  }
}
export function review(title, content, confirmText = "Save draft") {
  const dialog = document.querySelector("#order-dialog");
  if (dialog.open) return Promise.resolve(false);
  document.querySelector("#dialog-title").textContent = title;
  document.querySelector("#dialog-content").innerHTML = content;
  document.querySelector("#dialog-confirm").textContent = confirmText;
  dialog.returnValue = "";
  dialog.showModal();
  return new Promise((resolve) =>
    dialog.addEventListener(
      "close",
      () => resolve(dialog.returnValue === "confirm"),
      { once: true },
    ),
  );
}
export const table = (headers, rows) =>
  `<div class="table-wrap"><table><thead><tr>${headers.map((h) => `<th scope="col"${h.numeric ? ' class="number"' : ""}>${esc(typeof h === "object" ? h.label : h)}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table></div>`;
export const store = {
  get(key, fallback) {
    try {
      return JSON.parse(localStorage.getItem(key)) ?? fallback;
    } catch {
      return fallback;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {}
  },
};
export function friday(weeksAfter = 0) {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", {
      timeZone: "America/New_York",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      hourCycle: "h23",
    })
      .formatToParts(new Date())
      .map((p) => [p.type, p.value]),
  );
  const day = new Date(`${parts.year}-${parts.month}-${parts.day}T12:00:00Z`);
  let offset = (5 - day.getUTCDay() + 7) % 7;
  if (!offset && Number(parts.hour) >= 16) offset = 7;
  day.setUTCDate(day.getUTCDate() + offset + 7 * weeksAfter);
  return day.toISOString().slice(0, 10).replaceAll("-", "");
}
