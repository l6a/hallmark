"""Remote data file downloader for hallmark repositories."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import pandas as pd
import requests
from tqdm import tqdm

from .error import HallmarkError
from .repo_config import row_to_path


@dataclass
class DownloadProgress:
    """Compatibility wrapper for older callers."""

    filename: str
    total_bytes: int
    downloaded_bytes: int = 0

    @property
    def percent(self) -> float:
        if self.total_bytes == 0:
            return 0.0
        return (self.downloaded_bytes / self.total_bytes) * 100


class DownloadError(HallmarkError):
    """Raised when remote data download fails."""


def _resolve_remote_path(row: pd.Series, data_config: list[dict]) -> Path:
    """Resolve a downloadable relative path from state metadata."""
    if "path" in row.index and pd.notna(row["path"]):
        return Path(str(row["path"]))

    for entry in data_config:
        fmt = entry.get("fmt")
        if not fmt:
            continue

        try:
            return row_to_path(row, fmt)
        except KeyError:
            continue
        except (TypeError, ValueError) as exc:
            raise DownloadError(
                f"Invalid data format {fmt!r} for remote download: {exc}"
            ) from exc

    available = ", ".join(map(str, row.index.tolist()))
    raise DownloadError(
        "Unable to resolve download path from repository metadata. "
        f"Available columns: {available}"
    )


def _verify_sha1(path: Path, expected_sha1: Optional[str], 
                 chunk_size: int = 8192) -> None:
    if not expected_sha1:
        return

    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)

    if digest.hexdigest() != expected_sha1:
        raise DownloadError(f"Checksum mismatch for {path.name}")


def _download_file(
    url: str,
    destination: Path,
    expected_sha1: Optional[str] = None,
    chunk_size: int = 8192,
) -> int:
    """Download one file and return the number of bytes written."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_name(destination.name + ".part")
    temp_path.unlink(missing_ok=True)

    try:
        with requests.get(url, stream=True, timeout=(10, 30)) as response:
            response.raise_for_status()
            with temp_path.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        handle.write(chunk)

        _verify_sha1(temp_path, expected_sha1, chunk_size=chunk_size)
        size = temp_path.stat().st_size
        temp_path.replace(destination)
        return size
    except requests.RequestException as exc:
        temp_path.unlink(missing_ok=True)
        raise DownloadError(f"Failed to download {url}: {exc}") from exc
    except OSError as exc:
        temp_path.unlink(missing_ok=True)
        raise DownloadError(f"Failed to write {destination}: {exc}") from exc
    except DownloadError:
        temp_path.unlink(missing_ok=True)
        raise


def download_remote_data(
    repo,
    worktree_path: Path,
    max_workers: int = 4,
    show_progress: bool = False,
) -> dict:
    """Download remote data files for a cloned repository."""
    remote_config = repo.state.config.get("remote", {})
    if not remote_config:
        return {"succeeded": 0, "failed": 0, "total_bytes": 0, "errors": []}

    remote_url = remote_config.get("url", "").rstrip("/")
    if not remote_url:
        raise DownloadError("Remote URL not configured in config.yml")

    data_df = repo.state.data
    data_config = repo.state.config.get("data", [])
    if data_df.empty:
        return {"succeeded": 0, "failed": 0, "total_bytes": 0, "errors": []}

    files_to_download: list[tuple[str, Path, Optional[str]]] = []
    for _, row in data_df.iterrows():
        rel_path = _resolve_remote_path(row, data_config)
        file_url = urljoin(remote_url + "/", str(rel_path))
        destination = worktree_path / rel_path
        sha1 = str(row["sha1"]) if "sha1" in row.index and \
        pd.notna(row["sha1"]) else None
        files_to_download.append((file_url, destination, sha1))

    results = {"succeeded": 0, "failed": 0, "total_bytes": 0, "errors": []}
    progress = tqdm(total=len(files_to_download), unit="file", 
                    disable=not show_progress)

    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_download_file, 
                                url, destination, sha1): destination
                for url, destination, sha1 in files_to_download
            }
            for future in as_completed(futures):
                try:
                    results["total_bytes"] += future.result()
                    results["succeeded"] += 1
                except DownloadError as exc:
                    results["failed"] += 1
                    results["errors"].append(str(exc))
                finally:
                    progress.update(1)
    finally:
        progress.close()

    return results
