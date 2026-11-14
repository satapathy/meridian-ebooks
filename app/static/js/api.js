// Shared helpers: HTTP, escaping, icons, toasts, cover markup.

export const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export function toast(msg, kind = "ok", ms = 3800) {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = msg;
  document.getElementById("toasts").append(el);
  setTimeout(() => el.remove(), ms);
}

export async function api(path, opts = {}) {
  const { quiet, json, ...init } = opts;
  if (json !== undefined) {
    init.method ||= "POST";
    init.headers = { "Content-Type": "application/json", ...(init.headers || {}) };
    init.body = JSON.stringify(json);
  }
  let res;
  try {
    res = await fetch("/api" + path, init);
  } catch (e) {
    if (!quiet) toast("Cannot reach the server", "err");
    throw e;
  }
  if (!res.ok) {
    if (res.status === 401 && auth.enabled && !path.startsWith("/auth/")) {   // a write was refused: the session ended or admin mode was never entered
      setAuth({ admin: false });
      emit("admin-required");
    }
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {}
    if (!quiet) toast(detail, "err", 6000);
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

// Outline icons in the style of (and in places matching) Feather (MIT) and Lucide (ISC); notices in THIRD_PARTY_NOTICES.md
const ICONS = {
  home: "M3 11l9-8 9 8v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z",
  clock: "M12 7v5l3 2 M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z",
  library: "M4 4h4v16H4z M10 4h4v16h-4z M16.6 5.6l3.8-1 3 14.8-3.8 1z",
  users: "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z M22 21v-2a4 4 0 0 0-3-3.9 M16 3.1a4 4 0 0 1 0 7.8",
  folder: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
  lock: "M6 11h12a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-8a1 1 0 0 1 1-1z M8 11V7a4 4 0 0 1 8 0v4",
  shield: "M12 3l8 3v6c0 4.5-3.2 8-8 9-4.8-1-8-4.5-8-9V6z M9 12l2 2 4-4",
  tools: "M4 6h10 M18 6h2 M4 12h4 M12 12h8 M4 18h12 M20 18h0 M14 4v4 M8 10v4 M16 16v4",
  upload: "M12 16V4 M7 9l5-5 5 5 M4 20h16",
  download: "M12 4v12 M7 11l5 5 5-5 M4 20h16",
  search: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16z M21 21l-4.3-4.3",
  x: "M18 6L6 18 M6 6l12 12",
  trash: "M3 6h18 M8 6V4h8v2 M6 6l1 14h10l1-14",
  star: "M12 2l3 6.9 7.5.7-5.7 5 1.7 7.4L12 18l-6.5 4 1.7-7.4-5.7-5 7.5-.7z",
  image: "M4 5h16v14H4z M8.5 10a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3z M20 16l-5-5-8 8",
  book: "M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z M20 17v4H6.5A2.5 2.5 0 0 1 4 18.5",
  settings: "M4 21v-7 M4 10V3 M12 21v-9 M12 8V3 M20 21v-5 M20 12V3 M1 14h6 M9 8h6 M17 16h6",
  save: "M5 3h11l4 4v14H5z M8 3v6h7V3 M8 21v-7h8v7",
  grid: "M4 4h7v7H4z M13 4h7v7h-7z M4 13h7v7H4z M13 13h7v7h-7z",
  list: "M8 6h13 M8 12h13 M8 18h13 M3 6h.01 M3 12h.01 M3 18h.01",
};
export const icon = (n) =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${ICONS[n]}"/></svg>`;

export function hue(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) h = Math.imul(h ^ str.charCodeAt(i), 16777619);
  return Math.abs(h) % 360;
}

export function fmtBytes(n) {
  if (n < 1024) return n + " B";
  const u = ["KB", "MB", "GB", "TB"];
  let i = -1;
  do { n /= 1024; i++; } while (n >= 1024 && i < u.length - 1);
  return n.toFixed(n >= 100 ? 0 : 1) + " " + u[i];
}

/** Cover art: the real image when present, otherwise a generative gradient cover. */
export function coverHTML(b, full = false) {
  const h = hue(b.title + b.author);
  const gen = `<div class="gen" style="--h:${h};--h2:${(h + 55) % 360}"><b>${esc(b.title)}</b><span>${esc(b.authors?.[0] || b.format)}</span></div>`;
  if (!b.has_cover) return `<mx-cover>${gen}</mx-cover>`;
  // the tile shows the generated cover at once; the real (small) image is fetched afterwards, when the tile is on screen
  return `<mx-cover data-src="/api/books/${b.id}/${full ? "cover" : "thumb"}?v=${encodeURIComponent(b.updated_at)}">${gen}</mx-cover>`;
}

/** Lazy cover: the book tiles are painted first, then each image loads as its tile nears the viewport. */
const coverObserver = "IntersectionObserver" in window ? new IntersectionObserver((entries) => {
  for (const e of entries) if (e.isIntersecting) { coverObserver.unobserve(e.target); e.target.load(); }
}, { rootMargin: "300px" }) : null;
customElements.define("mx-cover", class extends HTMLElement {
  connectedCallback() {
    if (!this.dataset.src || this.dataset.loaded) return;
    if (coverObserver) coverObserver.observe(this); else this.load();
  }
  disconnectedCallback() { coverObserver?.unobserve(this); }
  load() {
    const src = this.dataset.src;
    if (!src || this.dataset.loaded) return;
    this.dataset.loaded = "1";
    const img = new Image();
    img.alt = "";
    img.decoding = "async";
    img.onload = () => { img.classList.add("in"); this.replaceChildren(img); };   // on error the generated cover simply stays
    img.src = src;
  }
});

const _colors = new Map();   // "id:updated_at" -> css colour
export const fallbackColor = (b) => `hsl(${hue(b.title + b.author)} 62% 42%)`;   // same hue as the generated cover
/** {id: css colour} for these books: the predominant colour of the cover, else the hue of their generated cover. */
export async function coverColors(books) {
  const key = (b) => `${b.id}:${b.updated_at}`;
  const need = books.filter((b) => b.has_cover !== false && !_colors.has(key(b)));
  for (let i = 0; i < need.length; i += 100) {
    const chunk = need.slice(i, i + 100);
    try {
      const got = await api("/books/colors?ids=" + chunk.map((b) => b.id).join(","), { quiet: true });
      for (const b of chunk) _colors.set(key(b), got[b.id] || fallbackColor(b));
    } catch { for (const b of chunk) _colors.set(key(b), fallbackColor(b)); }
  }
  return Object.fromEntries(books.map((b) => [b.id, _colors.get(key(b)) || fallbackColor(b)]));
}

// ---- batched bulk operations with a percent-complete bar (used by "Set fields" and "Advanced" bulk edit)
export const progressHTML = () => `<div class="progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><i></i></div>`;
export function setProgress(bar, done, total) {
  const pct = Math.round((done / total) * 100);
  bar.querySelector("i").style.width = pct + "%";
  bar.setAttribute("aria-valuenow", pct);
  return pct;
}
/** Send `ids` to `call(chunk)` a few at a time. Merges the {updated, unchanged, failed, books} answers and reports progress;
 *  an error or `shouldStop()` ends the run early, keeping what was saved so far. */
export async function runBatches(ids, size, call, { onProgress, shouldStop, onBatch = () => {} }) {
  const out = { updated: 0, unchanged: 0, failed: [], books: [], error: null };
  let i = 0;
  try {
    for (; i < ids.length && !shouldStop(); i += size) {
      const r = await call(ids.slice(i, i + size));
      out.updated += r.updated; out.unchanged += r.unchanged || 0; out.failed.push(...r.failed); out.books.push(...r.books);
      onBatch(r);
      onProgress(Math.min(i + size, ids.length));
    }
  } catch (e) { out.error = e; }
  return { ...out, stopped: shouldStop() || !!out.error, remaining: Math.max(0, ids.length - i) };
}
export const batchMessage = (r, total, verb = "Updated") => `${verb} ${r.updated} book${r.updated === 1 ? "" : "s"}`
  + (r.unchanged ? ` · ${r.unchanged} already fine` : "") + (r.failed.length ? ` · ${r.failed.length} failed` : "")
  + (r.error ? ` · stopped: ${r.error.message || "error"}` : r.stopped ? ` · stopped, ${r.remaining} not processed` : "");

/** Web-search URL for a book: quoted title, authors and the ISBN (else the word "book"). It is only ever opened by the user's click
 *  in a new tab - the app itself never contacts the search site. */
export function webSearchUrl({ title = "", author = "", isbn = "" }) {
  const authors = String(author).split(";").map((a) => a.trim()).filter(Boolean).join(" ");
  const q = [title.trim() ? `"${title.trim()}"` : "", authors, String(isbn).trim() || "book"].filter(Boolean).join(" ");
  return "https://www.google.com/search?q=" + encodeURIComponent(q);
}

export const emit = (name, detail) => document.dispatchEvent(new CustomEvent(name, { detail }));

// ---- admin mode. Reading is open to everyone; writes need a login (see app/auth.py). `enabled` is false when the
// server has no admin credentials configured, in which case nothing is hidden and nobody has to log in.
export const auth = { enabled: false, admin: false };
export function setAuth(next) {
  const before = `${auth.enabled}${auth.admin}`;
  Object.assign(auth, next);
  document.body.classList.toggle("auth-on", auth.enabled);
  document.body.classList.toggle("is-admin", auth.enabled && auth.admin);
  if (before !== `${auth.enabled}${auth.admin}`) emit("auth-changed", { ...auth });
}
export const loadAuth = async () => { try { const s = await api("/auth/status", { quiet: true }); setAuth({ enabled: s.auth_enabled, admin: s.admin }); } catch {} };
export const adminLogin = async (username, password) => { const s = await api("/auth/login", { json: { username, password }, quiet: true }); setAuth({ enabled: s.auth_enabled, admin: s.admin }); };
export const adminLogout = async () => { try { await api("/auth/logout", { method: "POST", quiet: true }); } catch {} setAuth({ admin: false }); };

// ---- user preferences (theme, cover borders), persisted per browser
export const THEMES = {
  vanilla: ["Vanilla", "linear-gradient(135deg,#ffffff,#d9d9de)"],
  aurora: ["Aurora", "linear-gradient(135deg,#7c5cff,#22d3ee)"],
  neon: ["Neon", "linear-gradient(135deg,#2dff9a,#00e0ff)"],
  sunset: ["Sunset", "linear-gradient(135deg,#ff6a3d,#ff3d81)"],
  ocean: ["Ocean", "linear-gradient(135deg,#1e90ff,#00d4c8)"],
  emerald: ["Emerald", "linear-gradient(135deg,#2fb37a,#e0c25a)"],
  cyber: ["Cyber", "linear-gradient(135deg,#ff2bd6,#00f0ff)"],
  paper: ["Paper", "linear-gradient(135deg,#f4f1ea,#c2410c)"],
  blossom: ["Blossom", "linear-gradient(135deg,#ffd6e2,#e0457b)"],
  lavender: ["Lavender", "linear-gradient(135deg,#e9e3fb,#7c3aed)"],
};
// Open-source (SIL OFL) fonts only. [label, CSS stack]
export const FONTS = {
  inter: ["Inter", "'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif"],
  dmsans: ["DM Sans", "'DM Sans', system-ui, sans-serif"],
  sourcesans: ["Source Sans 3", "'Source Sans 3', system-ui, sans-serif"],
  plex: ["IBM Plex Sans", "'IBM Plex Sans', system-ui, sans-serif"],
  nunito: ["Nunito", "'Nunito', system-ui, sans-serif"],
  poppins: ["Poppins", "'Poppins', system-ui, sans-serif"],
  space: ["Space Grotesk", "'Space Grotesk', system-ui, sans-serif"],
  atkinson: ["Atkinson Hyperlegible", "'Atkinson Hyperlegible', system-ui, sans-serif"],
  lora: ["Lora (serif)", "'Lora', Georgia, 'Times New Roman', serif"],
  merriweather: ["Merriweather (serif)", "'Merriweather', Georgia, 'Times New Roman', serif"],
  jetbrains: ["JetBrains Mono (mono)", "'JetBrains Mono', ui-monospace, Consolas, monospace"],
  system: ["System default", "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"],
};
export const clampFs = (v) => Math.max(80, Math.min(130, Number(v) || 100));
export function getPref(k, d) { try { return localStorage.getItem("mx-" + k) ?? d; } catch { return d; } }
export function setPref(k, v) { try { localStorage.setItem("mx-" + k, v); } catch {} applyPrefs(); emit("prefs-changed", { key: k }); }
export function applyPrefs() {
  const t = getPref("theme", "vanilla");
  document.documentElement.dataset.theme = THEMES[t] ? t : "vanilla";
  const root = document.documentElement;
  root.style.setProperty("--font", (FONTS[getPref("font", "inter")] || FONTS.inter)[1]);
  root.style.fontSize = (14.5 * clampFs(getPref("fs", "100"))) / 100 + "px";   // 100% = 14.5px (compact default)
  const bw = Math.max(0, Math.min(16, Number(getPref("border", "6")) || 0));
  document.documentElement.style.setProperty("--bw", bw + "px");
  document.documentElement.dataset.border = bw ? "on" : "off";
}
