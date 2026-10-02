// Deduplicate simultaneous reads; never retry a mutation automatically.
const pending = new Map();
let profileRevision = null;
export function setProfileRevision(revision) {
  profileRevision = revision;
}
export function request(path, { method = "GET", body, ...options } = {}) {
  const key = path;
  if (method === "GET" && pending.has(key)) return pending.get(key);
  const work = (async () => {
    const response = await fetch(path, {
      method,
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(profileRevision && method !== "GET"
          ? { "X-Wheel-Profile": profileRevision }
          : {}),
        ...options.headers,
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: options.signal || AbortSignal.timeout(120000),
    });
    let data;
    try {
      data = await response.json();
    } catch {
      throw new Error(
        `Server returned an unreadable response (${response.status}).`,
      );
    }
    if (!response.ok || data?.success === false || data?.error)
      throw new Error(data?.error || `Request failed (${response.status})`);
    return data;
  })();
  if (method === "GET") {
    pending.set(key, work);
    work.finally(() => pending.delete(key)).catch(() => {});
  }
  return work;
}
export const query = (values) =>
  new URLSearchParams(
    Object.entries(values).filter(
      ([, v]) => v !== undefined && v !== null && v !== "",
    ),
  ).toString();

// Stream completed symbols over one connection; never restart a scan implicitly.
export async function streamScan(path, onResult, signal) {
  const response = await fetch(path, { signal });
  if (!response.ok) {
    const data = await response.json();
    throw new Error(data.error || `Request failed (${response.status})`);
  }
  if (!response.headers.get("Content-Type")?.includes("application/x-ndjson")) {
    const data = await response.json();
    if (data.error) throw new Error(data.error);
    data.results.forEach(onResult);
    return data;
  }
  const reader = response.body.getReader(),
    decoder = new TextDecoder();
  let buffer = "",
    completed;
  function consume(line) {
    if (!line.trim()) return;
    const message = JSON.parse(line);
    if (message.type === "result") onResult(message.result);
    if (message.type === "complete") completed = message.data;
    if (message.type === "error") throw new Error(message.data.error);
  }
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const lines = buffer.split("\n");
      buffer = lines.pop();
      lines.forEach(consume);
      if (done) break;
    }
    if (buffer) consume(buffer);
    if (!completed)
      throw new Error(
        "Connection interrupted. Completed results are still available; retry to finish the scan.",
      );
    return completed;
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
