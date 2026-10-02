import { request } from "./api.js";
import { esc, icon, notice, loading, busy } from "./ui.js";
let draft = null,
  dirty = false;
export async function initSettings(settings, onSave) {
  const el = document.querySelector("#settings-content");
  el.innerHTML = loading("Loading connection settings");
  try {
    draft = structuredClone(settings || (await request("/api/settings")));
    render();
  } catch (error) {
    el.innerHTML = notice(error.message);
    return;
  }
  function capture() {
    const form = document.querySelector("#settings-form");
    if (!form) return;
    const profile = draft[draft.mode];
    for (const key of ["host", "port", "client_id", "account_id", "platform"])
      profile[key] = form.elements[key].value;
    profile.readonly = form.elements.readonly.checked;
  }
  function markDirty() {
    dirty = true;
    document.querySelector("#test-connection").disabled = true;
    document.querySelector("#save-hint").textContent = "Unsaved changes";
  }
  function render() {
    const mode = draft.mode,
      p = draft[mode];
    el.innerHTML = `<div class="mode-picker" role="group" aria-label="Trading mode"><button class="mode-choice ${mode === "paper" ? "selected" : ""}" data-mode="paper" aria-pressed="${mode === "paper"}">${icon("layers")}<span><strong>Paper trading</strong><small>Practice with simulated funds</small></span></button><button class="mode-choice ${mode === "live" ? "selected" : ""}" data-mode="live" aria-pressed="${mode === "live"}">${icon("wallet")}<span><strong>Live trading</strong><small>Your real brokerage account</small></span></button></div><form id="settings-form"><div class="form-grid"><label class="full-width">Broker application<select name="platform"><option value="tws" ${p.platform !== "gateway" ? "selected" : ""}>Trader Workstation (TWS)</option><option value="gateway" ${p.platform === "gateway" ? "selected" : ""}>IB Gateway</option></select><span class="field-help">Both use the same API. Gateway is a lighter app for dedicated connections.</span></label><label>Host<input name="host" value="${esc(p.host)}" required autocomplete="off"><span class="field-help">Use 127.0.0.1 when the broker runs on this computer.</span></label><label>Socket port<input name="port" type="number" min="1" max="65535" step="1" value="${esc(p.port)}" required><span class="field-help">Match the socket port in your broker’s API settings.</span></label><label><span>Account ID <span style="font-weight:400">(optional)</span></span><input name="account_id" value="${esc(p.account_id)}" placeholder="Auto-select first available" autocomplete="off"><span class="field-help">Selects the account used for positions and orders.</span></label><label>Client ID<input name="client_id" type="number" min="1" max="2147483647" value="${esc(p.client_id || 1)}" required><span class="field-help">Use a unique number for the connection test.</span></label></div><label class="toggle-row"><input name="readonly" type="checkbox" ${p.readonly ? "checked" : ""}><span><b>Read-only connection</b><small>Browse positions and save drafts. Broker order submission is disabled.</small></span></label><div class="settings-actions"><button class="button primary" type="submit" id="save-settings">Save settings</button><button class="button secondary" type="button" id="test-connection" ${dirty ? "disabled" : ""}>${icon("check")}Test connection</button><span class="save-hint" id="save-hint">${dirty ? "Unsaved changes" : "Settings loaded"}</span></div></form><div id="test-result" style="margin-top:20px"></div>`;
    el.querySelectorAll("[data-mode]").forEach((button) =>
      button.addEventListener("click", () => {
        capture();
        draft.mode = button.dataset.mode;
        dirty = true;
        render();
      }),
    );
    const form = el.querySelector("form");
    form.addEventListener("input", markDirty);
    form.elements.platform.addEventListener("change", () => {
      const defaults = {
        tws: { paper: 7497, live: 7496 },
        gateway: { paper: 4002, live: 4001 },
      };
      form.elements.port.value =
        defaults[form.elements.platform.value][draft.mode];
      markDirty();
    });
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      if (!form.reportValidity()) return;
      busy(document.querySelector("#save-settings"), async () => {
        capture();
        const saved = await request("/api/settings", {
          method: "PUT",
          body: draft,
        });
        draft = structuredClone(saved);
        dirty = false;
        onSave(saved);
        render();
        document.querySelector("#save-hint").textContent = "Saved";
      });
    });
    el.querySelector("#test-connection").addEventListener("click", (event) =>
      busy(event.currentTarget, async () => {
        const output = el.querySelector("#test-result");
        output.innerHTML = loading("Testing the saved connection");
        try {
          const data = await request("/api/settings/test", { method: "POST" });
          output.innerHTML = notice(
            `${data.message} Available accounts: ${data.accounts.join(", ") || "none"}.`,
            "info",
          );
          document.querySelector("#connection-dot").classList.add("connected");
        } catch (error) {
          output.innerHTML = notice(error.message);
          document
            .querySelector("#connection-dot")
            .classList.remove("connected");
        }
      }),
    );
  }
  window.addEventListener("beforeunload", (event) => {
    if (dirty) {
      event.preventDefault();
      event.returnValue = "";
    }
  });
}
