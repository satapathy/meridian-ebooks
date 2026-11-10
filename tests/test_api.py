import io
import json
import re
import zipfile

from app.config import settings
from app.search import parse_query

from .conftest import make_docx, make_epub, make_pdf


def upload(client, name, data, **form):
    r = client.post("/api/books/upload", files=[("files", (name, data))], data=form)
    assert r.status_code == 200, r.text
    return r.json()["results"][0]


def test_upload_assigns_uuid_and_flat_layout(client):
    res = upload(client, "my-book.epub", make_epub())
    assert res["status"] == "created"
    bid = res["book_id"]
    assert re.fullmatch(r"[0-9a-f]{32}", bid)
    book = client.get(f"/api/books/{bid}").json()
    assert book["title"] == "The Test Book" and book["author"] == "Ann Author"
    assert book["isbn"] == "9780306406157" and book["tags"] == ["fantasy"]
    expected = "/".join(bid[i:i + 4] for i in range(0, 32, 4)) + "/my-book.epub"
    assert book["path"] == expected
    assert (settings.library_dir / expected).is_file()


def test_duplicate_detection_by_md5(client):
    data = make_epub(marker="same")
    assert upload(client, "a.epub", data)["status"] == "created"
    dup = upload(client, "renamed-copy.epub", data)
    assert dup["status"] == "duplicate"
    assert client.get("/api/stats").json()["books"] == 1


def test_duplicate_still_detected_after_metadata_was_rewritten(client):
    data = make_epub(marker="orig")
    bid = upload(client, "a.epub", data)["book_id"]
    client.patch(f"/api/books/{bid}", json={"title": "Changed"})
    assert upload(client, "again.epub", data)["status"] == "duplicate"


def test_epub_metadata_written_into_file_and_title_does_not_rename(client):
    bid = upload(client, "orig-name.epub", make_epub())["book_id"]
    r = client.patch(f"/api/books/{bid}", json={"title": "New Title", "author": ["A One", "B Two"],
                                                  "tags": "x, y", "category": "Sci-Fi", "rating": 4})
    assert r.status_code == 200
    b = r.json()
    assert b["filename"] == "orig-name.epub"  # untouched
    assert {"title", "author", "tags"} <= set(b["storage"]["embedded"])
    assert set(b["storage"]["sidecar"]) == {"category", "isbn", "rating"}
    from app.metadata import read_metadata
    meta, _ = read_metadata(settings.library_dir / b["path"], "epub")
    assert meta["title"] == "New Title" and meta["author"] == "A One; B Two" and meta["tags"] == ["x", "y"]
    sidecar = settings.library_dir / b["path"].replace("orig-name.epub", "orig-name-info.json")
    assert json.loads(sidecar.read_text())["metadata"]["category"] == "Sci-Fi"


def test_pdf_and_docx_embed(client):
    from app.metadata import read_metadata
    pid = upload(client, "p.pdf", make_pdf())["book_id"]
    did = upload(client, "d.docx", make_docx())["book_id"]
    pb = client.patch(f"/api/books/{pid}", json={"title": "PT", "tags": ["one", "two"]}).json()
    db_ = client.patch(f"/api/books/{did}", json={"title": "DT", "category": "Docs"}).json()
    assert read_metadata(settings.library_dir / pb["path"], "pdf")[0]["title"] == "PT"
    assert read_metadata(settings.library_dir / db_["path"], "docx")[0]["category"] == "Docs"
    assert "category" in db_["storage"]["embedded"]
    assert pb["has_cover"]  # first page rendered


def test_sidecar_only_format(client):
    bid = upload(client, "plain_story.txt", b"once upon a time")["book_id"]
    b = client.patch(f"/api/books/{bid}", json={"author": "Anon", "category": "Tales"}).json()
    assert b["storage"]["embedded"] == []
    side = settings.library_dir / b["path"].replace("plain_story.txt", "plain_story-info.json")
    data = json.loads(side.read_text())
    assert data["metadata"]["author"] == "Anon" and data["storage"] == "sidecar"


def test_rename_file_independent_of_title(client):
    bid = upload(client, "plain_story.txt", b"abc")["book_id"]
    b = client.post(f"/api/books/{bid}/rename", json={"filename": "better name.txt"}).json()
    assert b["filename"] == "better name.txt" and b["title"] == "plain story"
    assert (settings.library_dir / b["path"]).is_file()
    assert (settings.library_dir / b["path"].replace("better name.txt", "better name-info.json")).is_file()
    assert client.post(f"/api/books/{bid}/rename", json={"filename": "../../etc/x"}).json()["filename"] == "x.txt"


def test_wildcard_search(client):
    upload(client, "1.epub", make_epub(title="The Lord of the Rings", author="J. R. R. Tolkien", marker="1"))
    upload(client, "2.epub", make_epub(title="Dune", author="Frank Herbert", subject="scifi", marker="2"))
    upload(client, "3.pdf", make_pdf(title="Ring Theory", author="Someone", marker="3"))

    def q(s):
        return {b["title"] for b in client.get("/api/books", params={"q": s}).json()["items"]}

    assert q("tolk*") == {"The Lord of the Rings"}
    assert q("title:*ring*") == {"The Lord of the Rings", "Ring Theory"}
    assert q("title:D?ne") == {"Dune"}
    assert q("ring -format:pdf") == {"The Lord of the Rings"}
    assert q('"lord of"') == {"The Lord of the Rings"}
    assert q("tag:scifi author:herb*") == {"Dune"}
    assert q("100%") == set()  # % is literal, not a wildcard


def test_folder_upload_and_zip_and_unsupported(client):
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w") as z:
        z.writestr("deep/er/zipped.epub", make_epub(title="Zipped", marker="z"))
    files = [
        ("files", ("a.epub", make_epub(title="A", marker="a"))),
        ("files", ("b.pdf", make_pdf(title="B", marker="b"))),
        ("files", ("cover.jpg", b"notabook")),
        ("files", ("pack.zip", zbuf.getvalue())),
    ]
    paths = ["Lib/Fantasy/a.epub", "Lib/Fantasy/Deep/b.pdf", "Lib/cover.jpg", "Lib/Misc/pack.zip"]
    r = client.post("/api/books/upload-folder", files=files, data={"relative_paths": paths}).json()
    assert r["summary"]["created"] == 3 and r["summary"]["skipped"] == 1
    cats = {b["title"]: b["category"] for b in client.get("/api/books").json()["items"]}
    assert cats["A"] == "Fantasy" and cats["B"] == "Deep" and cats["Zipped"] == "er"


def test_export_by_category_and_author(client):
    upload(client, "a.epub", make_epub(title="A", author="Zed", marker="a"), category="Alpha")
    upload(client, "b.epub", make_epub(title="B", author="Yan; Xi", marker="b"))
    r = client.get("/api/export", params={"group_by": "category"})
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert "Alpha/a.epub" in names and "Uncategorized/b.epub" in names and "Alpha/a-info.json" in names
    r = client.get("/api/export", params={"group_by": "author", "include_metadata": "false"})
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert sorted(names) == ["Yan/b.epub", "Zed/a.epub"]


def test_cleanup_orphans_and_duplicates(client):
    a = upload(client, "a.epub", make_epub(marker="a"))["book_id"]
    orphan = settings.library_dir / "/".join(["dead"] * 8)
    orphan.mkdir(parents=True)
    (orphan / "x.epub").write_bytes(b"1234")
    dry = client.post("/api/cleanup").json()
    assert dry["dry_run"] and "".join(["dead"] * 8) in dry["orphan_folders_removed"] and orphan.exists()
    done = client.post("/api/cleanup", params={"dry_run": "false"}).json()
    assert not orphan.exists() and not (settings.library_dir / "dead").exists()
    assert client.get(f"/api/books/{a}").status_code == 200


def test_delete_prunes_folders(client):
    bid = upload(client, "a.epub", make_epub())["book_id"]
    assert client.delete(f"/api/books/{bid}").status_code == 204
    assert client.get(f"/api/books/{bid}").status_code == 404
    assert not any(settings.library_dir.iterdir())


def test_query_parser():
    sql, params = parse_query('author:tolk* -"audio book"')
    assert sql.count("LIKE") == 1 + len(__import__("app.search", fromlist=["x"]).ANY_FIELDS) and sql.endswith(")") and "NOT" in sql
    assert params[0] == "%tolk%%"


def test_subcategory_edit_search_and_filter(client):
    bid = upload(client, "a.epub", make_epub(marker="sub"), category="Fantasy")["book_id"]
    b = client.patch(f"/api/books/{bid}", json={"subcategory": "Epic"}).json()
    assert b["subcategory"] == "Epic" and "subcategory" in b["storage"]["sidecar"]
    assert client.get("/api/books", params={"q": "sub:ep*"}).json()["total"] == 1
    assert client.get("/api/books", params={"subcategory": "epic"}).json()["total"] == 1
    assert client.get("/api/books", params={"subcategory": "other"}).json()["total"] == 0


def test_migration_adds_subcategory_column(client):
    import sqlite3
    from app.db import init_db
    con = sqlite3.connect(settings.db_path)
    con.execute("ALTER TABLE books DROP COLUMN subcategory")
    con.commit(); con.close()
    init_db()
    con = sqlite3.connect(settings.db_path)
    assert "subcategory" in {r[1] for r in con.execute("PRAGMA table_info(books)")}
    con.close()


def test_json_import_matching_diffs_overwrite_and_ordering(client):
    upload(client, "dune.epub", make_epub(title="Dune", author="Frank Herbert", marker="d"))
    bid = client.get("/api/books", params={"q": "dune"}).json()["items"][0]["id"]

    def imp(name, payload, **form):
        r = client.post("/api/books/upload", files=[("files", (name, json.dumps(payload).encode()))], data=form)
        assert r.status_code == 200, r.text
        return r.json()["results"][0]

    # matched by title; empty fields are filled in without any warning
    r = imp("dune-info.json", {"metadata": {"title": "Dune", "category": "SciFi", "rating": 5}})
    assert r["status"] == "updated" and r["book_id"] == bid
    assert client.get(f"/api/books/{bid}").json()["category"] == "SciFi"

    # existing differing value: warning with diffs, nothing applied
    r = imp("dune-info.json", {"metadata": {"title": "Dune", "category": "Classics"}})
    assert r["status"] == "warning"
    assert r["diffs"] == [{"field": "category", "current": "SciFi", "imported": "Classics"}]
    assert client.get(f"/api/books/{bid}").json()["category"] == "SciFi"
    # identical -> nothing to do
    assert imp("x.json", {"metadata": {"title": "Dune", "category": "SciFi"}})["status"] == "skipped"
    # explicit overwrite applies it
    assert imp("dune-info.json", {"metadata": {"title": "Dune", "category": "Classics"}},
               overwrite_json="true")["status"] == "updated"
    assert client.get(f"/api/books/{bid}").json()["category"] == "Classics"

    # unmatched / invalid
    assert imp("nope.json", {"metadata": {"title": "No Such Book", "category": "x"}})["status"] == "skipped"
    bad = client.post("/api/books/upload", files=[("files", ("bad.json", b"{oops"))]).json()["results"][0]
    assert bad["status"] == "error"

    # folder upload: JSON listed *before* its book is still applied, because books go first
    sidecar = json.dumps({"metadata": {"title": "The Hobbit", "subcategory": "Epic"}}).encode()
    files = [("files", ("hobbit-info.json", sidecar)),
             ("files", ("hobbit.epub", make_epub(title="The Hobbit", marker="h")))]
    rep = client.post("/api/books/upload-folder", files=files,
                      data={"relative_paths": ["Lib/hobbit-info.json", "Lib/hobbit.epub"]}).json()
    assert [r["status"] for r in rep["results"]] == ["created", "updated"]
    assert client.get("/api/books", params={"q": "hobbit"}).json()["items"][0]["subcategory"] == "Epic"


def test_json_overrides_folder_derived_category_without_warning(client):
    files = [("files", ("b.epub", make_epub(title="Folder Book", marker="fb"))),
             ("files", ("b-info.json", json.dumps({"metadata": {"title": "Folder Book", "category": "Real"}}).encode()))]
    rep = client.post("/api/books/upload-folder", files=files,
                      data={"relative_paths": ["Lib/b.epub", "Lib/b-info.json"]}).json()
    assert [r["status"] for r in rep["results"]] == ["created", "updated"]
    assert client.get("/api/books").json()["items"][0]["category"] == "Real"


def _png(color, size=(120, 80)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def test_user_cover_overrides_embedded_and_lives_next_to_json(client):
    from PIL import Image
    bid = upload(client, "doc.pdf", make_pdf(marker="cov"))["book_id"]
    b = client.get(f"/api/books/{bid}").json()
    assert b["cover_source"] == "embedded"
    embedded = client.get(f"/api/books/{bid}/cover").content

    b = client.put(f"/api/books/{bid}/cover", files={"file": ("c.png", _png((250, 0, 0)))}).json()
    assert b["cover_source"] == "user" and b["has_cover"]
    folder = (settings.library_dir / b["path"]).parent
    assert (folder / "doc-cover.jpg").is_file() and (folder / "cover.jpg").is_file()  # both kept
    served = client.get(f"/api/books/{bid}/cover").content
    assert served != embedded
    px = Image.open(io.BytesIO(served)).getpixel((10, 10))
    assert px[0] > 200 and px[1] < 60  # the red user cover is what is shown

    # follows a file rename; exported next to the sidecar
    client.post(f"/api/books/{bid}/rename", json={"filename": "renamed"})
    assert (folder / "renamed-cover.jpg").is_file() and not (folder / "doc-cover.jpg").exists()
    names = zipfile.ZipFile(io.BytesIO(client.get("/api/export").content)).namelist()
    assert "Uncategorized/renamed-cover.jpg" in names

    # removing it falls back to the embedded cover
    b = client.delete(f"/api/books/{bid}/cover").json()
    assert b["cover_source"] == "embedded" and client.get(f"/api/books/{bid}/cover").content == embedded

    # a book with no embedded cover: user cover, then removal -> no cover at all
    tid = upload(client, "t.txt", b"x")["book_id"]
    assert client.get(f"/api/books/{tid}").json()["cover_source"] is None
    client.put(f"/api/books/{tid}/cover", files={"file": ("c.png", _png((0, 0, 255)))})
    assert client.delete(f"/api/books/{tid}/cover").json()["has_cover"] is False
    assert client.get(f"/api/books/{tid}/cover").status_code == 404
    assert client.put(f"/api/books/{tid}/cover", files={"file": ("bad.png", b"nope")}).status_code == 400
