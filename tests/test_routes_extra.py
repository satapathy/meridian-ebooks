"""API behaviour not covered elsewhere: error responses, export, cleanup, server-side import, static files."""
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from app import main, service, uploads
from app.config import settings
from app.db import db
from app.storage import book_dir

from .conftest import make_docx, make_epub


def png_bytes(w=80, h=120, color=(10, 200, 10)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


def upload(client, data=None, name="a.epub", **kw):
    data = data or make_epub(**kw)
    r = client.post("/api/books/upload", files=[("files", (name, data))])
    assert r.status_code == 200, r.text
    res = r.json()["results"][0]
    assert res["status"] == "created", res
    return res["book_id"]


# ----------------------------------------------------------------------------- main app
def test_static_files_are_revalidated_and_index_is_served(client):
    r = client.get("/static/js/app.js")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
    r = client.get("/")
    assert r.status_code == 200 and "Meridian" in r.text and r.headers["cache-control"] == "no-cache"


def test_version_endpoint_reads_version_json(client, monkeypatch, tmp_path):
    d = client.get("/api/version").json()
    assert d["version"] and d["build"] is not None
    f = tmp_path / "version.json"
    f.write_text('{"version": "9.9.9", "build": 42}')
    monkeypatch.setattr(main, "VERSION_FILE", f)
    assert client.get("/api/version").json() == {"version": "9.9.9", "build": 42}
    f.write_text("not json")
    assert client.get("/api/version").json()["build"] is None          # unreadable file: still answers
    monkeypatch.setattr(main, "VERSION_FILE", tmp_path / "missing.json")
    assert client.get("/api/version").json()["build"] is None


def test_startup_removes_stale_temp_files():
    settings.tmp_dir.mkdir(parents=True, exist_ok=True)
    stale = settings.tmp_dir / "left-over.tmp"
    stale.write_bytes(b"x")
    with TestClient(main.app):
        assert not stale.exists()


def test_health_stats_and_facets(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    upload(client, title="Facet Book", author="A. One; B. Two", subject="scifi", marker="f1")
    s = client.get("/api/stats").json()
    assert s["books"] == 1 and s["authors"] == 2 and s["bytes"] > 0
    f = client.get("/api/facets").json()
    assert {a["name"] for a in f["authors"]} == {"A. One", "B. Two"} and f["formats"][0]["name"] == "epub"


# ----------------------------------------------------------------------------- books: error responses
def test_unknown_book_returns_404_everywhere(client):
    for method, path, kw in [
        ("get", "/api/books/nope/download", {}),
        ("get", "/api/books/nope/cover", {}),
        ("put", "/api/books/nope/cover", {"files": {"file": ("c.png", png_bytes(), "image/png")}}),
        ("delete", "/api/books/nope/cover", {}),
        ("patch", "/api/books/nope", {"json": {"title": "x"}}),
        ("post", "/api/books/nope/rename", {"json": {"filename": "x"}}),
        ("delete", "/api/books/nope", {}),
    ]:
        assert getattr(client, method)(path, **kw).status_code == 404, (method, path)


def test_download_reports_a_file_missing_from_disk(client):
    bid = upload(client, marker="d1")
    ok = client.get(f"/api/books/{bid}/download")
    assert ok.status_code == 200 and "attachment" in ok.headers["content-disposition"]
    assert "inline" in client.get(f"/api/books/{bid}/download?inline=true").headers["content-disposition"]
    (book_dir(bid) / client.get(f"/api/books/{bid}").json()["filename"]).unlink()
    assert client.get(f"/api/books/{bid}/download").status_code == 410


def test_cover_upload_rejects_garbage_and_cover_can_be_removed(client):
    bid = upload(client, marker="d2")
    assert client.put(f"/api/books/{bid}/cover", files={"file": ("c.png", b"not an image", "image/png")}).status_code == 400
    assert client.get(f"/api/books/{bid}/cover").status_code in (200, 404)
    assert client.delete(f"/api/books/{bid}/cover").status_code == 200


def test_patch_rejects_an_empty_title_and_bad_rating(client):
    bid = upload(client, marker="d3")
    assert client.patch(f"/api/books/{bid}", json={"title": "  "}).status_code == 400
    with pytest.raises(service.BadRequest):
        service.update_book(bid, {"rating": 9})
    assert service.update_book(bid, {"series_index": 2.5, "rating": 3})["series_index"] == 2.5


def test_bulk_update_reports_a_book_that_fails_validation(client, monkeypatch):
    a, b = upload(client, marker="d4"), upload(client, title="Other", marker="d5")
    real = service.update_book

    def flaky(bid, patch):
        if bid == b:
            raise service.BadRequest("nope")
        return real(bid, patch)

    monkeypatch.setattr(service, "update_book", flaky)
    d = client.post("/api/books/bulk-update", json={"ids": [a, b], "fields": {"publisher": "P"}}).json()
    assert d["updated"] == 1 and d["failed"] == [{"id": b, "error": "nope"}]


def test_rename_rules(client):
    bid = upload(client, marker="r1")
    book = client.get(f"/api/books/{bid}").json()
    assert client.post(f"/api/books/{bid}/rename", json={"filename": "   "}).status_code == 400
    same = client.post(f"/api/books/{bid}/rename", json={"filename": book["filename"]})
    assert same.status_code == 200 and same.json()["filename"] == book["filename"]          # no-op
    (book_dir(bid) / "taken.epub").write_bytes(b"x")
    assert client.post(f"/api/books/{bid}/rename", json={"filename": "taken"}).status_code == 409


def test_rename_moves_the_sidecar_and_cover_along(client):
    bid = upload(client, marker="r2")
    client.patch(f"/api/books/{bid}", json={"rating": 4, "publisher": "Side"})     # not embeddable -> sidecar file
    book = client.get(f"/api/books/{bid}").json()
    sidecar = book_dir(bid) / book["storage"]["sidecar_file"]
    assert sidecar.exists()
    r = client.post(f"/api/books/{bid}/rename", json={"filename": "renamed"})
    assert r.status_code == 200
    moved = book_dir(bid) / r.json()["storage"]["sidecar_file"]
    assert moved.exists() and json.loads(moved.read_text())["file"] == "renamed.epub"
    moved.write_text("{ broken json")                                               # a damaged sidecar must not block a rename
    assert client.post(f"/api/books/{bid}/rename", json={"filename": "again"}).status_code == 200


def test_list_filters(client):
    a = upload(client, title="Alpha", marker="l1")
    upload(client, title="Beta", marker="l2")
    client.patch(f"/api/books/{a}", json={"category": "Fiction", "subcategory": "Sci", "tags": ["x"], "series": "S1"})

    def titles(**params):
        return sorted(i["title"] for i in client.get("/api/books", params=params).json()["items"])

    assert titles(category="Uncategorized") == ["Beta"]
    assert titles(category="fiction") == ["Alpha"]
    assert titles(subcategory="sci") == ["Alpha"]
    assert titles(format="EPUB") == ["Alpha", "Beta"] and titles(format="pdf") == []
    assert titles(tag="x") == ["Alpha"] and titles(series="s1") == ["Alpha"]
    assert titles(q="http://nowhere") == []                      # unknown "field:" prefix is searched literally
    assert titles(q='""') == ["Alpha", "Beta"]                   # an empty term is ignored


# ----------------------------------------------------------------------------- export
def test_export_variants(client):
    a = upload(client, title="One", author="Zed Author", marker="e1")
    upload(client, data=make_docx(title="Two", author="", marker="e2"), name="two.docx")
    client.patch(f"/api/books/{a}", json={"category": "Fiction", "rating": 5})

    def names(**params):
        r = client.get("/api/export", params=params)
        assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
        return sorted(zipfile.ZipFile(io.BytesIO(r.content)).namelist()), int(r.headers["x-book-count"])

    by_cat, n = names()
    assert n == 2 and any(x.startswith("Fiction/") for x in by_cat) and any(x.startswith("Uncategorized/") for x in by_cat)
    assert any(x.endswith("-info.json") for x in by_cat)                       # sidecar included
    no_meta, _ = names(include_metadata="false")
    assert not any(x.endswith("-info.json") for x in no_meta)
    by_author, _ = names(group_by="author")
    assert any(x.startswith("Zed Author/") for x in by_author) and any(x.startswith("Unknown Author/") for x in by_author)
    assert names(format="docx")[1] == 1
    assert names(ids=[a])[1] == 1
    assert client.get("/api/export", params={"format": "pdf"}).status_code == 404         # nothing to export


def test_export_keeps_same_named_files_apart_and_includes_user_covers(client):
    ids = [upload(client, title=f"Twin {i}", marker=f"x{i}") for i in range(2)]
    for i in ids:
        client.patch(f"/api/books/{i}", json={"category": "Same"})
        client.post(f"/api/books/{i}/rename", json={"filename": "twin"})
    client.put(f"/api/books/{ids[0]}/cover", files={"file": ("c.png", png_bytes(), "image/png")})
    r = client.get("/api/export")
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert "Same/twin.epub" in names and "Same/twin (2).epub" in names
    assert any(n.endswith("-cover.jpg") for n in names)


def test_export_skips_rows_whose_file_is_gone(client):
    a = upload(client, marker="g1")
    upload(client, title="Kept", marker="g2")
    (book_dir(a) / client.get(f"/api/books/{a}").json()["filename"]).unlink()
    assert int(client.get("/api/export").headers["x-book-count"]) == 1


# ----------------------------------------------------------------------------- duplicates and cleanup
def test_duplicates_and_cleanup_dry_run_then_apply(client):
    a = upload(client, title="Orig", marker="u1")
    b = upload(client, title="Copy", marker="u2")
    c = upload(client, title="Lost", marker="u3")
    with db() as conn:                                                           # make b look like a copy of a
        conn.execute("UPDATE books SET current_md5=(SELECT md5 FROM books WHERE id=?) WHERE id=?", (a, b))
        conn.execute("UPDATE books SET added_at='2000-01-01T00:00:00+00:00' WHERE id=?", (a,))   # a is the oldest -> it is kept
    (book_dir(c) / client.get(f"/api/books/{c}").json()["filename"]).unlink()      # c lost its file
    orphan = settings.library_dir.joinpath(*["abcd"] * 8)
    orphan.mkdir(parents=True)
    (orphan / "stray.bin").write_bytes(b"1234")

    groups = client.get("/api/duplicates").json()["groups"]
    assert len(groups) == 1 and {x["id"] for x in groups[0]} == {a, b}
    dry = client.post("/api/cleanup").json()
    assert dry["dry_run"] and [d["id"] for d in dry["duplicates_removed"]] == [b]
    assert [m["id"] for m in dry["missing_file_rows_removed"]] == [c] and dry["orphan_folders_removed"] == ["abcd" * 8]
    assert client.get(f"/api/books/{b}").status_code == 200 and orphan.exists()          # dry run changed nothing

    done = client.post("/api/cleanup", params={"dry_run": "false"}).json()
    assert not done["dry_run"] and done["bytes_freed"] >= 4
    assert client.get(f"/api/books/{b}").status_code == 404 and client.get(f"/api/books/{c}").status_code == 404
    assert client.get(f"/api/books/{a}").status_code == 200 and not orphan.exists()


# ----------------------------------------------------------------------------- uploads
def zip_of(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def results(client, name, data, path=None, **form):
    """Upload through /upload-folder (the endpoint that expands archives and understands folder paths)."""
    r = client.post("/api/books/upload-folder", files=[("files", (name, data))], data={"relative_paths": path or name, **form})
    assert r.status_code == 200, r.text
    return r.json()["results"]


def test_zip_upload_handles_junk_unsupported_and_unsafe_members(client):
    data = zip_of({"good/one.epub": make_epub(title="Zipped", marker="z1"), "notes.xyz": b"?",
                   "../evil.epub": make_epub(marker="z2"), "__MACOSX/._one.epub": b"junk", "dir/": b""})
    res = results(client, "bundle.zip", data)
    by = {r["filename"]: r for r in res}
    assert by["bundle.zip/good/one.epub"]["status"] == "created"
    assert by["bundle.zip/notes.xyz"]["status"] == "skipped"
    assert not any("evil" in k for k in by)                                      # path traversal member ignored
    assert client.get("/api/books", params={"q": "Zipped"}).json()["total"] == 1


def test_zip_upload_errors(client, monkeypatch):
    assert results(client, "bad.zip", b"this is not a zip")[0]["detail"] == "Not a valid zip archive"
    assert results(client, "._hidden.zip", zip_of({"a.epub": make_epub(marker="z3")}))[0]["detail"] == "macOS metadata file"
    monkeypatch.setattr(settings, "max_archive_bytes", 10)
    assert results(client, "big.zip", zip_of({"a.epub": make_epub(marker="z4")}))[0]["detail"] == "Archive too large when expanded"


def test_upload_skips_unsupported_oversized_json_and_survives_errors(client, monkeypatch):
    assert results(client, "x.exe", b"MZ")[0]["detail"] == "Unsupported file type"
    monkeypatch.setattr(uploads, "MAX_JSON_BYTES", 5)
    assert results(client, "meta.json", b'{"title": "much longer than five bytes"}')[0]["detail"] == "JSON file too large"

    def boom(*a, **k):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(service, "ingest", boom)
    r = results(client, "a.epub", make_epub(marker="z5"))[0]
    assert r["status"] == "error" and "disk on fire" in r["detail"]


# ----------------------------------------------------------------------------- sidecar JSON import
def test_json_import_error_cases(client):
    j = lambda obj, name="m.json": results(client, name, obj if isinstance(obj, bytes) else json.dumps(obj).encode())[0]  # noqa: E731
    assert j(b"{ nope")["detail"] == "Not valid JSON"
    assert j([1, 2])["detail"] == "JSON must be an object"
    assert j({"nothing": "useful"})["status"] == "skipped"
    assert j({"title": "T", "rating": "abc"})["detail"].startswith("Invalid metadata")
    assert "No book" in j({"title": "No Such Book", "publisher": "P"})["detail"]


def test_json_import_disambiguates_by_folder_and_reports_ambiguity(client):
    for folder in ("one", "two"):
        results(client, "a.epub", make_epub(title="Same Title", marker=folder), path=f"{folder}/a.epub")
    body = json.dumps({"title": "Same Title", "publisher": "Pub"}).encode()
    amb = results(client, "m.json", body)[0]                                         # JSON at the root: two candidates
    assert amb["status"] == "error" and "Ambiguous" in amb["detail"]
    ok = results(client, "m.json", body, path="two/m.json")[0]                       # JSON next to one of them
    assert ok["status"] == "updated", ok


# ----------------------------------------------------------------------------- server-side import
def test_server_side_import_runs_as_a_job(client, monkeypatch):
    root = settings.import_dir / "shelf"
    (root / "Sci-Fi").mkdir(parents=True)
    (root / "Sci-Fi" / "a.epub").write_bytes(make_epub(title="Imported", marker="i1"))
    (root / "pack.zip").write_bytes(zip_of({"inner.epub": make_epub(title="Zip Imported", marker="i2")}))
    (root / "Sci-Fi" / "a-info.json").write_text(json.dumps({"title": "Imported", "publisher": "FromJson"}))
    (root / "readme.txt.bak").write_text("ignore me")

    job = client.post("/api/import", json={"path": "shelf", "category_from_folders": True}).json()
    done = client.get(f"/api/import/{job['id']}").json()
    assert done["status"] == "done" and done["total"] == 4 and done["processed"] == 4
    assert done["summary"]["created"] == 2
    got = client.get("/api/books", params={"q": "Imported"}).json()["items"]
    assert {b["title"] for b in got} == {"Imported", "Zip Imported"}
    assert next(b for b in got if b["title"] == "Imported")["publisher"] == "FromJson"

    def boom(*a, **k):
        raise RuntimeError("bad file")

    monkeypatch.setattr(uploads, "ingest_one", boom)
    (root / "later.epub").write_bytes(make_epub(marker="i3"))
    job2 = client.post("/api/import", json={"path": "shelf"}).json()
    final = client.get(f"/api/import/{job2['id']}").json()
    assert any("bad file" in e for e in final["errors"])


def test_server_side_import_rejects_bad_paths(client):
    assert client.post("/api/import", json={"path": "../../etc"}).status_code == 400
    assert client.post("/api/import", json={"path": "does-not-exist"}).status_code == 404
    assert client.get("/api/import/unknown").status_code == 404
