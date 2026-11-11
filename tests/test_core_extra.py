"""Metadata readers/writers, the real HTTP layer of the online lookup (network mocked), colours and storage helpers."""
import io
import sys
import urllib.error
import urllib.request
import zipfile

import pytest
from PIL import Image

from app import lookup, metadata as md, service
from app.config import settings
from app.storage import book_dir, prune_empty_parents

from .conftest import make_docx, make_epub, make_pdf


def epub_with(opf: str, extra: dict | None = None, container: str | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", container or (
            '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'))
        z.writestr("OEBPS/content.opf", opf)
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return buf.getvalue()


def png(w=60, h=90, mode="RGB", color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new(mode, (w, h), color).save(buf, "PNG")
    return buf.getvalue()


OPF = ('<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0"><metadata '
       'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">'
       '<dc:title>T</dc:title>{meta}</metadata><manifest>{manifest}</manifest></package>')


# ----------------------------------------------------------------------------- EPUB
def test_epub_series_isbn_and_cover_by_properties(tmp_path):
    p = tmp_path / "a.epub"
    p.write_bytes(epub_with(OPF.format(
        meta='<opf:meta name="calibre:series" content="Saga"/><opf:meta name="calibre:series_index" content="2.5"/>'
             '<dc:identifier>ISBN 12</dc:identifier><dc:identifier>urn:isbn:978-0-306-40615-7</dc:identifier>',
        manifest='<item id="i" href="img/c.png" media-type="image/png" properties="cover-image"/>'),
        {"OEBPS/img/c.png": png()}))
    meta, cover = md.read_metadata(p, "epub")
    assert (meta["series"], meta["series_index"], meta["isbn"]) == ("Saga", 2.5, "9780306406157")
    assert cover and Image.open(io.BytesIO(cover)).size == (60, 90)


def test_epub_cover_by_meta_name_and_unusable_values(tmp_path):
    p = tmp_path / "a.epub"
    p.write_bytes(epub_with(OPF.format(
        meta='<opf:meta name="calibre:series_index" content="not-a-number"/><opf:meta name="cover" content="cv"/>',
        manifest='<item id="x" href="x.png" media-type="image/png"/><item id="cv" href="c.png" media-type="image/png"/>'),
        {"OEBPS/c.png": png()}))
    meta, cover = md.read_metadata(p, "epub")
    assert "series_index" not in meta and cover                                # bad number ignored, cover found via <meta name=cover>
    p.write_bytes(epub_with(OPF.format(meta="", manifest='<item id="i" href="missing.png" properties="cover-image"/>')))
    assert md.read_metadata(p, "epub")[1] is None                              # cover file absent: best effort, no failure


def test_epub_without_rootfile_or_metadata_block(tmp_path):
    p = tmp_path / "a.epub"
    p.write_bytes(epub_with("<package xmlns='http://www.idpf.org/2007/opf'/>", container=(
        '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles/></container>')))
    assert md.read_metadata(p, "epub") == ({}, None)                           # "no rootfile" is swallowed
    p.write_bytes(epub_with("<package xmlns='http://www.idpf.org/2007/opf'><manifest/></package>"))
    assert md.read_metadata(p, "epub") == ({}, None)                           # reader: no <metadata>
    assert md.write_metadata(p, "epub", {"title": "x"}) == set()               # writer refuses and leaves the file alone
    assert zipfile.ZipFile(p).testzip() is None


def test_write_failure_cleans_up_its_temp_file(tmp_path):
    p = tmp_path / "broken.epub"
    p.write_bytes(b"not a zip at all")
    stray = p.with_name(p.name + ".tmp")
    stray.write_bytes(b"leftover")
    assert md.write_metadata(p, "epub", {"title": "x"}) == set()
    assert not stray.exists()
    assert md.read_metadata(p, "epub") == ({}, None)


def test_unknown_formats_have_no_embedded_metadata(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("hello")
    assert md.read_metadata(p, "txt") == ({}, None) and md.write_metadata(p, "txt", {"title": "x"}) == set()


# ----------------------------------------------------------------------------- PDF / DOCX
def test_pdf_roundtrip_and_encrypted_files(tmp_path):
    import pymupdf

    p = tmp_path / "a.pdf"
    p.write_bytes(make_pdf(title="Old", author="Someone", marker="m"))
    assert md.write_metadata(p, "pdf", {"title": "New", "author": "Me", "tags": ["a", "b"], "description": "d"})
    meta, cover = md.read_metadata(p, "pdf")
    assert (meta["title"], meta["author"], meta["tags"]) == ("New", "Me", ["a", "b"]) and cover
    locked = tmp_path / "locked.pdf"
    doc = pymupdf.open(p)
    doc.save(locked, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="u", owner_pw="o")
    doc.close()
    assert md.read_metadata(locked, "pdf") == ({}, None)
    assert md.write_metadata(locked, "pdf", {"title": "x"}) == set()


def test_pdf_cover_is_best_effort(tmp_path, monkeypatch):
    import pymupdf

    p = tmp_path / "a.pdf"
    p.write_bytes(make_pdf(marker="c"))

    def boom(*a, **k):
        raise RuntimeError("render failed")

    monkeypatch.setattr(pymupdf, "Matrix", boom)
    meta, cover = md.read_metadata(p, "pdf")
    assert meta["title"] == "PDF Title" and cover is None


def test_pdf_support_is_skipped_when_pymupdf_is_missing(tmp_path, monkeypatch):
    p = tmp_path / "a.pdf"
    p.write_bytes(make_pdf(marker="n"))
    monkeypatch.setitem(sys.modules, "pymupdf", None)                         # `import pymupdf` now raises ImportError
    assert md.read_metadata(p, "pdf") == ({}, None) and md.write_metadata(p, "pdf", {"title": "x"}) == set()


def test_docx_write_removes_emptied_fields_and_tolerates_missing_core(tmp_path):
    p = tmp_path / "a.docx"
    p.write_bytes(make_docx(title="Keep", author="Gone", marker="d"))
    assert md.write_metadata(p, "docx", {"title": "Keep", "author": "", "tags": ["t"], "category": "C", "language": "en"})
    meta, _ = md.read_metadata(p, "docx")
    assert meta["title"] == "Keep" and "author" not in meta and meta["tags"] == ["t"] and meta["category"] == "C"
    bare = tmp_path / "bare.docx"
    with zipfile.ZipFile(bare, "w") as z:
        z.writestr("word/document.xml", "<x/>")
    assert md.read_metadata(bare, "docx") == ({}, None) and md.write_metadata(bare, "docx", {"title": "x"}) == set()


def test_cover_normalisation_handles_transparency_and_garbage():
    rgba = md.make_cover_jpeg(png(mode="RGBA", color=(255, 0, 0, 0)))
    assert Image.open(io.BytesIO(rgba)).mode == "RGB"
    big = md.make_cover_jpeg(png(200, 3000), max_height=300)
    assert Image.open(io.BytesIO(big)).size[1] == 300
    assert md.make_cover_jpeg(b"definitely not an image") is None


# ----------------------------------------------------------------------------- online lookup: the real HTTP layer
class FakeResp:
    def __init__(self, body: bytes, ctype="application/json"):
        self.body, self.headers = body, {"Content-Type": ctype}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        return self.body if n < 0 else self.body[:n]


@pytest.fixture()
def net(monkeypatch):
    monkeypatch.setattr(lookup, "MIN_GAP", 0)
    lookup.clear_cache()
    yield
    lookup.clear_cache()


def test_http_json_parses_caches_and_maps_errors(net, monkeypatch):
    calls = []

    def ok(req, timeout=None):
        calls.append(req.full_url)
        return FakeResp(b'{"a": 1}')

    monkeypatch.setattr(urllib.request, "urlopen", ok)
    assert lookup._http_json("https://x.test/a") == {"a": 1} and lookup._http_json("https://x.test/a") == {"a": 1}
    assert calls == ["https://x.test/a"]                                        # second call came from the cache

    def http_error(code):
        def f(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, code, "msg", {}, None)
        return f

    for code, text in ((429, "rate limited"), (500, "service error 500")):
        monkeypatch.setattr(urllib.request, "urlopen", http_error(code))
        with pytest.raises(lookup.LookupUnavailable, match=text):
            lookup._http_json(f"https://x.test/e{code}")
    for exc in (urllib.error.URLError("down"), TimeoutError(), ValueError("bad json")):
        monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None, e=exc: (_ for _ in ()).throw(e))
        with pytest.raises(lookup.LookupUnavailable, match="not reachable"):
            lookup._http_json("https://x.test/down")


def test_http_json_cache_is_bounded(net, monkeypatch):
    monkeypatch.setattr(lookup, "MAX_CACHE", 2)
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: FakeResp(b"{}"))
    for i in range(4):
        lookup._http_json(f"https://x.test/{i}")
    assert len(lookup._cache) <= 2


class FakeOpener:
    def __init__(self, resp=None, exc=None):
        self.resp, self.exc = resp, exc

    def open(self, req, timeout=None):
        if self.exc:
            raise self.exc
        return self.resp


def test_http_bytes_checks_type_size_and_errors(net, monkeypatch):
    url = "https://covers.openlibrary.org/b/id/1-L.jpg"

    def opener(resp=None, exc=None):
        monkeypatch.setattr(urllib.request, "build_opener", lambda *h: FakeOpener(resp, exc))

    opener(FakeResp(b"IMG", "image/jpeg"))
    assert lookup._http_bytes(url) == b"IMG"
    opener(FakeResp(b"<html>", "text/html"))
    with pytest.raises(lookup.LookupUnavailable, match="not an image"):
        lookup._http_bytes(url)
    monkeypatch.setattr(lookup, "MAX_IMAGE_BYTES", 2)
    opener(FakeResp(b"123456", "image/png"))
    with pytest.raises(lookup.LookupUnavailable, match="too large"):
        lookup._http_bytes(url)
    opener(exc=urllib.error.HTTPError(url, 404, "nf", {}, None))
    with pytest.raises(lookup.LookupUnavailable, match="error 404"):
        lookup._http_bytes(url)
    opener(exc=urllib.error.URLError("down"))
    with pytest.raises(lookup.LookupUnavailable, match="not reachable"):
        lookup._http_bytes(url)


def test_redirects_only_follow_allowed_hosts():
    handler = lookup._SafeRedirect()
    req = urllib.request.Request("https://covers.openlibrary.org/b/id/1-L.jpg")
    with pytest.raises(urllib.error.URLError):
        handler.redirect_request(req, None, 302, "Found", {}, "https://evil.example/x.jpg")
    nxt = handler.redirect_request(req, None, 302, "Found", {}, "https://ia800000.us.archive.org/x.jpg")
    assert nxt.full_url == "https://ia800000.us.archive.org/x.jpg"


# ----------------------------------------------------------------------------- cover colours + storage
def test_dominant_color_edge_cases(tmp_path):
    assert service.dominant_color(tmp_path / "missing.jpg") is None            # unreadable
    white = tmp_path / "w.png"
    white.write_bytes(png(color=(255, 255, 255)))
    assert service.dominant_color(white) is None                               # nothing but paper white
    red = tmp_path / "r.png"
    red.write_bytes(png(color=(220, 20, 20)))
    assert service.dominant_color(red) == "#dc1414"


def test_color_cache_resets_when_it_grows_too_large(client, monkeypatch):
    bid = client.post("/api/books/upload", files=[("files", ("a.epub", make_epub(marker="col")))]).json()["results"][0]["book_id"]
    client.put(f"/api/books/{bid}/cover", files={"file": ("c.png", png(), "image/png")})
    monkeypatch.setattr(service, "_color_cache", {("x", i): None for i in range(5001)})
    assert service.cover_colors([bid])[bid].startswith("#")
    assert len(service._color_cache) == 1


def test_prune_empty_parents_stops_at_a_non_empty_folder():
    root = settings.library_dir
    deep = root / "zz01" / "zz02" / "zz03"
    deep.mkdir(parents=True)
    (root / "zz01" / "keep.txt").write_text("x")
    prune_empty_parents(deep)
    assert not deep.exists() and not (root / "zz01" / "zz02").exists() and (root / "zz01").exists()
    assert book_dir("a" * 32).is_relative_to(root)
