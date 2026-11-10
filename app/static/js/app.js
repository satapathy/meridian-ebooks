import { api, esc, icon, toast, coverHTML, hue, fmtBytes, emit, applyPrefs, getPref } from "./api.js";
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
document.addEventListener("prefs-changed", (e) => { if (e.detail.key === "series") render(); });

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
    const group = !recent && !state.q && !state.series && getPref("series", "on") !== "off";
    const facets = await api("/facets");
    const set = (patch) => { const p = new URLSearchParams(); const s = { ...state, ...patch }; for (const [k, v] of Object.entries(s)) if (v && !(recent && (k === "sort" || k === "order"))) p.set(k, v); go((recent ? "/recent" : "/library") + (p.size ? "?" + p : ""), true); };
    const title = recent ? "Recently added" : state.q ? `Results for “${state.q}”` : state.author || state.category || (state.tag && `#${state.tag}`) || state.series || "Library";
    root.innerHTML = `<div class="page-head"><div><div class="eyebrow">${recent ? "Newest first" : state.q ? "Search" : state.series ? "Series" : "Browse"}</div><h1 class="grad-text">${esc(title)}</h1><div class="muted small" id="count"></div></div></div>
      <div class="toolbar">
        <button class="chip ${state.format ? "" : "on"}" data-f="">All</button>
        ${facets.formats.map((f) => `<button class="chip ${state.format === f.name ? "on" : ""}" data-f="${esc(f.name)}">${esc(f.name)} <small>${f.count}</small></button>`).join("")}
        <span class="grow"></span>
        <select class="in" id="cat" aria-label="Category"><option value="">All categories</option>${facets.categories.map((c) => `<option ${state.category === c.name ? "selected" : ""} value="${esc(c.name)}">${esc(c.name)} (${c.count})</option>`).join("")}</select>
        <select class="in" id="sort" aria-label="Sort">${[["added", "Date added"], ["title", "Title"], ["author", "Author"], ["published", "Published"], ["size", "Size"], ["rating", "Rating"], ["series", "Series"]].map(([v, l]) => `<option value="${v}" ${state.sort === v ? "selected" : ""}>${l}</option>`).join("")}</select>
        <button class="btn sm" id="order" title="Toggle sort order">${state.order === "asc" ? "↑ Asc" : "↓ Desc"}</button>
      </div>
      <div class="toolbar" id="active"></div><div class="grid" id="grid"></div><div class="sentinel" id="more"></div>`;
    if (recent) root.querySelectorAll("#sort, #order").forEach((e) => e.remove());
    const active = root.querySelector("#active");
    for (const k of ["author", "tag", "series"]) if (state[k]) active.insertAdjacentHTML("beforeend", `<button class="chip on" data-clear="${k}">${k}: ${esc(state[k])} ✕</button>`);
    if (!active.children.length) active.remove();
    root.querySelectorAll("[data-f]").forEach((b) => (b.onclick = () => set({ format: b.dataset.f })));
    root.querySelectorAll("[data-clear]").forEach((b) => (b.onclick = () => set({ [b.dataset.clear]: "" })));
    root.querySelector("#cat").onchange = (e) => set({ category: e.target.value });
    if (!recent) root.querySelector("#sort").onchange = (e) => set({ sort: e.target.value, order: ["added", "size", "rating", "published"].includes(e.target.value) ? "desc" : "asc" });
    if (!recent) root.querySelector("#order").onclick = () => set({ order: state.order === "asc" ? "desc" : "asc" });

    const grid = root.querySelector("#grid"), more = root.querySelector("#more"), count = root.querySelector("#count");
    let offset = 0, total = Infinity, loading = false;
    const load = async () => {
      if (loading || offset >= total) return;
      loading = true;
      const p = new URLSearchParams({ limit: 60, offset, sort: state.sort, order: state.order });
      for (const k of ["q", "author", "category", "format", "tag", "series"]) if (state[k]) p.set(k, state[k]);
      if (group) p.set("group_series", "true");
      const page = await api("/books?" + p);
      if (!alive()) return;
      total = page.total; offset += page.items.length;
      grid.append(...page.items.map(card));
      count.textContent = group ? `${total} item${total === 1 ? "" : "s"} · series grouped` : `${total} book${total === 1 ? "" : "s"}`;
      if (!total) {
        const filtered = state.q || state.author || state.category || state.format || state.tag || state.series;
        grid.outerHTML = filtered
          ? `<div class="empty"><h2>Nothing found</h2><p>Try a wildcard like <code>*${esc(state.q.replace(/\*/g, ""))}*</code> or a different filter.</p></div>`
          : emptyState();
      }
      loading = false;
    };
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
    const covers = await Promise.all(f.categories.slice(0, 60).map((c) => api(`/books?category=${enc(c.name)}&limit=3&sort=added`, { quiet: true }).catch(() => ({ items: [] }))));
    root.innerHTML = `<div class="page-head"><div><div class="eyebrow">Browse</div><h1 class="grad-text">Categories</h1><div class="muted small">${f.categories.length} collections</div></div></div><div class="tiles"></div>`;
    root.querySelector(".tiles").innerHTML = f.categories.map((c, i) => `<a class="tile glass" href="#/library?category=${enc(c.name)}&sort=title&order=asc">
      <div class="collage">${(covers[i]?.items || []).map((b) => `<div>${coverHTML(b)}</div>`).join("")}</div>
      <div style="min-width:0"><b>${esc(c.name)}</b><span class="muted small">${c.count} book${c.count > 1 ? "s" : ""}</span></div></a>`).join("");
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
      <section class="glass" style="padding:22px;margin-bottom:18px" id="sg">
        <h2>Suggest categories online</h2>
        <p class="muted">Look books up on <b>Google Books</b> (category, sub-category) and <b>Open Library</b> (tags). Nothing is changed until you review the suggestions and accept them. Only each book's title, author and ISBN are sent to those sites, and only when you press the button.</p>
        <div id="sg-off" class="muted small" style="display:none">Online lookup is turned off on this server (<code>ONLINE_LOOKUP=off</code>).</div>
        <div style="display:flex;gap:22px;flex-wrap:wrap">
          <label class="check"><input type="checkbox" id="sg-f-cat" checked><span>Categories &amp; tags</span></label>
          <label class="check"><input type="checkbox" id="sg-f-cover" checked><span>Covers</span></label>
        </div>
        <label class="check" style="margin-top:10px"><input type="checkbox" id="sg-missing" checked><span>Only books that are missing them <span class="muted">(no category / no cover at all)</span></span></label>
        <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:12px"><button class="btn primary" id="sg-go">Find suggestions</button><button class="btn" id="sg-stop" style="display:none">Stop</button></div>
        <div id="sg-prog"></div>
        <div id="sg-out"></div>
      </section>
      <section class="glass" style="padding:22px">
        <h2>API</h2><p class="muted">Everything in this UI is available over REST.</p>
        <a class="btn primary" href="/docs" target="_blank" rel="noopener">Swagger UI</a> <a class="btn" href="/redoc" target="_blank" rel="noopener">ReDoc</a> <a class="btn" href="/openapi.json" target="_blank" rel="noopener">openapi.json</a>
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
    suggestTool(root.querySelector("#sg"));
  },
};

/** "Suggest categories online": look up -> review/edit -> accept. Nothing is saved until "Accept". */
function suggestTool(box) {
  const $ = (s) => box.querySelector(s);
  const go = $("#sg-go"), stop = $("#sg-stop"), prog = $("#sg-prog"), out = $("#sg-out");
  let cancelled = false;
  api("/lookup/status", { quiet: true }).then((s) => {
    if (!s.enabled) { go.disabled = true; $("#sg-off").style.display = "block"; }
  }).catch(() => {});
  stop.onclick = () => { cancelled = true; stop.disabled = true; };

  const bar = (done, total, note = "", finished = false) => {
    prog.innerHTML = `<div class="progress${finished ? " done" : ""}"><i style="width:${total ? (done / total) * 100 : 0}%"></i></div><div class="muted small">${done} / ${total} looked up${note}</div>`;
  };
  const field = (label, f, v) => `<label class="field"><span>${label}</span><input class="in" data-f="${f}" value="${esc(v)}"></label>`;

  const showResults = (found, missed, unavailable) => {
    const how = (s) => `${esc(s.source)} · ${s.confidence === "isbn" ? "ISBN match" : "title match"}${s.matched ? ` · “${esc(s.matched)}”` : ""}`;
    const rows = found.map((x) => {
      const s = x.suggestion, c = x.cover;
      return `<div class="sg-row" data-id="${esc(x.id)}">
        <div class="sg-picks">
          ${s ? `<label class="check small"><input type="checkbox" class="sg-pick" checked aria-label="Accept metadata for ${esc(x.title)}"><span>Metadata</span></label>` : ""}
          ${c ? `<label class="check small"><input type="checkbox" class="sg-cpick" checked aria-label="Accept cover for ${esc(x.title)}"><span>Cover</span></label>` : ""}
        </div>
        <div style="min-width:0">
          <div><b>${esc(x.title)}</b> <span class="muted small">${esc(x.author)}</span></div>
          ${s ? `<div class="sg-fields">
            ${s.category != null ? field("Category", "category", s.category) : ""}
            ${s.subcategory != null ? field("Sub-category", "subcategory", s.subcategory) : ""}
            ${s.tags != null ? field("Tags (comma separated)", "tags", s.tags.join(", ")) : ""}
          </div><div class="muted small">${how(s)}</div>` : ""}
          ${c ? `<div class="muted small" style="margin-top:6px">Cover: ${how(c)}</div>` : ""}
        </div>
        ${c ? `<img class="sg-cover" loading="lazy" alt="Cover found for ${esc(x.title)}" src="/api/lookup/cover/${esc(x.id)}">` : ""}</div>`;
    }).join("");
    out.innerHTML = `${unavailable ? `<div class="log" style="margin-top:12px"><div class="error"><em>stopped</em><span>The public sites could not be reached (${esc(unavailable)}). Suggestions found so far are listed below.</span></div></div>` : ""}
      ${found.length ? `<div class="sg-bar"><b>${found.length} suggestion${found.length > 1 ? "s" : ""}</b>
          <button class="btn" id="sg-all">Select all</button><button class="btn" id="sg-none">Select none</button>
          <button class="btn primary" id="sg-accept"></button></div>
        <div class="sg-list">${rows}</div>` : `<p class="muted" style="margin-top:12px">No suggestions found.</p>`}
      ${missed.length ? `<details style="margin-top:12px"><summary class="muted small" style="cursor:pointer">${missed.length} book${missed.length > 1 ? "s" : ""} without a suggestion</summary>
        <div class="log">${missed.map((x) => `<div><span>${esc(x.title)} — ${esc(x.reason)}</span></div>`).join("")}</div></details>` : ""}`;
    if (!found.length) return;
    const picks = () => [...out.querySelectorAll(".sg-pick, .sg-cpick")];
    const accept = $("#sg-accept");
    const count = () => {
      const n = picks().filter((p) => p.checked).length;
      accept.textContent = `Accept selected (${n})`; accept.disabled = !n;
    };
    picks().forEach((p) => (p.onchange = count));
    $("#sg-all").onclick = () => { picks().forEach((p) => (p.checked = true)); count(); };
    $("#sg-none").onclick = () => { picks().forEach((p) => (p.checked = false)); count(); };
    count();
    accept.onclick = async () => {
      const rowsToSave = [...out.querySelectorAll(".sg-row")].filter((r) => r.querySelector(".sg-pick:checked, .sg-cpick:checked"));
      accept.disabled = true;
      let saved = 0, failed = 0, next = 0;
      const done = (row, sel) => { const p = row.querySelector(sel); if (p) { p.checked = false; p.disabled = true; } };
      const worker = async () => {
        while (next < rowsToSave.length) {
          const row = rowsToSave[next++], id = row.dataset.id;
          let ok = true;
          if (row.querySelector(".sg-pick:checked")) {         // category / sub-category / tags (as edited above)
            const patch = {};
            row.querySelectorAll("[data-f]").forEach((i) => {
              const v = i.value.trim();
              if (v) patch[i.dataset.f] = i.dataset.f === "tags" ? v.split(",").map((t) => t.trim()).filter(Boolean) : v;
            });
            try {
              if (Object.keys(patch).length) await api(`/books/${id}`, { method: "PATCH", json: patch, quiet: true });
              done(row, ".sg-pick");
            } catch { ok = false; }
          }
          if (row.querySelector(".sg-cpick:checked")) {         // cover: re-fetch the previewed image, then store it
            try {
              const img = await fetch(`/api/lookup/cover/${id}`);
              if (!img.ok) throw new Error("cover no longer available");
              const fd = new FormData(); fd.append("file", await img.blob(), "cover.jpg");
              await api(`/books/${id}/cover`, { method: "PUT", body: fd, quiet: true });
              done(row, ".sg-cpick");
            } catch { ok = false; }
          }
          row.classList.add(ok ? "saved" : "failed");
          ok ? saved++ : failed++;
        }
      };
      await Promise.all(Array.from({ length: 3 }, worker));
      toast(`${saved} book${saved === 1 ? "" : "s"} updated${failed ? ` · ${failed} failed` : ""}`, failed ? "err" : "ok");
      // not emit("library-changed"): that re-renders this page and would wipe the rows still under review
      refreshRail(); count();
    };
  };

  go.onclick = async () => {
    cancelled = false; go.disabled = true; stop.disabled = false; stop.style.display = ""; out.innerHTML = ""; prog.innerHTML = "";
    const found = [], missed = [];
    let unavailable = null, done = 0, total = 0;
    const fields = [$("#sg-f-cat").checked && "category", $("#sg-f-cover").checked && "cover"].filter(Boolean);
    if (!fields.length) { toast("Tick categories and/or covers", "err"); go.disabled = false; stop.style.display = "none"; return; }
    try {
      const { items } = await api(`/lookup/candidates?only_missing=${$("#sg-missing").checked}&${fields.map((f) => "fields=" + f).join("&")}`);
      total = items.length;
      if (!total) { prog.innerHTML = `<p class="muted">Nothing to look up: every book already has a ${fields.join(" and ")}.</p>`; return; }
      for (let i = 0; i < total && !cancelled && !unavailable; i += 5) {
        const ids = items.slice(i, i + 5).map((b) => b.id);
        const r = await api("/lookup/suggest", { json: { ids, fields }, quiet: true });
        for (const x of r.results) (x.suggestion || x.cover ? found : missed).push(x);
        unavailable = r.unavailable;
        done += ids.length;
        bar(done, total);
      }
      bar(done, total, cancelled ? " · stopped" : unavailable ? " · stopped" : " · done", true);
      showResults(found, missed, unavailable);
    } catch (e) {
      toast(e.message, "err", 6000);
      if (total) showResults(found, missed, null);
    } finally {
      go.disabled = false; stop.style.display = "none";
    }
  };
}

refreshRail();
render();
