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
        # Admin mode: with both set, uploading, editing, deleting and maintenance need a login. Unset = no access control.
        self.admin_user = os.getenv("ADMIN_USER", "").strip()
        self.admin_password = os.getenv("ADMIN_PASSWORD", "")
        # Safety cap for a single uploaded .zip archive once expanded (bytes).
        self.max_archive_bytes = int(os.getenv("MAX_ARCHIVE_BYTES", str(8 * 1024**3)))

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
