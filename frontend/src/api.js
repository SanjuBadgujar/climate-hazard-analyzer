export const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function getJson(path, params) {
  const url = `${API}${path}?${new URLSearchParams(params)}`;
  let res;
  try {
    res = await fetch(url);
  } catch {
    throw new Error("Cannot reach the API. Is the backend running?");
  }
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") msg = body.detail;
      else if (Array.isArray(body.detail)) msg = body.detail.map((d) => d.msg.replace("Value error, ", "")).join("; ");
      else if (body.error) msg = body.error; // slowapi rate limit
    } catch {}
    if (res.status === 429) msg = "Too many requests - please wait a minute and retry.";
    throw new Error(msg);
  }
  return res.json();
}

export const geocode = (q) => getJson("/api/geocode", { q });
export const analyze = (p) => getJson("/api/heatwave", p);
export const csvUrl = (p) => `${API}/api/heatwave/export.csv?${new URLSearchParams(p)}`;
