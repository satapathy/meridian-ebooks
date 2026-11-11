"""Advanced bulk edit: the text operations and the /books/bulk-transform endpoint."""
import pytest

from app import service, textops

from .conftest import make_epub


@pytest.mark.parametrize("op, text, expected", [
    ("lowercase", "The LORD of Rings", "the lord of rings"),
    ("uppercase", "dune messiah", "DUNE MESSIAH"),
    ("capitalize", "  the LORD of the rings ", "The lord of the rings"),
    ("capitalize", "   ", "   "),
    ("titlecase", "the lord of the rings", "The Lord of the Rings"),
    ("titlecase", "THE HITCHHIKER'S GUIDE TO THE GALAXY", "The Hitchhiker's Guide to the Galaxy"),
    ("titlecase", "a tale of two cities: the story of a state-of-the-art war", "A Tale of Two Cities: The Story of a State-of-the-Art War"),
    ("titlecase", "what we talk about when we talk about love", "What We Talk About When We Talk About Love"),
    ("titlecase", "mcDonald and iPhone fans", "mcDonald and iPhone Fans"),            # mixed-case words are left alone
    ("titlecase", "chapter 7 - the end of it", "Chapter 7 - the End of It"),
    ("collapse_spaces", "Too    many \t spaces  here", "Too many spaces here"),
    ("collapse_spaces", "line one  \nline  two", "line one \nline two"),                # line breaks survive
    ("trim", "  padded \n", "padded"),
])
def test_text_operations(op, text, expected):
    assert textops.apply(op, text) == expected


def test_replace_words_options():
    r = textops.replace_words
    assert r("Dune: The Illustrated Edition", "illustrated", "Special") == "Dune: The Special Edition"     # case-insensitive
    assert r("Dune: The Illustrated Edition", "illustrated", "x", case_sensitive=True) == "Dune: The Illustrated Edition"
    assert r("cat concatenate cat", "cat", "dog") == "dog concatenate dog"                                  # whole words only
    assert r("cat concatenate cat", "cat", "dog", whole_words=False) == "dog condogenate dog"
    assert r("Title (Ebook) Extra", "(Ebook)", "") == "Title Extra"                                         # removal tidies spaces
    assert r("a.b (x) a.b", "a.b", "-") == "- (x) -"                                                        # literal text, never a regex
    assert r("x", "x", "$1\\g<0>") == "$1\\g<0>"                                                            # replacement is literal too


def test_unknown_operation_is_rejected():
    with pytest.raises(ValueError):
        textops.apply("explode", "x")


def upload(client, **kw):
    r = client.post("/api/books/upload", files=[("files", ("a.epub", make_epub(**kw)))])
    return r.json()["results"][0]["book_id"]


def test_bulk_transform_updates_only_books_that_change(client):
    a = upload(client, title="placeholder", marker="t1")
    client.patch(f"/api/books/{a}", json={"title": "the  lord of the rings"})
    b = upload(client, title="Already Fine", marker="t2")
    r = client.post("/api/books/bulk-transform", json={"ids": [a, b, "nope"], "field": "title", "operation": "titlecase"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["updated"] == 1 and d["unchanged"] == 1 and d["failed"] == [{"id": "nope", "error": "Book not found"}]
    assert client.get(f"/api/books/{a}").json()["title"] == "The  Lord of the Rings"
    r = client.post("/api/books/bulk-transform", json={"ids": [a], "field": "title", "operation": "collapse_spaces"})
    assert r.json()["books"][0]["title"] == "The Lord of the Rings"


def test_bulk_transform_replace_and_tags(client):
    a = upload(client, title="Dune (Ebook)", marker="t3")
    client.patch(f"/api/books/{a}", json={"tags": ["Sci-Fi ", "CLASSIC", "classic"], "publisher": "Ace Books"})
    body = {"ids": [a], "field": "title", "operation": "replace", "find": "(Ebook)", "replace_with": ""}
    assert client.post("/api/books/bulk-transform", json=body).json()["books"][0]["title"] == "Dune"
    r = client.post("/api/books/bulk-transform", json={"ids": [a], "field": "tags", "operation": "lowercase"})
    assert client.get(f"/api/books/{a}").json()["tags"] == ["sci-fi", "classic"]                  # transformed per tag, de-duplicated
    r = client.post("/api/books/bulk-transform", json={"ids": [a], "field": "publisher", "operation": "replace",
                                                      "find": "books", "replace_with": "Press"})
    assert r.json()["books"][0]["publisher"] == "Ace Press"


def test_bulk_transform_validation(client):
    a = upload(client, marker="t4")
    base = {"ids": [a], "field": "title"}
    assert client.post("/api/books/bulk-transform", json={**base, "operation": "replace"}).status_code == 400      # nothing to find
    assert client.post("/api/books/bulk-transform", json={**base, "operation": "explode"}).status_code == 422
    assert client.post("/api/books/bulk-transform", json={"ids": [a], "field": "isbn", "operation": "trim"}).status_code == 422
    assert client.post("/api/books/bulk-transform", json={"ids": [], "field": "title", "operation": "trim"}).status_code == 422


def test_bulk_transform_reports_books_that_fail(client, monkeypatch):
    a = upload(client, title="padded", marker="t5")

    def refuse(bid, patch):
        raise service.BadRequest("Title cannot be empty")

    monkeypatch.setattr(service, "update_book", refuse)
    d = client.post("/api/books/bulk-transform", json={"ids": [a], "field": "title", "operation": "titlecase"}).json()
    assert d["updated"] == 0 and d["failed"] == [{"id": a, "error": "Title cannot be empty"}]
