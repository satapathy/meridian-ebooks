"""Regenerate the README screenshots in docs/screenshots/.

Run it against a THROWAWAY instance - it adds demo books to whatever server it is pointed at and refuses
to run unless that library is empty:

    DATA_DIR=./.demo-data uvicorn app.main:app --port 8000      # terminal 1 (empty demo library)
    pip install playwright                                      # once; add `playwright install chromium` if you
                                                                # do not want to use an installed Edge/Chrome
    python scripts/capture_screenshots.py                       # terminal 2

Options: --url http://127.0.0.1:8000   --browser msedge|chrome|chromium
         --admin-user U --admin-password P   when the demo server has admin mode on (ADMIN_USER / ADMIN_PASSWORD):
                                             the script logs in through the UI, so the shots show the full admin view,
                                             and it also writes admin-login.png (the login dialog)
"""
import argparse
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots"
sys.path.insert(0, str(ROOT))

# (category, title, author, series, series_index)
DEMO = [
    ("Science Fiction", "Dune", "Frank Herbert", "Dune Chronicles", 1),
    ("Science Fiction", "Neuromancer", "William Gibson", "", None),
    ("Science Fiction", "Hyperion", "Dan Simmons", "", None),
    ("Science Fiction", "Snow Crash", "Neal Stephenson", "", None),
    ("Fantasy", "The Hobbit", "J. R. R. Tolkien", "Middle-earth", 1),
    ("Fantasy", "The Fellowship of the Ring", "J. R. R. Tolkien", "Middle-earth", 2),
    ("Fantasy", "Mistborn", "Brandon Sanderson", "", None),
    ("Fantasy", "The Name of the Wind", "Patrick Rothfuss", "", None),
    ("Computing", "Clean Code", "Robert Martin", "", None),
    ("Computing", "Designing Data-Intensive Applications", "Martin Kleppmann", "", None),
    ("History", "SPQR", "Mary Beard", "", None),
    ("History", "Guns Germs and Steel", "Jared Diamond", "", None),
]
DUNE = dict(
    subtitle="The Desert Planet", publisher="Chilton Books", published="1965", subcategory="Space Opera",
    tags=["classic", "desert", "politics"], rating=5,
    description="Set on the desert planet Arrakis, Dune follows young Paul Atreides as his family accepts "
                "stewardship of the galaxy's most valuable resource - and the betrayal that follows.",
)


def seed(api: str, auth=None) -> None:
    from tests.conftest import make_docx, make_epub  # tiny generated books; no real titles are shipped

    if httpx.get(f"{api}/stats").json()["books"]:
        sys.exit("This library is not empty. Point --url at a throwaway demo instance (see the file header).")
    files, paths = [], []
    for i, (cat, title, author, _, _) in enumerate(DEMO):
        if i % 2:
            data, ext = make_docx(title=title, author=author, marker=title), "docx"
        else:
            data, ext = make_epub(title=title, author=author, subject=cat.lower(), marker=title), "epub"
        name = title.lower().replace(" ", "-") + "." + ext
        files.append(("files", (name, data)))
        paths.append(f"Books/{cat}/{name}")
    r = httpx.post(f"{api}/books/upload-folder", files=files, data={"relative_paths": paths}, timeout=120, auth=auth)
    r.raise_for_status()
    ids = {b["title"]: b["id"] for b in httpx.get(f"{api}/books", params={"limit": 100}).json()["items"]}
    for _, title, _, series, idx in DEMO:
        extra = DUNE if title == "Dune" else {}
        if series or extra:
            httpx.patch(f"{api}/books/{ids[title]}", json={"series": series, "series_index": idx, **extra}, auth=auth).raise_for_status()


def capture(base: str, browser: str, creds=None) -> None:
    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        launch = p.chromium.launch() if browser == "chromium" else p.chromium.launch(channel=browser)

        def open_library(theme: str):
            pg = launch.new_context(viewport={"width": 1440, "height": 900}).new_page()
            pg.add_init_script(f"localStorage.setItem('mx-theme', {theme!r});")
            pg.goto(base + "/#/library")
            pg.wait_for_selector("mx-card")
            pg.wait_for_timeout(900)  # covers and web fonts
            if creds:
                pg.click(".admin-nav")
                pg.fill("#lg-user", creds[0])
                pg.fill("mx-login input[type=password]", creds[1])
                if theme == "vanilla" and not (OUT / "_login_done").exists():
                    pg.wait_for_timeout(300)
                    pg.screenshot(path=str(OUT / "admin-login.png"))
                    (OUT / "_login_done").write_text("")
                pg.click("#lg-go")
                pg.wait_for_selector("body.is-admin")
                pg.wait_for_timeout(4500)  # let the "Admin mode on" toast fade out
            return pg

        pg = open_library("vanilla")
        pg.screenshot(path=str(OUT / "library.png"))
        pg.locator("mx-card", has_text="Dune").first.click()
        pg.wait_for_timeout(900)
        pg.screenshot(path=str(OUT / "book-details.png"))

        pg = open_library("aurora")
        pg.click("#btn-settings")
        pg.wait_for_timeout(700)
        pg.screenshot(path=str(OUT / "themes-settings.png"))
        launch.close()
    (OUT / "_login_done").unlink(missing_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--browser", default="msedge", help="msedge, chrome or chromium (Playwright's own build)")
    ap.add_argument("--admin-user", default="")
    ap.add_argument("--admin-password", default="")
    a = ap.parse_args()
    base = a.url.rstrip("/")
    creds = (a.admin_user, a.admin_password) if a.admin_user else None
    seed(base + "/api", creds)
    capture(base, a.browser, creds)
    print("Wrote", ", ".join(sorted(f.name for f in OUT.glob("*.png"))), "to", OUT)


if __name__ == "__main__":
    main()
