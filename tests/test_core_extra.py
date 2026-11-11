"""Metadata readers/writers, cover colours and storage helpers."""
import io
import sys
import zipfile

from PIL import Image

from app import metadata as md, service
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
def test_pdf_roundtrip_keeps_other_document_info(tmp_path):
    p = tmp_path / "a.pdf"
    p.write_bytes(make_pdf(title="Old", author="Someone", marker="m"))
    assert md.write_metadata(p, "pdf", {"title": "New", "author": "Me", "tags": ["a", "b"], "description": "d"}) == md.EMBEDDABLE["pdf"]
    meta, cover = md.read_metadata(p, "pdf")
    assert (meta["title"], meta["author"], meta["description"], meta["tags"]) == ("New", "Me", "d", ["a", "b"])
    assert cover and Image.open(io.BytesIO(cover)).size[1] > 500                  # first page rendered as a JPEG
    from pypdf import PdfReader

    assert "test m" in str(PdfReader(p).metadata["/Producer"])                  # untouched fields survive the rewrite
    md.write_metadata(p, "pdf", {"title": "Only title"})                          # emptied fields are cleared
    assert md.read_metadata(p, "pdf")[0] == {"title": "Only title"}


def test_pdf_with_a_password_is_left_alone(tmp_path):
    from pypdf import PdfReader, PdfWriter

    def protected(user_pw: str):
        w = PdfWriter(clone_from=PdfReader(io.BytesIO(make_pdf(marker=user_pw or "empty"))))
        w.encrypt(user_pw, "owner", algorithm="RC4-128")
        f = tmp_path / f"locked-{user_pw or 'empty'}.pdf"
        with open(f, "wb") as fh:
            w.write(fh)
        return f

    locked = protected("secret")
    before = locked.read_bytes()
    assert md.read_metadata(locked, "pdf") == ({}, None)                          # cannot be read without the password
    assert md.write_metadata(locked, "pdf", {"title": "x"}) == set() and locked.read_bytes() == before
    open_pw = protected("")                                                       # empty user password: readable, still not rewritten
    assert md.read_metadata(open_pw, "pdf")[0]["title"] == "PDF Title"
    assert md.write_metadata(open_pw, "pdf", {"title": "x"}) == set()


def test_pdf_cover_is_best_effort(tmp_path, monkeypatch):
    import pypdfium2

    p = tmp_path / "a.pdf"
    p.write_bytes(make_pdf(marker="c"))

    def boom(*a, **k):
        raise RuntimeError("render failed")

    monkeypatch.setattr(pypdfium2, "PdfDocument", boom)
    meta, cover = md.read_metadata(p, "pdf")
    assert meta["title"] == "PDF Title" and cover is None                         # the metadata is still read
    monkeypatch.undo()
    monkeypatch.setitem(sys.modules, "pypdfium2", None)                           # library missing altogether
    assert md.read_metadata(p, "pdf")[1] is None


def test_pdf_without_pages_has_no_cover(tmp_path):
    from pypdf import PdfWriter

    p = tmp_path / "empty.pdf"
    with open(p, "wb") as fh:
        PdfWriter().write(fh)
    assert md._pdf_cover(p) is None


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
