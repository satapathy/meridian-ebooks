"""Reading and writing metadata *inside* ebook files (EPUB, PDF, DOCX).

Other formats cannot be modified safely, so their metadata lives in a
`<book-name>-info.json` sidecar (handled by the service layer).
"""
import io
import logging
import os
import posixpath
import re
import zipfile
from pathlib import Path
from urllib.parse import unquote

from lxml import etree

log = logging.getLogger("meridian.metadata")

FIELDS = [
    "title", "author", "publisher", "description", "language", "published",
    "isbn", "tags", "category", "subcategory", "series", "series_index", "rating",
]

# Fields each format can carry inside the file itself.
EMBEDDABLE: dict[str, set[str]] = {
    "epub": {"title", "author", "publisher", "description", "language", "published", "tags", "series", "series_index"},
    "pdf": {"title", "author", "description", "tags"},
    "docx": {"title", "author", "description", "tags", "category", "language"},
}

_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
_TAG_RE = re.compile(r"<[^>]+>")
_ISBN_RE = re.compile(r"(97[89])?\d{9}[\dXx]")


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", text or "")).strip()


def _split_list(text: str) -> list[str]:
    return [t.strip() for t in re.split(r"[;,]", text or "") if t.strip()]


def title_from_filename(filename: str) -> str:
    stem = os.path.splitext(filename)[0]
    return re.sub(r"\s+", " ", re.sub(r"[_]+", " ", stem)).strip() or stem


# --------------------------------------------------------------------------- EPUB
_EPUB_NS = {
    "c": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
}
_DC = _EPUB_NS["dc"]
_OPF = _EPUB_NS["opf"]


def _epub_opf_path(z: zipfile.ZipFile) -> str:
    root = etree.fromstring(z.read("META-INF/container.xml"), _PARSER)
    rf = root.find(".//c:rootfile", _EPUB_NS)
    if rf is None:
        raise ValueError("EPUB has no rootfile")
    return rf.get("full-path")


def _read_epub(path: Path) -> tuple[dict, bytes | None]:
    with zipfile.ZipFile(path) as z:
        opf_path = _epub_opf_path(z)
        root = etree.fromstring(z.read(opf_path), _PARSER)
        md = root.find("opf:metadata", _EPUB_NS)
        if md is None:
            return {}, None

        def texts(tag: str) -> list[str]:
            return [_clean(e.text) for e in md.findall(f"dc:{tag}", _EPUB_NS) if _clean(e.text)]

        def meta_content(name: str) -> str:
            vals = md.xpath("opf:meta[@name=$n]/@content", namespaces=_EPUB_NS, n=name)
            return str(vals[0]).strip() if vals else ""

        meta: dict = {
            "title": (texts("title") or [""])[0],
            "author": "; ".join(texts("creator")),
            "publisher": (texts("publisher") or [""])[0],
            "description": " ".join(texts("description")),
            "language": (texts("language") or [""])[0],
            "published": (texts("date") or [""])[0][:10],
            "tags": texts("subject"),
            "series": meta_content("calibre:series"),
        }
        idx = meta_content("calibre:series_index")
        if idx:
            try:
                meta["series_index"] = float(idx)
            except ValueError:
                pass
        for ident in texts("identifier"):
            cleaned = re.sub(r"^urn:isbn:", "", ident, flags=re.I).replace("-", "").strip()
            if _ISBN_RE.fullmatch(cleaned):
                meta["isbn"] = cleaned
                break

        cover = None
        try:
            manifest = root.find("opf:manifest", _EPUB_NS)
            href = None
            if manifest is not None:
                for item in manifest.findall("opf:item", _EPUB_NS):
                    if "cover-image" in (item.get("properties") or "").split():
                        href = item.get("href")
                        break
                if not href:
                    cid = meta_content("cover")
                    for item in manifest.findall("opf:item", _EPUB_NS):
                        if cid and item.get("id") == cid:
                            href = item.get("href")
                            break
            if href:
                full = posixpath.normpath(posixpath.join(posixpath.dirname(opf_path), unquote(href)))
                cover = z.read(full)
        except Exception:  # cover is best-effort
            cover = None
        return {k: v for k, v in meta.items() if v not in ("", [], None)}, cover


def _write_epub(path: Path, meta: dict) -> set[str]:
    tmp = path.with_name(path.name + ".tmp")
    with zipfile.ZipFile(path) as zin:
        opf_path = _epub_opf_path(zin)
        root = etree.fromstring(zin.read(opf_path), _PARSER)
        md = root.find("opf:metadata", _EPUB_NS)
        if md is None:
            raise ValueError("EPUB has no metadata block")

        def set_dc(tag: str, values: list[str]) -> None:
            for e in md.findall(f"dc:{tag}", _EPUB_NS):
                md.remove(e)
            for v in values:
                if v:
                    etree.SubElement(md, f"{{{_DC}}}{tag}").text = v

        def set_meta(name: str, value: str) -> None:
            for e in md.xpath("opf:meta[@name=$n]", namespaces=_EPUB_NS, n=name):
                md.remove(e)
            if value:
                etree.SubElement(md, f"{{{_OPF}}}meta", name=name, content=value)

        authors = [a.strip() for a in (meta.get("author") or "").split(";") if a.strip()]
        set_dc("title", [meta.get("title") or ""])
        set_dc("creator", authors)
        set_dc("publisher", [meta.get("publisher") or ""])
        set_dc("description", [meta.get("description") or ""])
        set_dc("language", [meta.get("language") or ""])
        set_dc("date", [meta.get("published") or ""])
        set_dc("subject", list(meta.get("tags") or []))
        set_meta("calibre:series", meta.get("series") or "")
        idx = meta.get("series_index")
        set_meta("calibre:series_index", ("%g" % idx) if (idx is not None and meta.get("series")) else "")
        new_opf = etree.tostring(root, xml_declaration=True, encoding="utf-8")

        with zipfile.ZipFile(tmp, "w") as zout:
            for info in zin.infolist():
                data = new_opf if info.filename == opf_path else zin.read(info.filename)
                zout.writestr(info, data)
    os.replace(tmp, path)
    return set(EMBEDDABLE["epub"])


# --------------------------------------------------------------------------- PDF
def _read_pdf(path: Path) -> tuple[dict, bytes | None]:
    import pymupdf

    doc = pymupdf.open(path)
    try:
        if doc.needs_pass:
            return {}, None
        md = doc.metadata or {}
        meta = {
            "title": _clean(md.get("title")),
            "author": _clean(md.get("author")),
            "description": _clean(md.get("subject")),
            "tags": _split_list(md.get("keywords") or ""),
        }
        cover = None
        try:
            if doc.page_count:
                pix = doc.load_page(0).get_pixmap(matrix=pymupdf.Matrix(0.9, 0.9))
                cover = pix.tobytes("jpeg")
        except Exception:
            cover = None
        return {k: v for k, v in meta.items() if v not in ("", [], None)}, cover
    finally:
        doc.close()


def _write_pdf(path: Path, meta: dict) -> set[str]:
    import pymupdf

    tmp = path.with_name(path.name + ".tmp")
    doc = pymupdf.open(path)
    try:
        if doc.needs_pass:
            return set()
        current = doc.metadata or {}
        keep = {k: current.get(k) or "" for k in ("producer", "creator", "creationDate", "modDate", "trapped")}
        keep.update(
            title=meta.get("title") or "",
            author=meta.get("author") or "",
            subject=meta.get("description") or "",
            keywords=", ".join(meta.get("tags") or []),
        )
        doc.set_metadata(keep)
        doc.save(tmp, garbage=0, deflate=True)
    finally:
        doc.close()
    os.replace(tmp, path)
    return set(EMBEDDABLE["pdf"])


# --------------------------------------------------------------------------- DOCX
_CP = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
_DCT = "http://purl.org/dc/terms/"
_CORE = "docProps/core.xml"


def _read_docx(path: Path) -> tuple[dict, bytes | None]:
    with zipfile.ZipFile(path) as z:
        if _CORE not in z.namelist():
            return {}, None
        root = etree.fromstring(z.read(_CORE), _PARSER)

    def get(ns: str, tag: str) -> str:
        e = root.find(f"{{{ns}}}{tag}")
        return _clean(e.text) if e is not None else ""

    meta = {
        "title": get(_DC, "title"),
        "author": get(_DC, "creator"),
        "description": get(_DC, "description") or get(_DC, "subject"),
        "tags": _split_list(get(_CP, "keywords")),
        "category": get(_CP, "category"),
        "language": get(_DC, "language"),
    }
    return {k: v for k, v in meta.items() if v not in ("", [], None)}, None


def _write_docx(path: Path, meta: dict) -> set[str]:
    tmp = path.with_name(path.name + ".tmp")
    with zipfile.ZipFile(path) as zin:
        if _CORE not in zin.namelist():
            return set()
        root = etree.fromstring(zin.read(_CORE), _PARSER)

        def put(ns: str, tag: str, value: str) -> None:
            e = root.find(f"{{{ns}}}{tag}")
            if not value:
                if e is not None:
                    root.remove(e)
                return
            if e is None:
                e = etree.SubElement(root, f"{{{ns}}}{tag}")
            e.text = value

        put(_DC, "title", meta.get("title") or "")
        put(_DC, "creator", meta.get("author") or "")
        put(_DC, "description", meta.get("description") or "")
        put(_CP, "keywords", ", ".join(meta.get("tags") or []))
        put(_CP, "category", meta.get("category") or "")
        put(_DC, "language", meta.get("language") or "")
        new_core = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
        with zipfile.ZipFile(tmp, "w") as zout:
            for info in zin.infolist():
                zout.writestr(info, new_core if info.filename == _CORE else zin.read(info.filename))
    os.replace(tmp, path)
    return set(EMBEDDABLE["docx"])


# --------------------------------------------------------------------------- public API
_READERS = {"epub": _read_epub, "pdf": _read_pdf, "docx": _read_docx}
_WRITERS = {"epub": _write_epub, "pdf": _write_pdf, "docx": _write_docx}


def read_metadata(path: Path, ext: str) -> tuple[dict, bytes | None]:
    """Return (metadata found in the file, cover image bytes or None). Never raises."""
    reader = _READERS.get(ext)
    if not reader:
        return {}, None
    try:
        return reader(path)
    except Exception as exc:
        log.warning("could not read %s metadata from %s: %s", ext, path.name, exc)
        return {}, None


def write_metadata(path: Path, ext: str, meta: dict) -> set[str]:
    """Write metadata into the file. Returns the set of fields now stored inside it
    (empty if the format is unsupported or the write failed - caller falls back to a sidecar)."""
    writer = _WRITERS.get(ext)
    if not writer:
        return set()
    try:
        return writer(path, meta)
    except Exception as exc:
        log.warning("could not write %s metadata into %s: %s", ext, path.name, exc)
        tmp = path.with_name(path.name + ".tmp")
        if tmp.exists():
            tmp.unlink()
        return set()


def make_cover_jpeg(data: bytes, max_height: int = 600) -> bytes | None:
    """Normalise any cover image to a bounded-size JPEG."""
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(data))
        img = img.convert("RGB")
        if img.height > max_height:
            img = img.resize((max(1, round(img.width * max_height / img.height)), max_height), Image.LANCZOS)
        out = io.BytesIO()
        img.save(out, "JPEG", quality=82, optimize=True)
        return out.getvalue()
    except Exception as exc:
        log.warning("cover conversion failed: %s", exc)
        return None
