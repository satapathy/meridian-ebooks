// Web components (light DOM, themed by app.css).
import { api, esc, icon, toast, coverHTML, fmtBytes, emit, THEMES, FONTS, clampFs, getPref, setPref } from "./api.js";

const EXT_OK = new Set("epub pdf docx doc odt rtf txt md html htm mobi azw azw3 kfx fb2 djvu cbz cbr cb7 lit chm pdb zip json".split(" "));
const extOf = (n) => n.split(".").pop().toLowerCase();

// ------------------------------------------------------------------ <mx-card>
class MxCard extends HTMLElement {
  set book(b) { this._b = b; this.dataset.id = b.id; this.render(); }
  get book() { return this._b; }
  get isSeries() { return (this._b.series_count || 0) > 1; }
  connectedCallback() {
    this.tabIndex = 0;
    const open = () => {
      if (this.isSeries) location.hash = `#/library?series=${encodeURIComponent(this._b.series)}&sort=series&order=asc`;
      else emit("open-book", this._b);
    };
    this.addEventListener("click", open);
    this.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
    document.addEventListener("book-updated", this._upd = (e) => { if (!this.isSeries && e.detail.id === this.dataset.id) this.book = e.detail; });
  }
  disconnectedCallback() { document.removeEventListener("book-updated", this._upd); }
  render() {
    const b = this._b;
    if (this.isSeries) {  // one stacked tile standing for the whole series
      this.innerHTML = `<div class="stack"><i></i><i></i><div class="poster">${coverHTML({ ...b, title: b.series })}<span class="fmt">${b.series_count} books</span></div></div>
        <div class="meta"><div class="t" title="${esc(b.series)}">${esc(b.series)}</div><div class="a">Series · ${esc(b.author || "Unknown author")}</div></div>`;
      return;
    }
    this.innerHTML = `<div class="poster">${coverHTML(b)}<span class="fmt">${esc(b.format)}</span>
      ${b.rating ? `<span class="stars">${"★".repeat(b.rating)}</span>` : ""}</div>
      <div class="meta"><div class="t" title="${esc(b.title)}">${esc(b.title)}</div><div class="a">${esc(b.author || "Unknown author")}</div></div>`;
  }
}
customElements.define("mx-card", MxCard);

// ------------------------------------------------------------------ <mx-drawer>
class MxDrawer extends HTMLElement {
  connectedCallback() {
    document.addEventListener("open-book", (e) => this.open(e.detail));
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && this.classList.contains("open")) this.close(); });
  }
  async open(book) {
    this.book = book;
    this.classList.add("open");
    this.render();
    try { this.book = await api("/books/" + book.id, { quiet: true }); this.render(); } catch {}
  }
  close() { this.classList.remove("open"); this.innerHTML = ""; }

  render() {
    const b = this.book;
    const prev = this.querySelector(".panel")?.scrollTop || 0;
    const stars = (n) => [1, 2, 3, 4, 5].map((i) => `<button type="button" data-star="${i}" class="${i <= n ? "on" : ""}" aria-label="${i} stars">${icon("star")}</button>`).join("");
    const st = b.storage;
    const ext = "." + b.format;
    const stem = b.filename.endsWith(ext) ? b.filename.slice(0, -ext.length) : b.filename;
    this.innerHTML = `
      <div class="scrim"></div>
      <aside class="panel" role="dialog" aria-label="Book details">
        <button class="btn sm close" aria-label="Close">${icon("x")}</button>
        <div class="d-top">
          <div class="poster">${coverHTML(b)}<span class="fmt">${esc(b.format)}</span></div>
          <div>
            <div class="eyebrow">${esc(b.category || "Uncategorized")}${b.subcategory ? " › " + esc(b.subcategory) : ""}</div>
            <h2>${esc(b.title)}</h2>
            ${b.subtitle ? `<div class="subtitle">${esc(b.subtitle)}</div>` : ""}
            <div class="muted">${b.authors.length ? b.authors.map((a) => `<a href="#/library?author=${encodeURIComponent(a)}&sort=title&order=asc" data-nav>${esc(a)}</a>`).join(", ") : "Unknown author"}</div>
            ${b.series ? `<div class="small muted">${esc(b.series)}${b.series_index != null ? " · #" + b.series_index : ""}</div>` : ""}
            <div style="margin-top:10px;display:flex;gap:6px;flex-wrap:wrap">${b.tags.map((t) => `<a class="tag" href="#/library?tag=${encodeURIComponent(t)}" data-nav>${esc(t)}</a>`).join("")}</div>
            <div class="actions">
              <a class="btn primary" href="/api/books/${b.id}/download">${icon("download")}Download</a>
              ${b.format === "pdf" ? `<a class="btn" target="_blank" rel="noopener" href="/api/books/${b.id}/download?inline=true">${icon("book")}Read</a>` : ""}
              <button class="btn" data-act="cover">${icon("image")}${b.cover_source === "user" ? "Replace cover" : "Upload cover"}</button>
              <button class="btn" data-act="fetch-meta" title="Compare this book with Google Books / Open Library and pick what to keep">${icon("search")}Fetch metadata</button>
              ${b.cover_source === "user" ? `<button class="btn" data-act="uncover" title="Go back to the cover embedded in the book">Remove custom cover</button>` : ""}
              <input type="file" accept="image/*" hidden id="cover-in">
            </div>
          </div>
        </div>

        <section class="section">
          <h3>Metadata</h3>
          <form class="form" id="mform" autocomplete="off">
            <label class="field full"><span>Title</span><input class="in" name="title" required value="${esc(b.title)}"></label>
            <label class="field full"><span>Subtitle</span><input class="in" name="subtitle" value="${esc(b.subtitle)}"></label>
            <label class="field full"><span>Author(s) — separate with ;</span><input class="in" name="author" value="${esc(b.author)}"></label>
            <label class="field"><span>Series</span><input class="in" name="series" value="${esc(b.series)}"></label>
            <label class="field"><span>Series #</span><input class="in" name="series_index" type="number" step="any" value="${b.series_index ?? ""}"></label>
            <label class="field"><span>Category</span><input class="in" name="category" list="cat-list" value="${esc(b.category)}"></label>
            <label class="field"><span>Sub-category</span><input class="in" name="subcategory" value="${esc(b.subcategory)}"></label>
            <label class="field"><span>Publisher</span><input class="in" name="publisher" value="${esc(b.publisher)}"></label>
            <label class="field"><span>Published</span><input class="in" name="published" placeholder="YYYY or YYYY-MM-DD" value="${esc(b.published)}"></label>
            <label class="field"><span>Language</span><input class="in" name="language" placeholder="en" value="${esc(b.language)}"></label>
            <label class="field"><span>ISBN</span><input class="in" name="isbn" value="${esc(b.isbn)}"></label>
            <div class="field"><span>Rating</span><div class="stars-in" id="stars">${stars(b.rating || 0)}</div></div>
            <label class="field full"><span>Tags — comma separated</span><input class="in" name="tags" value="${esc(b.tags.join(", "))}"></label>
            <label class="field full"><span>Description</span><textarea class="in" name="description">${esc(b.description)}</textarea></label>
            <div class="full" style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap">
              <div class="storage">
                ${st.embedded.length ? `<span class="muted">In file:</span>${st.embedded.map((f) => `<span class="pill in">${f}</span>`).join("")}` : ""}
                ${st.sidecar.length ? `<span class="muted">In ${esc(st.sidecar_file || "sidecar")}:</span>${st.sidecar.map((f) => `<span class="pill side">${f}</span>`).join("")}` : ""}
              </div>
              <button class="btn primary" type="submit">${icon("save")}Save metadata</button>
            </div>
          </form>
          <datalist id="cat-list"></datalist>
        </section>

        <section class="section">
          <h3>File</h3>
          <p class="small muted" style="margin-top:-4px">The file name is independent of the title — renaming one never changes the other.</p>
          <form class="inline" id="rform"><input class="in" name="filename" value="${esc(stem)}" aria-label="File name"><span class="ext">${esc(ext)}</span><button class="btn" type="submit">Rename file</button></form>
          <dl class="kv" style="margin-top:16px">
            <dt>Size</dt><dd>${fmtBytes(b.size)}</dd>
            <dt>UUID</dt><dd><code>${b.id}</code></dd>
            <dt>MD5</dt><dd><code>${b.md5}</code></dd>
            <dt>Stored at</dt><dd><code>${esc(b.path)}</code></dd>
            ${b.source_path ? `<dt>Uploaded as</dt><dd>${esc(b.source_path)}</dd>` : ""}
            <dt>Added</dt><dd>${new Date(b.added_at).toLocaleString()}</dd>
          </dl>
        </section>

        <section class="section"><h3>Danger zone</h3><button class="btn danger" data-act="delete">${icon("trash")}Delete book</button></section>
      </aside>`;
    this.querySelector(".panel").scrollTop = prev;
    this.fillCategories();
    this.bind();
  }

  async fillCategories() {
    try {
      const f = await api("/facets", { quiet: true });
      const dl = this.querySelector("#cat-list");
      if (dl) dl.innerHTML = f.categories.filter((c) => c.name !== "Uncategorized").map((c) => `<option value="${esc(c.name)}">`).join("");
    } catch {}
  }

  bind() {
    const b = this.book;
    this.querySelector(".scrim").onclick = this.querySelector(".close").onclick = () => this.close();
    this.querySelectorAll("[data-nav]").forEach((a) => a.addEventListener("click", () => this.close()));
    let rating = b.rating || 0;
    const stars = this.querySelector("#stars");
    stars.onclick = (e) => {
      const i = Number(e.target.closest("[data-star]")?.dataset.star);
      if (!i) return;
      rating = rating === i ? 0 : i;
      stars.querySelectorAll("button").forEach((s, k) => s.classList.toggle("on", k < rating));
    };
    this.querySelector("#mform").onsubmit = async (e) => {
      e.preventDefault();
      const f = new FormData(e.target);
      const body = Object.fromEntries(f.entries());
      body.series_index = body.series_index === "" ? null : Number(body.series_index);
      body.rating = rating;
      body.tags = body.tags.split(",").map((t) => t.trim()).filter(Boolean);
      const btn = e.submitter || e.target.querySelector("[type=submit]"); btn.disabled = true;
      try {
        this.book = await api("/books/" + b.id, { method: "PATCH", json: body });
        const s = this.book.storage;
        toast(`Saved · ${s.embedded.length ? "written into the file" : "stored in sidecar"}${s.embedded.length && s.sidecar.length ? " + sidecar" : ""}`);
        emit("book-updated", this.book);
        this.close();
      } catch {} finally { btn.disabled = false; }
    };
    this.querySelector("#rform").onsubmit = async (e) => {
      e.preventDefault();
      try {
        this.book = await api(`/books/${b.id}/rename`, { json: { filename: e.target.filename.value } });
        toast("File renamed — title unchanged");
        emit("book-updated", this.book);
        this.render();
      } catch {}
    };
    const cin = this.querySelector("#cover-in");
    this.querySelector('[data-act="cover"]').onclick = () => cin.click();
    cin.onchange = async () => {
      if (!cin.files[0]) return;
      const fd = new FormData(); fd.append("file", cin.files[0]);
      try {
        this.book = await api(`/books/${b.id}/cover`, { method: "PUT", body: fd });
        emit("book-updated", this.book); this.renderKeepingEdits(); toast("Cover saved next to the book - it now overrides the embedded cover");
      } catch {}
    };
    const un = this.querySelector('[data-act="uncover"]');
    if (un) un.onclick = async () => {
      try { this.book = await api(`/books/${b.id}/cover`, { method: "DELETE" }); emit("book-updated", this.book); this.renderKeepingEdits(); toast("Custom cover removed"); } catch {}
    };
    this.bindLookup();
    this.querySelector('[data-act="delete"]').onclick = async () => {
      if (!confirm(`Delete “${b.title}” and its files permanently?`)) return;
      try {
        await api("/books/" + b.id, { method: "DELETE" });
        this.close(); toast("Book deleted"); emit("library-changed");
      } catch {}
    };
  }

  /** Re-render without losing metadata the user has typed but not saved yet (fields in `skip` were just saved). */
  renderKeepingEdits(skip = []) {
    const snap = [...this.querySelectorAll("#mform [name]")].filter((e) => !skip.includes(e.name)).map((e) => [e.name, e.value]);
    this.render();
    for (const [name, value] of snap) {
      const el = this.querySelector(`#mform [name="${name}"]`);
      if (el && el.value !== value) { el.value = value; el.classList.add("filled"); }
    }
  }

  /** "Fetch metadata": compare with Google Books / Open Library in a dialog and apply only what the user picks. */
  bindLookup() {
    const btn = this.querySelector('[data-act="fetch-meta"]');
    lookupEnabled().then((on) => { if (!on) btn.remove(); });
    btn.onclick = () => {
      const current = Object.fromEntries([...this.querySelectorAll("#mform [name]")].map((e) => [e.name, e.value]));
      document.getElementById("fetchmeta").open({
        book: this.book, current,
        applied: (book, skip) => { this.book = book; emit("book-updated", book); this.renderKeepingEdits(skip); },
      });
    };
  }
}
customElements.define("mx-drawer", MxDrawer);

let _lookupOn;
const lookupEnabled = () => (_lookupOn ||= api("/lookup/status", { quiet: true }).then((s) => s.enabled).catch(() => { _lookupOn = null; return false; }));

// ------------------------------------------------------------------ <mx-fetchmeta>
const FETCH_FIELDS = [["title", "Title"], ["subtitle", "Subtitle"], ["author", "Author(s)"], ["category", "Category"], ["subcategory", "Sub-category"],
  ["tags", "Tags"], ["publisher", "Publisher"], ["published", "Published"], ["language", "Language"], ["isbn", "ISBN"], ["description", "Description"]];
const asText = (v) => (Array.isArray(v) ? v.join(", ") : String(v ?? "").trim());
const splitTags = (v) => (Array.isArray(v) ? v : String(v || "").split(",")).map((t) => t.trim()).filter(Boolean);
const tagKey = (v) => [...new Set(splitTags(v).map((t) => t.toLowerCase()))].sort().join("|");
const squash = (name, v) => (name === "isbn" ? asText(v).replace(/[^0-9x]/gi, "") : asText(v)).toLowerCase();
const sameValue = (name, a, b) => (name === "tags" ? tagKey(a) === tagKey(b) : squash(name, a) === squash(name, b));
const mergeTags = (have, add) => [...splitTags(have), ...splitTags(add).filter((t) => !splitTags(have).some((h) => h.toLowerCase() === t.toLowerCase()))];

/** Compare a book with what Google Books / Open Library know; every choice defaults to the current value. */
class MxFetchMeta extends HTMLElement {
  open(ctx) {
    this.ctx = ctx;
    this.classList.add("open");
    this._esc = (e) => { if (e.key === "Escape") { e.stopImmediatePropagation(); this.close(); } };
    document.addEventListener("keydown", this._esc, true);
    this.frame(`<div class="fm-wait"><span class="spinner"></span><div><b>Looking up “${esc(ctx.book.title)}”…</b>
      <div class="muted small">Asking Google Books and Open Library and downloading a few covers - this takes a few seconds.</div></div></div>`,
      `<button class="btn" id="fm-cancel">Cancel</button>`);
    const mine = (this.token = {});
    api(`/lookup/metadata/${ctx.book.id}`, { quiet: true }).then((r) => { if (this.token === mine) this.show(r); })
      .catch((e) => { if (this.token === mine) this.frame(`<p class="muted">${esc(e.message || "Lookup failed.")}</p>`, `<button class="btn primary" id="fm-cancel">Close</button>`); });
  }
  close() {
    this.token = null; this.classList.remove("open"); this.innerHTML = "";
    document.removeEventListener("keydown", this._esc, true);
  }
  frame(body, actions, sub = "") {
    this.innerHTML = `<div class="scrim" style="position:absolute;inset:0;background:rgba(2,2,10,.6);backdrop-filter:blur(4px)"></div>
      <div class="dialog glass fm" role="dialog" aria-label="Fetch metadata">
        <h2>Fetch metadata</h2><div class="muted small">${sub || esc(this.ctx.book.title)}</div>
        <div class="fm-body">${body}</div><div class="dialog-actions">${actions}</div></div>`;
    this.querySelector(".scrim").onclick = () => this.close();
    this.querySelector("#fm-cancel").onclick = () => this.close();
  }

  show(r) {
    const { book, current } = this.ctx;
    const rows = FETCH_FIELDS.filter(([k]) => r.fields[k] != null && r.fields[k].length);
    const diff = rows.filter(([k]) => !sameValue(k, current[k], r.fields[k]));
    const same = rows.filter(([k]) => sameValue(k, current[k], r.fields[k]));
    const val = (v) => (asText(v) ? esc(asText(v)) : `<i class="muted">empty</i>`);
    const cell = (name, choice, html, cls = "") => `<label class="fm-opt${cls}"><input type="radio" name="f-${name}" value="${choice}"${choice === "keep" ? " checked" : ""}><span class="fm-val">${html}</span></label>`;
    const meta = diff.length ? `<div class="fm-grid"><div class="fm-h">Field</div><div class="fm-h">Current</div><div class="fm-h">New</div>
      ${diff.map(([k, label]) => {
        const both = k === "tags" && splitTags(current.tags).length ? mergeTags(current.tags, r.fields.tags) : null;
        return `<div class="fm-f">${label}</div>${cell(k, "keep", val(current[k]))}
          <div class="fm-new">${cell(k, "new", val(r.fields[k]))}${both ? cell(k, "merge", `<small class="muted">Both:</small> ${esc(both.join(", "))}`) : ""}</div>`;
      }).join("")}</div>`
      : `<p class="muted">${rows.length ? "Everything found online already matches this book." : "No metadata found online for this book."}</p>`;

    const cur = book.has_cover ? `<img src="/api/books/${book.id}/cover?v=${encodeURIComponent(book.updated_at)}" alt="Current cover">` : `<div class="fm-none">No cover</div>`;
    const covers = `<div class="fm-covers">
      <label class="fm-cv"><input type="radio" name="cover" value="current" checked><div class="fm-img">${cur}</div><span class="small"><b>Current</b></span></label>
      ${r.covers.map((c, i) => `<label class="fm-cv"><input type="radio" name="cover" value="${c.key}"><div class="fm-img"><img src="/api/lookup/cover-img/${c.key}" alt="Cover option ${i + 1}"></div>
        <span class="small"><b>${esc(c.source)}</b><br><span class="muted">${c.width}×${c.height}${c.confidence === "isbn" ? " · ISBN" : ""}</span></span></label>`).join("")}</div>
      ${r.covers.length ? (r.covers.length < 3 ? `<p class="muted small">Only ${r.covers.length} cover${r.covers.length > 1 ? "s" : ""} found online for this book.</p>` : "")
        : `<p class="muted small">No cover found online for this book.</p>`}`;

    this.frame(`<h3 class="fm-h3">Cover</h3>${covers}<h3 class="fm-h3">Metadata</h3>${meta}
      ${same.length ? `<p class="muted small">Already the same: ${same.map(([, l]) => l).join(", ")}.</p>` : ""}`,
      `<span class="muted small" id="fm-count" style="margin-right:auto"></span><button class="btn" id="fm-cancel">Cancel</button><button class="btn primary" id="fm-apply">${icon("save")}Apply</button>`,
      `${esc(r.source || "No match")}${r.matched ? ` · matched “${esc(r.matched)}”` : ""}${r.confidence ? ` · ${r.confidence === "isbn" ? "ISBN match" : "title + author match"}` : ""} · nothing changes until you press Apply`);

    const apply = this.querySelector("#fm-apply"), count = this.querySelector("#fm-count");
    const picks = () => {
      const fields = {};
      for (const [k] of diff) {
        const v = this.querySelector(`input[name="f-${k}"]:checked`)?.value;
        if (v === "new") fields[k] = k === "tags" ? splitTags(r.fields.tags) : r.fields[k];
        if (v === "merge") fields[k] = mergeTags(current.tags, r.fields.tags);
      }
      return { fields, cover: this.querySelector('input[name="cover"]:checked')?.value };
    };
    const refresh = () => {
      const p = picks(), n = Object.keys(p.fields).length + (p.cover !== "current" ? 1 : 0);
      apply.disabled = !n;
      count.textContent = n ? `${n} change${n > 1 ? "s" : ""} selected` : "Nothing selected - the current values are kept";
    };
    this.querySelector(".fm-body").addEventListener("change", refresh);
    refresh();
    apply.onclick = async () => {
      const p = picks(); apply.disabled = true; apply.textContent = "Saving…";
      try {
        let saved = book;
        if (Object.keys(p.fields).length) saved = await api(`/books/${book.id}`, { method: "PATCH", json: p.fields });
        if (p.cover !== "current") {
          const res = await fetch(`/api/lookup/cover-img/${p.cover}`);
          if (!res.ok) throw new Error("That cover is no longer available - fetch the metadata again.");
          const fd = new FormData(); fd.append("file", await res.blob(), "cover.jpg");
          saved = await api(`/books/${book.id}/cover`, { method: "PUT", body: fd });
        }
        this.ctx.applied(saved, Object.keys(p.fields));
        this.close(); toast("Saved" + (p.cover !== "current" ? " · cover stored next to the book" : ""));
      } catch (e) { toast(e.message || "Could not save", "err"); apply.disabled = false; apply.textContent = "Apply"; }
    };
    (apply.disabled ? this.querySelector("#fm-cancel") : apply).focus();
  }
}
customElements.define("mx-fetchmeta", MxFetchMeta);

// ------------------------------------------------------------------ <mx-upload>
async function walkEntry(entry, path = "") {
  if (entry.isFile) return new Promise((res) => entry.file((file) => res([{ file, rel: path + entry.name, folder: !!path }]), () => res([])));
  const reader = entry.createReader();
  const kids = [];
  for (;;) {
    const batch = await new Promise((res) => reader.readEntries(res, () => res([])));
    if (!batch.length) break;
    kids.push(...batch);
  }
  const out = [];
  for (const k of kids) out.push(...(await walkEntry(k, path + entry.name + "/")));
  return out;
}

class MxUpload extends HTMLElement {
  connectedCallback() { this.queue = []; this.render(); }
  open(items = []) { this.classList.add("open"); if (items.length) this.add(items); }
  close() { if (this.busy) return; this.classList.remove("open"); this.queue = []; this.render(); }

  async addFromDataTransfer(dt) {
    const entries = [...dt.items].map((i) => i.webkitGetAsEntry?.()).filter(Boolean);
    const out = [];
    if (entries.length) for (const e of entries) out.push(...(await walkEntry(e)));
    else for (const f of dt.files) out.push({ file: f, rel: f.name, folder: false });
    this.open(out);
  }

  add(items) {
    for (const it of items) {
      if (it.file.name.startsWith(".")) continue;
      if (!EXT_OK.has(extOf(it.file.name))) { this.ignored = (this.ignored || 0) + 1; continue; }
      this.queue.push(it);
    }
    this.render();
  }

  render() {
    const n = this.queue.length;
    const size = this.queue.reduce((s, i) => s + i.file.size, 0);
    this.innerHTML = `<div class="scrim" style="position:absolute;inset:0;background:rgba(2,2,10,.6);backdrop-filter:blur(4px)"></div>
      <div class="dialog glass" role="dialog" aria-label="Add books">
        <h2>Add books</h2>
        <div class="muted small">EPUB, PDF, DOCX, MOBI, AZW3, FB2, TXT, CBZ … .zip archives and metadata <code>.json</code> files. Duplicates (same MD5) are skipped; books are always added before JSON files are applied.</div>
        <div class="drop" id="drop">
          <div style="font-size:15px"><b>Drag &amp; drop</b> files or whole folders here</div>
          <div class="row">
            <button class="btn" id="pick-files">${icon("book")}Choose files</button>
            <button class="btn" id="pick-folder">${icon("folder")}Choose folder</button>
          </div>
          <input type="file" id="in-files" multiple hidden>
          <input type="file" id="in-folder" webkitdirectory directory multiple hidden>
        </div>
        <div class="opts">
          <label class="field"><span>Category for loose files (optional)</span><input class="in" id="cat" list="up-cats" placeholder="e.g. Science Fiction"></label>
          <datalist id="up-cats"></datalist>
          <label class="check"><input type="checkbox" id="fold" checked><span>Use folder names as categories for folder uploads</span></label>
          <label class="check"><input type="checkbox" id="ovw"><span>Let imported JSON overwrite existing metadata that differs <span class="muted">(otherwise you get a warning with the differences)</span></span></label>
        </div>
        <div id="status" style="margin-top:14px">
          ${n ? `<div class="counts"><span class="tag">${n} book file${n > 1 ? "s" : ""} · ${fmtBytes(size)}</span>${this.ignored ? `<span class="pill">${this.ignored} non-book files ignored</span>` : ""}</div>` : ""}
        </div>
        <div class="dialog-actions">
          <button class="btn" id="cancel">${this.done ? "Close" : "Cancel"}</button>
          <button class="btn primary" id="go" ${n ? "" : "disabled"}>${icon("upload")}Upload${n ? " " + n : ""}</button>
        </div>
      </div>`;
    this.bind();
  }

  bind() {
    const $ = (s) => this.querySelector(s);
    $(".scrim").onclick = $("#cancel").onclick = () => { this.done = false; this.close(); };
    $("#pick-files").onclick = () => $("#in-files").click();
    $("#pick-folder").onclick = () => $("#in-folder").click();
    $("#in-files").onchange = (e) => this.add([...e.target.files].map((f) => ({ file: f, rel: f.name, folder: false })));
    $("#in-folder").onchange = (e) => this.add([...e.target.files].map((f) => ({ file: f, rel: f.webkitRelativePath || f.name, folder: true })));
    const drop = $("#drop");
    drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
    drop.ondragleave = () => drop.classList.remove("over");
    drop.ondrop = (e) => { e.preventDefault(); e.stopPropagation(); drop.classList.remove("over"); this.addFromDataTransfer(e.dataTransfer); };
    api("/facets", { quiet: true }).then((f) => {
      const dl = $("#up-cats");
      if (dl) dl.innerHTML = f.categories.filter((c) => c.name !== "Uncategorized").map((c) => `<option value="${esc(c.name)}">`).join("");
    }).catch(() => {});
    $("#go").onclick = () => this.start();
  }

  async start() {
    const $ = (s) => this.querySelector(s);
    const category = $("#cat").value.trim();
    const useFolders = $("#fold").checked;
    const overwrite = $("#ovw").checked;
    const items = this.queue.slice();
    this.busy = true;
    $("#go").disabled = true; $("#cancel").disabled = true;
    const total = items.length;
    const tally = { created: 0, duplicate: 0, updated: 0, warning: 0, skipped: 0, error: 0 };
    const issues = [];
    let sent = 0;
    const status = $("#status");
    const fmtVal = (v) => (Array.isArray(v) ? v.join(", ") : v ?? "") || "∅";
    const paint = (finished = false) => {
      status.innerHTML = `<div class="progress${finished ? " done" : ""}"><i style="width:${(sent / total) * 100}%"></i></div>
        <div class="muted small">${sent} / ${total} processed${finished ? " · done" : ""}</div>
        <div class="counts"><span class="pill in">${tally.created} added</span><span class="pill in">${tally.updated} metadata updated</span><span class="pill">${tally.duplicate} duplicates</span><span class="pill">${tally.skipped} skipped</span><span class="pill side">${tally.warning} warnings</span><span class="pill side">${tally.error} errors</span></div>
        ${issues.length ? `<div class="log">${issues.slice(0, 300).map((i) => `<div class="${i.status}"><em>${i.status}</em><span>${esc(i.filename)}${i.title ? " → “" + esc(i.title) + "”" : ""}${i.detail ? " — " + esc(i.detail) : ""}${
          i.status === "warning" && i.diffs ? `<ul class="diffs">${i.diffs.map((d) => `<li><b>${esc(d.field)}</b>: <s>${esc(fmtVal(d.current))}</s> → ${esc(fmtVal(d.imported))}</li>`).join("")}</ul>` : ""}</span></div>`).join("")}</div>` : ""}`;
    };
    // Batches bounded by count and size. Books go first; metadata JSON files only after every book is in.
    const makeBatches = (list) => {
      const out = []; let cur = [], curSize = 0;
      for (const it of list) {
        if (cur.length && (cur.length >= 12 || curSize + it.file.size > 80 * 1024 * 1024)) { out.push(cur); cur = []; curSize = 0; }
        cur.push(it); curSize += it.file.size;
      }
      if (cur.length) out.push(cur);
      return out;
    };
    const runPhase = async (batches, workers) => {
      let next = 0;
      const worker = async () => {
        while (next < batches.length) {
          const batch = batches[next++];
          const fd = new FormData();
          const folderBatch = batch.some((b) => b.folder || b.rel.includes("/"));
          for (const it of batch) { fd.append("files", it.file, it.file.name); if (folderBatch) fd.append("relative_paths", it.rel); }
          if (category) fd.append("category", category);
          if (folderBatch) fd.append("category_from_folders", useFolders);
          fd.append("overwrite_json", overwrite);
          try {
            const rep = await api(folderBatch ? "/books/upload-folder" : "/books/upload", { method: "POST", body: fd, quiet: true });
            for (const r of rep.results) { tally[r.status] = (tally[r.status] || 0) + 1; if (r.status !== "created") issues.push(r); }
          } catch (e) {
            tally.error += batch.length;
            issues.push({ status: "error", filename: `${batch.length} files`, detail: e.message });
          }
          sent += batch.length;
          paint();
        }
      };
      await Promise.all(Array.from({ length: workers }, worker));
    };
    const isJson = (it) => extOf(it.file.name) === "json";
    paint();
    await runPhase(makeBatches(items.filter((i) => !isJson(i))), 3);   // 1) books
    await runPhase(makeBatches(items.filter(isJson)), 1);               // 2) metadata JSON
    this.busy = false; this.done = true; this.queue = [];
    paint(true);  // stops the bar's shimmer animation
    $("#cancel").disabled = false; $("#cancel").textContent = "Close";
    $("#cancel").focus();  // Enter / Space now closes the dialog
    toast(`${tally.created} added · ${tally.updated} metadata updated${tally.warning ? " · " + tally.warning + " warnings" : ""}`, tally.error || tally.warning ? "err" : "ok");
    emit("library-changed");
  }
}
customElements.define("mx-upload", MxUpload);

// ------------------------------------------------------------------ <mx-export>
class MxExport extends HTMLElement {
  async open() {
    this.classList.add("open");
    const [stats, f] = await Promise.all([api("/stats"), api("/facets")]);
    this.innerHTML = `<div class="scrim" style="position:absolute;inset:0;background:rgba(2,2,10,.6);backdrop-filter:blur(4px)"></div>
      <div class="dialog glass" role="dialog" aria-label="Export library">
        <h2>Export library</h2>
        <div class="muted small">${stats.books} books · ${fmtBytes(stats.bytes)} · downloaded as a single ZIP</div>
        <div class="radios">
          <label class="radio"><input type="radio" name="g" value="category" checked><b>By category</b><span class="small muted">${stats.categories} folders</span></label>
          <label class="radio"><input type="radio" name="g" value="author"><b>By author</b><span class="small muted">${stats.authors} folders</span></label>
        </div>
        <div class="opts">
          <label class="field"><span>Only this format</span><select class="in" id="fmt"><option value="">All formats</option>${f.formats.map((x) => `<option value="${esc(x.name)}">${esc(x.name)} (${x.count})</option>`).join("")}</select></label>
          <label class="check"><input type="checkbox" id="meta" checked><span>Include metadata sidecars (*-info.json)</span></label>
        </div>
        <div class="dialog-actions"><button class="btn" id="cancel">Cancel</button><button class="btn primary" id="go">${icon("download")}Download ZIP</button></div>
      </div>`;
    const $ = (s) => this.querySelector(s);
    $(".scrim").onclick = $("#cancel").onclick = () => this.close();
    $("#go").onclick = () => {
      const p = new URLSearchParams({ group_by: this.querySelector("input[name=g]:checked").value, include_metadata: $("#meta").checked });
      if ($("#fmt").value) p.set("format", $("#fmt").value);
      if (!stats.books) return toast("The library is empty", "err");
      window.location.href = "/api/export?" + p;
      this.close();
    };
  }
  close() { this.classList.remove("open"); this.innerHTML = ""; }
}
customElements.define("mx-export", MxExport);

// ------------------------------------------------------------------ <mx-settings>
class MxSettings extends HTMLElement {
  open() { this.classList.add("open"); this.render(); }
  close() { this.classList.remove("open"); this.innerHTML = ""; }
  render() {
    const theme = getPref("theme", "vanilla"), bw = Math.max(0, Math.min(16, Number(getPref("border", "6")) || 0));
    const font = getPref("font", "inter"), fs = clampFs(getPref("fs", "100")), group = getPref("series", "on") !== "off";
    this.innerHTML = `<div class="scrim" style="position:absolute;inset:0;background:rgba(2,2,10,.6);backdrop-filter:blur(4px)"></div>
      <div class="dialog glass" role="dialog" aria-label="Settings">
        <h2>Settings</h2>
        <div class="muted small">Saved in this browser.</div>

        <div class="set-h">Theme</div>
        <div class="theme-grid">${Object.entries(THEMES).map(([k, [name, bg]]) =>
          `<button class="theme-opt" data-t="${k}" aria-pressed="${k === theme}"><i style="background:${bg}"></i>${name}</button>`).join("")}</div>

        <div class="set-h">Typography</div>
        <div class="form">
          <label class="field"><span>Font</span><select class="in" id="font">${Object.entries(FONTS).map(([k, [name, stack]]) =>
            `<option value="${k}" ${k === font ? "selected" : ""} style="font-family:${stack}">${name}</option>`).join("")}</select></label>
          <label class="field"><span>Text size · <b id="fs-val">${fs}%</b></span><input type="range" id="fs" min="80" max="130" step="5" value="${fs}" style="accent-color:var(--a1);margin-top:8px" aria-label="Text size"></label>
        </div>
        <div class="preview"><b>The quick brown fox</b><span class="muted">Jumps over the lazy dog — 0123456789</span></div>

        <div class="set-h">Covers</div>
        <div class="row-set" style="display:block;border-top:0;padding-top:0"><div style="display:flex;justify-content:space-between"><div><b>Cover border</b><div class="small muted">White frame around every cover. 0 = no frame, cover stretched to fit (FitXY).</div></div><b id="bw-val">${bw}px</b></div>
          <input type="range" id="bw" min="0" max="16" step="1" value="${bw}" style="width:100%;margin-top:12px;accent-color:var(--a1)" aria-label="Cover border thickness"></div>

        <div class="set-h">Library</div>
        <div class="row-set" style="border-top:0;padding-top:0"><div><b>Group series</b><div class="small muted">Show each series as one stacked tile; click it to open the series. Off lists every book on its own.</div></div>
          <button class="switch" role="switch" id="sw-series" aria-checked="${group}" aria-label="Group series"></button></div>

        <div class="dialog-actions"><button class="btn primary" id="done">Done</button></div>
      </div>`;
    const $ = (s) => this.querySelector(s);
    $(".scrim").onclick = $("#done").onclick = () => this.close();
    this.querySelectorAll("[data-t]").forEach((b) => (b.onclick = () => { setPref("theme", b.dataset.t); this.render(); }));
    $("#font").onchange = (e) => setPref("font", e.target.value);
    $("#fs").oninput = (e) => { setPref("fs", e.target.value); $("#fs-val").textContent = e.target.value + "%"; };
    $("#bw").oninput = (e) => { setPref("border", e.target.value); $("#bw-val").textContent = e.target.value + "px"; };
    $("#sw-series").onclick = () => { setPref("series", group ? "off" : "on"); this.render(); };
  }
}
customElements.define("mx-settings", MxSettings);
