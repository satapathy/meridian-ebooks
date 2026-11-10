# Meridian Ebooks

A dockerized, self-hosted ebook library: FastAPI backend with a Swagger page, and a Plex-style browser UI.
Runs in one container, including on a Raspberry Pi.

## Highlights

*One bullet per feature - add or remove lines as the app changes. Details live in [Features](#features).*

**Library**
* Upload files, whole folders (recursive) or `.zip` archives; EPUB, PDF, DOCX, MOBI, AZW3, FB2, TXT, CBZ and more
* Plex-style cover wall with infinite scroll, series grouping, Authors, Categories and Recently added views
* Generated covers for books without one; replace any cover with your own image
* Server-side UUID per book, MD5 duplicate detection and one-call cleanup
* Sharded folder storage derived from the UUID (`1234/5678/abcd/…`)

**Metadata**
* Edit title, subtitle, author, publisher, series, category, subcategory, tags, ISBN, rating and more
* Written into the file for EPUB, PDF and DOCX; stored in a `book-name-info.json` sidecar for other formats
* Title and file name are independent; rename the file separately
* Import metadata from JSON, with a warning and diff when it would overwrite existing values

**Search and export**
* Wildcards (`*`, `?`), field scopes (`author:`, `title:`, `tag:`…), quoted phrases and `-exclusions`
* Export the library as a ZIP organised by category or author, with metadata and covers included

**Interface and API**
* Ten themes (plain Vanilla by default), eleven open-source fonts, adjustable text size and cover borders
* Every action is a REST endpoint, documented with Swagger at `/docs`
* No front-end build step: plain ES modules and native web components

**Deployment**
* Docker Compose with a configurable data folder, port and run-as user
* Restarts automatically after a reboot (see the Raspberry Pi section)
* No built-in authentication - put it behind a reverse proxy or VPN before exposing it

## Setting up the data folder

The container runs as a non-root user (UID/GID 1000 by default) and must be able to write to the data folder.
If the folder doesn't exist, Docker creates it owned by `root` and the app fails with
`PermissionError: [Errno 13] Permission denied: '/data/library'`. Create it yourself first:

```bash
mkdir -p data import
# Linux: make the folder writable by the user the container runs as
sudo chown -R "$(id -u):$(id -g)" data
```

Then tell Docker which folder and user to use via a `.env` file next to `docker-compose.yml`
(all values are optional; defaults shown):

```bash
MERIDIAN_DATA=./data        # any absolute or relative path, e.g. /srv/ebooks/data
MERIDIAN_IMPORT=./import    # optional read-only folder for server-side imports
MERIDIAN_UID=1000           # set to the output of `id -u`
MERIDIAN_GID=1000           # set to the output of `id -g`
MERIDIAN_PORT=8000
```

Or pass them inline: `MERIDIAN_DATA=/srv/ebooks MERIDIAN_UID=$(id -u) MERIDIAN_GID=$(id -g) docker compose up --build`.
On Docker Desktop (Windows/macOS) permissions are usually not an issue.

## Run

```bash
docker compose up --build
```

* Web UI: <http://localhost:8000/>
* Swagger: <http://localhost:8000/docs> (ReDoc at `/redoc`)
* Data lives in the data folder (`./data` by default: library files + `meridian.db`). Optional `./import` is mounted read-only at `/import` for server-side imports.

### Raspberry Pi: start automatically on boot

`docker-compose.yml` already has `restart: unless-stopped`, so once Docker itself starts at boot, Meridian comes back by itself. One-time setup on the Pi:

```bash
# 1. Install Docker (skip if `docker --version` already works) and let your user run it without sudo
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"        # log out and back in afterwards

# 2. Start Docker at boot (the installer usually does this already)
sudo systemctl enable --now docker containerd

# 3. Get the project onto the Pi and prepare the data folder (see "Setting up the data folder")
cd ~/meridian-ebooks
mkdir -p data import
echo "MERIDIAN_UID=$(id -u)" >> .env
echo "MERIDIAN_GID=$(id -g)" >> .env

# 4. Build and start in the background (-d), so it is not tied to your terminal
docker compose up --build -d
```

Check it: `docker compose ps` should show `meridian` as `running (healthy)`, and the UI is at `http://<pi-address>:8000/` (find the address with `hostname -I`).

Test the boot behaviour with `sudo reboot`, then after a minute or two open the UI again.

Useful commands (run in the project folder):

| Task | Command |
|---|---|
| Logs | `docker compose logs -f` |
| Stop / start | `docker compose stop` / `docker compose start` |
| Update after pulling new code | `docker compose up --build -d` |
| Remove the container (data is kept in `./data`) | `docker compose down` |

Notes:
* A container you stopped yourself with `docker compose stop` stays stopped after a reboot (that is what `unless-stopped` means). Use `docker compose start` to bring it back.
* Keep `data` on the SD card only for light use. For a big library, mount a USB drive or SSD (e.g. at `/mnt/books`), `chown` it to your user, and set `MERIDIAN_DATA=/mnt/books/meridian` in `.env`. Make sure the drive is mounted at boot (an `/etc/fstab` entry with the `nofail` option) so Docker doesn't start the container against an empty folder.
* `docker` works without `sudo` only after the `usermod` step and a fresh login.

### Raspberry Pi: 32-bit vs 64-bit OS

A 64-bit OS (`uname -m` prints `aarch64`) is recommended. On 32-bit Raspberry Pi OS (`armv7l`) PyMuPDF has no prebuilt package, so the image builds without it: everything works, but PDFs get no embedded metadata, no first-page cover (a generated cover is shown) and metadata edits for PDFs go to the `-info.json` sidecar.

## Features

| Requirement | How it works |
|---|---|
| Upload EPUB, PDF, DOCX, MOBI, AZW3, FB2, TXT, CBZ… | `POST /api/books/upload` (see `app/config.py` for the full list) |
| Upload whole folders recursively | `POST /api/books/upload-folder` takes files plus their relative paths (the UI uses the browser directory picker or drag-and-drop of folders). `.zip` archives are expanded recursively. `POST /api/import` imports a folder already on the server. Folder names can become categories. |
| Import metadata JSON | Upload `*.json` (e.g. an exported `book-name-info.json`) alone, in a folder, in a `.zip`, or from the server import folder. It is matched to the book by `id`, then title (case-insensitive), then file name, and applied to that book. **Books are always processed before JSON files** (the UI uploads every book first, then the JSONs). Empty fields are filled in; if the JSON would change a value the book already has, nothing is applied and you get a `warning` listing each field's current vs. imported value. Tick "overwrite" (`overwrite_json=true`) to apply anyway. A category that was merely inferred from the upload folder name does not count as an existing value. |
| Replace the cover | `PUT /api/books/{id}/cover` (or "Upload cover" in the book panel). Saved as `book-name-cover.jpg` in the book's folder, next to `book-name-info.json`, and always shown instead of the cover embedded in the book. The book file is untouched, the cover follows the file on rename and is included in the ZIP export. `DELETE /api/books/{id}/cover` reverts to the embedded cover. |
| Plex-like browser | Library is the landing page (format/category/sort filters, infinite scroll, series shown as one stacked tile that opens the series), Recently added, Authors, Categories, generated covers when a book has none, detail drawer |
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
* The UI has ten themes, chosen in Settings (the sliders icon, top right) and saved per browser. **Vanilla** (white and light greys, the default) plus nine colourful ones: Aurora, Neon, Sunset, Ocean, Emerald, Cyber (dark) and Paper, Blossom, Lavender (light). Settings also controls the font (11 open-source SIL OFL families - Inter, DM Sans, Source Sans 3, IBM Plex Sans, Nunito, Poppins, Space Grotesk, Atkinson Hyperlegible, Lora, Merriweather, JetBrains Mono - plus the system font), text size (80-130%), cover border thickness, and whether series are grouped. Fonts load from Google Fonts on demand and fall back to system fonts when offline. `GET /api/books?group_series=true` returns the grouped view (`series_count` on each entry; filter with `series=` to list one series).
