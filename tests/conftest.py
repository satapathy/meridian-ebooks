import io
import os
import tempfile
import zipfile

import pytest

_tmp = tempfile.mkdtemp(prefix="meridian-test-")
os.environ["DATA_DIR"] = _tmp
os.environ["IMPORT_DIR"] = os.path.join(_tmp, "import")
os.makedirs(os.environ["IMPORT_DIR"], exist_ok=True)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    import shutil
    from app.config import settings

    with TestClient(app) as c:
        yield c
    shutil.rmtree(settings.library_dir, ignore_errors=True)
    settings.db_path.unlink(missing_ok=True)


def make_epub(title="The Test Book", author="Ann Author", subject="fantasy", marker="x") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
        z.writestr("OEBPS/content.opf",
                   '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="id">'
                   '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">'
                   f'<dc:title>{title}</dc:title><dc:creator opf:role="aut">{author}</dc:creator>'
                   f'<dc:subject>{subject}</dc:subject><dc:language>en</dc:language>'
                   '<dc:identifier id="id">urn:isbn:9780306406157</dc:identifier></metadata>'
                   '<manifest><item id="c" href="c.xhtml" media-type="application/xhtml+xml"/></manifest>'
                   '<spine><itemref idref="c"/></spine></package>')
        z.writestr("OEBPS/c.xhtml", f"<html><body>{marker}</body></html>")
    return buf.getvalue()


def make_pdf(title="PDF Title", author="Pat PDF", marker="x") -> bytes:
    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(612, 792)
    w.add_metadata({"/Title": title, "/Author": author, "/Keywords": "alpha, beta", "/Producer": f"test {marker}"})   # producer makes each file unique
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def make_docx(title="Docx Title", author="Dana Docx", marker="x") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("word/document.xml", f"<w:document xmlns:w='x'><w:body>{marker}</w:body></w:document>")
        z.writestr("docProps/core.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                   'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/">'
                   f'<dc:title>{title}</dc:title><dc:creator>{author}</dc:creator></cp:coreProperties>')
    return buf.getvalue()
