import io
import json
import zipfile

from .conftest import make_epub


def _upload(client, name, data, **form):
    r = client.post("/api/books/upload", files=[("files", (name, data))], data=form)
    assert r.status_code == 200, r.text
    return r.json()["results"][0]


def test_author_filter_matches_semicolon_without_space(client):
    bid = _upload(client, "a.epub", make_epub(marker="a1"))["book_id"]
    client.patch(f"/api/books/{bid}", json={"author": "Ann;Bob"})
    names = {a["name"] for a in client.get("/api/facets").json()["authors"]}
    assert {"Ann", "Bob"} <= names
    for who in ("Ann", "Bob"):  # every author listed in the facets must be filterable
        assert client.get("/api/books", params={"author": who}).json()["total"] == 1, who
    assert client.get(f"/api/books/{bid}").json()["author"] == "Ann; Bob"  # stored normalised


def test_json_import_accepts_numbers_and_lists(client):
    bid = _upload(client, "a.epub", make_epub(title="Numbers", marker="n1"))["book_id"]
    payload = {"id": bid, "metadata": {"published": 1965, "isbn": 9780306406157, "publisher": 42,
                                         "tags": ["x", 7], "series_index": 2}}
    r = _upload(client, "a-info.json", json.dumps(payload).encode(), overwrite_json="true")  # sample epub has tag "fantasy"
    assert r["status"] == "updated", r
    b = client.get(f"/api/books/{bid}").json()
    assert b["published"] == "1965" and b["isbn"] == "9780306406157" and b["publisher"] == "42"
    assert b["tags"] == ["x", "7"]


def test_macos_junk_in_zip_is_not_imported(client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Lib/real.epub", make_epub(title="Real", marker="r1"))
        z.writestr("__MACOSX/Lib/._real.epub", b"\x00\x05\x16\x07 apple double junk")
        z.writestr("Lib/._other.epub", b"\x00\x05\x16\x07 apple double junk")
    r = client.post("/api/books/upload-folder", files=[("files", ("lib.zip", buf.getvalue()))],
                    data={"relative_paths": "lib.zip"})
    assert r.status_code == 200, r.text
    assert r.json()["summary"]["created"] == 1
    assert client.get("/api/books").json()["total"] == 1
