"""Suggest category, sub-category and tags for a book from public sites.

Sources (no API key needed):
* Google Books  - `categories` such as "Fiction / Science Fiction / General" -> category + sub-category
* Open Library  - `subject` list -> tags

Nothing is ever saved here: callers get *suggestions* for fields that are currently empty, and the user
accepts them (through the normal PATCH endpoint). A lookup sends only a book's title, author and ISBN.
"""
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .db import db
from .service import split_authors

log = logging.getLogger("meridian.lookup")

GOOGLE_URL = "https://www.googleapis.com/books/v1/volumes"
OPENLIB_URL = "https://openlibrary.org/search.json"
USER_AGENT = "MeridianEbooks/1.0 (self-hosted ebook library)"
TIMEOUT = 8
MIN_GAP = 0.35          # seconds between outgoing requests - be polite, and stay inside free-tier limits
MAX_CACHE = 2000


class LookupUnavailable(Exception):
    """The remote service could not be reached (offline, rate limited, server error)."""


_cache: dict[str, dict] = {}
_lock = threading.Lock()
_last_call = 0.0


def clear_cache() -> None:
    with _lock:
        _cache.clear()
        _img_cache.clear()


def _http_json(url: str) -> dict:
    """GET a JSON document (cached per URL, throttled). Patched in the tests."""
    global _last_call
    with _lock:
        if url in _cache:
            return _cache[url]
        wait = MIN_GAP - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        raise LookupUnavailable("rate limited by the service" if exc.code == 429 else f"service error {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise LookupUnavailable("service not reachable") from exc
    with _lock:
        if len(_cache) >= MAX_CACHE:
            _cache.clear()
        _cache[url] = data
    return data


# --------------------------------------------------------------------------- matching helpers
def _tokens(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (s or "").lower())


def _main_title(s: str) -> str:
    """Title without its subtitle: 'Dune: The Desert Planet' / 'The Hobbit, or There and Back Again' -> main part."""
    return " ".join(_tokens(re.split(r":|\(|, or ", s or "", maxsplit=1)[0]))


def title_matches(mine: str, theirs: str) -> bool:
    """Equal main titles only - 'Dune' must not match its sequel 'Dune Messiah'."""
    a, b = _main_title(mine), _main_title(theirs)
    return bool(a) and a == b


def authors_match(mine: list[str], theirs: list[str]) -> bool:
    if not mine or not theirs:  # nothing to compare against - the title match has to do
        return True
    def key(name: str) -> tuple[str, str]:  # (surname, first initial or "")
        t = _tokens(name)
        return (t[-1], t[0][0] if len(t) > 1 else "") if t else ("", "")

    for a in map(key, mine):
        for b in map(key, theirs):
            if a[0] and a[0] == b[0] and (not a[1] or not b[1] or a[1] == b[1]):  # "F. Herbert" ~ "Frank Herbert"
                return True
    return False


def clean_isbn(isbn: str) -> str:
    s = re.sub(r"[^0-9Xx]", "", isbn or "")
    return s.upper() if len(s) in (10, 13) else ""


# --------------------------------------------------------------------------- Google Books -> category
_PLACEHOLDER = {"general", ""}


def split_google_category(raw: str) -> tuple[str, str]:
    """'Fiction / Science Fiction / General' -> ('Science Fiction', ''); 'Computers / Programming / Java' -> ('Computers', 'Programming')."""
    parts = [p.strip() for p in (raw or "").split("/")]
    parts = [p for p in parts if p.lower() not in _PLACEHOLDER]
    if not parts:
        return "", ""
    if parts[0].lower() == "fiction" and len(parts) > 1:
        parts = parts[1:]
    return parts[0][:80], (parts[1][:80] if len(parts) > 1 else "")


def _google_image(links: dict) -> tuple[str, str]:
    """(preferred, original) cover URLs from Google's imageLinks: https, no page-curl, larger zoom first."""
    raw = (links or {}).get("thumbnail") or (links or {}).get("smallThumbnail") or ""
    if not raw:
        return "", ""
    raw = re.sub(r"^http://", "https://", raw).replace("&edge=curl", "")
    return re.sub(r"zoom=\d", "zoom=2", raw), raw


def google_lookup(book: dict, want_category: bool = True, want_cover: bool = False) -> dict | None:
    isbn = clean_isbn(book.get("isbn", ""))
    authors = split_authors(book.get("author", ""))
    if isbn:
        q, trusted = f"isbn:{isbn}", True
    else:
        title = _main_title(book.get("title", ""))
        if not title:
            return None
        q = f'intitle:"{title}"' + (f' inauthor:"{authors[0]}"' if authors else "")
        trusted = False
    url = GOOGLE_URL + "?" + urllib.parse.urlencode(
        {"q": q, "maxResults": 5, "printType": "books",
         "fields": "items(volumeInfo(title,authors,categories,imageLinks))"})
    for item in _http_json(url).get("items") or []:
        info = item.get("volumeInfo") or {}
        category, sub = split_google_category((info.get("categories") or [""])[0])
        cover, cover_alt = _google_image(info.get("imageLinks") or {})
        if not ((want_category and category) or (want_cover and cover)):
            continue
        if not trusted and not (title_matches(book.get("title", ""), info.get("title", ""))
                                and authors_match(authors, info.get("authors") or [])):
            continue
        return {"category": category, "subcategory": sub, "cover_url": cover, "cover_url_alt": cover_alt,
                "matched": info.get("title", ""), "confidence": "isbn" if trusted else "title"}
    return None


# --------------------------------------------------------------------------- Open Library -> tags
_NOISE = re.compile(r"accessible|daisy|large type|in library|open library|reading level|overdrive|nyt:|internet archive|"
                    r"lending library|protected", re.I)


def clean_subjects(subjects: list[str], limit: int = 5) -> list[str]:
    out, seen = [], set()
    for s in subjects or []:
        s = re.sub(r"\s+", " ", str(s)).strip()
        key = s.lower()
        if not s or len(s) > 40 or key in seen or key == "fiction" or _NOISE.search(s):
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= limit:
            break
    return out


def openlibrary_lookup(book: dict, want_tags: bool = True, want_cover: bool = False) -> dict | None:
    isbn = clean_isbn(book.get("isbn", ""))
    authors = split_authors(book.get("author", ""))
    params = {"limit": 5, "fields": "title,author_name,subject,cover_i"}
    if isbn:
        params["isbn"], trusted = isbn, True
    else:
        title = _main_title(book.get("title", ""))
        if not title:
            return None
        params["title"], trusted = title, False
        if authors:
            params["author"] = authors[0]
    for doc in _http_json(OPENLIB_URL + "?" + urllib.parse.urlencode(params)).get("docs") or []:
        tags = clean_subjects(doc.get("subject") or [])
        cover_id = doc.get("cover_i")
        cover = f"https://covers.openlibrary.org/b/id/{int(cover_id)}-L.jpg" if isinstance(cover_id, int) and cover_id > 0 else ""
        if not ((want_tags and tags) or (want_cover and cover)):
            continue
        if not trusted and not (title_matches(book.get("title", ""), doc.get("title", ""))
                                and authors_match(authors, doc.get("author_name") or [])):
            continue
        return {"tags": tags, "cover_url": cover, "cover_url_alt": "",
                "matched": doc.get("title", ""), "confidence": "isbn" if trusted else "title"}
    return None


# --------------------------------------------------------------------------- cover images
ALLOWED_IMAGE_HOSTS = {"books.google.com", "books.googleusercontent.com", "covers.openlibrary.org", "archive.org"}
MAX_IMAGE_BYTES = 6 * 1024 * 1024
MIN_COVER_W, MIN_COVER_H = 100, 140          # anything smaller is a placeholder or a thumbnail icon
_img_cache: "dict[str, bytes]" = {}           # url -> normalised JPEG (small, insertion-ordered)
MAX_IMG_CACHE = 40


def image_host_allowed(url: str) -> bool:
    """Only https URLs on the cover hosts we know. Cover URLs come from third-party JSON, so never fetch blindly."""
    p = urllib.parse.urlparse(url)
    host = (p.hostname or "").lower()
    return p.scheme == "https" and (host in ALLOWED_IMAGE_HOSTS or host.endswith(".archive.org"))


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not image_host_allowed(newurl):
            raise urllib.error.URLError(f"redirect to a host that is not allowed: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _http_bytes(url: str) -> bytes:
    """Download an image (size-capped, throttled). Patched in the tests."""
    global _last_call
    if not image_host_allowed(url):
        raise LookupUnavailable("image host not allowed")
    with _lock:
        wait = MIN_GAP - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "image/*"})
    try:
        with urllib.request.build_opener(_SafeRedirect).open(req, timeout=TIMEOUT) as r:
            if not (r.headers.get("Content-Type") or "").lower().startswith("image/"):
                raise LookupUnavailable("not an image")
            data = r.read(MAX_IMAGE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise LookupUnavailable(f"image service error {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LookupUnavailable("image not reachable") from exc
    if len(data) > MAX_IMAGE_BYTES:
        raise LookupUnavailable("image too large")
    return data


def _download_cover(url: str) -> bytes | None:
    """A normalised JPEG of a usable cover, or None (error, too small, not decodable)."""
    if url in _img_cache:
        return _img_cache[url]
    from . import metadata as md

    try:
        jpeg = md.make_cover_jpeg(_http_bytes(url), max_height=1400)
    except LookupUnavailable as exc:
        log.info("cover download skipped: %s", exc)
        return None
    if not jpeg:
        return None
    from io import BytesIO

    from PIL import Image

    w, h = Image.open(BytesIO(jpeg)).size
    if w < MIN_COVER_W or h < MIN_COVER_H:
        return None
    with _lock:
        if len(_img_cache) >= MAX_IMG_CACHE:
            _img_cache.pop(next(iter(_img_cache)))
        _img_cache[url] = jpeg
    return jpeg


def get_cover(book: dict) -> dict | None:
    """Best cover found online: {"jpeg", "source", "matched", "confidence"}, or None.
    Raises LookupUnavailable only when neither site could be reached."""
    unreachable = 0
    finders = (("Google Books", lambda: google_lookup(book, want_category=False, want_cover=True)),
               ("Open Library", lambda: openlibrary_lookup(book, want_tags=False, want_cover=True)))
    for source, find in finders:
        try:
            hit = find()
        except LookupUnavailable:
            unreachable += 1
            continue
        for url in dict.fromkeys(u for u in ((hit or {}).get("cover_url"), (hit or {}).get("cover_url_alt")) if u):
            jpeg = _download_cover(url)
            if jpeg:
                return {"jpeg": jpeg, "source": source, "matched": hit["matched"], "confidence": hit["confidence"]}
    if unreachable == len(finders):
        raise LookupUnavailable("service not reachable")
    return None


# --------------------------------------------------------------------------- combine
def suggest(book: dict, existing_categories: dict[str, str] | None = None, overwrite: bool = False) -> dict:
    """Suggestion for the *empty* fields of one book (all fields with overwrite=True, for an explicit per-book fetch).

    Returns {"suggestion": {...} | None, "reason": str}. Raises LookupUnavailable only when no source answered.
    `existing_categories` maps lower-case -> the library's own spelling, so "science fiction" reuses "Science Fiction".
    """
    existing_categories = existing_categories or {}
    need_cat = overwrite or not (book.get("category") or "").strip()
    need_sub = overwrite or not (book.get("subcategory") or "").strip()
    need_tags = overwrite or not book.get("tags")
    if not (need_cat or need_sub or need_tags):
        return {"suggestion": None, "reason": "Category, sub-category and tags are already set"}

    errors, g, o = [], None, None
    if need_cat or need_sub:
        try:
            g = google_lookup(book)
        except LookupUnavailable as exc:
            errors.append(f"Google Books: {exc}")
    if need_tags:
        try:
            o = openlibrary_lookup(book)
        except LookupUnavailable as exc:
            errors.append(f"Open Library: {exc}")
    asked = (need_cat or need_sub) + need_tags
    if len(errors) >= asked:
        raise LookupUnavailable("; ".join(errors))

    sug: dict = {}
    sources, matched, confidence = [], "", ""
    if g:
        cat = existing_categories.get(g["category"].lower(), g["category"])
        if need_cat:
            sug["category"] = cat
        if need_sub and g["subcategory"] and (need_cat or (book.get("category") or "").lower() == cat.lower()):
            sug["subcategory"] = g["subcategory"]
        if sug:
            sources.append("Google Books")
            matched, confidence = g["matched"], g["confidence"]
    if o and need_tags:
        sug["tags"] = o["tags"]
        sources.append("Open Library")
        matched, confidence = matched or o["matched"], confidence or o["confidence"]
    if not sug:
        return {"suggestion": None, "reason": "No match found" + (f" ({'; '.join(errors)})" if errors else "")}
    sug.update(source=" + ".join(sources), matched=matched, confidence=confidence)
    return {"suggestion": sug, "reason": ""}


# --------------------------------------------------------------------------- batch helpers
def candidates(only_missing: bool = True, fields: tuple[str, ...] = ("category",), limit: int = 5000) -> list[dict]:
    """Books worth looking up: those without a category and/or without any cover, depending on `fields`
    (with only_missing=False, every book - suggestions are still only made for fields that are empty)."""
    conds = [c for f, c in (("category", "category = ''"), ("cover", "has_cover = 0")) if f in fields]
    where = (" WHERE " + " OR ".join(conds)) if (only_missing and conds) else ""
    with db() as conn:
        rows = conn.execute(f"SELECT id, title, author, isbn FROM books{where} ORDER BY title COLLATE NOCASE LIMIT ?",
                            (limit,)).fetchall()
    return [dict(r) for r in rows]


def existing_categories() -> dict[str, str]:
    with db() as conn:
        rows = conn.execute("SELECT DISTINCT category FROM books WHERE category != ''").fetchall()
    return {r[0].lower(): r[0] for r in rows}
