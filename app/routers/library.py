import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from .. import service, uploads
from ..config import settings
from ..exporter import build_export
from ..schemas import Facets, ImportJob, ImportRequest

router = APIRouter()
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


@router.get("/facets", response_model=Facets, tags=["Library"], summary="Authors, categories, formats and tags with counts")
def facets():
    return service.facets()


@router.get("/stats", tags=["Library"], summary="Library totals")
def stats():
    return service.stats()


@router.get("/health", tags=["Library"], summary="Liveness probe")
def health():
    return {"status": "ok"}


@router.get(
    "/export", tags=["Export"], summary="Export the library as a ZIP",
    description="Organises books into one folder per **category** or per **author**. "
                "Metadata sidecars are included unless disabled.",
    responses={200: {"content": {"application/zip": {}}}},
)
def export_library(
    group_by: Literal["category", "author"] = "category",
    format: Optional[str] = Query(None, description="Only export this file format"),
    ids: Optional[list[str]] = Query(None, description="Only export these book ids"),
    include_metadata: bool = True,
):
    path, count = build_export(group_by, ids=ids, fmt=format, include_metadata=include_metadata)
    if count == 0:
        path.unlink(missing_ok=True)
        raise HTTPException(404, "Nothing to export")
    name = f"meridian-library-by-{group_by}-{datetime.now():%Y%m%d-%H%M}.zip"
    return FileResponse(path, media_type="application/zip", filename=name,
                        headers={"X-Book-Count": str(count)},
                        background=BackgroundTask(lambda: path.unlink(missing_ok=True)))


@router.get("/duplicates", tags=["Library"], summary="List groups of duplicate books (same MD5)")
def duplicates():
    return {"groups": service.duplicate_groups()}


@router.post(
    "/cleanup", tags=["Library"], summary="Remove duplicates, orphan folders and dangling records",
    description="The oldest copy of each duplicate group is kept. **Defaults to a dry run** - pass `dry_run=false` to apply.",
)
def cleanup(dry_run: bool = True):
    return service.cleanup(dry_run)


# ------------------------------------------------------------------ server-side folder import
def _resolve_import_path(rel: str) -> Path:
    root = settings.import_dir
    target = (root / rel.lstrip("/\\")).resolve()
    if target != root and root not in target.parents:
        raise HTTPException(400, "Path must be inside the import directory")
    if not target.is_dir():
        raise HTTPException(404, f"Folder not found in import directory: {rel or '/'}")
    return target


def _run_import(job_id: str, root: Path, use_folders: bool) -> None:
    job = _jobs[job_id]
    files = [Path(d) / f for d, _, fs in os.walk(root) for f in fs]
    job["total"] = len(files)
    job["status"] = "running"
    results: list[dict] = []
    for p in files:
        rel = p.relative_to(root).as_posix()
        try:
            tmp = uploads.new_tmp()
            if service.is_supported(p.name) or p.suffix.lower() == ".zip":
                import shutil
                shutil.copyfile(p, tmp)
                if p.suffix.lower() == ".zip":
                    r = uploads.expand_zip(tmp, p.name, rel, use_folders, None)
                else:
                    cat = uploads.category_from_path(f"{root.name}/{rel}") if use_folders else None
                    r = [uploads.ingest_one(tmp, p.name, rel, cat)]
            else:
                r = [{"filename": rel, "status": "skipped"}]
        except Exception as exc:
            r = [{"filename": rel, "status": "error", "detail": str(exc)[:200]}]
        results += r
        job["processed"] += 1
        job["summary"] = uploads.summarise(results)
        job["errors"] = [f"{x['filename']}: {x.get('detail', '')}" for x in results if x["status"] == "error"][:50]
    job["status"] = "done"


@router.post(
    "/import", response_model=ImportJob, tags=["Upload"], summary="Import a folder that is already on the server",
    description="Recursively imports books from the server's import directory (the `/import` volume in Docker). "
                "Runs in the background - poll `GET /import/{job_id}`.",
)
def import_folder(body: ImportRequest, background: BackgroundTasks):
    root = _resolve_import_path(body.path)
    job_id = uuid.uuid4().hex[:12]
    with _jobs_lock:
        _jobs[job_id] = {"id": job_id, "status": "queued", "path": str(root), "total": 0, "processed": 0,
                         "summary": {k: 0 for k in uploads.SUMMARY_KEYS}, "errors": []}
    background.add_task(_run_import, job_id, root, body.category_from_folders)
    return _jobs[job_id]


@router.get("/import/{job_id}", response_model=ImportJob, tags=["Upload"], summary="Server import progress")
def import_status(job_id: str):
    if job_id not in _jobs:
        raise HTTPException(404, "Unknown job")
    return _jobs[job_id]
