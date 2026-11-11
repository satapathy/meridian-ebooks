"""On-disk layout: the 32-char UUID is split into 4-char folders.

    12345678abcdef0123456789abcdef01 -> library/1234/5678/abcd/ef01/2345/6789/abcd/ef01/<book-name>.<ext>
"""
import os
import re
import shutil
from pathlib import Path

from .config import settings

_ILLEGAL = re.compile(r'[<>:"/\|?*\x00-\x1f]')


def uuid_to_rel_dir(book_id: str) -> str:
    return "/".join(book_id[i : i + 4] for i in range(0, len(book_id), 4))


def book_dir(book_id: str) -> Path:
    return settings.library_dir / uuid_to_rel_dir(book_id)


def sanitize_component(name: str, max_len: int = 120) -> str:
    name = _ILLEGAL.sub("_", name or "")
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:max_len].strip(" .")


def safe_filename(original: str, fallback_ext: str = "") -> str:
    """Sanitised `name.ext` from an arbitrary (possibly path-like) client filename."""
    base = original.replace("\\", "/").split("/")[-1]
    stem, ext = os.path.splitext(base)
    stem = sanitize_component(stem, 150) or "book"
    ext = ext.lower() or (("." + fallback_ext) if fallback_ext else "")
    return stem + ext


def sidecar_name(filename: str) -> str:
    return f"{os.path.splitext(filename)[0]}-info.json"


def user_cover_name(filename: str) -> str:
    """Cover chosen by the user; lives next to the book and its -info.json."""
    return f"{os.path.splitext(filename)[0]}-cover.jpg"


def prune_empty_parents(path: Path) -> None:
    """Remove now-empty ancestor folders up to (not including) the library root."""
    root = settings.library_dir
    cur = path
    while cur != root and root in cur.parents:
        try:
            cur.rmdir()
        except OSError:
            break
        cur = cur.parent


def folder_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) if path.exists() else 0


def remove_book_dir(book_id: str) -> bool:
    """Delete the book's folder (book file, cover, sidecar...) and any parent folders that are now empty.
    Returns False if something could not be removed (e.g. a file locked by another program)."""
    d = book_dir(book_id)
    shutil.rmtree(d, ignore_errors=True)
    prune_empty_parents(d.parent)
    return not d.exists()
