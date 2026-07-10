# Copyright 2019 Chi-kwan Chan
# Copyright 2019 Steward Observatory
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
"""
Utilities for discovering and parsing parameterized file collections.

This module defines :class:`ParaFrame`, a subclass of
:class:`pandas.DataFrame` that provides convenient methods for locating,
parsing, and filtering files whose names follow parameterized naming
conventions.
"""

from glob import glob
from pathlib import Path

import re
import parse
import pandas as pd
import numpy as np

from .helper_functions import find_spec_by_fmt, regex_sub, try_numeric_conversion


class ParaFrame(pd.DataFrame):
    """
    A subclass of :class:`pandas.DataFrame` with additional methods for
    parameterized file discovery and filtering.

    ``ParaFrame`` behaves like a standard ``pandas.DataFrame`` while
    providing the following additional functionality:

    * ``__init__``: Initializes the class and stores ``encodings`` and
      ``base_path`` as metadata.
    * ``_constructor``: Returns a new ``ParaFrame`` while preserving
      ``encodings`` and ``base_path``.
    * ``glob_search``: Finds files matching a parameterized format string.
    * ``parse``: Builds a ``ParaFrame`` by parsing file paths that match
      a format pattern.
    * ``__call__`` and ``filter``: Convenience methods for filtering rows
      by column values.
    """

    _metadata = ["encodings", "base_path"]

    def __init__(self, data=None, encodings=None, base_path=None, **kwargs):
        """
        Initialize a ``ParaFrame``.

        Args:
            data: Data used to initialize the ``ParaFrame``.
            encodings (dict, optional): Filename encoding specifications.
                Defaults to ``{}``.
            base_path (Path or str, optional): Root directory associated with
                the ``ParaFrame``. Defaults to the current working directory.
            **kwargs: Additional arguments passed to
                :class:`pandas.DataFrame`.
        """
        super().__init__(data, **kwargs)
        self.encodings = encodings or {}
        self.base_path = Path(base_path) if base_path is not None else Path.cwd()

    @property
    def _constructor(self):
        """
        Return the constructor used by pandas operations.

        Returns:
            callable: A constructor that preserves ``encodings`` and
            ``base_path`` metadata.
        """
        def _c(*args, **kwargs):
            kwargs.setdefault("encodings", self.encodings)
            kwargs.setdefault("base_path", self.base_path)
            return ParaFrame(*args, **kwargs)
        return _c

    def __call__(self, **kwds):
        """
        Filter the ``ParaFrame``.

        Equivalent to calling :meth:`filter`.

        Args:
            **kwds: Column names and values used for filtering.

        Returns:
            pandas.DataFrame: The filtered ``ParaFrame``.
        """
        return self.filter(**kwds)

    def filter(self, **kwargs):
        """
        Filter a ``ParaFrame`` by matching column values.

        This method filters the current ``ParaFrame`` by applying one or more
        conditions on its columns. Rows satisfying any of the specified
        conditions are returned.

        Args:
            ``**kwargs``: Keyword arguments specifying column names and values to
            filter by. Values may be scalars or sequences (lists or tuples).
            Sequence values match any element in the sequence.

        Returns:
            pandas.DataFrame: A filtered DataFrame containing only the rows
            that satisfy the requested conditions.
        """
        mask = np.zeros(len(self), dtype=bool)
        for k, v in kwargs.items():
            if isinstance(v, (tuple, list)):  # looking through the specified conditions
                mask |= np.isin(np.array(self[k]), np.array(v))
            else:
                mask |= np.array(self[k]) == v
        return self[mask]

    @classmethod
    def glob_search(
        cls,
        fmt,
        *args,
        encodings=None,
        base_path=None,
        debug=False,
        return_pattern=False,
        encoding=False,
        **kwargs,
    ):
        """
        Find files matching a parameterized format string.

        This method searches for files using the supplied format string.
        When ``encoding=True``, regular-expression encodings defined in the
        YAML configuration are also applied.

        Args:
            fmt (str):
                Format string describing the expected filename pattern.

            ``*args``:
                Positional arguments used to fill the format string.

            encodings (dict):
                Encoding specifications from ``config.yml``.

            base_path (Path):
                Root directory to search.

            debug (bool):
                If ``True``, prints debugging information.

            return_pattern (bool):
                If ``True``, returns both the glob pattern and the matched
                files.

            encoding (bool):
                If ``True``, applies regex encodings defined in the YAML
                configuration.

            ``**kwargs``:
                Keyword arguments used to fill the format string.
                Missing values are replaced with the wildcard ``*``.

        Returns:
            tuple:
                If ``return_pattern`` is ``True``, returns
                ``(globbed_files, pattern)``.

                Otherwise returns
                ``(yaml_encodings, fmt_g, globbed_files)``.
        """
        encodings = encodings or {}
        base_path = Path(base_path) if base_path is not None else Path.cwd()

        pmax = len(fmt) // 3  # to specify a parameter, we need at least
        # three characters '{p}'; the maximum number
        # of possible parameters is `len(fmt) // 3`.

        fmt_enc = fmt
        enc_dict = {}
        needs_encoding = None

        if encoding:
            for entry in encodings:
                if entry.get("fmt") in fmt:
                    fmt_enc = entry["fmt"]
                    break

            yaml_encodings = find_spec_by_fmt(fmt_enc, encodings)

            # Conditionals checking .yaml file and user specifications are consistent.
            if yaml_encodings is None:
                raise ValueError(
                    f"Error: The format '{fmt_enc}' is missing from hallmark.yml."
                )

            enc_dict = yaml_encodings.get("encoding", {})
            needs_encoding = any(v != "" for v in enc_dict.values())
            if not needs_encoding and encoding:
                raise ValueError(
                    f"'{fmt_enc}' has no regex spec; use encoding=False."
                )
        else:
            yaml_encodings = {}

        if needs_encoding is not None and not encoding:
            raise ValueError(
                f"'{fmt_enc}' has a regex spec; use encoding=True."
            )

        # pattern = base + fmt
        pattern = str(base_path / fmt.lstrip("/"))
        fmt_g = fmt_enc.lstrip("/")
        
        for i in range(pmax):
            if debug:
                print(i, pattern, args, kwargs)
            try:
                pattern = pattern.format(*args, **kwargs)
                break
            except KeyError as e:
                k = e.args[0]
                pattern = re.sub(r"\{" + k + r":?.*?\}", "{" + k + "}", pattern)
                fmt_g = re.sub(r"\{" + k + r":?.*?\}", "{" + k + "}", fmt_g)
                kwargs[k] = "*"

        # Obtain list of files based on the glob pattern
        globbed_files = sorted(glob(pattern))

        # Print the glob pattern and a summary of matches
        if debug:
            print(f'Pattern: "{pattern}"')
            n = len(globbed_files)
            if n > 1:
                print(f'{n} matches, e.g., "{globbed_files[0]}"')
            elif n > 0:
                print(f'{n} match, i.e., "{globbed_files[0]}"')
            else:
                print("No match; please check format string")

        if return_pattern:
            return (globbed_files, pattern)
        else:
            return (yaml_encodings, fmt_g, globbed_files)

    @classmethod
    def parse(
        cls,
        fmt,
        *args,
        encodings=None,
        base_path=None,
        debug=False,
        encoding=False,
        **kwargs,
    ):
        """
        Build a ``ParaFrame`` by parsing file paths that match a format
        string.

        Args:
            fmt (str):
                Format string containing ``{parameter}`` fields.

            encodings (dict):
                Encoding specifications from ``config.yml``.
                Defaults to ``{}``.

            base_path (Path):
                Root directory to search.
                Defaults to ``Path.cwd()``.

            debug (bool):
                If ``True``, prints debugging information.
                Defaults to ``False``.

            encoding (bool):
                If ``True``, applies regex encoding.
                Defaults to ``False``.

        Returns:
            ParaFrame: A ``ParaFrame`` whose rows correspond to matched files.
            Parsed parameters are stored as columns together with a ``path`` column.
        """
        base_path = Path(base_path) if base_path is not None else Path.cwd()

        yaml_encodings, fmt_g, globbed_files = cls.glob_search(
            fmt, *args,
            encodings=encodings,
            base_path=base_path,
            debug=debug,
            encoding=encoding,
            **kwargs,
        )

        parser = parse.compile(fmt_g)
        frame = []

        # Writing the ParaFrame
        for f in globbed_files:
            f_short = str(Path(f).relative_to(base_path))
            if encoding:
                f_new = regex_sub(f_short, yaml_encodings)
            else:
                f_new = f_short

            r = parser.parse(f_new)

            if r is None:
                print(f'Failed to parse "{f}"')
            else:
                frame.append({"path": f_short, **r.named})
        # attempt to convert each parameter column to numeric
        # if conversion fails the column stays as string
        result = cls(frame, encodings=encodings, base_path=base_path)
        for col in result.columns:
            result[col] = try_numeric_conversion(result[col])
        return result
