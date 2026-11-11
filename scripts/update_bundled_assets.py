"""Re-download the third-party files the app serves itself (needs internet, run by a maintainer - the app never does).

    python scripts/update_bundled_assets.py

* app/static/fonts/   Latin subset of the UI fonts (SIL Open Font License) from the Fontsource npm packages, plus licences
* app/static/vendor/  Swagger UI for /docs (Apache-2.0: LICENSE and NOTICE are kept)
Then regenerate app/static/css/fonts.css if you add a font or weight (one @font-face per file).
"""
import urllib.request
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"
CDN = "https://cdn.jsdelivr.net/npm"
SWAGGER = "swagger-ui-dist@5.17.14"
# fontsource id -> weights
FONTS = {"inter": (400, 500, 600), "dm-sans": (400, 500, 600), "source-sans-3": (400, 500, 600), "ibm-plex-sans": (400, 500, 600),
         "nunito": (400, 500, 600), "poppins": (400, 500, 600), "space-grotesk": (400, 500, 600), "lora": (400, 500, 600),
         "merriweather": (400, 700), "atkinson-hyperlegible": (400, 700), "jetbrains-mono": (400, 500, 600)}


def get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "meridian-assets/1.0"}), timeout=120) as r:
        return r.read()


def save(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    print(f"{path.relative_to(STATIC)}  {len(data) // 1024} KB")


for fid, weights in FONTS.items():
    for w in weights:
        data = get(f"{CDN}/@fontsource/{fid}@5/files/{fid}-latin-{w}-normal.woff2")
        assert data[:4] == b"wOF2", f"{fid} {w}: not a woff2 file"
        save(STATIC / "fonts" / f"{fid}-latin-{w}.woff2", data)
    licence = f"{CDN}/@fontsource/{fid}@5/LICENSE"
    if fid == "source-sans-3":   # Fontsource's copy omits Adobe's copyright line and Reserved Font Name - use the upstream licence
        licence = "https://raw.githubusercontent.com/adobe-fonts/source-sans/release/LICENSE.md"
    save(STATIC / "fonts" / "licenses" / f"{fid}-OFL.txt", get(licence))

for name in ("swagger-ui-bundle.js", "swagger-ui.css"):
    save(STATIC / "vendor" / name, get(f"{CDN}/{SWAGGER}/{name}"))
save(STATIC / "vendor" / "LICENSE-swagger-ui.txt", get(f"{CDN}/{SWAGGER}/LICENSE"))
save(STATIC / "vendor" / "NOTICE-swagger-ui.txt", get(f"{CDN}/{SWAGGER}/NOTICE"))   # Apache-2.0 section 4(d): keep the NOTICE
