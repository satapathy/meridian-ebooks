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


def test_export_by_author_never_uses_a_nameless_folder(client):
    bid = _upload(client, "a.epub", make_epub(marker="x1"))["book_id"]
    client.patch(f"/api/books/{bid}", json={"author": "..."})
    r = client.get("/api/export", params={"group_by": "author"})
    assert r.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert all(not n.startswith("/") for n in names), names
    assert any(n.startswith("Unknown Author/") for n in names), names


def test_cleanup_does_not_delete_a_book_that_is_being_ingested(client, monkeypatch):
    import threading

    from app import metadata as md
    from app import service

    real = md.read_metadata
    outcome = {}

    def slow_read(path, ext):
        # cleanup(apply) starts while the new book's folder exists but its row doesn't yet
        t = threading.Thread(target=lambda: outcome.update(service.cleanup(dry_run=False)))
        t.start()
        t.join(0.5)  # with the lock held by ingest it must still be waiting
        outcome["thread"] = t
        return real(path, ext)

    monkeypatch.setattr(md, "read_metadata", slow_read)
    res = _upload(client, "a.epub", make_epub(title="Racy", marker="race"))
    outcome["thread"].join(10)
    assert res["status"] == "created"
    b = client.get(f"/api/books/{res['book_id']}")
    assert b.status_code == 200
    assert client.get(f"/api/books/{res['book_id']}/download").status_code == 200
    assert outcome["orphan_folders_removed"] == []


# --------------------------------------------------------------------------- bulk update + all sort columns
def test_bulk_update_sets_chosen_fields_only(client):
    ids = []
    for i in range(3):
        r = client.post("/api/books/upload", files=[("files", (f"b{i}.epub", make_epub(title=f"Bulk {i}", author="A. Writer", marker=f"bk{i}")))])
        ids.append(r.json()["results"][0]["book_id"])
    client.patch(f"/api/books/{ids[0]}", json={"tags": ["keep"], "publisher": "Orig"})
    r = client.post("/api/books/bulk-update", json={"ids": ids + ["missing"], "fields": {"category": "Sci-Fi", "subcategory": "Space"}})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["updated"] == 3 and d["failed"] == [{"id": "missing", "error": "Book not found"}]
    for b in d["books"]:
        assert (b["category"], b["subcategory"], b["author"]) == ("Sci-Fi", "Space", "A. Writer")
    assert client.get(f"/api/books/{ids[0]}").json()["publisher"] == "Orig"                      # untouched field kept
    # tags: add keeps each book's own tags, replace overwrites; an empty string clears a field
    client.post("/api/books/bulk-update", json={"ids": ids, "fields": {"tags": "new, extra"}, "tags_mode": "add"})
    assert client.get(f"/api/books/{ids[0]}").json()["tags"] == ["keep", "new", "extra"]
    client.post("/api/books/bulk-update", json={"ids": ids, "fields": {"tags": ["only"]}})
    assert client.get(f"/api/books/{ids[0]}").json()["tags"] == ["only"]
    client.post("/api/books/bulk-update", json={"ids": ids, "fields": {"subcategory": ""}})
    assert client.get(f"/api/books/{ids[1]}").json()["subcategory"] == ""
    assert client.post("/api/books/bulk-update", json={"ids": ids, "fields": {}}).status_code == 400
    assert client.post("/api/books/bulk-update", json={"ids": ids, "fields": {"rating": 9}}).status_code in (400, 422)
    assert client.post("/api/books/bulk-update", json={"ids": [], "fields": {"category": "x"}}).status_code == 422


def test_every_list_column_is_sortable(client):
    client.post("/api/books/upload", files=[("files", ("s.epub", make_epub(title="Sortable", marker="so1")))])
    for key in ("title", "subtitle", "author", "series", "series_index", "category", "subcategory", "tags", "publisher",
                "published", "language", "isbn", "rating", "format", "size", "added", "filename", "description"):
        for group in ("false", "true"):
            r = client.get("/api/books", params={"sort": key, "order": "asc", "group_series": group})
            assert r.status_code == 200 and r.json()["total"] == 1, (key, group, r.text)
