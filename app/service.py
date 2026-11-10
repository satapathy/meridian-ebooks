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
from .config import SUPPORTED_EXTENSIONS, settings
from .db import db
from .search import parse_query
from .storage import (
    book_dir, prune_empty_parents, remove_book_dir, safe_filename, sanitize_component,
    sidecar_name, uuid_to_rel_dir,
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
    p = book_dir(book_id) / "cover.jpg"
    return p if p.exists() else None


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
                "id": book_id, "title": title, "author": meta.get("author", ""),
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
def _normalise_patch(patch: dict) -> dict:
    out: dict = {}
    for k, v in patch.items():
        if k == "author":
            if isinstance(v, list):
                v = "; ".join(a.strip() for a in v if a and a.strip())
            out[k] = (v or "").strip()
        elif k == "tags":
            if isinstance(v, str):
                v = [t for t in v.replace(";", ",").split(",")]
            seen, tags = set(), []
            for t in v or []:
                t = t.strip()
                if t and t.lower() not in seen:
                    seen.add(t.lower())
                    tags.append(t)
            out[k] = json.dumps(tags, ensure_ascii=False)
        elif k == "title":
            v = (v or "").strip()
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
            out[k] = (v or "").strip()
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
    jpeg = md.make_cover_jpeg(data)
    if not jpeg:
        raise BadRequest("Could not read that image")
    with _write_lock, db() as conn:
        _get_row(conn, book_id)
        (book_dir(book_id) / "cover.jpg").write_bytes(jpeg)
        conn.execute("UPDATE books SET has_cover=1, updated_at=? WHERE id=?", (now(), book_id))
        return to_book(_get_row(conn, book_id))


def delete_book(book_id: str) -> None:
    with _write_lock, db() as conn:
        _get_row(conn, book_id)
        conn.execute("DELETE FROM books WHERE id=?", (book_id,))
    remove_book_dir(book_id)


# --------------------------------------------------------------------------- query
SORTS = {
    "title": "title COLLATE NOCASE", "author": "author COLLATE NOCASE",
    "added": "added_at", "updated": "updated_at", "size": "size",
    "published": "published", "series": "series COLLATE NOCASE, series_index",
    "format": "format", "category": "category COLLATE NOCASE", "rating": "rating",
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
        parts.append("('; ' || author || '; ') LIKE ? ESCAPE '\\'")
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
               sort="added", order="desc", limit=60, offset=0) -> dict:
    where, params = _where(q, author, category, fmt, tag, series, subcategory)
    col = SORTS.get(sort, SORTS["added"])
    direction = "ASC" if order.lower() == "asc" else "DESC"
    with db() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM books{where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM books{where} ORDER BY {col} {direction}, title COLLATE NOCASE ASC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        items = [to_book(r) for r in rows]
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
