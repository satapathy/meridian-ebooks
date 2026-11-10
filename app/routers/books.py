import mimetypes
from typing import Literal, Optional

from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse

from .. import service
from ..schemas import Book, BookPage, BookUpdate, RenameFile

router = APIRouter(prefix="/books", tags=["Books"])


@router.get("", response_model=BookPage, summary="Browse and search books")
def list_books(
    q: Optional[str] = Query(
        None,
        description=(
            "Metadata search. Terms are AND-ed; `*` matches any run of characters, `?` one character. "
            "Scope a term with `author:`, `title:`, `publisher:`, `tag:`, `category:`, `format:`, `series:`, "
            "`isbn:`, `lang:`, `year:`, `file:`. Quote phrases, prefix `-` to exclude. "
            "Example: `author:tolk* title:\"*ring*\" -audio`"
        ),
        examples=["author:tolk* format:epub"],
    ),
    author: Optional[str] = Query(None, description="Exact author name"),
    category: Optional[str] = Query(None, description="Exact category ('Uncategorized' for none)"),
    format: Optional[str] = Query(None, description="File format, e.g. epub"),
    tag: Optional[str] = None,
    series: Optional[str] = None,
    sort: Literal["title", "author", "added", "updated", "size", "published", "series", "format", "category", "rating"] = "added",
    order: Literal["asc", "desc"] = "desc",
    limit: int = Query(60, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    return service.list_books(q=q, author=author, category=category, fmt=format, tag=tag,
                              series=series, sort=sort, order=order, limit=limit, offset=offset)


@router.get("/{book_id}", response_model=Book, summary="Get one book")
def get_book(book_id: str):
    try:
        return service.get_book(book_id)
    except service.BookNotFound:
        raise HTTPException(404, "Book not found")


@router.get("/{book_id}/download", summary="Download the book file")
def download(book_id: str, inline: bool = Query(False, description="Open in the browser instead of saving")):
    try:
        path = service.book_file(book_id)
    except service.BookNotFound:
        raise HTTPException(404, "Book not found")
    if not path.exists():
        raise HTTPException(410, "File is missing from disk")
    media = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media, filename=path.name,
                        content_disposition_type="inline" if inline else "attachment")


@router.get("/{book_id}/cover", summary="Cover image (JPEG)", responses={404: {"description": "No cover"}})
def cover(book_id: str):
    p = service.cover_file(book_id)
    if not p:
        raise HTTPException(404, "No cover")
    return FileResponse(p, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=300"})


@router.put("/{book_id}/cover", response_model=Book, summary="Replace the cover image")
def set_cover(book_id: str, file: UploadFile = File(...)):
    try:
        return service.replace_cover(book_id, file.file.read(15 * 1024 * 1024))
    except service.BookNotFound:
        raise HTTPException(404, "Book not found")
    except service.BadRequest as e:
        raise HTTPException(400, str(e))


@router.patch(
    "/{book_id}", response_model=Book, summary="Edit book metadata",
    description=(
        "Updates metadata. EPUB, PDF and DOCX store what they can **inside the file**; everything else "
        "(and any field the format cannot hold) goes to a `<book-name>-info.json` sidecar next to the book. "
        "The response's `storage` shows which fields ended up where. "
        "Changing the title never renames the file - use `POST /books/{id}/rename` for that."
    ),
)
def update_book(book_id: str, body: BookUpdate):
    try:
        return service.update_book(book_id, body.model_dump(exclude_unset=True))
    except service.BookNotFound:
        raise HTTPException(404, "Book not found")
    except service.BadRequest as e:
        raise HTTPException(400, str(e))


@router.post("/{book_id}/rename", response_model=Book, summary="Rename the file on disk (not the title)")
def rename(book_id: str, body: RenameFile):
    try:
        return service.rename_file(book_id, body.filename)
    except service.BookNotFound:
        raise HTTPException(404, "Book not found")
    except service.BadRequest as e:
        raise HTTPException(400, str(e))
    except service.Conflict as e:
        raise HTTPException(409, str(e))


@router.delete("/{book_id}", status_code=204, summary="Delete a book and its files")
def delete(book_id: str):
    try:
        service.delete_book(book_id)
    except service.BookNotFound:
        raise HTTPException(404, "Book not found")
    return Response(status_code=204)
