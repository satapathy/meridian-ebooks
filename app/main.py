from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import settings
from .db import init_db
from .routers import books, library, upload

STATIC = Path(__file__).parent / "static"

DESCRIPTION = """
**Meridian** is a self-hosted ebook library.

* Upload ebooks (EPUB, PDF, DOCX, MOBI, ...) - singly, as whole folder trees, or as `.zip` archives
* Every book gets a server-assigned **UUID**; an **MD5** of the content blocks and cleans up duplicates
* Files live in a flat, UUID-sharded layout: `1234/5678/abcd/.../book-name.ext`
* Search by metadata with **wildcards**: `author:tolk* title:"*ring*" -audio`
* Edit metadata - written **into the file** when the format allows, otherwise into `book-name-info.json`
* Rename files independently of titles
* Export the whole library as a ZIP organised by **category** or **author**

The web UI is served at `/`.
"""

TAGS = [
    {"name": "Books", "description": "Browse, search, edit, rename, download."},
    {"name": "Upload", "description": "Single files, folder trees, archives and server-side imports."},
    {"name": "Export", "description": "Library export as ZIP."},
    {"name": "Library", "description": "Facets, stats, duplicate detection and cleanup."},
]


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    # stale temp files from an interrupted run
    for p in settings.tmp_dir.glob("*"):
        p.unlink(missing_ok=True)
    yield


app = FastAPI(title="Meridian Ebooks", version=__version__, description=DESCRIPTION,
              openapi_tags=TAGS, lifespan=lifespan)

app.include_router(books.router, prefix="/api")
app.include_router(upload.router, prefix="/api")
app.include_router(library.router, prefix="/api")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})
