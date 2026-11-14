import shutil
from typing import Optional

from fastapi import APIRouter, File, Form, UploadFile

from .. import uploads
from ..schemas import UploadReport

router = APIRouter(prefix="/books", tags=["Upload"])


def _store(upload: UploadFile):
    tmp = uploads.new_tmp()
    with open(tmp, "wb") as out:
        shutil.copyfileobj(upload.file, out, 1024 * 1024)
    return tmp


def _process(items: list[tuple], expand: bool, use_folders: bool, overwrite: bool, series: Optional[str] = None) -> list[dict]:
    """items = (tmp, name, rel_path, category). Books and archives first, metadata JSONs last."""
    results: list[dict] = []
    for tmp, name, rel, cat in sorted(items, key=lambda i: uploads.is_json(i[1])):
        if expand and name.lower().endswith(".zip"):
            results += uploads.expand_zip(tmp, name, rel, use_folders, cat, overwrite, series)
        else:
            results.append(uploads.ingest_one(tmp, name, rel, cat, overwrite, series))
    return results


@router.post(
    "/upload", response_model=UploadReport, summary="Upload one or more ebooks (or metadata JSON files)",
    description=(
        "Accepts EPUB, PDF, DOCX, MOBI, AZW3, FB2, TXT, RTF, CBZ and more. Each book gets a server-side UUID. "
        "An MD5 of the content detects duplicates - an identical file is never stored twice.\n\n"
        "**Metadata JSON** (`*.json`, e.g. a `book-name-info.json` exported earlier) is matched to the book with the "
        "same `id`, title or file name and applied to it. Books in the same request are always processed before "
        "JSON files. If the JSON would change metadata the book already has, nothing is applied and the result has "
        "status `warning` with the differences; set `overwrite_json=true` to apply anyway."
    ),
)
def upload_books(
    files: list[UploadFile] = File(..., description="Ebook files and/or metadata JSON files"),
    category: Optional[str] = Form(None, description="Optional category for every uploaded book"),
    series: Optional[str] = Form(None, description="Optional series for every uploaded book; replaces any series the file already has"),
    overwrite_json: bool = Form(False, description="Let JSON overwrite existing metadata that differs"),
):
    items = [(_store(f), f.filename or "book", None, category or None) for f in files]
    results = _process(items, False, False, overwrite_json, (series or "").strip() or None)
    return {"results": results, "summary": uploads.summarise(results)}


@router.post(
    "/upload-folder", response_model=UploadReport, summary="Upload a whole folder tree",
    description=(
        "Send every file of a folder (e.g. from a browser directory picker) in one or more calls, with "
        "`relative_paths` holding each file's path inside the folder (same order as `files`). Sub-folders at any "
        "depth are supported. `.zip` archives are expanded recursively. With `category_from_folders` the book's "
        "parent folder name becomes its category. Unsupported files are skipped, not failed.\n\n"
        "Within a call, **books are processed first, then metadata JSON files**, so a JSON can find its book. "
        "When splitting a large folder over several calls, send the JSON files in the last call(s). "
        "See `POST /books/upload` for how JSON files are matched and what a `warning` means."
    ),
)
def upload_folder(
    files: list[UploadFile] = File(...),
    relative_paths: list[str] = Form(default=[], description="Relative path for each file, same order as files"),
    category_from_folders: bool = Form(True),
    expand_archives: bool = Form(True),
    category: Optional[str] = Form(None, description="Fallback category when folders do not provide one"),
    series: Optional[str] = Form(None, description="Optional series for every uploaded book; replaces any series the file already has"),
    overwrite_json: bool = Form(False, description="Let JSON overwrite existing metadata that differs"),
):
    items = []
    for i, f in enumerate(files):
        rel = (relative_paths[i] if i < len(relative_paths) else (f.filename or "book")).replace("\\", "/").lstrip("/")
        cat = (uploads.category_from_path(rel) if category_from_folders else None) or category or None
        items.append((_store(f), rel.split("/")[-1], rel, cat))
    results = _process(items, expand_archives, category_from_folders, overwrite_json, (series or "").strip() or None)
    return {"results": results, "summary": uploads.summarise(results)}
