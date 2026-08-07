from __future__ import annotations

from copy import deepcopy
from io import StringIO
from git.exc import GitCommandError

import pandas as pd

from .helper_functions import load_yaml
from .state import State

def _load_revision_yaml(
    repo,
    revision: str,
    filename: str,
    fallback: dict,
    ) -> dict:
    """
    Used by load_revision_state.
    Load a YAML file from a specific Git revision.

    Args:
        repo:     The repository object.
        revision: The Git revision (commit hash, branch name, etc.) to load.
        filename: The name of the YAML file to load (e.g., "config.yml").
        fallback: A dictionary to return if the file does not exist in the specified
        revision.

    Returns:
        (dict) The contents of the YAML file at the specified revision, or the
        fallback dictionary if the file does not exist.
        Uses a deep copy of the fallback dictionary to ensure that it is not modified.
    """
    # try to load the YAML file from the specified revision in the Git repository
    try:
        return load_yaml(repo.dothm.git.show(f"{revision}:{filename}"))
    # if the file does not exist in the specified revision, return fallback dictionary
    except GitCommandError:
        # ensure that the fallback dictionary is not modified by returning a deep copy
        return deepcopy(fallback)


def _parse_data_tsv(data: str) -> pd.DataFrame:
    """
    Used by load_revision_state.
    Parse Git-backed TSV text into a DataFrame.

    Args:
        data: TSV text to parse.

    Returns:
        A pandas DataFrame containing the parsed TSV data, or an empty DataFrame
        if the input data is empty.
    """
    # if the input data is empty or contains only whitespace, return an empty DataFrame
    if not data.strip():
        return State().data.copy()
    # otherwise, parse the TSV data into a DataFrame with specified options
    return pd.read_csv(StringIO(data), sep="\t", dtype=str, keep_default_na=False)


def _copy_current_state(repo, *, include_data: bool) -> State:
    """
    Used by load_head_state and load_branch_data.
    Create an independent copy of the repository's current state.
    Args:
        repo: The repository object.
        include_data: Whether to include the current data in the copied state.

    Returns:
        (State) An independent copy of the repository's current state.
    """
    # if include_data is True, copy current data; otherwise, create an empty DataFrame
    data = (repo.state.data.copy() if include_data else State().data.copy())

    # new State object with deep copies of current config and meta, and the copied data
    return State(
        config=deepcopy(repo.state.config), meta=deepcopy(repo.state.meta), data=data)


def _load_revision_state(repo, revision: str) -> State:
    """
    Used by load_head_state and load_branch_data.
    Load the state from a specific Git revision.

    Args:
        repo:     The repository object.
        revision: The Git revision (commit hash, branch name, etc.) to load.

    Returns:
        (State) The state loaded from the specified Git revision.
    """
    # Load the data.tsv content from the specified revision
    data_text = repo.dothm.git.show(f"{revision}:data.tsv")
    # Load the config.yml and meta.yml content from the specified revision,
    # falling back to current state if not found
    return State(
        config=_load_revision_yaml(repo, revision, "config.yml", repo.state.config),
        meta=_load_revision_yaml(repo, revision, "meta.yml", repo.state.meta),
        data=_parse_data_tsv(data_text))


def load_branch_data(repo, branch: str) -> State:
    '''
    Load the state associated with a branch

    Args:
        repo (Repo): repository object
        branch (String): branch name
    Returns:
        (State) A ``State`` constructed from the ``config.yml``, ``meta.yml``,
        and ``data.tsv`` files at the specified branch. If no state can be loaded
        from the branch, returns a state with the current configuration and
        metadata and an empty data table.
    '''
    # get the names of all branches in the repository
    branch_names = {head.name for head in repo.dothm.heads}
    # if the specified branch exists, load the state from that branch
    if branch in branch_names:
        return _load_revision_state(repo, branch)

    # if the specified branch does not exist, return a state with the current
    # configuration and metadata and an empty data table
    return _copy_current_state(repo, include_data=True)


def load_head_state(repo) -> State:
    '''
    Load the state stored at ``Head``.

    Args:
        repo (Repo): Repository object.

    Returns:
        Result from ``_load_revision_state``, which is a ``State`` object containing
        the contents of ``config.yml``, ``meta.yml``, and ``data.tsv`` at the current
        ``HEAD`` revision. If the state can't be loaded, returns a
        state with the current configuration and metadata and an empty data table.
    '''
    # attempt to load the state from the HEAD revision of the repository
    try:
        return _load_revision_state(repo, "HEAD")
    # if the HEAD revision cannot be loaded (e.g., no commits), return a state
    # with the current configuration and metadata and an empty data table
    except GitCommandError:
        return _copy_current_state(repo, include_data=False)