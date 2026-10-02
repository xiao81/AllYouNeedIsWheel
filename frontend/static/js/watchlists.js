export const WATCHLIST_KEY = "wheel.watchlists.v2";
const valid = (value) => /^[A-Z0-9][A-Z0-9.-]{0,19}$/.test(value);
const clean = (values) => [
  ...new Set(
    (Array.isArray(values) ? values : [])
      .filter((value) => typeof value === "string")
      .map((value) => value.trim().toUpperCase())
      .filter(valid),
  ),
];
export function loadWatchlists(storage = localStorage) {
  const read = (key) => {
    try {
      return JSON.parse(storage.getItem(key));
    } catch {
      return null;
    }
  };
  const current = read(WATCHLIST_KEY);
  if (current && Array.isArray(current.PUT))
    return {
      PUT: clean(current.PUT),
      CALL: Array.isArray(current.CALL) ? clean(current.CALL) : null,
    };
  const legacy = read("customTickers"),
    recent = read("wheel.watchlist");
  const excluded = clean(read("excludedPositionTickers"));
  // Prefer the original put-only list over the redesign's shared list.
  return {
    PUT: clean(Array.isArray(legacy) ? legacy : recent).filter(
      (s) => !excluded.includes(s),
    ),
    CALL: null,
  };
}
export function saveWatchlists(lists, storage = localStorage) {
  storage.setItem(WATCHLIST_KEY, JSON.stringify(lists));
}
export function parseSymbols(value) {
  const symbols = [
    ...new Set(
      value
        .toUpperCase()
        .split(/[\s,;]+/)
        .filter(Boolean),
    ),
  ];
  if (symbols.some((s) => !valid(s)))
    throw new Error(
      "Use ticker symbols such as AAPL, TSLA or BRK.B, separated by commas or spaces.",
    );
  return symbols;
}
