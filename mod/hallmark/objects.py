import os
import shutil
from pathlib import Path
from typing import Union


class Objects:
    def __init__(self, path: Union[Path, str]):
        self.root = Path(path) / "objects"

    def _split_checksum(self, sha1: str) -> Path:
        return self.root / sha1[:2] / sha1[2:]

    def store(self, src: Path, sha1: str) -> Path:
        stored_checksum = self._split_checksum(sha1)
        if stored_checksum.exists():
            return stored_checksum
        stored_checksum.parent.mkdir(parents=True, exist_ok=True)
        try:
            # try to create a hard link to avoid copying the file if possible
            os.link(src, stored_checksum)
        except OSError:
            # if hard link creation fails, fall back to copying the file
            shutil.copy2(src, stored_checksum)
        return stored_checksum

    def restore(self, sha1: str, dest: Path) -> Path:
        stored = self._split_checksum(sha1)
        if not stored.exists():
            raise FileNotFoundError(f"object {sha1} not found in objects store")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest.unlink()
        os.link(stored, dest)
        return dest
