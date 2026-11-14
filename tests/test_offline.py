"""The app must never contact another host: fonts and API docs are bundled, and pages carry a CSP that enforces it."""
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"
# w3.org appears only as an XML namespace inside inline SVG
EXTERNAL = re.compile(r"""(?:https?:)?//(?!www\.w3\.org)[a-z0-9-]+(?:\.[a-z0-9-]+)+""", re.I)


def own_sources():
    return [p for p in STATIC.rglob("*") if p.suffix in {".html", ".css", ".js", ".svg"} and "vendor" not in p.parts]


@pytest.mark.parametrize("path", own_sources(), ids=lambda p: p.name)
def test_own_static_files_reference_no_other_host(path):
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"https?://www\.w3\.org/[^\s'\"]*", "", text)      # xmlns attributes
    text = text.replace("https://www.google.com/search?q=", "")        # the book panel's Web search button, see the test below
    assert not EXTERNAL.findall(text), f"{path.name} mentions another host"


def test_every_ui_font_is_bundled():
    api = (STATIC / "js" / "api.js").read_text(encoding="utf-8")
    families = set(re.findall(r"""\["[^"]+", "'([^']+)'""", api))
    assert len(families) == 11
    css = (STATIC / "css" / "fonts.css").read_text(encoding="utf-8")
    for fam in families:
        assert f"font-family: '{fam}'" in css, fam
    for url in re.findall(r"url\('\.\./fonts/([^']+)'\)", css):
        assert (STATIC / "fonts" / url).stat().st_size > 1000, url        # real files, not placeholders
    for fam_dir in (STATIC / "fonts" / "licenses").iterdir():
        assert fam_dir.stat().st_size > 500


def test_pages_forbid_other_hosts_but_downloads_are_untouched(client):
    for page in ("/", "/docs"):
        csp = client.get(page).headers["content-security-policy"]
        assert "default-src 'self'" in csp and "connect-src 'self'" in csp and "font-src 'self'" in csp
    assert "content-security-policy" not in client.get("/api/stats").headers


def test_swagger_docs_use_bundled_assets(client):
    html = client.get("/docs").text
    assert "/static/vendor/swagger-ui-bundle.js" in html and "/static/vendor/swagger-ui.css" in html
    assert not EXTERNAL.findall(html)
    for asset in ("swagger-ui-bundle.js", "swagger-ui.css", "LICENSE-swagger-ui.txt"):
        assert client.get(f"/static/vendor/{asset}").status_code == 200
    assert client.get("/redoc").status_code == 404                          # ReDoc loads a badge from another host
    assert client.get("/openapi.json").status_code == 200


# ----------------------------------------------------------------------------- licences of what we ship
ROOT = STATIC.parent.parent


def test_bundled_assets_carry_their_licences():
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    fonts = {p.name.rsplit("-latin-", 1)[0] for p in (STATIC / "fonts").glob("*.woff2")}
    assert len(fonts) == 11
    for fid in fonts:
        lic = (STATIC / "fonts" / "licenses" / f"{fid}-OFL.txt").read_text(encoding="utf-8")
        assert "SIL OPEN FONT LICENSE" in lic.upper() and re.search(r"copyright", lic, re.I), fid     # licence text + a copyright line
    for line in ("Inter", "Source Sans 3", "Lora", "Merriweather", "Swagger UI", "pypdf", "pypdfium2", "PDFium", "Feather", "Lucide"):
        assert line in notices, line
    assert "Apache License" in (STATIC / "vendor" / "LICENSE-swagger-ui.txt").read_text(encoding="utf-8")
    assert "SmartBear" in (STATIC / "vendor" / "NOTICE-swagger-ui.txt").read_text(encoding="utf-8")       # Apache-2.0 section 4(d)
    assert (ROOT / "LICENSE").read_text(encoding="utf-8").startswith("MIT License")


def test_web_search_is_only_a_link_the_user_clicks():
    """The one place that names another host: the book panel's Web search button. It must open a new tab (window.open from a click),
    never be fetched by the app, and live in exactly one file."""
    js = {p.name: p.read_text(encoding="utf-8") for p in (STATIC / "js").glob("*.js")}
    assert [n for n, t in js.items() if "google.com" in t] == ["api.js"]
    assert 'window.open(webSearchUrl(f), "_blank", "noopener,noreferrer")' in js["components.js"]
    assert not any(re.search(r"fetch\(\s*webSearchUrl|api\(\s*webSearchUrl", t) for t in js.values())
