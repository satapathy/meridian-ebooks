"""Library business logic: ingest, query, edit, rename, delete, cleanup."""
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import metadata as md
from . import textops
from .config import SUPPORTED_EXTENSIONS, settings
from .db import db
from .search import parse_query
from .storage import (
    book_dir, folder_size, prune_empty_parents, remove_book_dir, safe_filename, sanitize_component,
    sidecar_name, user_cover_name, uuid_to_rel_dir,
)

log = logging.getLogger("meridian.service")
_write_lock = threading.RLock()  # serialises on-disk metadata rewrites / renames


class BookNotFound(Exception):
    pass


class Conflict(Exception):
    pass


class BadRequest(Exception):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def file_md5(path: Path) -> str:
    h = hashlib.md5(usedforsecurity=False)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def ext_of(filename: str) -> str:
    return os.path.splitext(filename)[1].lower().lstrip(".")


def is_supported(filename: str) -> bool:
    return ext_of(filename) in SUPPORTED_EXTENSIONS


def _nonempty(v) -> bool:
    return v not in (None, "", [])


def split_authors(author: str) -> list[str]:
    return [a.strip() for a in (author or "").split(";") if a.strip()]


# --------------------------------------------------------------------------- serialisation
def to_book(row: sqlite3.Row) -> dict:
    d = dict(row)
    d.pop("rn", None)  # helper column of the grouped query
    d["tags"] = json.loads(d["tags"] or "[]")
    d["authors"] = split_authors(d["author"])
    d["has_cover"] = bool(d["has_cover"])
    embedded = set(json.loads(d.pop("embedded") or "[]"))
    sidecar_fields = [f for f in md.FIELDS if _nonempty(d.get(f)) and f not in embedded]
    sc = book_dir(d["id"]) / sidecar_name(d["filename"])
    d["storage"] = {
        "embedded": sorted(embedded),
        "sidecar": sorted(sidecar_fields),
        "sidecar_file": sc.name if sc.exists() else None,
    }
    d["cover_source"] = ("user" if (book_dir(d["id"]) / user_cover_name(d["filename"])).exists()
                         else "embedded" if d["has_cover"] else None)
    d["path"] = f"{d['rel_dir']}/{d['filename']}"
    d.pop("current_md5", None)
    d.pop("rel_dir", None)
    return d


def _get_row(conn: sqlite3.Connection, book_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
    if not row:
        raise BookNotFound(book_id)
    return row


def get_book(book_id: str) -> dict:
    with db() as conn:
        return to_book(_get_row(conn, book_id))


def book_file(book_id: str) -> Path:
    with db() as conn:
        row = _get_row(conn, book_id)
    return book_dir(book_id) / row["filename"]


def cover_file(book_id: str) -> Path | None:
    """The cover to display: a user-uploaded one wins over the one extracted from the book."""
    with db() as conn:
        row = conn.execute("SELECT filename FROM books WHERE id=?", (book_id,)).fetchone()
    if not row:
        return None
    for p in (book_dir(book_id) / user_cover_name(row["filename"]), book_dir(book_id) / "cover.jpg"):
        if p.exists():
            return p
    return None


_color_cache: "dict[tuple, str | None]" = {}


def dominant_color(image_path: Path) -> str | None:
    """The cover's predominant colour as '#rrggbb'. Pixels are bucketed (4 bits per channel) and weighted towards
    saturated ones, so a white page or a black border around a cover does not win over the artwork."""
    try:
        from PIL import Image

        with Image.open(image_path) as im:
            im.draft("RGB", (96, 96))
            data = im.convert("RGB").resize((40, 40)).tobytes()
    except Exception:
        return None
    buckets: dict[tuple, list] = {}          # key -> [weight, pixels, r sum, g sum, b sum]
    for r, g, b in zip(data[0::3], data[1::3], data[2::3]):
        hi, lo = max(r, g, b), min(r, g, b)
        if (hi > 238 and lo > 225) or hi < 18:       # paper white / pure black
            continue
        e = buckets.setdefault((r >> 4, g >> 4, b >> 4), [0.0, 0, 0, 0, 0])
        e[0] += 1 + 3 * (hi - lo) / hi
        e[1] += 1; e[2] += r; e[3] += g; e[4] += b
    if not buckets:
        return None

    def near(a, b):      # neighbouring buckets count as one colour, so a smooth gradient is not split into many
        return all(abs(a[i] - b[i]) <= 1 for i in range(3))

    best = max(buckets, key=lambda k: sum(buckets[n][0] for n in buckets if near(k, n)))
    grp = [buckets[n] for n in buckets if near(best, n)]
    count = sum(e[1] for e in grp)
    r, g, b = (round(sum(e[i] for e in grp) / count) for i in (2, 3, 4))
    return f"#{r:02x}{g:02x}{b:02x}"


def cover_colors(ids: list[str]) -> dict[str, str | None]:
    """Predominant cover colour per book id (None when the book has no cover). Cached until the cover file changes."""
    out: dict[str, str | None] = {}
    for bid in dict.fromkeys(ids):
        p = cover_file(bid)
        if not p:
            out[bid] = None
            continue
        key = (str(p), p.stat().st_mtime_ns)
        if key not in _color_cache:
            if len(_color_cache) > 5000:
                _color_cache.clear()
            _color_cache[key] = dominant_color(p)
        out[bid] = _color_cache[key]
    return out


# --------------------------------------------------------------------------- sidecar + persistence
def _write_sidecar(book: dict, embedded: set[str]) -> None:
    d = book_dir(book["id"])
    path = d / sidecar_name(book["filename"])
    extras = {f: book[f] for f in md.FIELDS if _nonempty(book.get(f)) and f not in embedded}
    if not extras and embedded:
        if path.exists():
            path.unlink()
        return
    payload = {
        "schema": "meridian-book-info/1",
        "id": book["id"],
        "file": book["filename"],
        "storage": "embedded+sidecar" if embedded else "sidecar",
        "embedded_fields": sorted(embedded),
        "metadata": extras,
        "updated_at": now(),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _persist(conn: sqlite3.Connection, book_id: str) -> None:
    """Push the DB metadata into the file (when the format allows) and the sidecar."""
    row = _get_row(conn, book_id)
    book = dict(row)
    book["tags"] = json.loads(book["tags"] or "[]")
    path = book_dir(book_id) / book["filename"]
    embedded = md.write_metadata(path, book["format"], book) if book["format"] in md.EMBEDDABLE else set()
    _write_sidecar(book, embedded)
    conn.execute(
        "UPDATE books SET embedded=?, size=?, current_md5=?, updated_at=? WHERE id=?",
        (json.dumps(sorted(embedded)), path.stat().st_size, file_md5(path), now(), book_id),
    )


# --------------------------------------------------------------------------- ingest
def ingest(tmp_path: Path, original_name: str, *, source_path: str | None = None, category: str | None = None) -> dict:
    """Move an uploaded temp file into the library. Returns a result dict:
    status = created | duplicate. Raises on unexpected errors. Always consumes tmp_path."""
    ext = ext_of(original_name)
    try:
        digest = file_md5(tmp_path)
        with db() as conn:
            dup = conn.execute(
                "SELECT id, title FROM books WHERE md5=? OR current_md5=?", (digest, digest)
            ).fetchone()
        if dup:
            return {"status": "duplicate", "filename": original_name,
                    "book_id": dup["id"], "detail": f"Same content as '{dup['title']}'"}

        # Hold the write lock until the row exists, so cleanup() can't mistake the half-built folder for an orphan.
        with _write_lock:
            book_id = uuid.uuid4().hex
            bdir = book_dir(book_id)
            bdir.mkdir(parents=True, exist_ok=False)
            filename = safe_filename(original_name, ext)
            dest = bdir / filename
            try:
                shutil.move(str(tmp_path), dest)
                meta, cover = md.read_metadata(dest, ext)
                title = meta.get("title") or md.title_from_filename(filename)
                tags = meta.get("tags") or []
                category = (category or meta.get("category") or "").strip()
                has_cover = 0
                if cover:
                    jpeg = md.make_cover_jpeg(cover)
                    if jpeg:
                        (bdir / "cover.jpg").write_bytes(jpeg)
                        has_cover = 1
                embedded = sorted(f for f in md.EMBEDDABLE.get(ext, set()) if _nonempty(meta.get(f)))
                ts = now()
                row = {
                    "id": book_id, "title": title, "subtitle": "", "author": "; ".join(split_authors(meta.get("author", ""))),
                    "publisher": meta.get("publisher", ""), "description": meta.get("description", ""),
                    "language": meta.get("language", ""), "published": meta.get("published", ""),
                    "isbn": meta.get("isbn", ""), "tags": json.dumps(tags, ensure_ascii=False),
                    "category": category, "subcategory": "", "series": meta.get("series", ""),
                    "series_index": meta.get("series_index"), "rating": None,
                    "format": ext, "filename": filename, "rel_dir": uuid_to_rel_dir(book_id),
                    "size": dest.stat().st_size, "md5": digest, "current_md5": digest,
                    "has_cover": has_cover, "embedded": json.dumps(embedded),
                    "source_path": source_path, "added_at": ts, "updated_at": ts,
                }
                cols = ",".join(row)
                with db() as conn:
                    conn.execute(f"INSERT INTO books ({cols}) VALUES ({','.join('?' * len(row))})", list(row.values()))
                book = dict(row, tags=tags)
                _write_sidecar(book, set(embedded))
            except sqlite3.IntegrityError:  # lost a race with an identical concurrent upload
                remove_book_dir(book_id)
                return {"status": "duplicate", "filename": original_name, "detail": "Same content already uploaded"}
            except Exception:
                remove_book_dir(book_id)
                raise
            return {"status": "created", "filename": original_name, "book_id": book_id, "title": title}
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


# --------------------------------------------------------------------------- edit
def _text(v) -> str:
    """Scalar JSON values (numbers, booleans) as text; None -> ''."""
    return "" if v is None else str(v).strip()


def _normalise_patch(patch: dict) -> dict:
    out: dict = {}
    for k, v in patch.items():
        if k == "author":
            if isinstance(v, list):
                v = "; ".join(_text(a) for a in v)
            out[k] = "; ".join(split_authors(_text(v)))  # canonical "A; B" separator
        elif k == "tags":
            if isinstance(v, str):
                v = [t for t in v.replace(";", ",").split(",")]
            seen, tags = set(), []
            for t in v or []:
                t = _text(t)
                if t and t.lower() not in seen:
                    seen.add(t.lower())
                    tags.append(t)
            out[k] = json.dumps(tags, ensure_ascii=False)
        elif k == "title":
            v = _text(v)
            if not v:
                raise BadRequest("Title cannot be empty")
            out[k] = v
        elif k == "rating":
            if v is not None and not (0 <= int(v) <= 5):
                raise BadRequest("Rating must be between 0 and 5")
            out[k] = int(v) if v else None
        elif k == "series_index":
            out[k] = float(v) if v is not None else None
        elif k in md.FIELDS:
            out[k] = _text(v)
    return out


def update_book(book_id: str, patch: dict) -> dict:
    changes = _normalise_patch(patch)
    with _write_lock, db() as conn:
        _get_row(conn, book_id)
        if changes:
            sets = ",".join(f"{k}=?" for k in changes)
            conn.execute(f"UPDATE books SET {sets} WHERE id=?", [*changes.values(), book_id])
        _persist(conn, book_id)
        return to_book(_get_row(conn, book_id))


def bulk_update(ids: list[str], patch: dict, tags_mode: str = "replace") -> dict:
    """Apply the same field changes to many books. One bad id never blocks the rest.
    tags_mode "add" appends the given tags to each book's own tags instead of replacing them."""
    if not _normalise_patch(patch):          # validates once, up front (e.g. rating range)
        raise BadRequest("No fields to update")
    books, failed = [], []
    for bid in dict.fromkeys(ids):
        try:
            p = dict(patch)
            if "tags" in p and tags_mode == "add":
                add = json.loads(_normalise_patch({"tags": p["tags"]})["tags"])
                p["tags"] = [*get_book(bid)["tags"], *add]
            books.append(update_book(bid, p))
        except BookNotFound:
            failed.append({"id": bid, "error": "Book not found"})
        except BadRequest as exc:
            failed.append({"id": bid, "error": str(exc)})
    return {"updated": len(books), "failed": failed, "books": books}


def bulk_transform(ids: list[str], field: str, operation: str, *, find: str = "", replace_with: str = "",
                   case_sensitive: bool = False, whole_words: bool = True) -> dict:
    """Run one text operation (lowercase, titlecase, find/replace...) on one field of many books.
    Books whose value would not change are left untouched; tags are transformed one by one."""
    if operation == "replace" and not find:
        raise BadRequest("Say which word to replace")
    opts = dict(find=find, replacement=replace_with, case_sensitive=case_sensitive, whole_words=whole_words)
    books, failed, unchanged = [], [], 0
    for bid in dict.fromkeys(ids):
        try:
            current = get_book(bid)[field]
            new = [textops.apply(operation, t, **opts) for t in current] if isinstance(current, list) else textops.apply(operation, current or "", **opts)
            if new == current:
                unchanged += 1
                continue
            books.append(update_book(bid, {field: new}))
        except BookNotFound:
            failed.append({"id": bid, "error": "Book not found"})
        except BadRequest as exc:
            failed.append({"id": bid, "error": str(exc)})
    return {"updated": len(books), "unchanged": unchanged, "failed": failed, "books": books}


def rename_file(book_id: str, new_name: str) -> dict:
    """Rename the file on disk. Deliberately independent of the book title."""
    with _write_lock, db() as conn:
        row = _get_row(conn, book_id)
        old = row["filename"]
        ext = os.path.splitext(old)[1]
        name = new_name.replace("\\", "/").split("/")[-1].strip()
        if name.lower().endswith(ext.lower()):
            name = name[: -len(ext)]
        stem = sanitize_component(name, 150)
        if not stem:
            raise BadRequest("Filename cannot be empty")
        new = stem + ext
        if new == old:
            return to_book(row)
        bdir = book_dir(book_id)
        if (bdir / new).exists():
            raise Conflict(f"A file named '{new}' already exists")
        os.replace(bdir / old, bdir / new)
        old_cv, new_cv = bdir / user_cover_name(old), bdir / user_cover_name(new)
        if old_cv.exists():
            os.replace(old_cv, new_cv)
        old_sc, new_sc = bdir / sidecar_name(old), bdir / sidecar_name(new)
        if old_sc.exists():
            os.replace(old_sc, new_sc)
            try:
                payload = json.loads(new_sc.read_text(encoding="utf-8"))
                payload["file"] = new
                new_sc.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass
        conn.execute("UPDATE books SET filename=?, updated_at=? WHERE id=?", (new, now(), book_id))
        return to_book(_get_row(conn, book_id))


def replace_cover(book_id: str, data: bytes) -> dict:
    """Store a user cover next to the book/JSON. It overrides the embedded cover for display."""
    jpeg = md.make_cover_jpeg(data, max_height=1400)
    if not jpeg:
        raise BadRequest("Could not read that image")
    with _write_lock, db() as conn:
        row = _get_row(conn, book_id)
        (book_dir(book_id) / user_cover_name(row["filename"])).write_bytes(jpeg)
        conn.execute("UPDATE books SET has_cover=1, updated_at=? WHERE id=?", (now(), book_id))
        return to_book(_get_row(conn, book_id))


def remove_user_cover(book_id: str) -> dict:
    """Drop the user cover; the book falls back to its embedded cover (or a generated one)."""
    with _write_lock, db() as conn:
        row = _get_row(conn, book_id)
        (book_dir(book_id) / user_cover_name(row["filename"])).unlink(missing_ok=True)
        has = 1 if (book_dir(book_id) / "cover.jpg").exists() else 0
        conn.execute("UPDATE books SET has_cover=?, updated_at=? WHERE id=?", (has, now(), book_id))
        return to_book(_get_row(conn, book_id))


def delete_book(book_id: str) -> bool:
    """Remove the record, then its folder on disk (book file, cover, sidecar) and any folders left empty.
    Returns False if the files could not all be removed; `cleanup` (Tools) sweeps up such leftovers later."""
    with _write_lock, db() as conn:
        _get_row(conn, book_id)
        conn.execute("DELETE FROM books WHERE id=?", (book_id,))
    return remove_book_dir(book_id)


def bulk_delete(ids: list[str]) -> dict:
    """Delete many books. A missing id is reported and never stops the others."""
    deleted, failed, freed, leftover = [], [], 0, 0
    for bid in dict.fromkeys(ids):
        try:
            size = folder_size(book_dir(bid))
            if not delete_book(bid):
                leftover += 1
            deleted.append(bid)
            freed += size
        except BookNotFound:
            failed.append({"id": bid, "error": "Book not found"})
    return {"deleted": len(deleted), "deleted_ids": deleted, "failed": failed, "bytes_freed": freed, "leftover": leftover}


# --------------------------------------------------------------------------- query
SORTS = {
    "title": "title COLLATE NOCASE", "author": "author COLLATE NOCASE",
    "added": "added_at", "updated": "updated_at", "size": "size",
    "published": "published", "series": "series COLLATE NOCASE, series_index",
    "format": "format", "category": "category COLLATE NOCASE", "rating": "rating",
    "subtitle": "subtitle COLLATE NOCASE", "series_index": "series_index", "subcategory": "subcategory COLLATE NOCASE",
    "tags": "tags COLLATE NOCASE", "publisher": "publisher COLLATE NOCASE", "language": "language COLLATE NOCASE",
    "isbn": "isbn", "filename": "filename COLLATE NOCASE", "description": "description COLLATE NOCASE",
}


def _escape_like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _where(q=None, author=None, category=None, fmt=None, tag=None, series=None, subcategory=None) -> tuple[str, list]:
    parts, params = [], []
    if q:
        sql, p = parse_query(q)
        if sql:
            parts.append(sql)
            params += p
    if author:
        # tolerate rows saved as "A;B" (no space): compare on the canonical "A; B" form, as facets() does
        parts.append("('; ' || replace(replace(author, '; ', ';'), ';', '; ') || '; ') LIKE ? ESCAPE '\\'")
        params.append(f"%; {_escape_like(author)}; %")
    if category is not None and category != "":
        if category == "Uncategorized":
            parts.append("category = ''")
        else:
            parts.append("category = ? COLLATE NOCASE")
            params.append(category)
    if subcategory:
        parts.append("subcategory = ? COLLATE NOCASE")
        params.append(subcategory)
    if fmt:
        parts.append("format = ?")
        params.append(fmt.lower().lstrip("."))
    if tag:
        parts.append("tags LIKE ? ESCAPE '\\'")
        params.append("%" + _escape_like(json.dumps(tag, ensure_ascii=False)) + "%")
    if series:
        parts.append("series = ? COLLATE NOCASE")
        params.append(series)
    return (" WHERE " + " AND ".join(parts)) if parts else "", params


def list_books(*, q=None, author=None, category=None, fmt=None, tag=None, series=None, subcategory=None,
               sort="added", order="desc", limit=60, offset=0, group_series=False) -> dict:
    where, params = _where(q, author, category, fmt, tag, series, subcategory)
    col = SORTS.get(sort, SORTS["added"])
    direction = "ASC" if order.lower() == "asc" else "DESC"
    if group_series:
        return _list_grouped(where, params, col, direction, limit, offset)
    with db() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM books{where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM books{where} ORDER BY {col} {direction}, title COLLATE NOCASE ASC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        items = [to_book(r) for r in rows]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def _list_grouped(where: str, params: list, col: str, direction: str, limit: int, offset: int) -> dict:
    """Like list_books, but every series collapses into one entry: its first book (by series number)
    with `series_count` set to the size of the whole series. Books without a series are unchanged."""
    base = (
        f"WITH f AS (SELECT * FROM books{where}), "
        "r AS (SELECT f.*, CASE WHEN f.series = '' THEN 1 ELSE ROW_NUMBER() OVER ("
        "PARTITION BY lower(f.series) ORDER BY COALESCE(f.series_index, 1e9), f.title COLLATE NOCASE) END AS rn FROM f) "
    )
    with db() as conn:
        total = conn.execute(base + "SELECT COUNT(*) FROM r WHERE rn = 1", params).fetchone()[0]
        rows = conn.execute(
            base + f"SELECT * FROM r WHERE rn = 1 ORDER BY {col} {direction}, title COLLATE NOCASE ASC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        names = sorted({r["series"].lower() for r in rows if r["series"]})
        counts: dict[str, int] = {}
        if names:
            q = ",".join("?" * len(names))
            counts = {r[0]: r[1] for r in conn.execute(
                f"SELECT lower(series), COUNT(*) FROM books WHERE lower(series) IN ({q}) GROUP BY lower(series)", names)}
        items = []
        for r in rows:
            b = to_book(r)
            b["series_count"] = counts.get(r["series"].lower(), 1) if r["series"] else 1
            items.append(b)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def facets() -> dict:
    with db() as conn:
        rows = conn.execute("SELECT author, category, format, tags FROM books").fetchall()
    authors: dict[str, int] = {}
    cats: dict[str, int] = {}
    fmts: dict[str, int] = {}
    tags: dict[str, int] = {}
    for r in rows:
        for a in split_authors(r["author"]) or ["Unknown"]:
            authors[a] = authors.get(a, 0) + 1
        c = r["category"] or "Uncategorized"
        cats[c] = cats.get(c, 0) + 1
        fmts[r["format"]] = fmts.get(r["format"], 0) + 1
        for t in json.loads(r["tags"] or "[]"):
            tags[t] = tags.get(t, 0) + 1

    def pack(d: dict) -> list[dict]:
        return [{"name": k, "count": v} for k, v in sorted(d.items(), key=lambda kv: (-kv[1], kv[0].lower()))]

    return {"authors": pack(authors), "categories": pack(cats), "formats": pack(fmts), "tags": pack(tags)}


def stats() -> dict:
    with db() as conn:
        total, size = conn.execute("SELECT COUNT(*), COALESCE(SUM(size),0) FROM books").fetchone()
    f = facets()
    return {"books": total, "bytes": size, "authors": len(f["authors"]),
            "categories": len(f["categories"]), "formats": f["formats"]}


# --------------------------------------------------------------------------- duplicates / cleanup
def duplicate_groups() -> list[list[dict]]:
    """Groups of books whose content hashes collide (original or current md5)."""
    with db() as conn:
        rows = conn.execute("SELECT * FROM books ORDER BY added_at, id").fetchall()
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    by_hash: dict[str, str] = {}
    for r in rows:
        parent.setdefault(r["id"], r["id"])
        for h in {r["md5"], r["current_md5"]}:
            if h in by_hash:
                parent[find(r["id"])] = find(by_hash[h])
            else:
                by_hash[h] = r["id"]
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(find(r["id"]), []).append(to_book(r))
    return [g for g in groups.values() if len(g) > 1]


def cleanup(dry_run: bool = True) -> dict:
    """Remove duplicate books (keeping the oldest), orphan folders and rows with missing files."""
    report = {"dry_run": dry_run, "duplicates_removed": [], "orphan_folders_removed": [],
              "missing_file_rows_removed": [], "bytes_freed": 0}
    with _write_lock:
        for group in duplicate_groups():
            for dup in group[1:]:
                report["duplicates_removed"].append(
                    {"id": dup["id"], "title": dup["title"], "filename": dup["filename"], "duplicate_of": group[0]["id"]})
                report["bytes_freed"] += dup["size"]
                if not dry_run:
                    delete_book(dup["id"])

        with db() as conn:
            rows = conn.execute("SELECT id, title, filename FROM books").fetchall()
        known = set()
        for r in rows:
            known.add(r["id"])
            if not (book_dir(r["id"]) / r["filename"]).exists():
                report["missing_file_rows_removed"].append({"id": r["id"], "title": r["title"]})
                if not dry_run:
                    delete_book(r["id"])

        for leaf in settings.library_dir.glob("*/*/*/*/*/*/*/*"):
            if not leaf.is_dir():
                continue
            book_id = "".join(leaf.relative_to(settings.library_dir).parts)
            if book_id not in known:
                report["orphan_folders_removed"].append(book_id)
                report["bytes_freed"] += sum(f.stat().st_size for f in leaf.rglob("*") if f.is_file())
                if not dry_run:
                    shutil.rmtree(leaf, ignore_errors=True)
                    prune_empty_parents(leaf.parent)
    return report


# --------------------------------------------------------------------------- sidecar JSON import
def _find_books_for_sidecar(conn, payload: dict, fields: dict, name: str, rel_path: str | None) -> list:
    """Candidate books for an imported JSON: id, then title, then file-name stem."""
    json_stem = os.path.splitext(os.path.basename(name))[0]
    if json_stem.lower().endswith("-info"):
        json_stem = json_stem[:-5]
    file_stem = os.path.splitext(str(payload.get("file") or ""))[0] or json_stem
    title = str(fields.get("title") or payload.get("title") or "").strip()

    rows: list = []
    bid = payload.get("id")
    if isinstance(bid, str) and bid:
        r = conn.execute("SELECT * FROM books WHERE id=?", (bid,)).fetchone()
        rows = [r] if r else []
    if not rows and title:
        rows = conn.execute("SELECT * FROM books WHERE lower(title)=lower(?)", (title,)).fetchall()
    if not rows:
        rows = [r for r in conn.execute(
            "SELECT * FROM books WHERE lower(filename) LIKE ? ESCAPE '\\'", (_escape_like(file_stem.lower()) + ".%",)
        ) if os.path.splitext(r["filename"])[0].lower() == file_stem.lower()]
    if not rows:
        rows = conn.execute("SELECT * FROM books WHERE lower(title)=lower(?)", (json_stem,)).fetchall()

    if len(rows) > 1:  # disambiguate: same folder as the JSON, then same file-name stem
        folder = os.path.dirname(rel_path or "")
        same_dir = [r for r in rows if r["source_path"] and os.path.dirname(r["source_path"]) == folder]
        rows = same_dir or rows
    if len(rows) > 1:
        same_stem = [r for r in rows if os.path.splitext(r["filename"])[0].lower() == file_stem.lower()]
        rows = same_stem or rows
    return rows


def import_sidecar(raw: bytes, name: str, *, rel_path: str | None = None, overwrite: bool = False) -> dict:
    """Apply an uploaded metadata JSON to the book it belongs to.

    Fields the book has no value for are filled in. If the JSON would *change* an existing value the
    import is refused with a warning listing the differences, unless overwrite=True."""
    label = rel_path or name
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except Exception:
        return {"status": "error", "filename": label, "detail": "Not valid JSON"}
    if not isinstance(payload, dict):
        return {"status": "error", "filename": label, "detail": "JSON must be an object"}
    meta = payload["metadata"] if isinstance(payload.get("metadata"), dict) else payload
    fields = {k: meta[k] for k in md.FIELDS if k in meta}
    if not fields:
        return {"status": "skipped", "filename": label, "detail": "No book metadata fields in this JSON"}
    try:
        changes = _normalise_patch(fields)
    except (BadRequest, ValueError, TypeError) as exc:
        return {"status": "error", "filename": label, "detail": f"Invalid metadata: {exc}"}

    with db() as conn:
        rows = _find_books_for_sidecar(conn, payload, fields, name, rel_path)
    if not rows:
        return {"status": "skipped", "filename": label, "detail": "No book with a matching title found"}
    if len(rows) > 1:
        return {"status": "error", "filename": label,
                "detail": f"Ambiguous: {len(rows)} books match - add an \"id\" to the JSON"}
    row = rows[0]
    current = to_book(row)

    diffs = []
    for k, new in changes.items():
        old = row[k]
        if k == "tags":
            same = json.loads(old or "[]") == json.loads(new)
        else:
            same = (old if old is not None else "") == (new if new is not None else "")
        if not same:
            diffs.append({"field": k, "current": current[k],
                          "imported": json.loads(new) if k == "tags" else new})
    base = {"filename": label, "book_id": row["id"], "title": row["title"], "diffs": diffs}
    if not diffs:
        return {**base, "status": "skipped", "detail": "Identical to the book's existing metadata"}
    # A category that was only inferred from the upload folder name is not a user-set value.
    parts = [p for p in (row["source_path"] or "").replace("\\", "/").split("/") if p]
    auto_category = parts[-2] if len(parts) >= 2 else None
    conflicts = [d["field"] for d in diffs
                 if _nonempty(d["current"]) and not (d["field"] == "category" and d["current"] == auto_category)]
    if conflicts and not overwrite:
        return {**base, "status": "warning",
                "detail": f"Metadata already exists and differs ({', '.join(conflicts)}) - not applied"}
    update_book(row["id"], {d["field"]: fields[d["field"]] for d in diffs})
    return {**base, "status": "updated",
            "detail": f"Applied {len(diffs)} field(s)" + (" (overwrote existing)" if conflicts else "")}
