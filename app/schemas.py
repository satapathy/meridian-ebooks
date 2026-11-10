from typing import Optional, Union

from pydantic import BaseModel, Field


class StorageInfo(BaseModel):
    embedded: list[str] = Field(description="Metadata fields stored inside the book file itself")
    sidecar: list[str] = Field(description="Metadata fields stored in the *-info.json sidecar")
    sidecar_file: Optional[str] = Field(None, description="Sidecar file name, if one exists")


class Book(BaseModel):
    id: str = Field(description="Server-assigned UUID (32 hex chars)")
    title: str
    author: str = Field(description="Authors joined with '; '")
    authors: list[str]
    publisher: str
    description: str
    language: str
    published: str
    isbn: str
    tags: list[str]
    category: str
    subcategory: str = Field(description="Optional second level under the category")
    series: str
    series_index: Optional[float]
    rating: Optional[int] = Field(description="0-5 stars")
    format: str = Field(description="File extension, e.g. epub")
    filename: str = Field(description="Name of the file on disk (independent of the title)")
    path: str = Field(description="Path relative to the library root")
    size: int
    md5: str = Field(description="MD5 of the file as first uploaded (duplicate key)")
    has_cover: bool
    cover_source: Optional[str] = Field(None, description="user (uploaded, stored next to the book) | embedded (from the book file) | null")
    source_path: Optional[str] = Field(None, description="Original relative path for folder uploads")
    added_at: str
    updated_at: str
    storage: StorageInfo


class BookPage(BaseModel):
    items: list[Book]
    total: int
    limit: int
    offset: int


class BookUpdate(BaseModel):
    """Only the fields you send are changed."""
    title: Optional[str] = None
    author: Optional[Union[str, list[str]]] = Field(None, description="'A; B' or ['A','B']")
    publisher: Optional[str] = None
    description: Optional[str] = None
    language: Optional[str] = None
    published: Optional[str] = None
    isbn: Optional[str] = None
    tags: Optional[Union[list[str], str]] = Field(None, description="List, or comma separated string")
    category: Optional[str] = None
    subcategory: Optional[str] = None
    series: Optional[str] = None
    series_index: Optional[float] = None
    rating: Optional[int] = Field(None, ge=0, le=5)


class RenameFile(BaseModel):
    filename: str = Field(description="New file name; the extension is kept automatically", examples=["dune-first-edition"])


class UploadResult(BaseModel):
    filename: str
    status: str = Field(description="created | duplicate | skipped | error | updated (JSON applied) | warning (JSON differs from existing metadata, not applied)")
    book_id: Optional[str] = None
    title: Optional[str] = None
    detail: Optional[str] = None
    diffs: Optional[list[dict]] = Field(None, description="For JSON imports: field, current and imported values that differ")


class UploadReport(BaseModel):
    results: list[UploadResult]
    summary: dict[str, int]


class FacetCount(BaseModel):
    name: str
    count: int


class Facets(BaseModel):
    authors: list[FacetCount]
    categories: list[FacetCount]
    formats: list[FacetCount]
    tags: list[FacetCount]


class ImportRequest(BaseModel):
    path: str = Field("", description="Folder inside the server's import directory ('' = the whole import dir)")
    category_from_folders: bool = True
    overwrite_json: bool = Field(False, description="Let imported JSON files overwrite existing metadata that differs")


class ImportJob(BaseModel):
    id: str
    status: str
    path: str
    total: int
    processed: int
    summary: dict[str, int]
    errors: list[str]
