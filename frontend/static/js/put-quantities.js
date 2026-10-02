const key = "wheel.put-quantities.v1";
let memory = {};
function read() {
  try {
    const saved = JSON.parse(localStorage.getItem(key));
    if (saved && typeof saved === "object" && !Array.isArray(saved))
      memory = saved;
  } catch {}
  return memory;
}
export function putQuantity(symbol) {
  const value = read()[symbol.toUpperCase()];
  return Number.isSafeInteger(value) && value > 0 ? value : 1;
}
export function rememberPutQuantity(symbol, quantity) {
  if (!Number.isSafeInteger(quantity) || quantity < 1) return;
  memory = { ...read(), [symbol.toUpperCase()]: quantity };
  try {
    localStorage.setItem(key, JSON.stringify(memory));
  } catch {}
}
