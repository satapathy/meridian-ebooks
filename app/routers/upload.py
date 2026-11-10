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


@router.post(
    "/upload", response_model=UploadReport, summary="Upload one or more ebooks",
    description=(
        "Accepts EPUB, PDF, DOCX, MOBI, AZW3, FB2, TXT, RTF, CBZ and more. Each book gets a server-side UUID. "
        "An MD5 of the content detects duplicates - an identical file is never stored twice."
    ),
)
def upload_books(
    files: list[UploadFile] = File(..., description="Ebook files"),
    category: Optional[str] = Form(None, description="Optional category for every uploaded book"),
):
    results = []
    for f in files:
        results.append(uploads.ingest_one(_store(f), f.filename or "book", None, category or None))
    return {"results": results, "summary": uploads.summarise(results)}


@router.post(
    "/upload-folder", response_model=UploadReport, summary="Upload a whole folder tree",
    description=(
        "Send every file of a folder (e.g. from a browser directory picker) in one or more calls, with "
        "`relative_paths` holding each file's path inside the folder (same order as `files`). Sub-folders at any "
        "depth are supported. `.zip` archives are expanded recursively. With `category_from_folders` the book's "
        "parent folder name becomes its category. Unsupported files are skipped, not failed."
    ),
)
def upload_folder(
    files: list[UploadFile] = File(...),
    relative_paths: list[str] = Form(default=[], description="Relative path for each file, same order as files"),
    category_from_folders: bool = Form(True),
    expand_archives: bool = Form(True),
    category: Optional[str] = Form(None, description="Fallback category when folders do not provide one"),
):
    results: list[dict] = []
    for i, f in enumerate(files):
        rel = relative_paths[i] if i < len(relative_paths) else (f.filename or "book")
        rel = rel.replace("\\", "/").lstrip("/")
        name = rel.split("/")[-1]
        cat = (uploads.category_from_path(rel) if category_from_folders else None) or category or None
        tmp = _store(f)
        if expand_archives and name.lower().endswith(".zip"):
            results += uploads.expand_zip(tmp, name, rel, category_from_folders, cat)
        else:
            results.append(uploads.ingest_one(tmp, name, rel, cat))
    return {"results": results, "summary": uploads.summarise(results)}
