from __future__ import annotations

from pathlib import Path

import parse
import pandas as pd

from .repo_config import fmt_fields, row_to_path


def manifest_frame_from_pf(pf, fmt: str) -> pd.DataFrame:
    """
    Build a manifest table from a ``ParaFrame``. Raises RuntimeError
    if a file path cannot be parsed using ``fmt``.

    The returned table contains a ``sha1`` column together with the
    fields extracted from the configured filename format.

    Args:
        pf: ``ParaFrame`` containing indexed file paths.
        fmt (str): Filename format used to parse the paths.

    Returns:
        pandas.DataFrame: Manifest table containing ``sha1`` values and
        parsed filename fields.
    """
    if pf.empty:
        return pd.DataFrame(columns=["sha1", *fmt_fields(fmt)])

    parser = parse.compile(fmt)
    rows = []
    for _, row in pf.iterrows():
        parsed = parser.parse(str(row["path"]))
        if parsed is None:
            raise RuntimeError(f'failed to parse "{row["path"]}" \
                               using branch fmt "{fmt}"')
        rows.append({"sha1": row["sha1"], **{k: str(v) 
                                for k, v in parsed.named.items()}})
    return pd.DataFrame(rows, columns=["sha1", *fmt_fields(fmt)])


def manifest_map(state) -> dict[str, str]:
    """
    Create a mapping from file paths to SHA-1 checksums.

    Args:
        state: Repository state.

    Returns:
        dict[str, str]: Dictionary mapping relative file paths to their
        corresponding SHA-1 checksums.
    """
    if state.data.empty:
        return {}
    data = state.config.get("data")
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        return {}
    fmt = data[0].get("fmt")
    if not isinstance(fmt, str) or not fmt.strip():
        return {}
    return {
        str(row_to_path(row, fmt)): str(row["sha1"])
        for _, row in state.data.iterrows()
    }


def frame_from_paths(repo, rel_paths: list[Path]):
    """
    Build a ``ParaFrame`` from repository paths.

    Each path is converted into a row containing the relative path and
    its SHA-1 checksum.

    Args:
        repo: Repository object.
        rel_paths (list[Path]): Relative paths within the repository.

    Returns:
        ParaFrame: ``ParaFrame`` containing the indexed paths and their
        checksums.
    """
    records = [{"path": str(path)} for path in rel_paths]
    pf = repo.paraframe_cls(records, base_path=repo.worktree)
    if not pf.empty:
        pf["sha1"] = [repo.checksum(repo.worktree / path) for path in rel_paths]
    return pf
