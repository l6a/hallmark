"""
Utilities for storing and restoring content-addressed objects.

This module defines the ``Objects`` class, which manages the Hallmark
object store. Files are stored using their SHA-1 checksum and can later
be restored to a specified location.
"""

import os
import shutil
from pathlib import Path
from typing import Union


class Objects:
    """
    Manage the Hallmark object store.

    Files are stored in a content-addressed directory structure based on
    their SHA-1 checksum, allowing them to be efficiently retrieved and
    restored.
    """
    def __init__(self, path: Union[Path, str]):
        """
        Initialize the object store.

        Args:
            path (Path or str): Path to the Hallmark repository. The object
                store is located in the ``objects`` subdirectory.
        """
        self.root = Path(path) / "objects"

    def _split_checksum(self, sha1: str) -> Path:
        """
        Convert a SHA-1 checksum into its storage path.

        The first two characters of the checksum form the directory name,
        while the remaining characters form the filename.

        Args:
            sha1 (str): SHA-1 checksum.

        Returns:
            Path: Path where the object is stored.
        """
        return self.root / sha1[:2] / sha1[2:]

    def store(self, src: Path, sha1: str) -> Path:
        """
        Store a file in the object store.

        The file is copied only if an object with the same checksum does not
        already exist.

        Args:
            src (Path): Source file to store.
            sha1 (str): SHA-1 checksum of the file.

        Returns:
            Path: Path to the stored object.
        """
        stored_checksum = self._split_checksum(sha1)
        if not stored_checksum.exists():
            stored_checksum.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, stored_checksum)
        return stored_checksum

    def restore(self, sha1: str, dest: Path) -> Path:
        """
        Restore an object from the object store. Raises FileNotFoundError if 
        the requested object does not exist in the object store.

        The stored object is hard-linked to the destination path.

        Args:
            sha1 (str): SHA-1 checksum of the stored object.
            dest (Path): Destination path for the restored file.

        Returns:
            Path: Path to the restored file.
        """
        stored = self._split_checksum(sha1)
        if not stored.exists():
            raise FileNotFoundError(f"object {sha1} not found in objects store")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest.unlink()
        os.link(stored, dest)
        return dest
