"""Shared upload plumbing: temp files, zip expansion, result accounting."""
import os
import posixpath
import shutil
import uuid
import zipfile
from pathlib import Path

from . import service
from .config import settings

SUMMARY_KEYS = ("created", "duplicate", "skipped", "error")


def new_tmp() -> Path:
    return settings.tmp_dir / f"up-{uuid.uuid4().hex}"


def summarise(results: list[dict]) -> dict[str, int]:
    s = {k: 0 for k in SUMMARY_KEYS}
    for r in results:
        s[r["status"]] = s.get(r["status"], 0) + 1
    return s


def category_from_path(rel_path: str) -> str | None:
    """Folder-based category: the file's immediate parent folder."""
    parts = [p for p in rel_path.replace("\\", "/").split("/") if p]
    return parts[-2] if len(parts) >= 2 else None


def ingest_one(tmp: Path, name: str, rel_path: str | None, category: str | None) -> dict:
    """Ingest a single temp file, converting any failure into an error result."""
    try:
        if not service.is_supported(name):
            tmp.unlink(missing_ok=True)
            return {"filename": rel_path or name, "status": "skipped", "detail": "Unsupported file type"}
        res = service.ingest(tmp, name, source_path=rel_path, category=category)
        res["filename"] = rel_path or name
        return res
    except Exception as exc:  # keep one bad file from failing the whole batch
        tmp.unlink(missing_ok=True)
        return {"filename": rel_path or name, "status": "error", "detail": str(exc)[:300]}


def expand_zip(zip_tmp: Path, zip_name: str, rel_path: str | None, use_folders: bool, category: str | None) -> list[dict]:
    """Ingest every supported book inside an uploaded .zip (recursively, any depth)."""
    results: list[dict] = []
    base = rel_path or zip_name
    try:
        with zipfile.ZipFile(zip_tmp) as z:
            members = [i for i in z.infolist() if not i.is_dir()]
            if sum(i.file_size for i in members) > settings.max_archive_bytes:
                return [{"filename": base, "status": "error", "detail": "Archive too large when expanded"}]
            for info in members:
                inner = posixpath.normpath(info.filename.replace("\\", "/"))
                if inner.startswith(("..", "/")) or "/../" in inner:
                    continue
                label = f"{base}/{inner}"
                if not service.is_supported(inner):
                    results.append({"filename": label, "status": "skipped", "detail": "Unsupported file type"})
                    continue
                tmp = new_tmp()
                with z.open(info) as src, open(tmp, "wb") as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
                cat = (category_from_path(inner) if use_folders else None) or category
                results.append(ingest_one(tmp, os.path.basename(inner), label, cat))
    except zipfile.BadZipFile:
        results.append({"filename": base, "status": "error", "detail": "Not a valid zip archive"})
    finally:
        zip_tmp.unlink(missing_ok=True)
    return results
