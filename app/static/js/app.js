import { api, esc, icon, toast, hue, fmtBytes, emit, applyPrefs, getPref, setPref, coverColors, fallbackColor,
  progressHTML, setProgress, runBatches, batchMessage } from "./api.js";
import "./components.js";

const view = document.getElementById("view");
let token = 0; // guards against out-of-order async renders

// ------------------------------------------------------------------ chrome
document.querySelectorAll("[data-icon]").forEach((el) => (el.innerHTML = icon(el.dataset.icon)));
const NAV = { library: ["library", "Library"], recent: ["clock", "Recently added"], authors: ["users", "Authors"], categories: ["folder", "Categories"], tools: ["tools", "Tools"] };
document.querySelectorAll("#nav a").forEach((a) => { const [i, l] = NAV[a.dataset.route]; a.innerHTML = `${icon(i)}<span>${l}</span>`; });

applyPrefs();

const $ = (id) => document.getElementById(id);
$("btn-upload").onclick = () => $("upload").open();
$("btn-settings").onclick = () => $("settings").open();
$("btn-export").onclick = () => $("export").open();

// Global drag & drop anywhere on the page.
let dragDepth = 0;
const hasFiles = (e) => [...(e.dataTransfer?.types || [])].includes("Files");
addEventListener("dragenter", (e) => { if (hasFiles(e)) { dragDepth++; $("dropveil").classList.add("on"); } });
addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth = 0; $("dropveil").classList.remove("on"); } });
addEventListener("dragover", (e) => { if (hasFiles(e)) e.preventDefault(); });
addEventListener("drop", (e) => {
  if (!hasFiles(e)) return;
  e.preventDefault(); dragDepth = 0; $("dropveil").classList.remove("on");
  $("upload").classList.add("open");
  $("upload").addFromDataTransfer(e.dataTransfer);
});

// Search
const searchEl = $("search");
let searchTimer;
$("search-form").onsubmit = (e) => { e.preventDefault(); clearTimeout(searchTimer); go(searchEl.value.trim() ? `/library?q=${encodeURIComponent(searchEl.value.trim())}` : "/library"); };
searchEl.oninput = () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => go(searchEl.value.trim() ? `/library?q=${encodeURIComponent(searchEl.value.trim())}` : "/library", true), 280);
};
addEventListener("keydown", (e) => {
  if (e.key === "/" && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) { e.preventDefault(); searchEl.focus(); searchEl.select(); }
});
$("search-help").onclick = (e) => {
  const old = document.querySelector(".popover");
  if (old) return old.remove();
  const r = e.target.getBoundingClientRect();
  const p = document.createElement("div");
  p.className = "popover glass";
  p.style.cssText = `top:${r.bottom + 10}px;right:${Math.max(16, innerWidth - r.right)}px;background:var(--bg2)`;
  p.innerHTML = `<b>Search syntax</b>
    <p><code>tolk*</code> — <code>*</code> any characters, <code>?</code> one character</p>
    <p><code>author:herbert</code> <code>title:"*ring*"</code> <code>tag:scifi</code> <code>publisher:</code> <code>category:</code> <code>format:epub</code> <code>series:</code> <code>isbn:</code> <code>lang:en</code> <code>year:19*</code> <code>file:</code></p>
    <p><code>"exact phrase"</code> · <code>-word</code> excludes · terms are AND-ed</p>`;
  document.body.append(p);
  setTimeout(() => addEventListener("click", () => p.remove(), { once: true }), 0);
};

// ------------------------------------------------------------------ routing
function parse() {
  const [path, qs = ""] = (location.hash.slice(1) || "/").split("?");
  return { path, params: new URLSearchParams(qs) };
}
function go(to, replace = false) {
  if (replace) { history.replaceState(null, "", "#" + to); render(); } else if (location.hash === "#" + to) render(); else location.hash = to;
}
addEventListener("hashchange", () => { $("drawer").close(); render(); });
document.addEventListener("library-changed", () => { refreshRail(); render(); });
document.addEventListener("prefs-changed", (e) => { if (e.detail.key === "series" || e.detail.key === "view") render(); });

async function refreshRail() {
  try { const s = await api("/stats", { quiet: true }); $("rail-stats").textContent = `${s.books} books · ${fmtBytes(s.bytes)}`; } catch {}
}

async function render() {
  const my = ++token;
  const { path, params } = parse();
  const route = path === "/" ? "library" : path.split("/")[1];
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.route === route));
  if (document.activeElement !== searchEl) searchEl.value = route === "library" ? params.get("q") || "" : "";
  const fn = VIEWS[route] || VIEWS.library;
  const html = document.createElement("div");
  try { await fn(html, params, () => my === token); } catch (e) { html.innerHTML = `<div class="empty"><h2>Something went wrong</h2>${esc(e.message)}</div>`; }
  if (my !== token) return;
  view.replaceChildren(...html.childNodes);
  view.style.animation = "none"; void view.offsetWidth; view.style.animation = "";
}

// ------------------------------------------------------------------ helpers
const card = (b) => { const c = document.createElement("mx-card"); c.book = b; return c; };

// Table view: one column per metadata field. [key, heading, sort key (or null), cell html, css class]
const dash = (v) => (v ? esc(v) : `<span class="muted">-</span>`);
const COLS = [
  ["title", "Title", "title", (b) => `<b>${esc(b.title)}</b>`, "c-title"],
  ["subtitle", "Subtitle", "subtitle", (b) => dash(b.subtitle), "c-wide"],
  ["author", "Author(s)", "author", (b) => dash(b.author), "c-wide"],
  ["series", "Series", "series", (b) => dash(b.series), ""],
  ["series_index", "#", "series_index", (b) => (b.series_index != null ? esc(String(b.series_index)) : `<span class="muted">-</span>`), "c-num"],
  ["category", "Category", "category", (b) => dash(b.category), ""],
  ["subcategory", "Sub-category", "subcategory", (b) => dash(b.subcategory), ""],
  ["tags", "Tags", "tags", (b) => (b.tags.length ? b.tags.map((t) => `<span class="tag">${esc(t)}</span>`).join(" ") : `<span class="muted">-</span>`), "c-wide"],
  ["publisher", "Publisher", "publisher", (b) => dash(b.publisher), ""],
  ["published", "Published", "published", (b) => dash(b.published), ""],
  ["language", "Lang", "language", (b) => dash(b.language), "c-num"],
  ["isbn", "ISBN", "isbn", (b) => dash(b.isbn), "c-mono"],
  ["rating", "Rating", "rating", (b) => (b.rating ? `<span class="stars-txt">${"★".repeat(b.rating)}</span>` : `<span class="muted">-</span>`), ""],
  ["format", "Format", "format", (b) => `<span class="pill in">${esc(b.format)}</span>`, ""],
  ["size", "Size", "size", (b) => fmtBytes(b.size), "c-num"],
  ["added_at", "Added", "added", (b) => new Date(b.added_at).toLocaleDateString(), ""],
  ["filename", "File name", "filename", (b) => esc(b.filename), "c-mono"],
  ["description", "Description", "description", (b) => (b.description ? `<span class="c-desc" title="${esc(b.description)}">${esc(b.description)}</span>` : `<span class="muted">-</span>`), "c-desc-cell"],
];
const DESC_FIRST = ["added", "size", "rating", "published"];   // columns whose first click should sort high-to-low
const FILTERS = ["q", "author", "category", "format", "tag", "series"];   // library state that is sent to the API
const SORT_OPTS = [["added", "Date added"], ...COLS.filter((c) => c[2] && c[2] !== "added").map((c) => [c[2], c[1] === "#" ? "Series #" : c[1]])];
const paintDots = async (books, scope) => {
  const colors = await coverColors(books);
  for (const b of books) scope.querySelector(`tr[data-id="${b.id}"] .dot`)?.style.setProperty("--c", colors[b.id]);
};
const bookRow = (b, sel) => {
  const tr = document.createElement("tr");
  tr.tabIndex = 0; tr.dataset.id = b.id;
  tr.classList.toggle("sel", sel.has(b.id));
  tr.innerHTML = `<td class="c-sel"><input type="checkbox" aria-label="Select ${esc(b.title)}"${sel.has(b.id) ? " checked" : ""}></td><td class="c-cover"><span class="dot" style="--c:${fallbackColor(b)}" title="Predominant cover colour"></span></td>`
    + COLS.map(([, , , cell, cls]) => `<td class="${cls}">${cell(b)}</td>`).join("");
  const box = tr.querySelector(".c-sel input");
  tr.querySelector(".c-sel").onclick = (e) => { e.stopPropagation(); if (e.target !== box) box.click(); };   // the whole cell is the click target
  box.onclick = (e) => { e.stopPropagation(); sel.toggle(b.id, box.checked, e.shiftKey); };
  const open = () => emit("open-book", b);
  tr.onclick = open;
  tr.onkeydown = (e) => { if (e.key === "Enter" && e.target === tr) open(); };
  return tr;
};

const emptyState = () => `<div class="empty"><h2>Your shelves are empty</h2><p>Add some books to get started — drop files or entire folders anywhere on this page.</p>
  <button class="btn primary" onclick="document.getElementById('upload').open()">${icon("upload")}Add books</button></div>`;

const initials = (n) => n.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase() || "?";
const enc = encodeURIComponent;

// ------------------------------------------------------------------ views
const VIEWS = {
  recent(root, params, alive) { return VIEWS.library(root, params, alive, { recent: true }); },

  async library(root, params, alive, opts = {}) {
    const recent = !!opts.recent;
    const state = { q: params.get("q") || "", author: params.get("author") || "", category: params.get("category") || "",
      format: params.get("format") || "", tag: params.get("tag") || "", series: params.get("series") || "",
      sort: recent ? "added" : params.get("sort") || "title", order: recent ? "desc" : params.get("order") || "asc" };
    const list = getPref("view", "grid") === "list";
    const group = !list && !recent && !state.q && !state.series && getPref("series", "on") !== "off";   // the table shows every book and has a Series column
    const facets = await api("/facets");
    const set = (patch) => { const p = new URLSearchParams(); const s = { ...state, ...patch }; for (const [k, v] of Object.entries(s)) if (v && !(recent && (k === "sort" || k === "order"))) p.set(k, v); go((recent ? "/recent" : "/library") + (p.size ? "?" + p : ""), true); };
    const title = recent ? "Recently added" : state.q ? `Results for “${state.q}”` : state.author || state.category || (state.tag && `#${state.tag}`) || state.series || "Library";
    root.innerHTML = `<div class="page-head"><div><div class="eyebrow">${recent ? "Newest first" : state.q ? "Search" : state.series ? "Series" : "Browse"}</div><h1 class="grad-text">${esc(title)}</h1><div class="muted small" id="count"></div></div></div>
      <div class="toolbar">
        <button class="chip ${state.format ? "" : "on"}" data-f="">All</button>
        ${facets.formats.map((f) => `<button class="chip ${state.format === f.name ? "on" : ""}" data-f="${esc(f.name)}">${esc(f.name)} <small>${f.count}</small></button>`).join("")}
        <span class="grow"></span>
        <select class="in" id="cat" aria-label="Category"><option value="">All categories</option>${facets.categories.map((c) => `<option ${state.category === c.name ? "selected" : ""} value="${esc(c.name)}">${esc(c.name)} (${c.count})</option>`).join("")}</select>
        <select class="in" id="sort" aria-label="Sort">${SORT_OPTS.map(([v, l]) => `<option value="${v}" ${state.sort === v ? "selected" : ""}>${l}</option>`).join("")}</select>
        <button class="btn sm" id="order" title="Toggle sort order">${state.order === "asc" ? "↑ Asc" : "↓ Desc"}</button>
        <div class="seg" role="group" aria-label="View">
          <button class="btn sm ${list ? "" : "on"}" data-view="grid" aria-pressed="${!list}" title="Card view">${icon("grid")}</button>
          <button class="btn sm ${list ? "on" : ""}" data-view="list" aria-pressed="${list}" title="List view (table with all metadata)">${icon("list")}</button>
        </div>
      </div>
      <div class="toolbar" id="active"></div>` + (list
      ? `<div class="tablewrap" id="grid"><table class="books"><thead><tr><th class="c-sel"><input type="checkbox" id="sel-all" aria-label="Select all loaded rows" title="Select all loaded rows"></th><th class="c-cover"></th>${COLS.map(([k, h, sk]) => sk
          ? `<th data-sort="${sk}" class="sortable ${state.sort === sk ? "sorted" : ""}" aria-sort="${state.sort === sk ? (state.order === "asc" ? "ascending" : "descending") : "none"}" title="Sort by ${h}">${h}${state.sort === sk ? (state.order === "asc" ? " ↑" : " ↓") : ""}</th>`
          : `<th>${h}</th>`).join("")}</tr></thead><tbody></tbody></table><div class="sentinel" id="more"></div></div>`
      : `<div class="grid" id="grid"></div><div class="sentinel" id="more"></div>`);
    root.querySelectorAll("[data-view]").forEach((b) => (b.onclick = () => { if (b.dataset.view !== (list ? "list" : "grid")) setPref("view", b.dataset.view); }));
    root.querySelectorAll("th[data-sort]").forEach((th) => (th.onclick = () => {
      const k = th.dataset.sort;
      set({ sort: k, order: state.sort === k ? (state.order === "asc" ? "desc" : "asc") : DESC_FIRST.includes(k) ? "desc" : "asc" });
    }));
    if (recent) root.querySelectorAll("#sort, #order").forEach((e) => e.remove());
    const active = root.querySelector("#active");
    for (const k of ["author", "tag", "series"]) if (state[k]) active.insertAdjacentHTML("beforeend", `<button class="chip on" data-clear="${k}">${k}: ${esc(state[k])} ✕</button>`);
    if (!active.children.length) active.remove();
    root.querySelectorAll("[data-f]").forEach((b) => (b.onclick = () => set({ format: b.dataset.f })));
    root.querySelectorAll("[data-clear]").forEach((b) => (b.onclick = () => set({ [b.dataset.clear]: "" })));
    root.querySelector("#cat").onchange = (e) => set({ category: e.target.value });
    if (!recent) root.querySelector("#sort").onchange = (e) => set({ sort: e.target.value, order: DESC_FIRST.includes(e.target.value) ? "desc" : "asc" });
    if (!recent) root.querySelector("#order").onclick = () => set({ order: state.order === "asc" ? "desc" : "asc" });

    const grid = root.querySelector("#grid"), more = root.querySelector("#more"), count = root.querySelector("#count");
    let offset = 0, total = Infinity, loading = false, selApi = null;
    const load = async () => {
      if (loading || offset >= total) return;
      loading = true;
      const p = new URLSearchParams({ limit: 60, offset, sort: state.sort, order: state.order });
      for (const k of FILTERS) if (state[k]) p.set(k, state[k]);
      if (group) p.set("group_series", "true");
      const page = await api("/books?" + p);
      if (!alive()) return;
      total = page.total; offset += page.items.length;
      (list ? grid.querySelector("tbody") : grid).append(...page.items.map(list ? (b) => bookRow(b, selApi) : card));
      selApi?.paint();
      if (list) paintDots(page.items, grid);
      count.textContent = group ? `${total} item${total === 1 ? "" : "s"} · series grouped` : `${total} book${total === 1 ? "" : "s"}`;
      if (!total) {
        const filtered = state.q || state.author || state.category || state.format || state.tag || state.series;
        selApi?.bar.remove();
        grid.outerHTML = filtered
          ? `<div class="empty"><h2>Nothing found</h2><p>Try a wildcard like <code>*${esc(state.q.replace(/\*/g, ""))}*</code> or a different filter.</p></div>`
          : emptyState();
      }
      loading = false;
    };
    if (list) {
      // ---- row selection + bulk edit bar
      const sel = new Set(); let lastId = null;
      const bar = document.createElement("div"); bar.className = "bulkbar"; grid.before(bar);   // in the page flow, right above the table
      const rows = () => [...grid.querySelectorAll("tbody tr")];
      let running = false;   // an advanced bulk edit owns the bar until it finishes
      const openBulk = () => document.getElementById("bulkedit").open({
        ids: [...sel],
        applied: (res) => { res.books.forEach((b) => emit("book-updated", b)); sel.clear(); paint(); },
        advanced: (spec) => runAdvanced(spec, [...sel]),
      });
      /** Run `call(chunk)` over `ids` in batches, with the progress bar and a Stop button in the bar above the table. */
      const runInBar = async (label, ids, call, extra = {}) => {
        let stop = false;
        running = true;
        bar.classList.add("on");
        bar.innerHTML = `<b>${esc(label)}</b>${progressHTML()}<span class="small muted" id="bp-t"></span><button class="btn sm" id="bp-stop">Stop</button>`;
        const meter = bar.querySelector(".progress"), text = bar.querySelector("#bp-t"), stopBtn = bar.querySelector("#bp-stop");
        stopBtn.onclick = () => { stop = true; stopBtn.disabled = true; stopBtn.textContent = "Stopping…"; };
        const show = (done) => { text.textContent = `${setProgress(meter, done, ids.length)}% · ${done} of ${ids.length}`; };
        show(0);
        const r = await runBatches(ids, 10, call, { onProgress: show, shouldStop: () => stop, ...extra });
        if (!r.stopped) { meter.classList.add("done"); text.textContent = `100% · ${ids.length} of ${ids.length}`; await new Promise((res) => setTimeout(res, 450)); }
        running = false;
        sel.clear(); paint();
        return r;
      };
      const runAdvanced = async (spec, ids) => {   // the dialog has closed: show the progress where the buttons were
        const r = await runInBar(spec.label, ids, (chunk) => api("/books/bulk-transform", { json: { ...spec.body, ids: chunk }, quiet: true }));
        r.books.forEach((b) => emit("book-updated", b));
        toast(batchMessage(r, ids.length), r.failed.length || r.stopped ? "err" : undefined);
      };
      const deleteSelected = async () => {
        const ids = [...sel], n = ids.length;
        const titles = rows().filter((tr) => sel.has(tr.dataset.id)).map((tr) => tr.querySelector(".c-title").textContent.trim());
        const shown = titles.slice(0, 6);
        const ok = await document.getElementById("confirm").ask({
          title: `Delete ${n} book${n === 1 ? "" : "s"}?`, confirm: `Delete ${n}`, requireText: n >= 10 ? "delete" : "",
          body: `<p>This <b>permanently</b> removes ${n === 1 ? "this book" : `these ${n} books`} from the library <b>and deletes the files from disk</b>: the books, their covers and metadata files. Folders left empty are removed too.</p>
            <ul class="cf-list">${shown.map((t) => `<li>${esc(t)}</li>`).join("")}${n > shown.length ? `<li class="muted">…and ${n - shown.length} more</li>` : ""}</ul>
            <p><b>This cannot be undone.</b> Want a backup first? Use <b>Export</b> (top right) before deleting.</p>` });
        if (!ok) return;
        const freed = { bytes: 0, leftover: 0 };
        const r = await runInBar(`Deleting ${n} book${n === 1 ? "" : "s"}`, ids,
          (chunk) => api("/books/bulk-delete", { json: { ids: chunk }, quiet: true }).then((x) => ({ ...x, updated: x.deleted, books: [] })),
          { onBatch: (x) => { freed.bytes += x.bytes_freed; freed.leftover += x.leftover; } });
        toast(batchMessage(r, n, "Deleted") + (freed.bytes ? ` · freed ${fmtBytes(freed.bytes)}` : "")
          + (freed.leftover ? ` · ${freed.leftover} folder(s) could not be fully removed - run Tools > Duplicates & cleanup` : ""),
          r.failed.length || r.stopped || freed.leftover ? "err" : undefined);
        emit("library-changed");                    // reload the list and the totals
      };
      const paint = () => {
        const loaded = rows(), n = sel.size, all = grid.querySelector("#sel-all");
        for (const tr of loaded) { const on = sel.has(tr.dataset.id); tr.classList.toggle("sel", on); tr.querySelector(".c-sel input").checked = on; }
        all.checked = loaded.length > 0 && loaded.every((tr) => sel.has(tr.dataset.id));
        all.indeterminate = !all.checked && loaded.some((tr) => sel.has(tr.dataset.id));
        if (running) return;   // keep the progress bar on screen
        const many = n >= 2;   // bulk editing needs at least two books; with 0 or 1 selected the buttons stay hidden
        bar.classList.toggle("on", n > 0);
        bar.innerHTML = !n ? `<span class="muted small">Tick rows to select them; two or more can be edited together.</span>`
          : `<b>${n} selected</b>${n < total ? `<button class="btn sm" id="bb-all">Select all ${total}</button>` : ""}
          ${many ? `<button class="btn sm primary" id="bb-edit">${icon("settings")}Bulk edit</button>` : ""}<button class="btn sm danger" id="bb-del">${icon("trash")}Delete</button><button class="btn sm" id="bb-clear">Clear</button>`;
        if (!n) return;
        bar.querySelector("#bb-clear").onclick = () => { sel.clear(); paint(); };
        if (many) bar.querySelector("#bb-edit").onclick = openBulk;
        bar.querySelector("#bb-del").onclick = deleteSelected;
        const allBtn = bar.querySelector("#bb-all");
        if (allBtn) allBtn.onclick = async () => {   // every book matching the current filters, not just the loaded rows
          allBtn.disabled = true; allBtn.textContent = "Selecting…";
          const p = new URLSearchParams({ limit: 500, sort: state.sort, order: state.order });
          for (const k of FILTERS) if (state[k]) p.set(k, state[k]);
          try {
            for (let off = 0; ; off += 500) {
              p.set("offset", off);
              const pageOfBooks = await api("/books?" + p);
              pageOfBooks.items.forEach((b) => sel.add(b.id));
              if (off + 500 >= pageOfBooks.total) break;
            }
          } catch {}
          paint();
        };
      };
      selApi = {
        has: (id) => sel.has(id), paint, bar,
        toggle(id, on, shift) {   // shift-click selects the range since the last click
          const ids = rows().map((tr) => tr.dataset.id), a = ids.indexOf(lastId), z = ids.indexOf(id);
          const targets = shift && a >= 0 ? ids.slice(Math.min(a, z), Math.max(a, z) + 1) : [id];
          for (const t of targets) on ? sel.add(t) : sel.delete(t);
          lastId = id; paint();
        },
      };
      grid.querySelector("#sel-all").onchange = (e) => { for (const tr of rows()) e.target.checked ? sel.add(tr.dataset.id) : sel.delete(tr.dataset.id); paint(); };
      // keep table rows in step with edits made in the book panel or the bulk dialog
      const onUpdate = (e) => {
        if (!alive()) return document.removeEventListener("book-updated", onUpdate);
        const old = grid.querySelector(`tr[data-id="${e.detail.id}"]`);
        if (old) { old.replaceWith(bookRow(e.detail, selApi)); paintDots([e.detail], grid); }
      };
      document.addEventListener("book-updated", onUpdate);
    }
    new IntersectionObserver((en) => en[0].isIntersecting && load(), { rootMargin: "500px" }).observe(more);
    await load();
  },

  async authors(root) {
    const f = await api("/facets");
    root.innerHTML = `<div class="page-head"><div><div class="eyebrow">Browse</div><h1 class="grad-text">Authors</h1><div class="muted small">${f.authors.length} authors</div></div>
      <input class="in" id="flt" placeholder="Filter authors…" style="width:240px"></div><div class="tiles" id="tiles"></div>`;
    const tiles = root.querySelector("#tiles");
    const draw = (q = "") => {
      const list = f.authors.filter((a) => a.name.toLowerCase().includes(q.toLowerCase()));
      tiles.innerHTML = list.map((a) => { const h = hue(a.name); return `<a class="tile glass" href="#/library?author=${enc(a.name)}&sort=title&order=asc"><div class="avatar" style="--h:${h};--h2:${(h + 60) % 360}">${esc(initials(a.name))}</div><div style="min-width:0"><b>${esc(a.name)}</b><span class="muted small">${a.count} book${a.count > 1 ? "s" : ""}</span></div></a>`; }).join("") || `<div class="empty">No matches</div>`;
    };
    draw();
    root.querySelector("#flt").oninput = (e) => draw(e.target.value);
  },

  async categories(root) {
    const f = await api("/facets");
    const shelves = await Promise.all(f.categories.slice(0, 60).map((c) => api(`/books?category=${enc(c.name)}&limit=5&sort=added`, { quiet: true }).catch(() => ({ items: [] }))));
    const HEIGHTS = [100, 76, 92, 66, 84];   // fixed, so every shelf looks alike from visit to visit
    const spine = (b, i) => `<i style="--c:${fallbackColor(b)};--h:${HEIGHTS[i % 5]}%" data-id="${b.id}"></i>`;
    root.innerHTML = `<div class="page-head"><div><div class="eyebrow">Browse</div><h1 class="grad-text">Categories</h1><div class="muted small">${f.categories.length} collections</div></div></div><div class="tiles"></div>`;
    root.querySelector(".tiles").innerHTML = f.categories.map((c, i) => `<a class="tile cat glass" data-cat="${i}" href="#/library?category=${enc(c.name)}&sort=title&order=asc">
      <div class="spines" aria-hidden="true">${(shelves[i]?.items || []).map(spine).join("")}</div>
      <div style="min-width:0"><b>${esc(c.name)}</b><span class="muted small">${c.count} book${c.count > 1 ? "s" : ""}</span></div></a>`).join("");
    // swap in each book's real cover colour, and tint the card with the first one
    const all = shelves.flatMap((s) => s.items || []);
    coverColors(all).then((colors) => {
      root.querySelectorAll(".tile.cat").forEach((tile) => {
        const items = shelves[Number(tile.dataset.cat)]?.items || [];
        tile.querySelectorAll(".spines i").forEach((el) => el.style.setProperty("--c", colors[el.dataset.id]));
        if (items[0]) tile.style.setProperty("--tint", colors[items[0].id]);
      });
    });
    if (f.tags.length) {
      root.insertAdjacentHTML("beforeend", `<div class="page-head" style="margin-top:34px"><h1 style="font-size:22px">Popular tags</h1></div><div class="toolbar">${f.tags.slice(0, 40).map((t) => `<a class="chip" href="#/library?tag=${enc(t.name)}">${esc(t.name)} <small>${t.count}</small></a>`).join("")}</div>`);
    }
  },

  async tools(root) {
    const s = await api("/stats");
    root.innerHTML = `<div class="page-head"><div><div class="eyebrow">Maintenance</div><h1 class="grad-text">Tools</h1></div></div>
      <div class="stats">
        <div class="stat glass"><b class="grad-text">${s.books}</b><span class="muted">books</span></div>
        <div class="stat glass"><b class="grad-text">${fmtBytes(s.bytes)}</b><span class="muted">on disk</span></div>
        ${s.formats.map((f) => `<div class="stat glass"><b>${f.count}</b><span class="muted">${esc(f.name)}</span></div>`).join("")}
      </div>
      <section class="glass" style="padding:22px;margin-bottom:18px">
        <h2>Duplicates &amp; cleanup</h2>
        <p class="muted">Books are fingerprinted with an MD5 of their content. Scan for duplicates, orphaned folders on disk and records whose file went missing. The oldest copy is always kept.</p>
        <div style="display:flex;gap:10px;flex-wrap:wrap"><button class="btn" id="scan">Scan (dry run)</button><button class="btn danger" id="clean" disabled>Clean up now</button></div>
        <pre id="report" class="log" style="display:none;white-space:pre-wrap"></pre>
      </section>
      <section class="glass" style="padding:22px;margin-bottom:18px">
        <h2>Import from server folder</h2>
        <p class="muted">Recursively import books from the server's import directory (mounted at <code>/import</code> in Docker).</p>
        <div class="inline"><input class="in" id="ipath" placeholder="Sub-folder (blank = everything)"><button class="btn primary" id="imp">${icon("folder")}Import</button></div>
        <label class="check" style="margin-top:10px"><input type="checkbox" id="iovw"><span>Let JSON files overwrite existing metadata that differs <span class="muted">(books are imported first, then JSON)</span></span></label>
        <div id="iprog"></div>
      </section>
      <section class="glass" style="padding:22px">
        <h2>API</h2><p class="muted">Everything in this UI is available over REST.</p>
        <a class="btn primary" href="/docs" target="_blank" rel="noopener">Swagger UI</a> <a class="btn" href="/openapi.json" target="_blank" rel="noopener">openapi.json</a>
      </section>`;
    const rep = root.querySelector("#report"), clean = root.querySelector("#clean");
    const show = (r) => {
      rep.style.display = "block";
      const n = (a) => a.length;
      rep.textContent = `${r.dry_run ? "DRY RUN — nothing deleted\n" : "Done\n"}duplicates: ${n(r.duplicates_removed)}\norphan folders: ${n(r.orphan_folders_removed)}\nmissing-file records: ${n(r.missing_file_rows_removed)}\nspace ${r.dry_run ? "to free" : "freed"}: ${fmtBytes(r.bytes_freed)}` +
        r.duplicates_removed.map((d) => `\n  • ${d.filename} (${d.title})`).join("");
      return n(r.duplicates_removed) + n(r.orphan_folders_removed) + n(r.missing_file_rows_removed);
    };
    root.querySelector("#scan").onclick = async () => { clean.disabled = !show(await api("/cleanup")); };
    clean.onclick = async () => {
      if (!confirm("Permanently remove the items listed in the scan?")) return;
      show(await api("/cleanup?dry_run=false", { method: "POST" })); clean.disabled = true; toast("Cleanup complete"); emit("library-changed");
    };
    root.querySelector("#imp").onclick = async () => {
      const box = root.querySelector("#iprog");
      try {
        let job = await api("/import", { json: { path: root.querySelector("#ipath").value.trim(), category_from_folders: true, overwrite_json: root.querySelector("#iovw").checked } });
        while (job.status !== "done") {
          box.innerHTML = `<div class="progress"><i style="width:${job.total ? (job.processed / job.total) * 100 : 5}%"></i></div><div class="muted small">${job.processed} / ${job.total || "?"} · ${job.summary.created} added · ${job.summary.duplicate} duplicates</div>`;
          await new Promise((r) => setTimeout(r, 900));
          job = await api("/import/" + job.id);
        }
        box.innerHTML = `<div class="counts"><span class="pill in">${job.summary.created} added</span><span class="pill in">${job.summary.updated} metadata updated</span><span class="pill">${job.summary.duplicate} duplicates</span><span class="pill side">${job.summary.warning} warnings</span><span class="pill">${job.summary.skipped} skipped</span><span class="pill side">${job.summary.error} errors</span></div>`;
        toast(`Import finished: ${job.summary.created} added`); refreshRail();
      } catch {}
    };
  },
};

refreshRail();
(async () => {
  try {
    const v = await api("/version", { quiet: true });
    $("build").textContent = `v${v.version}` + (v.build != null ? ` · build ${v.build}` : "");
  } catch {}
})();
render();
