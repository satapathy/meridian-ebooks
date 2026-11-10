import pytest

from app import lookup
from app.config import settings

from .conftest import make_epub


def _upload(client, name, data):
    r = client.post("/api/books/upload", files=[("files", (name, data))])
    assert r.status_code == 200, r.text
    return r.json()["results"][0]["book_id"]


def png(w=300, h=450, color=(200, 40, 40)) -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture()
def fake_net(monkeypatch):
    """Replace the network: `.google` / `.openlib` hold the JSON each site answers with, `.images` maps url -> bytes."""
    state = type("S", (), {"google": {}, "openlib": {}, "urls": [], "down": False, "images": {}, "image_urls": []})()
    lookup.clear_cache()

    def fake(url):
        state.urls.append(url)
        if state.down:
            raise lookup.LookupUnavailable("service not reachable")
        return state.google if "googleapis" in url else state.openlib

    def fake_bytes(url):
        state.image_urls.append(url)
        if state.down or url not in state.images:
            raise lookup.LookupUnavailable("image not reachable")
        return state.images[url]

    monkeypatch.setattr(lookup, "_http_json", fake)
    monkeypatch.setattr(lookup, "_http_bytes", fake_bytes)
    yield state
    lookup.clear_cache()


def test_split_google_category():
    f = lookup.split_google_category
    assert f("Fiction / Science Fiction / General") == ("Science Fiction", "")
    assert f("Fiction / Fantasy / Epic") == ("Fantasy", "Epic")
    assert f("Computers / Programming / Java") == ("Computers", "Programming")
    assert f("History") == ("History", "")
    assert f("Fiction / General") == ("Fiction", "")
    assert f("General") == ("", "")  # only a placeholder -> nothing useful
    assert f("") == ("", "")


def test_title_and_author_matching():
    assert lookup.title_matches("Dune", "Dune: The Desert Planet")
    assert lookup.title_matches("The Hobbit", "The Hobbit, or There and Back Again")
    assert not lookup.title_matches("Dune", "Dune Messiah")  # a sequel is a different book
    assert lookup.authors_match(["Frank Herbert"], ["F. Herbert"])
    assert not lookup.authors_match(["Frank Herbert"], ["Isaac Asimov"])
    assert lookup.authors_match([], ["Anyone"])


def test_clean_subjects_drops_noise():
    raw = ["Fiction", "Desert planets", "Accessible book", "Protected DAISY", "desert planets", "Ecology",
           "x" * 60, "Large type books", "Political science"]
    assert lookup.clean_subjects(raw) == ["Desert planets", "Ecology", "Political science"]


def test_suggest_by_isbn_fills_only_empty_fields(client, fake_net):
    bid = _upload(client, "a.epub", make_epub(title="Dune", marker="l1"))  # has an ISBN and the tag "fantasy"
    fake_net.google = {"items": [{"volumeInfo": {"title": "Dune", "authors": ["Frank Herbert"],
                                                 "categories": ["Fiction / Science Fiction / Space Opera"]}}]}
    fake_net.openlib = {"docs": [{"title": "Dune", "subject": ["Desert planets"]}]}
    book = client.get(f"/api/books/{bid}").json()
    out = lookup.suggest(book)
    s = out["suggestion"]
    assert (s["category"], s["subcategory"], s["confidence"]) == ("Science Fiction", "Space Opera", "isbn")
    assert "tags" not in s                      # the book already has the tag "fantasy"
    assert any("isbn%3A9780306406157" in u for u in fake_net.urls)
    assert not any("openlibrary" in u for u in fake_net.urls)  # tags weren't needed -> no request


def test_suggest_by_title_rejects_wrong_matches(client, fake_net):
    bid = _upload(client, "a.epub", make_epub(title="Dune", author="Frank Herbert", marker="l2"))
    client.patch(f"/api/books/{bid}", json={"isbn": "", "tags": []})
    fake_net.google = {"items": [
        {"volumeInfo": {"title": "Dune Messiah", "authors": ["Frank Herbert"], "categories": ["Fiction / Wrong"]}},
        {"volumeInfo": {"title": "Dune", "authors": ["Brian Herbert"], "categories": ["Fiction / Wrong Author"]}},
        {"volumeInfo": {"title": "Dune: Deluxe", "authors": ["Frank Herbert"], "categories": ["Fiction / Science Fiction"]}},
    ]}
    fake_net.openlib = {"docs": [{"title": "Other Book", "author_name": ["Frank Herbert"], "subject": ["Nope"]},
                                 {"title": "Dune", "author_name": ["Frank Herbert"], "subject": ["Desert planets", "Ecology"]}]}
    s = lookup.suggest(client.get(f"/api/books/{bid}").json())["suggestion"]
    assert s["category"] == "Science Fiction" and s["confidence"] == "title"
    assert s["tags"] == ["Desert planets", "Ecology"]
    assert s["source"] == "Google Books + Open Library"


def test_suggest_reuses_the_librarys_category_spelling(client, fake_net):
    bid = _upload(client, "a.epub", make_epub(title="Dune", marker="l3"))
    fake_net.google = {"items": [{"volumeInfo": {"title": "Dune", "categories": ["Fiction / science fiction"]}}]}
    s = lookup.suggest(client.get(f"/api/books/{bid}").json(), {"science fiction": "Sci-Fi"})["suggestion"]
    assert s["category"] == "Sci-Fi"


def test_endpoints_preview_then_accept(client, fake_net):
    a = _upload(client, "a.epub", make_epub(title="Dune", marker="l4"))
    b = _upload(client, "b.epub", make_epub(title="Has Category", marker="l5"))
    client.patch(f"/api/books/{b}", json={"category": "Mine"})
    fake_net.google = {"items": [{"volumeInfo": {"title": "Dune", "categories": ["Fiction / Science Fiction"]}}]}

    assert client.get("/api/lookup/status").json()["enabled"] is True
    cands = client.get("/api/lookup/candidates").json()
    assert [c["id"] for c in cands["items"]] == [a]            # only the uncategorised book
    assert client.get("/api/lookup/candidates", params={"only_missing": "false"}).json()["total"] == 2

    r = client.post("/api/lookup/suggest", json={"ids": [a, b]}).json()
    by_id = {x["id"]: x for x in r["results"]}
    assert by_id[a]["suggestion"]["category"] == "Science Fiction"
    # b has its own category ("Mine"), so a sub-category from a *different* category is not offered
    assert by_id[b]["suggestion"] is None and by_id[b]["reason"]

    # previewing changed nothing
    assert client.get(f"/api/books/{a}").json()["category"] == ""
    # accepting = the ordinary PATCH
    client.patch(f"/api/books/{a}", json={"category": by_id[a]["suggestion"]["category"]})
    assert client.get(f"/api/books/{a}").json()["category"] == "Science Fiction"


def test_unreachable_service_is_reported_not_crashed(client, fake_net):
    a = _upload(client, "a.epub", make_epub(title="Dune", marker="l6"))
    b = _upload(client, "b.epub", make_epub(title="Other", marker="l7"))
    fake_net.down = True
    r = client.post("/api/lookup/suggest", json={"ids": [a, b]})
    assert r.status_code == 200
    body = r.json()
    assert body["unavailable"] and all(x["suggestion"] is None for x in body["results"])
    assert len(fake_net.urls) == 1                               # stopped after the first failure


GBOOK = "http://books.google.com/books/content?id=ABC&printsec=frontcover&img=1&zoom=1&edge=curl&source=gbs_api"
GBOOK2 = "https://books.google.com/books/content?id=ABC&printsec=frontcover&img=1&zoom=2&source=gbs_api"
GBOOK1 = "https://books.google.com/books/content?id=ABC&printsec=frontcover&img=1&zoom=1&source=gbs_api"
OL = "https://covers.openlibrary.org/b/id/777-L.jpg"


def google_with_cover(title="Dune"):
    return {"items": [{"volumeInfo": {"title": title, "authors": ["Frank Herbert"], "imageLinks": {"thumbnail": GBOOK}}}]}


def test_google_image_url_is_upgraded():
    assert lookup._google_image({"thumbnail": GBOOK}) == (GBOOK2, GBOOK1)
    assert lookup._google_image({}) == ("", "")


def test_only_known_https_hosts_are_fetched():
    ok = lookup.image_host_allowed
    assert ok("https://books.google.com/x.jpg") and ok("https://covers.openlibrary.org/b/id/1-L.jpg")
    assert ok("https://ia800000.us.archive.org/x.jpg")
    assert not ok("http://books.google.com/x.jpg")              # not https
    assert not ok("https://evil.example/x.jpg")
    assert not ok("https://books.google.com.evil.example/x.jpg")
    assert not ok("file:///etc/passwd")
    with pytest.raises(lookup.LookupUnavailable):               # the real downloader refuses before any network access
        lookup._http_bytes("https://evil.example/x.jpg")


def test_get_cover_prefers_google_and_falls_back_to_the_smaller_image(client, fake_net):
    bid = _upload(client, "a.epub", make_epub(title="Dune", marker="c1"))
    fake_net.google = google_with_cover()
    fake_net.images = {GBOOK1: png()}                            # zoom=2 is missing -> original URL is used
    c = lookup.get_cover(client.get(f"/api/books/{bid}").json())
    assert c["source"] == "Google Books" and c["confidence"] == "isbn" and c["jpeg"][:2] == b"\xff\xd8"
    assert fake_net.image_urls == [GBOOK2, GBOOK1]


def test_get_cover_falls_back_to_open_library(client, fake_net):
    bid = _upload(client, "a.epub", make_epub(title="Dune", marker="c2"))
    fake_net.google = {"items": [{"volumeInfo": {"title": "Dune"}}]}            # no image
    fake_net.openlib = {"docs": [{"title": "Dune", "cover_i": 777, "subject": []}]}
    fake_net.images = {OL: png()}
    c = lookup.get_cover(client.get(f"/api/books/{bid}").json())
    assert c["source"] == "Open Library"


def test_tiny_or_missing_images_are_rejected(client, fake_net):
    bid = _upload(client, "a.epub", make_epub(title="Dune", marker="c3"))
    book = client.get(f"/api/books/{bid}").json()
    fake_net.google = google_with_cover()
    fake_net.images = {GBOOK2: png(40, 60), GBOOK1: b"not an image"}   # placeholder-sized, then garbage
    assert lookup.get_cover(book) is None


def test_cover_endpoint_preview_then_keep(client, fake_net):
    bid = _upload(client, "a.epub", make_epub(title="Dune", marker="c4"))
    fake_net.google = google_with_cover()
    fake_net.images = {GBOOK2: png()}
    r = client.get(f"/api/lookup/cover/{bid}")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert r.headers["x-cover-source"] == "Google Books" and r.headers["x-cover-confidence"] == "isbn"
    assert client.get(f"/api/books/{bid}").json()["cover_source"] is None          # previewing saved nothing
    kept = client.put(f"/api/books/{bid}/cover", files={"file": ("c.jpg", r.content, "image/jpeg")}).json()
    assert kept["cover_source"] == "user" and kept["has_cover"]


def test_cover_endpoint_not_found_and_unreachable(client, fake_net):
    bid = _upload(client, "a.epub", make_epub(title="Dune", marker="c5"))
    assert client.get(f"/api/lookup/cover/{bid}").status_code == 404
    fake_net.down = True
    assert client.get(f"/api/lookup/cover/{bid}").status_code == 503
    assert client.get("/api/lookup/cover/nope").status_code == 404


def test_suggest_covers_only_for_books_without_one_unless_overwrite(client, fake_net):
    a = _upload(client, "a.epub", make_epub(title="Dune", marker="c6"))
    b = _upload(client, "b.epub", make_epub(title="Dune", marker="c7"))
    client.put(f"/api/books/{b}/cover", files={"file": ("c.png", png(), "image/png")})     # b already has a cover
    fake_net.google = google_with_cover()
    fake_net.images = {GBOOK2: png()}
    cands = client.get("/api/lookup/candidates", params={"fields": "cover"}).json()
    assert [c["id"] for c in cands["items"]] == [a]
    r = client.post("/api/lookup/suggest", json={"ids": [a, b], "fields": ["cover"]}).json()
    by = {x["id"]: x for x in r["results"]}
    assert by[a]["cover"]["source"] == "Google Books" and by[a]["suggestion"] is None
    assert by[b]["cover"] is None
    r = client.post("/api/lookup/suggest", json={"ids": [b], "fields": ["cover"], "overwrite": True}).json()
    assert r["results"][0]["cover"]["source"] == "Google Books"


def test_per_book_category_fetch_can_overwrite(client, fake_net):
    bid = _upload(client, "a.epub", make_epub(title="Dune", marker="c8"))
    client.patch(f"/api/books/{bid}", json={"category": "Old", "subcategory": "Old sub"})
    fake_net.google = {"items": [{"volumeInfo": {"title": "Dune", "categories": ["Fiction / Science Fiction / Space Opera"]}}]}
    plain = client.post("/api/lookup/suggest", json={"ids": [bid]}).json()["results"][0]
    assert plain["suggestion"] is None                                          # nothing empty -> nothing to suggest
    forced = client.post("/api/lookup/suggest", json={"ids": [bid], "overwrite": True}).json()["results"][0]
    assert (forced["suggestion"]["category"], forced["suggestion"]["subcategory"]) == ("Science Fiction", "Space Opera")


def test_lookup_can_be_disabled(client, monkeypatch):
    monkeypatch.setattr(settings, "online_lookup", False)
    assert client.get("/api/lookup/status").json()["enabled"] is False
    assert client.get("/api/lookup/candidates").status_code == 403
    assert client.post("/api/lookup/suggest", json={"ids": ["x"]}).status_code == 403
