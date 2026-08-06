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
import re
import hashlib
import os
import tempfile
import yaml
from contextlib import contextmanager
from pathlib import Path
import pandas as pd

# map checksum algorithms to their expected lengths in hexadecimal characters.
CHECKSUM_LENGTHS = {"md5": 32, "sha1": 40, "sha256": 64, "sha512": 128}
# create a tuple of supported checksum algorithms from the keys of CHECKSUM_LENGTHS.
CHECKSUM_ALGORITHMS = tuple(CHECKSUM_LENGTHS)
# sort by their expected lengths in descending order to prioritize stronger algorithms.
CHECKSUM_ALGORITHMS_BY_STRENGTH = tuple(
    sorted(CHECKSUM_ALGORITHMS, key=CHECKSUM_LENGTHS.__getitem__, reverse=True))
# create a frozenset of supported checksum algorithms for efficient membership testing.
SUPPORTED_CHECKSUM_ALGORITHMS = frozenset(CHECKSUM_ALGORITHMS)
# create a regex pattern that matches any of the supported checksum algorithms.
CHECKSUM_ALGORITHM_PATTERN = "|".join(
    re.escape(algorithm) for algorithm in CHECKSUM_ALGORITHMS)
# remote request timeout settings for network operations (connect timeout, read timeout)
REMOTE_REQUEST_TIMEOUT = (10, 30)
# define a frozenset of internal repo names that should be ignored during processing.
REPOSITORY_INTERNAL_NAMES = frozenset({".git", ".hm"})
# define a default chunk size for file I/O operations (1 MB).
FILE_IO_CHUNK_SIZE = 1024 * 1024


def valid_checksum(
    algorithm: str,
    checksum: str,
    *,
    allow_unknown_algorithm: bool = False,
    ) -> bool:
    """
    Validate a checksum against its expected length for the given algorithm.

    Args:
        algorithm: The checksum algorithm (e.g., "md5", "sha1", "sha256", "sha512").
        checksum: The checksum string to validate.
        allow_unknown_algorithm: If True, allows unknown algorithms to pass validation.

    Returns:
        True if the checksum is valid for the given algorithm, False otherwise.
    """
    # Validate a checksum against its expected length for the given algorithm.
    if not isinstance(algorithm, str) or not isinstance(checksum, str):
        # If either the algorithm or checksum is not a string, return False.
        return False

    normalized_algorithm = algorithm.strip().lower()
    normalized_checksum = checksum.strip()
    # Check if the normalized algorithm is in the set of supported algorithms.
    if re.fullmatch(r"[0-9a-f]+", normalized_checksum, re.IGNORECASE) is None:
        return False

    expected_length = CHECKSUM_LENGTHS.get(normalized_algorithm)
    # If the algorithm is not recognized, return the value of allow_unknown_algorithm.
    if expected_length is None:
        return allow_unknown_algorithm

    # if all checks pass, return True if the length matches the expected length.
    return len(normalized_checksum) == expected_length


def file_checksum(
    path: Path,
    algorithm: str = "sha1",
    chunk_size: int = FILE_IO_CHUNK_SIZE,
    ) -> str:
    """
    Compute a file checksum using streaming reads.

    Uses hashlib.file_digest when available and retains compatibility
    with Python versions before 3.11.

    Args:
        path:       Path to the file.
        algorithm:  Checksum algorithm to use (default: "sha1").
        chunk_size: Size of chunks to read at a time (default: 1 MB).

    Returns:
        The hexadecimal checksum string.
    """
    path = Path(path)
    # Normalize the algorithm name to lowercase and strip whitespace.
    algorithm = str(algorithm).strip().lower()
    # try to use the built-in file_digest method if available (Python 3.11+)
    try:
        with path.open("rb") as handle:
            return hashlib.file_digest(handle, algorithm).hexdigest()
    # if file_digest not available (Python < 3.11), fall back to manual chunked reading
    except AttributeError:
        # hashlib.new() will raise a ValueError if the algorithm is not supported
        digest = hashlib.new(algorithm)
        with path.open("rb") as handle:
            # read the file in chunks to avoid loading the entire file into memory
            for block in iter(lambda: handle.read(chunk_size), b""):
                digest.update(block)
        # return the hexadecimal digest of the file's contents
        return digest.hexdigest()


# use contextmanager to create a temporary file path for atomic writes
@contextmanager
def atomic_output_path(path: Path, *, suffix: str = ".tmp"):
    """
    Context manager that yields a temporary file path for atomic writes.
    The temporary file is created in the same directory as the target path
    and is replaced with the target path upon successful completion.

    Args:
        path: Path to the target file.
        suffix: Suffix for the temporary file (default: ".tmp").

    Yields:
        A temporary Path object for writing.
    """
    path = Path(path)
    # create a temporary file in the same directory as the target path
    file_descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=suffix,
        dir=path.parent)
    # close the file descriptor immediately; we only need the path for writing later
    os.close(file_descriptor)
    temp_path = Path(temp_name)

    # try to yield the temporary path for writing
    try:
        yield temp_path
        # replace the target path with the temporary file atomically
        temp_path.replace(path)
    # always clean up the temporary file if an exception occurs or after replacement
    finally:
        temp_path.unlink(missing_ok=True)


def load_yaml(source):
    """
    Load YAML from text or a readable stream.
    Empty YAML documents are represented consistently as an empty
    dictionary.

    Args:
        source: A string or a file-like object containing YAML content.

    Returns:
        A dictionary representing the loaded YAML content,
        or an empty dictionary if the content is empty.
    """
    # safely load YAML content from a string or file-like object into a dictionary
    loaded = yaml.safe_load(source)
    if loaded is None:
        return {}
    # if the loaded content is not a dictionary, raise a ValueError
    if not isinstance(loaded, dict):
        raise ValueError("YAML document must contain a mapping")

    return loaded


def load_yaml_file(path: Path):
    """
    Load YAML from a file, returning an empty dictionary for empty files.

    Args:
        path: Path to the YAML file.
    Returns:
        Result from load_yaml, which is a dictionary or an empty dictionary.
    """
    # use safe_load to parse the YAML content from a file into a Python dictionary
    with Path(path).open("r", encoding="utf-8") as handle:
        return load_yaml(handle)


def normalize_nonempty_string(
    value,
    *,
    label: str,
    exception_type=ValueError
    ) -> str:
    """
    Normalize a string by stripping whitespace and ensuring it is non-empty.

    Args:
        value: The string to normalize.
        label: A label for the string, used in error messages.
        exception_type: The type of exception to raise if the string is invalid.

    Returns:
        The normalized string with leading and trailing whitespace removed.
    """
    # raise an exception if the value is not a string or is empty
    if not isinstance(value, str) or not value.strip():
        raise exception_type(f"{label} must be a non-empty string")
    # if the value is valid, return the stripped string
    return value.strip()


def iter_repository_files(root: Path):
    """
    Iterate over all files in a repository, excluding internal directories.

    Args:
        root: Path to the root of the repository.

    Yields:
        Paths to all regular files in the repository, excluding internal directories.
    """
    root = Path(root)
    # for each directory, subdirectory, and file in the repository, yield file paths
    for current, directory_names, file_names in os.walk(root):
        # directory_names is modified in place to skip internal repository directories
        directory_names[:] = [
            name
            for name in directory_names
            if name.lower() not in REPOSITORY_INTERNAL_NAMES]
        # get the current path as a Path object for easier file path manipulation
        current_path = Path(current)
        for file_name in file_names:
            # skip files that are internal to the repository (e.g., .git, .hm)
            if file_name.lower() in REPOSITORY_INTERNAL_NAMES:
                continue
            file_path = current_path / file_name
            # only yield file path if its a regular file or symlink (not a directory)
            if file_path.is_file() and not file_path.is_symlink():
                # yield the file path for further processing
                yield file_path


def find_spec_by_fmt(fmt, encodings):
    """Find the encoding spec for a given format string.

    Args:
        fmt:       Format string to look up.
        encodings: The ``encodings`` list from ``State`` (i.e., the contents
                   of ``config.yml``).

    Returns:
        The matching spec dict, or ``None`` if not found.
    """
    for spec in encodings:
        if spec.get("fmt") == fmt:
            return spec
    return None


def regex_sub(value, yaml_encodings):
    """Apply regex substitution defined in an encoding spec.

    Args:
        value:          Format string / file path to transform.
        yaml_encodings: A single encoding spec dict (one entry from the
                        ``data`` list in ``hallmark.yml``), or ``None``.

    Returns:
        The transformed string, or the original string if no regex is
        defined in the encoding spec or if ``yaml_encodings`` is ``None``.
    """
    if yaml_encodings is None:
        return value

    enc = yaml_encodings.get("encoding")
    if not enc:
        return value

    regex = enc.get("aspin", "")
    if not regex:
        return value
    # apply the regex substitution to the value,
    # replacing matches with a hyphen followed by the first captured group.
    return re.sub(regex, lambda match: "-" + str(match.group(1)), value)

def try_numeric_conversion(series):
    """
    Attempt to convert a pandas Series to numeric.

    Converts the series to numeric iff:
      1. All values are numeric
      2. Converting back to string matches the original values to avoid
         unintended conversions (e.g., "001" -> 1)

    Args:
        series: A pandas Series of strings to attempt conversion on.

    Returns:
        The converted numeric Series if both conditions are met,
        otherwise returns original series.
    """
    # replace unconvertible values with NaN
    converted = pd.to_numeric(series, errors="coerce")
    # if any values were unconvertible, return original series
    if converted.isna().any():
        return series
    # if converting back to str doesn't match original, return original series
    # prevents unintended conversions like "001" -> 1
    if not all(str(int(numeric_val)) == str(original_val)
                 or str(numeric_val) == str(original_val)
               # check each pair of converted and original values
               for numeric_val, original_val in zip(converted, series)):
        return series
    return converted

