"""Text clean-up operations for the "advanced" bulk edit. Pure functions: easy to test and free of any I/O."""
import re

OPERATIONS = ("lowercase", "uppercase", "capitalize", "titlecase", "replace", "collapse_spaces", "trim")

_SMALL = frozenset("a an and as at but by for if in nor of on or per the to up via vs".split())
_WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*")      # letters, with inner apostrophes ("don't")


def collapse_spaces(s: str) -> str:
    """Runs of spaces/tabs become one space; line breaks (descriptions) are kept."""
    return re.sub(r"[^\S\n]{2,}", " ", s)


def _cap(word: str) -> str:
    return word[:1].upper() + word[1:]


def titlecase(s: str) -> str:
    """Capitalise each word, keep small words (of, the, and...) lower unless first, last or after a colon.
    Words that already mix cases (McDonald, iPhone) are left alone; ALL-CAPS words are converted."""
    matches = list(_WORD.finditer(s))
    out, last = [], 0
    for i, m in enumerate(matches):
        word = m.group()
        mixed = any(c.isupper() for c in word[1:]) and any(c.islower() for c in word)
        lead = s[last:m.start()]
        after_colon = ":" in lead or i == 0
        if mixed:
            new = word
        elif word.lower() in _SMALL and not after_colon and i != len(matches) - 1:
            new = word.lower()
        else:
            new = _cap(word.lower())
        out.append(lead + new)
        last = m.end()
    return "".join(out) + s[last:]


def replace_words(s: str, find: str, replacement: str, *, case_sensitive: bool = False, whole_words: bool = True) -> str:
    """Literal (never regex) find and replace. An empty replacement removes the text and tidies the spaces."""
    pattern = re.escape(find)
    if whole_words:
        pattern = rf"(?<!\w){pattern}(?!\w)"
    out = re.sub(pattern, lambda _m: replacement, s, flags=0 if case_sensitive else re.IGNORECASE)
    return collapse_spaces(out).strip() if replacement == "" else out


def apply(operation: str, s: str, *, find: str = "", replacement: str = "", case_sensitive: bool = False,
          whole_words: bool = True) -> str:
    if operation == "lowercase":
        return s.lower()
    if operation == "uppercase":
        return s.upper()
    if operation == "capitalize":
        return _cap(s.strip().lower()) if s.strip() else s
    if operation == "titlecase":
        return titlecase(s)
    if operation == "replace":
        return replace_words(s, find, replacement, case_sensitive=case_sensitive, whole_words=whole_words)
    if operation == "collapse_spaces":
        return collapse_spaces(s)
    if operation == "trim":
        return s.strip()
    raise ValueError(f"Unknown operation: {operation}")
