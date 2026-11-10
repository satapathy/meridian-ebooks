"""Metadata search with wildcard support.

Syntax (all terms are AND-ed, case-insensitive, "contains" semantics):
    dune                      any metadata field contains "dune"
    tolk*                     * = any run of characters, ? = exactly one character
    "lord of the rings"       quoted phrase
    author:tolkien title:"*ring*"   field-scoped terms
    -fantasy                  exclude books matching the term
"""
import re

ANY_FIELDS = [
    "title", "author", "publisher", "description", "tags", "category",
    "series", "isbn", "filename", "format", "language", "published",
]
FIELD_ALIASES = {
    "title": ["title"], "author": ["author"], "by": ["author"],
    "publisher": ["publisher"], "description": ["description"], "desc": ["description"],
    "tag": ["tags"], "tags": ["tags"], "category": ["category"], "cat": ["category"],
    "format": ["format"], "ext": ["format"], "lang": ["language"], "language": ["language"],
    "isbn": ["isbn"], "series": ["series"], "file": ["filename"], "filename": ["filename"],
    "year": ["published"], "published": ["published"],
}
_TOKEN = re.compile(r'(-)?(?:(\w+):)?(?:"([^"]*)"|(\S+))')


def like_pattern(term: str) -> str:
    esc = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return "%" + esc.replace("*", "%").replace("?", "_") + "%"


def parse_query(q: str) -> tuple[str, list]:
    """Translate a user query into an SQL WHERE fragment and parameters."""
    clauses: list[str] = []
    params: list = []
    for neg, field, quoted, bare in _TOKEN.findall(q or ""):
        term = quoted if quoted else bare
        cols = FIELD_ALIASES.get(field.lower()) if field else None
        if field and cols is None:  # not a known field, e.g. "http://x" - search literally
            term = f"{field}:{term}"
        if not term.strip():
            continue
        cols = cols or ANY_FIELDS
        pat = like_pattern(term.strip())
        clause = "(" + " OR ".join(f"{c} LIKE ? ESCAPE '\\'" for c in cols) + ")"
        clauses.append(("NOT " if neg else "") + clause)
        params.extend([pat] * len(cols))
    return " AND ".join(clauses), params
