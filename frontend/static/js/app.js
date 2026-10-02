import { request, setProfileRevision } from "./api.js";
import { icons, toast } from "./ui.js";
import { setMode } from "./orders.js";
icons();
const clock = document.querySelector("#market-clock");
clock.textContent =
  new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date()) + " ET";
export function applySettings(settings) {
  setProfileRevision(settings.revision);
  setMode(settings);
  const profile = settings[settings.mode];
  const badge = document.querySelector("#mode-badge");
  badge.className = `badge ${settings.mode === "live" ? "warn" : "good"}`;
  badge.textContent = `${settings.mode === "live" ? "LIVE ACCOUNT" : "PAPER ACCOUNT"}${profile.readonly ? " · READ ONLY" : ""}`;
  document.querySelector("#sidebar-status").textContent =
    `${profile.platform === "gateway" ? "IB Gateway" : "Trader Workstation"} · ${profile.readonly ? "Read only" : "Trading enabled"}`;
}
const settingsPromise = request("/api/settings")
  .then((settings) => {
    applySettings(settings);
    return settings;
  })
  .catch((error) => {
    document.querySelector("#mode-badge").textContent = "Connection setup";
    document.querySelector("#sidebar-status").textContent =
      "Open Settings to get connected";
    return null;
  });
try {
  const page = document.body.dataset.page;
  if (page === "dashboard") {
    const { initDashboard } = await import("./dashboard.js");
    await settingsPromise;
    initDashboard();
  } else if (page === "portfolio") {
    const { initPortfolio } = await import("./portfolio.js");
    initPortfolio();
  } else if (page === "rollover") {
    const { initRollover } = await import("./rollover.js");
    await settingsPromise;
    initRollover();
  } else if (page === "settings") {
    const { initSettings } = await import("./settings.js");
    await initSettings(await settingsPromise, applySettings);
  }
} catch (error) {
  toast(error.message, true);
}
