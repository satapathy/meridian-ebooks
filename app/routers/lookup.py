from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .. import lookup, service
from ..config import settings

router = APIRouter(prefix="/lookup", tags=["Lookup"])


def _require_enabled() -> None:
    if not settings.online_lookup:
        raise HTTPException(403, "Online lookup is disabled on this server (ONLINE_LOOKUP=off)")


class LookupStatus(BaseModel):
    enabled: bool
    sources: list[str]


class Candidate(BaseModel):
    id: str
    title: str
    author: str
    isbn: str


class CandidateList(BaseModel):
    total: int
    items: list[Candidate]


class SuggestRequest(BaseModel):
    ids: list[str] = Field(..., min_length=1, max_length=10, description="Book ids to look up (keep batches small)")
    fields: list[Literal["category", "cover"]] = Field(
        ["category"], description="`category` = category, sub-category and tags; `cover` = look for a cover image")
    overwrite: bool = Field(False, description="Also suggest for fields that already have a value (an explicit per-book fetch)")


class Suggestion(BaseModel):
    category: Optional[str] = Field(None, description="Only present when the book has no category yet")
    subcategory: Optional[str] = None
    tags: Optional[list[str]] = Field(None, description="Only present when the book has no tags yet")
    source: str
    matched: str = Field("", description="Title of the record that was matched on the public site")
    confidence: str = Field("", description="'isbn' (exact) or 'title' (title + author match)")


class CoverFound(BaseModel):
    source: str
    matched: str = ""
    confidence: str = ""


class SuggestResult(BaseModel):
    id: str
    title: str
    author: str
    suggestion: Optional[Suggestion] = None
    cover: Optional[CoverFound] = Field(None, description="A cover was found: fetch the image from `GET /lookup/cover/{id}`")
    reason: str = ""


class SuggestResponse(BaseModel):
    results: list[SuggestResult]
    unavailable: Optional[str] = Field(None, description="Set when the public sites could not be reached; remaining ids were not looked up")


@router.get("/status", response_model=LookupStatus, summary="Is online lookup enabled?")
def status():
    return {"enabled": settings.online_lookup, "sources": ["Google Books", "Open Library"]}


@router.get("/candidates", response_model=CandidateList, summary="Books to look up",
            description="By default the books that have no category. Use these ids with `POST /lookup/suggest`.")
def candidates(
    only_missing: bool = Query(True, description="Only books missing what `fields` asks for (otherwise every book)"),
    fields: list[Literal["category", "cover"]] = Query(["category"], description="`category` = no category; `cover` = no cover at all"),
):
    _require_enabled()
    items = lookup.candidates(only_missing, tuple(fields))
    return {"total": len(items), "items": items}


@router.post(
    "/suggest", response_model=SuggestResponse, summary="Suggest category, sub-category and tags from public sites",
    description=(
        "Looks each book up on **Google Books** (category / sub-category) and **Open Library** (tags) by ISBN, or by "
        "title and author when there is no ISBN. Only the title, author and ISBN of the books you list are sent.\n\n"
        "**Nothing is saved.** Suggestions are only returned for fields that are currently empty (unless `overwrite`). "
        "Apply the ones you accept with `PATCH /books/{id}`; for a cover, download `GET /lookup/cover/{id}` and send it "
        "to `PUT /books/{id}/cover`."
    ),
)
def suggest(body: SuggestRequest):
    _require_enabled()
    cats = lookup.existing_categories()
    want_cat, want_cover = "category" in body.fields, "cover" in body.fields
    results, unavailable = [], None
    for bid in body.ids:
        try:
            book = service.get_book(bid)
        except service.BookNotFound:
            raise HTTPException(404, f"Book not found: {bid}")
        row = {"id": bid, "title": book["title"], "author": book["author"]}
        if unavailable:
            results.append({**row, "reason": "Not looked up (service unreachable)"})
            continue
        try:
            entry = dict(row)
            if want_cat:
                entry.update(lookup.suggest(book, cats, body.overwrite))
            if want_cover and (body.overwrite or not book["has_cover"]):
                c = lookup.get_cover(book)
                entry["cover"] = {k: c[k] for k in ("source", "matched", "confidence")} if c else None
            if not entry.get("suggestion") and not entry.get("cover") and not entry.get("reason"):
                entry["reason"] = "No cover found" if want_cover and not want_cat else "Nothing to look up"
            results.append(entry)
        except lookup.LookupUnavailable as exc:
            unavailable = str(exc)
            results.append({**row, "reason": f"Not looked up ({exc})"})
    return {"results": results, "unavailable": unavailable}


@router.get(
    "/cover/{book_id}", summary="Find a cover for one book online (returns the image, saves nothing)",
    responses={200: {"content": {"image/jpeg": {}}}, 404: {"description": "No cover found"},
               503: {"description": "Google Books / Open Library not reachable"}},
    description="Searches Google Books then Open Library and returns the first usable cover as a JPEG, with the source in "
                "`X-Cover-Source`, the matched title in `X-Cover-Matched` and `X-Cover-Confidence` (`isbn` or `title`). "
                "To keep it, send the image to `PUT /books/{id}/cover`.",
)
def find_cover(book_id: str):
    _require_enabled()
    try:
        book = service.get_book(book_id)
    except service.BookNotFound:
        raise HTTPException(404, "Book not found")
    try:
        c = lookup.get_cover(book)
    except lookup.LookupUnavailable as exc:
        raise HTTPException(503, f"Could not reach the cover services ({exc})")
    if not c:
        raise HTTPException(404, "No cover found online")
    return Response(c["jpeg"], media_type="image/jpeg", headers={
        "X-Cover-Source": c["source"], "X-Cover-Matched": c["matched"].encode("ascii", "ignore").decode()[:120],
        "X-Cover-Confidence": c["confidence"], "Cache-Control": "no-store"})
