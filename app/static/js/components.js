// Web components (light DOM, themed by app.css).
import { api, esc, icon, toast, coverHTML, fmtBytes, emit, THEMES, FONTS, clampFs, getPref, setPref,
  progressHTML, setProgress, runBatches, batchMessage, webSearchUrl } from "./api.js";

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
          <div class="poster">${coverHTML(b, true)}<span class="fmt">${esc(b.format)}</span></div>
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
              <button class="btn" data-act="web-search" title="Opens a web search in a new tab for this book's title, author and ISBN as shown in the form below. Nothing is sent until you click.">${icon("search")}Web search</button>
              <button class="btn" data-act="cover">${icon("image")}${b.cover_source === "user" ? "Replace cover" : "Upload cover"}</button>
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
            <div class="full" id="save-prog" hidden><div class="progress indet" role="progressbar" aria-label="Saving metadata"><i></i></div><div class="small muted">Saving…</div></div>
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
      const prog = this.querySelector("#save-prog"); prog.hidden = false;
      try {
        this.book = await api("/books/" + b.id, { method: "PATCH", json: body });
        const s = this.book.storage;
        toast(`Saved · ${s.embedded.length ? "written into the file" : "stored in sidecar"}${s.embedded.length && s.sidecar.length ? " + sidecar" : ""}`);
        emit("book-updated", this.book);
        // grouped grid: a new/changed series (or number) changes which tiles exist, so reload the list
        if (this.book.series !== b.series || this.book.series_index !== b.series_index) emit("library-changed");
        this.close();
      } catch {} finally { btn.disabled = false; prog.hidden = true; }
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
    this.querySelector('[data-act="web-search"]').onclick = () => {      // uses the form as it is now, including unsaved edits
      const f = Object.fromEntries([...this.querySelectorAll("#mform [name]")].map((e) => [e.name, e.value]));
      window.open(webSearchUrl(f), "_blank", "noopener,noreferrer");
    };
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
    this.querySelector('[data-act="delete"]').onclick = async () => {
      const ok = await document.getElementById("confirm").ask({
        title: "Delete this book?", confirm: "Delete book",
        body: `<p><b>${esc(b.title)}</b>${b.author ? ` <span class="muted">by ${esc(b.author)}</span>` : ""}<br><span class="muted small">${esc(b.filename)} · ${fmtBytes(b.size)}</span></p>
          <p>This <b>permanently</b> removes the book from the library <b>and deletes its files from disk</b>: the book itself, its cover and its metadata file. Folders left empty are removed too.</p>
          <p><b>This cannot be undone.</b> Export or download the book first if you may want it back.</p>` });
      if (!ok) return;
      try {
        await api("/books/" + b.id, { method: "DELETE" });
        this.close(); toast("Book deleted"); emit("library-changed");
      } catch {}
    };
  }

  /** Re-render (after a cover change) without losing metadata the user has typed but not saved yet. */
  renderKeepingEdits() {
    const snap = [...this.querySelectorAll("#mform [name]")].map((e) => [e.name, e.value]);
    this.render();
    for (const [name, value] of snap) {
      const el = this.querySelector(`#mform [name="${name}"]`);
      if (el && el.value !== value) { el.value = value; el.classList.add("filled"); }
    }
  }

}
customElements.define("mx-drawer", MxDrawer);

// ------------------------------------------------------------------ <mx-confirm>
/** A themed "are you sure" dialog: `await $("confirm").ask({ title, body, confirm, requireText })` -> true / false.
 *  Cancel has the focus (Enter does not delete by accident); `requireText` makes the user type a word first. */
class MxConfirm extends HTMLElement {
  ask({ title, body, confirm = "Delete", requireText = "" }) {
    this.classList.add("open");
    this.innerHTML = `<div class="scrim" style="position:absolute;inset:0;background:rgba(2,2,10,.6);backdrop-filter:blur(4px)"></div>
      <div class="dialog glass cf" role="alertdialog" aria-labelledby="cf-title" aria-describedby="cf-body">
        <h2 id="cf-title">${esc(title)}</h2>
        <div class="cf-warn" id="cf-body">${body}</div>
        ${requireText ? `<label class="field" style="margin-top:12px"><span>Type <b>${esc(requireText)}</b> to confirm</span><input class="in" id="cf-type" autocomplete="off"></label>` : ""}
        <div class="dialog-actions"><button class="btn" id="cf-no">Cancel</button><button class="btn danger solid" id="cf-yes"${requireText ? " disabled" : ""}>${icon("trash")}${esc(confirm)}</button></div>
      </div>`;
    const $ = (s) => this.querySelector(s), yes = $("#cf-yes");
    return new Promise((resolve) => {
      const done = (answer) => {
        document.removeEventListener("keydown", onKey, true);
        this.classList.remove("open"); this.innerHTML = "";
        resolve(answer);
      };
      const onKey = (e) => { if (e.key === "Escape") { e.stopImmediatePropagation(); done(false); } };
      document.addEventListener("keydown", onKey, true);
      $(".scrim").onclick = $("#cf-no").onclick = () => done(false);
      yes.onclick = () => done(true);
      if (requireText) $("#cf-type").oninput = (e) => { yes.disabled = e.target.value.trim().toLowerCase() !== requireText.toLowerCase(); };
      $("#cf-no").focus();
    });
  }
}
customElements.define("mx-confirm", MxConfirm);

// ------------------------------------------------------------------ <mx-bulkedit>
const BULK_FIELDS = [["category", "Category"], ["subcategory", "Sub-category"], ["tags", "Tags"], ["author", "Author(s)"],
  ["series", "Series"], ["publisher", "Publisher"], ["published", "Published"], ["language", "Language"], ["rating", "Rating"]];

/** Edit many books at once. Two modes: "Set fields" (the same value on every book) and "Advanced" (clean up one field with an
 *  operation such as Title Case or find/replace). Set fields saves with progress inside the dialog; Advanced closes the dialog and
 *  reports progress in the bar above the table (ctx.advanced). */
const ADV_FIELDS = [["title", "Title"], ["subtitle", "Subtitle"], ["author", "Author(s)"], ["series", "Series"], ["category", "Category"],
  ["subcategory", "Sub-category"], ["publisher", "Publisher"], ["tags", "Tags (each tag)"], ["language", "Language"], ["description", "Description"]];
// [value, label, what it does]
const ADV_OPS = [
  ["lowercase", "Lowercase", "the Lord OF the Rings  →  the lord of the rings"],
  ["uppercase", "Uppercase", "dune messiah  →  DUNE MESSIAH"],
  ["capitalize", "Capitalize (first letter only)", "the LORD of the rings  →  The lord of the rings"],
  ["titlecase", "Title Case", "the lord of the rings  →  The Lord of the Rings (small words like of/the stay lowercase)"],
  ["replace", "Replace words (empty = remove)", "Find a word or phrase and swap it for something else. Leave “Replace with” empty to remove it."],
  ["collapse_spaces", "Replace multiple spaces by one", "Too    many   spaces  →  Too many spaces"],
  ["trim", "Trim spaces at both ends", "“  padded  ”  →  “padded”"],
];

class MxBulkEdit extends HTMLElement {
  async open(ctx) {
    this.ctx = ctx;
    this.classList.add("open");
    this._esc = (e) => { if (e.key === "Escape") { e.stopImmediatePropagation(); this.close(); } };
    document.addEventListener("keydown", this._esc, true);
    let cats = [];
    try { cats = (await api("/facets", { quiet: true })).categories.filter((c) => c.name !== "Uncategorized"); } catch {}
    if (!this.classList.contains("open")) return;
    const n = ctx.ids.length;
    const input = (k) => (k === "rating"
      ? `<select class="in" data-in="rating">${[0, 1, 2, 3, 4, 5].map((i) => `<option value="${i}">${i ? "★".repeat(i) : "No rating"}</option>`).join("")}</select>`
      : `<input class="in" data-in="${k}"${k === "category" ? ' list="bk-cats"' : ""} placeholder="${k === "tags" ? "comma separated" : k === "published" ? "YYYY or YYYY-MM-DD" : k === "language" ? "en" : ""}">`);
    this.innerHTML = `<div class="scrim" style="position:absolute;inset:0;background:rgba(2,2,10,.6);backdrop-filter:blur(4px)"></div>
      <div class="dialog glass bk" role="dialog" aria-label="Edit ${n} books">
        <h2>Edit ${n} book${n === 1 ? "" : "s"}</h2>
        <div class="seg bk-tabs" role="tablist"><button class="btn sm on" role="tab" data-mode="set" aria-selected="true">Set fields</button><button class="btn sm" role="tab" data-mode="adv" aria-selected="false">Advanced</button></div>
        <div id="bk-set">
          <div class="muted small">Tick the fields to change. Unticked fields keep each book's own value. A ticked field left empty is cleared.</div>
          <div class="bk-grid">${BULK_FIELDS.map(([k, label]) => `<label class="check bk-on"><input type="checkbox" data-on="${k}"><span>${label}</span></label>
            <div class="bk-in">${input(k)}${k === "tags" ? `<div class="bk-mode small"><label class="check"><input type="radio" name="tmode" value="add" checked><span>Add to each book's tags</span></label>
              <label class="check"><input type="radio" name="tmode" value="replace"><span>Replace all tags</span></label></div>` : ""}</div>`).join("")}</div>
          <datalist id="bk-cats">${cats.map((c) => `<option value="${esc(c.name)}">`).join("")}</datalist>
          <div id="bk-prog" hidden>${progressHTML()}<div class="small muted" id="bk-prog-t"></div></div>
        </div>
        <div id="bk-adv" hidden>
          <div class="muted small">Clean up one field on all ${n} books. Books that would not change are left alone.</div>
          <div class="bk-grid">
            <span class="bk-on">Field</span><select class="in" id="ad-field">${ADV_FIELDS.map(([k, l]) => `<option value="${k}">${l}</option>`).join("")}</select>
            <span class="bk-on">Operation</span><select class="in" id="ad-op">${ADV_OPS.map(([k, l]) => `<option value="${k}">${l}</option>`).join("")}</select>
            <div id="ad-params" class="bk-params" hidden>
              <label class="field"><span>Find (word or phrase)</span><input class="in" id="ad-find" autocomplete="off"></label>
              <label class="field"><span>Replace with (leave empty to remove)</span><input class="in" id="ad-with" autocomplete="off"></label>
              <div class="bk-mode small"><label class="check"><input type="checkbox" id="ad-whole" checked><span>Whole words only</span></label>
                <label class="check"><input type="checkbox" id="ad-case"><span>Match case</span></label></div>
            </div>
          </div>
          <p class="muted small" id="ad-help"></p>
        </div>
        <div class="dialog-actions"><span class="muted small" id="bk-count" style="margin-right:auto"></span>
          <button class="btn" id="bk-cancel">Cancel</button>
          <button class="btn primary" id="bk-apply">${icon("save")}Apply to ${n}</button>
          <button class="btn primary" id="bk-run" hidden>${icon("settings")}Run on ${n}</button></div>
      </div>`;
    const $ = (s) => this.querySelector(s), apply = $("#bk-apply"), run = $("#bk-run");
    $(".scrim").onclick = $("#bk-cancel").onclick = () => this.close();

    // ---- mode switch
    let mode = "set";
    const setMode = (m) => {
      mode = m;
      this.querySelectorAll("[data-mode]").forEach((b) => { const on = b.dataset.mode === m; b.classList.toggle("on", on); b.setAttribute("aria-selected", on); });
      $("#bk-set").hidden = m !== "set"; $("#bk-adv").hidden = m !== "adv";
      apply.hidden = m !== "set"; run.hidden = m !== "adv";
      refresh();
    };
    this.querySelectorAll("[data-mode]").forEach((b) => (b.onclick = () => setMode(b.dataset.mode)));

    // ---- Set fields
    const ticked = () => BULK_FIELDS.map(([k]) => k).filter((k) => $(`[data-on="${k}"]`).checked);
    const refresh = () => {
      if (mode === "adv") {
        const op = $("#ad-op").value;
        $("#ad-params").hidden = op !== "replace";
        $("#ad-help").textContent = ADV_OPS.find(([k]) => k === op)[2];
        run.disabled = op === "replace" && !$("#ad-find").value;
        $("#bk-count").textContent = run.disabled ? "Enter the word to find" : "The dialog closes and progress is shown above the table";
        return;
      }
      const t = ticked();
      for (const [k] of BULK_FIELDS) $(`[data-in="${k}"]`).disabled = !t.includes(k);
      const clearing = t.filter((k) => k !== "rating" && !$(`[data-in="${k}"]`).value.trim());
      apply.disabled = !t.length;
      $("#bk-count").textContent = t.length ? `${t.length} field${t.length > 1 ? "s" : ""} will change${clearing.length ? ` · ${clearing.join(", ")} will be cleared` : ""}` : "Nothing ticked";
    };
    this.querySelectorAll("[data-on]").forEach((c) => (c.onchange = () => { refresh(); if (c.checked) $(`[data-in="${c.dataset.on}"]`).focus(); }));
    this.querySelectorAll("[data-in], #ad-op, #ad-find").forEach((i) => i.addEventListener("input", refresh));
    refresh();

    apply.onclick = async () => {
      const fields = {};
      for (const k of ticked()) { const v = $(`[data-in="${k}"]`).value; fields[k] = k === "rating" ? Number(v) : v.trim(); }
      const tags_mode = this.querySelector('[name="tmode"]:checked')?.value || "replace";
      const total = ctx.ids.length, bar = $("#bk-prog .progress"), text = $("#bk-prog-t"), cancel = $("#bk-cancel");
      const show = (done) => { const pct = setProgress(bar, done, total); text.textContent = `${pct}% · ${done} of ${total} books`; apply.textContent = `Saving… ${pct}%`; };
      this.running = true; this.stop = false;                       // Esc / Stop = finish the current batch, then stop
      $("#bk-prog").hidden = false; $("#bk-set .bk-grid").classList.add("busy");
      apply.disabled = true; cancel.textContent = "Stop"; show(0);
      const r = await runBatches(ctx.ids, 10, (chunk) => api("/books/bulk-update", { json: { ids: chunk, fields, tags_mode }, quiet: true }),
        { onProgress: show, shouldStop: () => this.stop });
      this.running = false;
      if (r.updated) ctx.applied(r);                                // rows for the books that did save
      if (!r.stopped) { bar.classList.add("done"); text.textContent = `100% · ${total} of ${total} books`; await new Promise((res) => setTimeout(res, 450)); }
      this.close();
      toast(batchMessage(r, total), r.failed.length || r.stopped ? "err" : undefined);
    };

    // ---- Advanced: close the dialog, the page shows the progress
    run.onclick = () => {
      const field = $("#ad-field").value, op = $("#ad-op").value;
      ctx.advanced({
        label: `${ADV_FIELDS.find(([k]) => k === field)[1]}: ${ADV_OPS.find(([k]) => k === op)[1]}`,
        body: { field, operation: op, find: $("#ad-find").value, replace_with: $("#ad-with").value,
                case_sensitive: $("#ad-case").checked, whole_words: $("#ad-whole").checked },
      });
      this.close();
    };
    $("[data-on]").focus();
  }
  close() {
    if (this.running) { this.stop = true; return; }
    this.classList.remove("open"); this.innerHTML = "";
    document.removeEventListener("keydown", this._esc, true);
  }
}
customElements.define("mx-bulkedit", MxBulkEdit);

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
  close() { if (this.busy) return; this.classList.remove("open"); this.queue = []; this.ignored = 0; this.render(); }

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
          <label class="field"><span>Series for all these books (optional - replaces a series the book already has)</span><input class="in" id="ser" list="up-series" placeholder="Pick an existing series or type a new one"></label>
          <datalist id="up-series"></datalist>
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
      const sl = $("#up-series");
      if (sl) sl.innerHTML = (f.series || []).map((x) => `<option value="${esc(x.name)}">${x.count} book${x.count === 1 ? "" : "s"}</option>`).join("");
    }).catch(() => {});
    $("#go").onclick = () => this.start();
  }

  async start() {
    const $ = (s) => this.querySelector(s);
    const category = $("#cat").value.trim(), series = $("#ser").value.trim();
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
    // One request per file, so the progress bar moves with every book. Books go first; metadata JSON files only after every book is in.
    const makeBatches = (list) => list.map((it) => [it]);
    const runPhase = async (batches, workers) => {
      let next = 0;
      const worker = async () => {
        while (next < batches.length) {
          const batch = batches[next++];
          const fd = new FormData();
          const folderBatch = batch.some((b) => b.folder || b.rel.includes("/"));
          for (const it of batch) { fd.append("files", it.file, it.file.name); if (folderBatch) fd.append("relative_paths", it.rel); }
          if (category) fd.append("category", category);
          if (series) fd.append("series", series);
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
    await runPhase(makeBatches(items.filter((i) => !isJson(i))), 4);   // 1) books
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
