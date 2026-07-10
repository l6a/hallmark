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

from pathlib   import Path
from functools import cached_property
from typing import Optional, Union

from git import GitCommandError, Repo
import pandas as pd
import yaml

from .state import State
from .error import CloneError, DothmError


class Dothm(Repo):
    """Local ``.hm`` storage backend.

    The backend version controls the hallmark ``State`` database files
    (``config.yml``, ``meta.yml``, ``data.tsv``) on-disk.
    It is itself a git worktree.
    """

    @cached_property
    def path(self) -> Path:
        return Path(self.working_tree_dir)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.working_tree_dir is None:
            raise DothmError('The ".hm" directory must be a valid git ' \
            'worktree.')

    @classmethod
    def init(cls, *args, **kwargs) -> "Dothm":
        if kwargs.get('bare', False):
            raise DothmError('A ".hm" directory must not be a bare git ' \
            'repository')
        kwargs.setdefault("initial_branch", "main")

        dothm = super().init(*args, **kwargs)
        readme_path = dothm.path / "README.md"
        with open(readme_path, "w", encoding="utf-8") as f:
            f.write("""# Local `.hm` Repository

This is a dot-hallmark repository.
It is a git-version-controlled dataset index used by `hallmark`.
See https://l6a.github.io/hallmark/ for `hallmark` usage.
""")
        if not dothm.heads:
            dothm.index.add([readme_path])
            dothm.index.commit("Initial commit: local `.hm` repository")
        return dothm

    @staticmethod
    def config_template() -> str:
        return """# Edit this file only if your branch needs regex substitutions.
# For simple names, you can just run: hallmark add "a{a}_i{i}.h5"
data:
  -
    # fmt: "{release}_{source}_{year}_{doy:03d}_{band}.uvfits"
    encoding:
      # aspin: m([0-9]+(\\.[0-9]+)?|\\.[0-9]+)
remote:
  # name: origin
  # url: https://example.com/path/to/data/
"""

    @classmethod
    def clone(
        cls,
        url: str,
        to_path: Union[Path, str],
        display_path: Optional[Union[Path, str]] = None,
    ) -> "Dothm":
        to_path = Path(to_path)

        try:
            super().clone_from(url, str(to_path))
            dothm = cls(str(to_path))

            required_files = ["config.yml", "meta.yml", "data.tsv"]
            for file in required_files:
                if not (dothm.path / file).exists():
                    raise CloneError(
                        f'Cloned repository missing required file: {file}'
                    )
            return dothm
        except GitCommandError as e:
            raise CloneError.from_git_command(
                e,
                fallback=f'Failed to clone from "{url}"',
                clone_path=to_path,
                display_path=display_path,
            ) from e
        except CloneError:
            raise

    def link(self, path: Union[Path, str], branch: Optional[str] = None):
        cmd = self.git  # has its own working directory
        path = Path(path).resolve()  # use absolute path
        try:
            cmd.worktree("add", path, branch)
        except GitCommandError as e:
            raise DothmError(f'Failed to link "{path}": {e}')
        return Dothm(path)

    def load(self) -> State:
        return State(
            self.load_yml("config"),
            self.load_yml("meta"),
            self.load_tsv("data"),
        )

    def dump(self, state: State) -> None:
        self.dump_yml(state.config, "config")
        self.dump_yml(state.meta,   "meta")
        self.dump_tsv(state.data,   "data")
        self.index.add(["config.yml", "meta.yml", "data.tsv"])

    def load_yml(self, stem: Union[Path, str]) -> dict:
        with open((self.path/stem).with_suffix(".yml"), "r") as f:
            return yaml.safe_load(f)

    def dump_yml(self, data: dict, stem: Union[Path, str]) -> None:
        with open((self.path/stem).with_suffix(".yml"), "w") as f:
            yaml.dump(data, f, sort_keys=False)

    def load_tsv(self, stem: Union[Path, str]) -> pd.DataFrame:
        return pd.read_csv((self.path/stem).with_suffix(".tsv"), sep="\t", 
                           dtype=str)

    def dump_tsv(self, data: pd.DataFrame, stem: Union[Path, str]) -> None:
        data.to_csv((self.path/stem).with_suffix(".tsv"), sep="\t", index=False)
