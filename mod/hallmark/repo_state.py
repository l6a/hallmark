from __future__ import annotations

from io import StringIO

import pandas as pd
import yaml
from git.exc import GitCommandError

from .state import State


def load_branch_config(repo, branch: str) -> dict:
    '''
    Load the configuration for a specific branch

    Args: 
        repo (Repo): repository object containing Git and state information/
        branch (String): Name of the branch whose configuration should be loaded
    Returns:
        (dict) A dictionary contaiing the branch configuration. Returns the 
        parsed contents of ``config.yml`` from the specified branch when
        available, otherwise returns a copy of ``repo.state.config``.
    '''
    try:
        return yaml.safe_load(repo.dothm.git.show(f"{branch}:config.yml")) or {}
    except GitCommandError:
        return dict(repo.state.config)


def load_branch_meta(repo, branch: str) -> dict:
    '''
    Load the metadata for a specific branch
    
    Args: 
        repo (Repo): repository object
        branch (String): Name of the branch
    Returns:
        The contents of ``meta.yml`` from the specified branch. If 
        metadata can't be loaded, returns ``repo.state.meta``.
    '''
    try:
        return yaml.safe_load(repo.dothm.git.show(f"{branch}:meta.yml")) or {}
    except GitCommandError:
        return dict(repo.state.meta)


def load_branch_data(repo, branch: str) -> State:
    '''
    Load the state associated with a branch

    Args: 
        repo (Repo): repository object
        branch (String): branch name
    Returns:
        (State) A ``State`` consturcted from the branch's ``config.yml``,
        ``meta.yml``, and ``data.tsv`` files. If the branch does
        not exist, returns a copy of the current repository state.
    '''
    if branch in {head.name for head in repo.dothm.heads}:
        data = repo.dothm.git.show(f"{branch}:data.tsv")
        frame = State().data if not data.strip() else None
        if frame is None:
            parsed = pd.read_csv(StringIO(data), sep="\t", dtype=str)
        else:
            parsed = frame
        return State(
            load_branch_config(repo, branch),
            load_branch_meta(repo, branch),
            parsed,
        )

    return State(
        dict(repo.state.config),
        dict(repo.state.meta),
        repo.state.data.copy(),
    )


def load_head_state(repo) -> State:
    '''
    Load the state stored at ``Head``.

    Args:
        repo (Repo): Repository object.

    Returns:
        (State) A ``State`` constructed from the ``config.yml``, ``meta.yml``, 
        and``data.tsv`` files at ``HEAD``. If no state can be loaded 
        from ``HEAD``, returns a state with the current configuration 
        and metadata and an empty data table.
    '''
    try:
        data = repo.dothm.git.show("HEAD:data.tsv")
    except GitCommandError:
        return State(
            dict(repo.state.config),
            dict(repo.state.meta),
            State().data.copy(),
        )

    if data.strip():
        parsed = pd.read_csv(StringIO(data), sep="\t", dtype=str)
    else:
        parsed = State().data.copy()

    return State(
        load_branch_config(repo, "HEAD"),
        load_branch_meta(repo, "HEAD"),
        parsed,
    )
