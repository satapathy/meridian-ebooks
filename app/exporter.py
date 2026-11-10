"""Whole-library ZIP export, organised by category or author."""
import uuid
import zipfile
from pathlib import Path

from .config import settings
from .db import db
from .service import split_authors
from .storage import book_dir, sanitize_component, sidecar_name, user_cover_name

_STORED = {"epub", "pdf", "docx", "cbz", "azw3", "mobi", "odt"}  # already compressed


def _folder_for(row, group_by: str) -> str:
    if group_by == "author":
        authors = split_authors(row["author"])
        # a name made only of punctuation sanitises to "" - never produce a nameless (root-level) folder
        return (sanitize_component(authors[0], 100) if authors else "") or "Unknown Author"
    return sanitize_component(row["category"], 100) or "Uncategorized"


def build_export(group_by: str, *, ids: list[str] | None = None, fmt: str | None = None,
                 include_metadata: bool = True) -> tuple[Path, int]:
    """Create the zip in the temp dir. Returns (path, number_of_books)."""
    sql, params = "SELECT * FROM books", []
    wheres = []
    if ids:
        wheres.append(f"id IN ({','.join('?' * len(ids))})")
        params += ids
    if fmt:
        wheres.append("format = ?")
        params.append(fmt.lower().lstrip("."))
    if wheres:
        sql += " WHERE " + " AND ".join(wheres)
    with db() as conn:
        rows = conn.execute(sql + " ORDER BY author COLLATE NOCASE, title COLLATE NOCASE", params).fetchall()

    out = settings.tmp_dir / f"export-{uuid.uuid4().hex}.zip"
    used: set[str] = set()
    count = 0
    with zipfile.ZipFile(out, "w", allowZip64=True) as z:
        for row in rows:
            src = book_dir(row["id"]) / row["filename"]
            if not src.exists():
                continue
            folder = _folder_for(row, group_by)
            arc, n = f"{folder}/{row['filename']}", 1
            while arc.lower() in used:  # same file name in the same folder
                n += 1
                stem, dot, ext = row["filename"].rpartition(".")
                arc = f"{folder}/{stem} ({n}).{ext}" if dot else f"{folder}/{row['filename']} ({n})"
            used.add(arc.lower())
            comp = zipfile.ZIP_STORED if row["format"] in _STORED else zipfile.ZIP_DEFLATED
            z.write(src, arc, compress_type=comp)
            count += 1
            if include_metadata:
                sc = book_dir(row["id"]) / sidecar_name(row["filename"])
                if sc.exists():
                    z.write(sc, arc.rpartition(".")[0] + "-info.json", compress_type=zipfile.ZIP_DEFLATED)
                uc = book_dir(row["id"]) / user_cover_name(row["filename"])
                if uc.exists():
                    z.write(uc, arc.rpartition(".")[0] + "-cover.jpg", compress_type=zipfile.ZIP_STORED)
    return out, count
