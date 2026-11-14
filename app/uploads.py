"""Shared upload plumbing: temp files, zip expansion, ordering, result accounting."""
import os
import posixpath
import shutil
import uuid
import zipfile
from pathlib import Path

from . import service
from .config import settings

SUMMARY_KEYS = ("created", "duplicate", "updated", "warning", "skipped", "error")
MAX_JSON_BYTES = 5 * 1024 * 1024


def new_tmp() -> Path:
    return settings.tmp_dir / f"up-{uuid.uuid4().hex}"


def is_json(name: str) -> bool:
    return name.lower().endswith(".json")


def summarise(results: list[dict]) -> dict[str, int]:
    s = {k: 0 for k in SUMMARY_KEYS}
    for r in results:
        s[r["status"]] = s.get(r["status"], 0) + 1
    return s


def category_from_path(rel_path: str) -> str | None:
    """Folder-based category: the file's immediate parent folder."""
    parts = [p for p in rel_path.replace("\\", "/").split("/") if p]
    return parts[-2] if len(parts) >= 2 else None


def is_junk(path: str) -> bool:
    """macOS resource-fork leftovers (`__MACOSX/` folders, `._name` files) that zips and copies contain."""
    parts = [p for p in path.replace("\\", "/").split("/") if p]
    return any(p == "__MACOSX" or p.startswith("._") for p in parts)


def ingest_one(tmp: Path, name: str, rel_path: str | None, category: str | None, overwrite: bool = False,
               series: str | None = None) -> dict:
    """Ingest one temp file (a book, or a metadata JSON), turning any failure into an error result."""
    label = rel_path or name
    try:
        if is_junk(label) or is_junk(name):
            tmp.unlink(missing_ok=True)
            return {"filename": label, "status": "skipped", "detail": "macOS metadata file"}
        if is_json(name):
            raw = tmp.read_bytes()[: MAX_JSON_BYTES + 1]
            tmp.unlink(missing_ok=True)
            if len(raw) > MAX_JSON_BYTES:
                return {"filename": label, "status": "skipped", "detail": "JSON file too large"}
            return service.import_sidecar(raw, name, rel_path=rel_path, overwrite=overwrite)
        if not service.is_supported(name):
            tmp.unlink(missing_ok=True)
            return {"filename": label, "status": "skipped", "detail": "Unsupported file type"}
        res = service.ingest(tmp, name, source_path=rel_path, category=category)
        res["filename"] = label
        if series and res.get("status") == "created":
            # a series given at upload time replaces whatever the file carried; the number only survives for the same series
            old = service.get_book(res["book_id"])
            keep = old["series_index"] if old["series"].lower() == series.lower() else None
            service.update_book(res["book_id"], {"series": series, "series_index": keep})
        return res
    except Exception as exc:  # keep one bad file from failing the whole batch
        tmp.unlink(missing_ok=True)
        return {"filename": label, "status": "error", "detail": str(exc)[:300]}


def expand_zip(zip_tmp: Path, zip_name: str, rel_path: str | None, use_folders: bool,
               category: str | None, overwrite: bool = False, series: str | None = None) -> list[dict]:
    """Ingest everything useful inside an uploaded .zip: books first, then metadata JSONs."""
    results: list[dict] = []
    base = rel_path or zip_name
    if is_junk(base) or is_junk(zip_name):
        zip_tmp.unlink(missing_ok=True)
        return [{"filename": base, "status": "skipped", "detail": "macOS metadata file"}]
    try:
        with zipfile.ZipFile(zip_tmp) as z:
            members = [i for i in z.infolist() if not i.is_dir()]
            if sum(i.file_size for i in members) > settings.max_archive_bytes:
                return [{"filename": base, "status": "error", "detail": "Archive too large when expanded"}]
            members.sort(key=lambda i: is_json(i.filename))  # stable: books, then JSONs
            for info in members:
                inner = posixpath.normpath(info.filename.replace("\\", "/"))
                if inner.startswith(("..", "/")) or "/../" in inner:
                    continue
                label = f"{base}/{inner}"
                if not (service.is_supported(inner) or is_json(inner)):
                    results.append({"filename": label, "status": "skipped", "detail": "Unsupported file type"})
                    continue
                tmp = new_tmp()
                with z.open(info) as src, open(tmp, "wb") as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
                cat = (category_from_path(inner) if use_folders else None) or category
                results.append(ingest_one(tmp, os.path.basename(inner), label, cat, overwrite, series))
    except zipfile.BadZipFile:
        results.append({"filename": base, "status": "error", "detail": "Not a valid zip archive"})
    finally:
        zip_tmp.unlink(missing_ok=True)
    return results
