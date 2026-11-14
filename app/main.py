import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import settings
from .db import init_db
from . import auth
from .auth import router as auth_router
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
    {"name": "Auth", "description": "Admin mode: log in to upload, edit and delete (reading never needs it)."},
    {"name": "Library", "description": "Facets, stats, duplicate detection and cleanup."},
]


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    log = logging.getLogger("uvicorn.error")
    if auth.enabled():
        log.info("Admin mode is ON: uploading, editing and deleting need the admin password")
    else:
        log.warning("Admin mode is OFF (ADMIN_PASSWORD is not set): anyone who can reach this server can change the library")
    # stale temp files from an interrupted run
    for p in settings.tmp_dir.glob("*"):
        p.unlink(missing_ok=True)
    yield


# /docs is served below from bundled files (the FastAPI default loads Swagger UI from a CDN); ReDoc is not offered because it
# insists on loading a badge image from another host
app = FastAPI(title="Meridian Ebooks", version=__version__, description=DESCRIPTION,
              openapi_tags=TAGS, lifespan=lifespan, docs_url=None, redoc_url=None)

# Pages may only load things from this server. Together with the bundled fonts and docs assets this means the app
# never contacts another host, and the browser enforces it.
CSP = ("default-src 'self'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; "
       "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; worker-src 'self'; "
       "object-src 'none'; base-uri 'self'; form-action 'self'")


@app.middleware("http")
async def content_security_policy(request: Request, call_next):
    response = await call_next(request)
    if response.headers.get("content-type", "").startswith("text/html"):     # the pages, not the book downloads
        response.headers["Content-Security-Policy"] = CSP
    return response

app.include_router(auth_router, prefix="/api")
app.include_router(books.router, prefix="/api")
app.include_router(upload.router, prefix="/api")
app.include_router(library.router, prefix="/api")


class NoCacheStatic(StaticFiles):
    """Always revalidate, so a rebuilt image shows up on a normal reload (ETag keeps it cheap)."""

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


app.mount("/static", NoCacheStatic(directory=STATIC), name="static")

VERSION_FILE = Path(__file__).parent.parent / "version.json"


@app.get("/api/version", tags=["Library"], summary="Version and build number")
def version():
    """Contents of `version.json` in the project root (read on each call)."""
    info = {"version": __version__, "build": None}
    try:
        info.update(json.loads(VERSION_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return JSONResponse(info, headers={"Cache-Control": "no-store"})


@app.get("/docs", include_in_schema=False)
def swagger_ui():
    return get_swagger_ui_html(openapi_url="/openapi.json", title=f"{app.title} - Swagger UI",
                               swagger_js_url="/static/vendor/swagger-ui-bundle.js", swagger_css_url="/static/vendor/swagger-ui.css",
                               swagger_favicon_url="/static/favicon.svg")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})
