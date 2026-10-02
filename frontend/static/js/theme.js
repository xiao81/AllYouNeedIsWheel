// Apply the saved appearance before the stylesheet paints.
(() => {
  const key = "wheel.theme";
  function apply(theme) {
    const dark = theme !== "light";
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    const button = document.querySelector("#theme-toggle");
    if (button) {
      button.textContent = dark ? "Light" : "Dark";
      button.setAttribute(
        "aria-label",
        `Switch to ${dark ? "light" : "dark"} theme`,
      );
      button.setAttribute("aria-pressed", String(dark));
    }
  }
  let saved;
  try {
    saved = localStorage.getItem(key);
  } catch {}
  apply(saved);
  document.addEventListener("DOMContentLoaded", () => {
    apply(document.documentElement.dataset.theme);
    document.querySelector("#theme-toggle")?.addEventListener("click", () => {
      const next =
        document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      apply(next);
      try {
        localStorage.setItem(key, next);
      } catch {}
    });
  });
  window.addEventListener("storage", (event) => {
    if (event.key === key) apply(event.newValue);
  });
})();
