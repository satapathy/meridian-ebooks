import os
from pathlib import Path

SUPPORTED_EXTENSIONS = {
    "epub", "pdf", "docx", "doc", "odt", "rtf", "txt", "md", "html", "htm",
    "mobi", "azw", "azw3", "kfx", "fb2", "djvu", "cbz", "cbr", "cb7", "lit", "chm", "pdb",
}


class Settings:
    """Runtime configuration, read from the environment when the app starts."""

    def __init__(self) -> None:
        self.data_dir = Path(os.getenv("DATA_DIR", "./data")).resolve()
        self.import_dir = Path(os.getenv("IMPORT_DIR", "./import")).resolve()
        # Safety cap for a single uploaded .zip archive once expanded (bytes).
        self.max_archive_bytes = int(os.getenv("MAX_ARCHIVE_BYTES", str(8 * 1024**3)))
        # Online category lookup (Google Books / Open Library). Only runs when a user starts it;
        # set ONLINE_LOOKUP=off to forbid outgoing lookups entirely.
        self.online_lookup = os.getenv("ONLINE_LOOKUP", "on").strip().lower() not in ("0", "off", "false", "no")

    @property
    def library_dir(self) -> Path:
        return self.data_dir / "library"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "meridian.db"

    def ensure_dirs(self) -> None:
        self.library_dir.mkdir(parents=True, exist_ok=True)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
