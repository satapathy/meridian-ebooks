# Meridian Ebooks

A dockerized, self-hosted ebook library: FastAPI backend with a Swagger page, and a Plex-style browser UI.

```bash
docker compose up --build
```

* Web UI: <http://localhost:8000/>
* Swagger: <http://localhost:8000/docs> (ReDoc at `/redoc`)
* Data lives in `./data` (library files + `meridian.db`). Optional `./import` is mounted read-only at `/import` for server-side imports.

## Features

| Requirement | How it works |
|---|---|
| Upload EPUB, PDF, DOCX, MOBI, AZW3, FB2, TXT, CBZ… | `POST /api/books/upload` (see `app/config.py` for the full list) |
| Upload whole folders recursively | `POST /api/books/upload-folder` takes files plus their relative paths (the UI uses the browser directory picker or drag-and-drop of folders). `.zip` archives are expanded recursively. `POST /api/import` imports a folder already on the server. Folder names can become categories. |
| Plex-like browser | Home with hero + shelves, Library grid (format/category/sort filters, infinite scroll), Authors, Categories, generated covers when a book has none, detail drawer |
| Metadata search with wildcards | `GET /api/books?q=…` - `*` and `?` wildcards, `author:`/`title:`/`tag:`/`category:`/`format:`/`series:`/`isbn:`/`lang:`/`year:`/`file:` scopes, `"phrases"`, `-exclusions`. Example: `author:tolk* title:"*ring*" -format:pdf` |
| UUID per book + MD5 duplicate control | UUID4 assigned at upload. The MD5 of the upload is unique-indexed; identical content is rejected. The hash is kept even after metadata is written into a file, so the original is still recognised. `GET /api/duplicates` and `POST /api/cleanup` (dry-run by default) remove duplicates, orphan folders and dangling records. |
| Flat sharded storage | UUID hex split 4 chars at a time: `1234/5678/abcd/ef01/…/book-name.ext` (32 hex chars → 8 levels) |
| Library export as ZIP | `GET /api/export?group_by=category` or `author` (optionally `format=`, `ids=`, `include_metadata=`) |
| Metadata editing | `PATCH /api/books/{id}`. EPUB, PDF and DOCX get what they can hold **inside the file**; everything else goes into `book-name-info.json` next to the book. The response's `storage` field shows what went where. |
| Title ≠ filename | Editing the title never touches the file name. `POST /api/books/{id}/rename` renames the file (and its sidecar) separately. |

### What is stored where

| Format | Inside the file | Sidecar `*-info.json` |
|---|---|---|
| EPUB | title, author, publisher, description, language, date, tags, series | category, ISBN, rating |
| PDF | title, author, description (subject), tags (keywords) | everything else |
| DOCX | title, author, description, tags, category, language | everything else |
| MOBI, AZW3, FB2, TXT, RTF, CBZ, … | – | all metadata |

Writing metadata into a file changes its bytes, so the server tracks both the original and the current MD5.

## Development

```bash
pip install -r requirements.txt
python -m pytest                      # backend test suite
DATA_DIR=./data uvicorn app.main:app --reload
```

Configuration (environment): `DATA_DIR` (default `./data`), `IMPORT_DIR` (default `./import`), `MAX_ARCHIVE_BYTES`.

Layout: `app/service.py` (ingest, edit, search, cleanup), `app/metadata.py` (EPUB/PDF/DOCX read & write), `app/search.py` (query parser), `app/routers/` (API), `app/static/` (UI - plain ES modules and native web components, no build step).

## Notes

* No authentication is built in - put it behind a reverse proxy or VPN before exposing it.
* The UI has three themes (Aurora, Neon, Paper), switchable from the sidebar.
