# Copyright 2025 the Hallmark Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha1
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from .dothm import Dothm
from .error import CheckoutError, DestinationExistsError
from .objects import Objects
from .paraframe import ParaFrame
from .repo_config import branch_encodings, branch_fmt, path_from_row, row_to_path, \
    set_branch_fmt, set_config as repo_set_config
from .repo_manifest import manifest_frame_from_pf, manifest_map
from .repo_state import load_branch_data, load_head_state
from .repo_worktree import effective_cwd, ensure_clean_tracked_files, \
    filtered_paraframe, tracked_paths
from .state import State
from .worktree import Worktree


@contextmanager
def chdir(path):
    '''
    Temporarily change the current working directory. No Yields. 

    Args:
        Path: Directory to dwitch to while inside the context.
    Returns:
        None.
    '''
    old = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


@dataclass(init=False)
class Repo:
    """
    Hallmark repository.

    This is the Python API boundary.
    It loads the in-memory ``State`` from repository ``Dothm``, and
    potentially populate the ``Worktree``.
    """

    state: State
    dothm: Optional[Dothm] = None
    worktree: Optional[Worktree] = None

    @staticmethod
    def lwpaths(path: Union[Path, str]) -> Tuple[Path, Optional[Path]]:
        '''
        Resolve repository and worktree paths.

        Args:
            path (Path | str): Path to either a worktree or a 
            ``.hm`` repository.

        Returns:
            tuple[Path, Path | None]: A ``(dothm_path, worktree_path)`` tuple. 
            If ``path`` refers to a ``.hm`` directory, ``worktree_path`` is ``None``.
        '''
        path = Path(path).resolve()
        if path.suffix == ".hm":
            return path, None
        return path / ".hm", path

    def __init__(self, path: Union[Path, str]) -> None:
        '''
        Open an existing hallmark repository.

        Args: 
            path: path to a worktree or '.hm repository'/
        Returns:
            none.
        '''
        dothm_path, worktree_path = self.lwpaths(path)
        self.dothm = Dothm(dothm_path)
        self.worktree = worktree_path and Worktree(worktree_path)
        self.state = self.dothm.load()
        self.paraframe_cls = ParaFrame

        common = Path(self.dothm.common_dir).resolve().parent
        self.objects = Objects(common)
        dothm_objects = Path(dothm_path) / "objects"
        main_objects = common / "objects"
        if dothm_objects.resolve() != main_objects.resolve() \
        and not dothm_objects.exists():
            dothm_objects.symlink_to(main_objects)

    @classmethod
    def init(cls, path: Union[Path, str]) -> "Repo":
        '''
        Initialize a new hallmark repository.

        Args:
            paht(paht|string): path to initialize a worktree or ``.hm`` repository.

        Returns:
            Repo: newly created repository instance
        '''
        dothm_path, worktree_path = cls.lwpaths(path)
        dothm = Dothm.init(dothm_path)
        (dothm.path/"config.yml").write_text(Dothm.config_template(),encoding="utf-8")
        dothm.dump_yml({}, "meta")
        dothm.dump_tsv(State().data, "data")
        dothm.index.add(["config.yml", "meta.yml", "data.tsv"])
        Objects(dothm_path)
        worktree_path and Worktree.init(worktree_path)
        return cls(path)

    @classmethod
    def clone(
        cls,
        url: str,
        path: Union[Path, str],
        *,
        fetch_data: bool = True,
        max_workers: int = 4,
        show_progress: bool = False,
    ) -> "Repo":
        '''
        Clone a remote hallmark repository. Raises DestinationExistsError
        if the destination path already exists. Raises DownloadError if 
        data download is enabled and files fail to download.

        Args:
            url(string): remote repository URL.
            path(path|string): destination path for clone.
            fetch_data (boolean): if true, downloads associated data files. 
            max_workers (integer): Number of parallel workers for downloading data.
            show_progress (boolean): wether to display download progress.
        Returns:
            Repo: Cloned Repository instance
        '''
        clone_path = Path(path)
        if clone_path.exists():
            raise DestinationExistsError(
                f"fatal: destination path '{clone_path}' already exists "
                "and is not an empty directory."
            )

        dothm_path, worktree_path = cls.lwpaths(path)

        Dothm.clone(url, dothm_path, display_path=path)

        # Initialize worktree if non-bare
        if worktree_path:
            Worktree.init(worktree_path)

        repo = cls(path)
        repo.download_result = None

        if fetch_data and worktree_path:
            from .downloader import DownloadError, download_remote_data

            result = download_remote_data(
                repo,
                worktree_path,
                max_workers=max_workers,
                show_progress=show_progress,
            )
            repo.download_result = result
            if result["failed"]:
                errors = result.get("errors", [])
                details = "\n".join(f"  - {error}" for error in errors[:5])
                remaining = result["failed"] - len(errors[:5])
                if remaining > 0:
                    details += f"\n  - ... {remaining} more error(s)"
                raise DownloadError(
                    f"Failed to download {result['failed']} file(s):\n"
                    f"{details}"
                )

        return repo

    @staticmethod
    def checksum(path: Path, chunk_size: int = 1024 * 1024) -> str:
        '''
        Computes the SHA1 checksum of a file. 

        Args:
            path (path): path to the file to hash.
            chunk_size (integer): size of chunks used for streaming reads.
        Returns:
            String: Hexadecimal SHA1 digest of the file contents.
        '''
        digest = sha1()
        with path.open("rb") as f:
            for block in iter(lambda: f.read(chunk_size), b""):
                digest.update(block)
        return digest.hexdigest()

    def add_paths(self, paths: List[Union[Path, str]]) -> ParaFrame:
        '''
        Add explicit file paths to the repository index. Raises RuntimeError.
        Operation not supported in Hallmark.
        '''
        raise RuntimeError(
            'explicit path add is not supported while data.tsv ' \
            'stores only sha1 plus fmt fields')

    def set_config(
        self,
        *,
        fmt: Optional[str] = None,
        remote_name: Optional[str] = None,
        remote_url: Optional[str] = None,
        encoding_updates: Optional[Dict[str, str]] = None,
    ) -> dict:
        """
        Update repository configuration values.

        Args:
            fmt (str, optional): Data format specification.
            remote_name (str, optional): Name of the remote repository.
            remote_url (str, optional): URL of the remote repository.
            encoding_updates (dict[str, str], optional): Updates to encoding rules.

        Returns:
            dict: Updated configuration dictionary.
        """
        repo_set_config(
            self,
            fmt=fmt,
            remote_name=remote_name,
            remote_url=remote_url,
            encoding_updates=encoding_updates,
        )
        self.dothm.dump(self.state)
        return self.state.config

    def status(self) -> dict[str, object]:
        """
        Return repository status information. Includes staged changes, 
        orktree modifications, deletions, and untracked files.

        Args: 
            none?

        Returns:
            dict[str, object]: Status summary including:
            - branch (str)
            - staged changes (dict)
            - worktree changes (dict)
            - untracked files (list[str])
        """
        head_state = load_head_state(self)
        head_map = manifest_map(head_state)
        staged_map = manifest_map(self.state)
        state_changes = sorted({
            diff.a_path or diff.b_path
            for diff in self.dothm.index.diff("HEAD")
            if diff.a_path or diff.b_path
        })

        staged_added = sorted(path for path in staged_map if path not in head_map)
        staged_deleted = sorted(path for path in head_map if path not in staged_map)
        staged_modified = sorted(
            path for path in staged_map
            if path in head_map and staged_map[path] != head_map[path]
        )

        worktree_modified: list[str] = []
        worktree_deleted: list[str] = []
        tracked_paths = set(staged_map)

        if self.worktree is not None:
            for path, staged_sha1 in staged_map.items():
                full_path = self.worktree / path
                if not full_path.exists():
                    worktree_deleted.append(path)
                elif self.checksum(full_path) != staged_sha1:
                    worktree_modified.append(path)

            untracked = sorted(
                str(path.relative_to(self.worktree))
                for path in effective_cwd(self).rglob("*")
                if path.is_file()
                and ".hm" not in path.relative_to(self.worktree).parts
                and str(path.relative_to(self.worktree)) not in tracked_paths
            )
        else:
            untracked = []

        return {
            "branch": self.dothm.active_branch.name,
            "staged": {
                "state": state_changes,
                "added": staged_added,
                "modified": staged_modified,
                "deleted": staged_deleted,
            },
            "worktree": {
                "modified": sorted(worktree_modified),
                "deleted": sorted(worktree_deleted),
            },
            "untracked": untracked,
        }

    def add(self, fstr: str, encoding: bool = False) -> ParaFrame:
        '''
        Stage files or updated repository indecing from the worktree.

        Args:
            fstr (string): Format string or "." for full directory scan.
            encoding (boolean): Whether to apply encoding rules.
        Returns:
            paraframe Parsed and filtered file index (without checksums).
        '''
        if self.worktree is None:
            raise RuntimeError(
                "cannot add files in a bare repository without a worktree")

        if fstr == ".":
            fmt = branch_fmt(self)
            with chdir(self.worktree):
                pf = ParaFrame.parse(
                    fmt,
                    base_path=self.worktree,
                    encodings=branch_encodings(self) if encoding else None,
                    encoding=encoding,
                )
            pf = filtered_paraframe(self, pf)
            if not pf.empty:
                pf["sha1"] = [
                    self.checksum(self.worktree / Path(path))
                    for path in pf["path"].astype(str)
                ]
            self.state.replace(manifest_frame_from_pf(pf, fmt))
            self.dothm.dump(self.state)
            return pf.drop(columns=["sha1"], errors="ignore")

        try:
            previous_fmt = branch_fmt(self)
        except RuntimeError:
            previous_fmt = None

        set_branch_fmt(self, fstr)

        with chdir(self.worktree):
            pf = ParaFrame.parse(
                fstr,
                base_path = self.worktree,
                encodings = branch_encodings(self)
                            if encoding else None,
                encoding = encoding,
                )

        if not pf.empty:
            pf["sha1"] = [
                self.checksum(self.worktree / Path(path))
                for path in pf["path"].astype(str)
            ]

        manifest = manifest_frame_from_pf(pf, fstr)
        if previous_fmt is None or previous_fmt != fstr:
            self.state.replace(manifest)
        else:
            self.state.update(manifest)
        self.dothm.dump(self.state)
        return pf.drop(columns=["sha1"], errors="ignore")

    def commit(self, msg: str, allow_empty: bool = False) -> bool:
        '''
        Commit staged changes to the repository. Raises ValueError if commit
        message is empty or invalid. 

        Args:
            msg (string): commit message.
            allow_empty (boolean): Allow comitting even if no changes exists.
        Returns:
            boolean: True if a commit was created, false otherwise. 
        '''
        if not isinstance(msg, str) or not msg.strip():
            raise ValueError("commit message must be a non-empty string")

        if allow_empty or self.dothm.index.diff("HEAD"):
            for _, row in self.state.data.iterrows():
                self.objects.store(self.worktree / path_from_row(self, row), 
                                   row["sha1"])
            self.dothm.index.commit(msg)
            return True
        return False

    def log(self) -> str:
        '''
        Return commit history log.

        Returns:
            string: Git log output, or an empty string if no valid HEAD exists.
        '''
        if not self.dothm.head.is_valid():
            return ""
        return self.dothm.git.log()

    def branches(self) -> dict[str, object]:
        '''
        List repository branches. 

        Returns:
            dictionary[string, object]: Dictionary containing:
                - ``current`` (string): Active branch name
                - ``names``: All branch names
        '''
        current = self.dothm.active_branch.name
        names = sorted(head.name for head in self.dothm.heads)
        return {"current": current, "names": names}

    def checkout(self, target_branch: str) -> bool:
        '''
        Switch to a different branch and update the worktree. Raises ValueError if
        branch name is invalid. Raises CheckoutError if the workign directoary
        is not clean or checkout can't be completed safely.

        Args:
            target_branch (string): Branch to switch to.
        Returns: 
            boolean: True if checkout succeeds.


        '''
        if not isinstance(target_branch, str) or not target_branch.strip():
            raise ValueError("branch name must be a non-empty string")

        if self.worktree is None:
            raise CheckoutError("cannot checkout without a worktree")
        ensure_clean_tracked_files(self)

        existing = {head.name for head in self.dothm.heads}
        new_branch = target_branch not in existing
        current_tracked = tracked_paths(self)
        target_state = load_branch_data(self, target_branch)
        target_fmt = target_state.config["data"][0]["fmt"]
        target_tracked = {
            row_to_path(row, target_fmt)
            for _, row in target_state.data.iterrows()
        }

        for _, row in target_state.data.iterrows():
            rel_path = row_to_path(row, target_fmt)
            target_path = self.worktree / rel_path
            if rel_path not in current_tracked and target_path.exists():
                if self.checksum(target_path) != row["sha1"]:
                    raise CheckoutError(
                        f'target tracked path "{rel_path}" already exists '
                        "as an untracked file")

        # switch .hm branch
        if new_branch:
            self.dothm.git.checkout("-b", target_branch)
        else:
            self.dothm.git.checkout(target_branch)

        # reload state from the new branch
        self.state = self.dothm.load()

        removed_paths = []
        for rel_path in sorted(current_tracked - target_tracked, reverse=True):
            path = self.worktree / rel_path
            if path.exists():
                path.unlink()
                removed_paths.append(path)

        # restore files from objects store via hardlinks
        for _, row in self.state.data.iterrows():
            self.objects.restore(row["sha1"], self.worktree / path_from_row(self, row))

        for path in removed_paths:
            parent = path.parent
            while parent != self.worktree and parent.exists():
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent

        return True

    def add_worktree(self, target_branch: str) -> bool:
        '''
        Create or link a new worktree for a branch. Raises ValueError if branch name 
        is invalid.
        Rasies Runtime error if called in a bare repository or worktree creation fails.
        
        Args:
            target_branch (string): Name of the branch to attach.
        Returns:
            boolean: True if the worktree was successfully created.
        '''
        from shutil import copy2
        from git.exc import GitCommandError

        if not isinstance(target_branch, str) or not target_branch.strip():
            raise ValueError("branch name must be a non-empty string")

        if self.worktree is None:
            raise RuntimeError("cannot add a worktree in a bare " \
            "repository without a worktree")

        source = Path(self.worktree).resolve()
        target = source.parent / target_branch
        target_dothm = target / ".hm"

        linked_dothm = None
        if target_dothm.exists():
            linked_dothm = Dothm(target_dothm)
        else:
            target.mkdir(parents=True, exist_ok=True)
            existing_branches = {head.name for head in self.dothm.heads}
            try:
                if target_branch in existing_branches:
                    linked_dothm = self.dothm.link(target_dothm, target_branch)
                else:
                    self.dothm.git.worktree("add","-b",target_branch,str(target_dothm))
                    linked_dothm = Dothm(target_dothm)
            except GitCommandError as e:
                raise RuntimeError(f'failed to create worktree for \
                                    branch "{target_branch}": {e}')

            target_state = linked_dothm.load()
            for _, row in target_state.data.iterrows():
                rel_path = row_to_path(row, target_state.config["data"][0]["fmt"])
                src = source / rel_path
                dest = target / rel_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                copy2(src, dest)
        return True
