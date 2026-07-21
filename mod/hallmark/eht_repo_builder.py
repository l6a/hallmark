from __future__ import annotations
from pathlib import Path
import hashlib
import re
import shutil
from urllib.parse import urljoin
from functools import lru_cache
import string
from string import Formatter
import pandas as pd
import parse
import requests
import time
from .repo import Repo
from .repo_config import fmt_fields
from .fmt_detection import detect_fmt


_ARCHIVE_FORMAT_BY_EXT = {
    ".zip": "zip",
    ".tar": "tar",
    ".tgz": "gztar",
    ".bz2": "bztar",
    ".xz": "xztar",}
_CYVERSE_CURATED_BASE = \
    "https://data.cyverse.org/dav-anon/iplant/commons/cyverse_curated/"
_INDEX_ROW_RE = re.compile(
    r'<tr class="object (collection|data-object[^"]*)">'
    r'<td class="name"><a href="([^"]+)"')
_SUMS_LINE_RE = re.compile(r"^([0-9a-fA-F]{8,})\s+\*?(.+?)\s*$", re.MULTILINE)
_SUMS_FILENAME_RE = \
    re.compile(r"^(?P<name>.+)\.(?P<algorithm>md5|sha1|sha256|sha512)sums$")
_VALID_CHECKSUM_ALGORITHMS = {"md5", "sha1", "sha256", "sha512"}
_CHECKSUM_NAME_KEYWORDS = (
    "sum", "checksum", "md5", "sha1", "sha256", "sha512", "hash", "manifest")
_MANIFEST_LINE_MATCH_RATIO = 0.5
_ALGORITHM_IN_NAME_RE = re.compile(r"(md5|sha1|sha256|sha512)", re.IGNORECASE)
_UNKNOWN_CHECKSUM_ALGORITHM = "unknown"
_MAX_DOWNLOAD_SIZE_FOR_CHECKSUM = 10 * 1024 * 1024 # 10 MB
_MAX_CLEARABLE_LITERAL_LENGTH = 2
KNOWN_STATIC_FILES = {"readme", "license", "licence", "inventory", "run"}
KNOWN_FIELD_VALUES: dict[str, tuple[str, ...]] = {
    "kind": ("fits", "hops", "4fit", "dxin", "haxp", "pcin", "pcqk", "swin"),
    "algorithm": ("md5", "sha1", "sha256", "sha512")
}

def _extract_drive(drive_path: Path) -> Path:
    """
    Extracts a drive archive to a directory with the same name as the drive
    (minus the extension) in the same parent directory.

    Args:
        drive_path: Path to the drive archive file.

    Returns:
        Path to the directory where the drive was extracted.
    """
    # remove extension from drive name to create the extraction directory
    name = drive_path.name
    # remove extra drive extensions
    for double_ext in (".tar.gz", ".tar.bz2", ".tar.xz"):
        if name.lower().endswith(double_ext):
            stem = name[: -len(double_ext)]
            break
    else:
        stem = drive_path.stem
    extract_dir = drive_path.parent / stem
    
    # check that the drive has not already been extracted
    if not extract_dir.exists():
        archive_format = _ARCHIVE_FORMAT_BY_EXT.get(drive_path.suffix.lower())
        # avoid errors with shutil in Python 3.14+ 
        kwargs = {"filter": "data"} if archive_format in \
                    ("tar", "gztar", "bztar", "xztar") else {}
        if archive_format:
            shutil.unpack_archive(str(drive_path), str(extract_dir),
                                   format=archive_format, **kwargs)
        else:
            shutil.unpack_archive(str(drive_path), str(extract_dir))
    return extract_dir


def _leak_score(segments, result, greedy_names=frozenset()):
    """
    Compute a "leak score" for a parse result, which counts how many times
    the last character of a literal segment appears in the matched value
    of a non-greedy named field. A score of 0 means no leaks, which is ideal.

    Args:
        segments: List of (literal, name, format_spec, conversion) tuples
        result: The parse.Result object from parsing the rel_path string
        greedy_names: Set of names that are considered greedy and should be ignored

    Returns:
        An integer leak score, where 0 indicates no leaks
    """
    leak = 0
    # count how many times the last char of its literal appears in the matched value
    for lit, name, _fmt_spec, _conv in segments:
        # if the segment has no name or is greedy, skip it
        if name is None or name in greedy_names:
            continue
        value = str(result.named.get(name, ""))
        if lit and lit[-1] in string.punctuation:
            leak += value.count(lit[-1])
    return leak


def _drop_and_greedy_search(segments, rel_path):
    """
    Try all combinations of dropping fields and making fields greedy to find a
    leak-free parse result. Is more expensive than _greedy_only_search, 
    so we only use it as a last resort.
    
    Args:
        segments: List of (literal, name, format_spec, conversion) tuples from fmt
        rel_path: The file path string to parse

    Returns:
        A tuple of (parse.Result, drop_count) if a leak-free parse is found,
        otherwise (None, None)
    """

    # reconstruct the format string from the segments, ignoring any dropped fields
    fmt = "".join((lit + "{" + name + (":" + _fs if _fs else "") + "}") 
                  if name is not None else lit for lit, name, _fs, _c in segments)
    literal_positions = [] # list of (start_idx, end_idx) for each literal segment
    search_start_idx = 0
    # find all literal segments that are not matched in the rel_path
    # meaning that their corresponding fields must be dropped to find a match
    for lit, _name, _fs, _c in segments:
        if not lit:
            # if there are no literal characters in this segment, record its position
            # even tho no lit is present, we still need to track position for dropping
            literal_positions.append((search_start_idx, search_start_idx))
            continue
        # find the literal in the rel_path starting from the current search position
        idx = rel_path.find(lit, search_start_idx)
        # if the literal is not found, record None for its start and end positions
        if idx == -1:
            literal_positions.append((None, None))
        else:
            # if the literal is found, record its start and end positions
            literal_positions.append((idx, idx + len(lit)))
            # move the search start to the next position
            search_start_idx = idx + len(lit)

    # field names that appear more than once in the segments are considered repeated
    seen_names: set[str] = set()
    repeated_names: set[str] = set()
    for _lit, name, _fs, _c in segments:
        if name is None:
            continue
        if name in seen_names:
            # if a name is repeated it requires special handling
            repeated_names.add(name)
        else:
            seen_names.add(name)

    # for repeated names, we need to resolve their values based on the first occurrence
    resolved_values: dict[str, str] = {}
    # track names that are dropped because their literal segment was not found
    dropped_names: set[str] = set()
    # track the first occurrence of each repeated name along with its value
    first_seen: dict[str, tuple[int, str]] = {}
    # find the values of repeated names based on their literal positions in rel_path
    for idx, (_lit, name, _fs, _c) in enumerate(segments):
        # if the name is not repeated, we don't need to resolve it
        if not (name and name in repeated_names):
            continue
        _lit_start, lit_end = literal_positions[idx]
        # if lit_end is None, it means the literal was not found in this rel_path
        if lit_end is None:
            dropped_names.add(name)
            continue

        # next start is the start index of the next literal segment unless at the end
        next_lit_start = literal_positions[idx + 1][0] \
            if idx + 1 < len(segments) else None
        # the field is between the end of this literal and the start of the next literal
        field_end = next_lit_start if next_lit_start is not None else len(rel_path)
        # value is naive because it may not be correct
        naive_field_value = rel_path[lit_end:field_end]
        if name not in first_seen:
            # if this is the first occurrence of the repeated name, store its value
            first_seen[name] = (field_end, naive_field_value)
        # if this is not the first, check if the naive value matches the first
        elif name not in resolved_values and name not in dropped_names:
            first_field_end, first_field_value = first_seen[name]
            # if the first occurrence's value is found in the current field's value
            if first_field_value in rel_path[first_field_end:]:
                resolved_values[name] = first_field_value
            else:
                # if the naive value does not match the first, we drop this name
                dropped_names.add(name)

    # reconstruct the fmt with dropped names removed and repeated names resolved
    parts = []
    for lit, name, _fs, _c in segments:
        if name in dropped_names:
            continue
        if name in resolved_values:
            # concatenate the literal and the resolved value for repeated names
            parts.append(lit + resolved_values[name])
            continue
        # if the name is not dropped or resolved, include it in the format string
        parts.append(lit)
        # is still an unresolved repeated name, so we include it in the format string
        if name is not None:
            parts.append("{" + name + (":" + _fs if _fs else "") + "}")
    simplified_segments = list(Formatter().parse("".join(parts)))
    global_delimiters = {
        lit[-1] for lit, _name, _fs, _c in simplified_segments
        if lit and lit[-1] in string.punctuation
    }

    segment_count = len(simplified_segments)
    path_length = len(rel_path)

    @lru_cache(maxsize=None)
    def solve(segment_idx, path_idx):
        """
        Recursive function to explore all combinations of dropping fields and
        making fields greedy to find a leak-free parse result. 
        Utilizes memoization to avoid recomputing the same subproblems.
        
        Args:
            segment_idx: Current index in the simplified_segments list. 
                    prior to this index, all segments have been processed.    
            path_idx: Current index in the rel_path string.
            
            Returns:
                A tuple (drop_count, leak_count, future_matches) if a valid parse,
                otherwise None.
        """
        # best case: all segments are processed
        if segment_idx == segment_count:
            # if the entire rel_path has been consumed, return a successful parse
            return (0, 0, ()) if path_idx == path_length else None
        
        # unpack the current segment into its components
        lit, name, _fs, _c = simplified_segments[segment_idx]
        best = None # format is (drop_count, leak_count, future_matches)

        # if the segment has a name and is not repeated, we can consider dropping it
        if name is not None and not _fs:
            # if the literal is short enough, we can consider dropping this field
            if len(lit) <= _MAX_CLEARABLE_LITERAL_LENGTH:
                # recursively try dropping this field and moving to the next segment
                sub = solve(segment_idx + 1, path_idx)
                # if dropping the field leads to a valid parse, consider it a candidate
                if sub is not None:
                    # unpack the result of the recursive call
                    drop_count, leak_count, future_matches = sub
                    candidate = (drop_count + 1, leak_count, future_matches)
                    # if the candidate is better than the current best, update best
                    # is better if it has fewer drops, or same drops but fewer leaks
                    if best is None or candidate[:2] < best[:2]:
                        best = candidate
            # if the segment starts with a literal, try matching it against the rel_path
            if rel_path.startswith(lit, path_idx):
                # recursively try matching this field by moving to the next segment 
                # and updating the path index to account for the matched literal
                sub = solve(segment_idx + 1, path_idx + len(lit))
                # same logic as above
                if sub is not None:
                    drop_count, leak_count, future_matches = sub
                    candidate = (drop_count + 1, leak_count, future_matches)
                    if best is None or candidate[:2] < best[:2]:
                        best = candidate

        # if the segment has no name, it is a literal that must be matched
        if rel_path.startswith(lit, path_idx):
            # the field starts immediately after the matched literal
            field_start = path_idx + len(lit)

            # name is None means this is a literal segment
            if name is None:
                # recursively try matching the next segment after this literal
                sub = solve(segment_idx + 1, field_start)
                if sub is not None:
                    if best is None or sub[:2] < best[:2]:
                        best = sub
            # if the segment has a name, it is a field that can be greedy
            else:
                # allow only the specified values if a format spec is provided
                allowed_values = set(_fs.split("|")) if _fs else None
                # try all possible end positions for the field
                for end in range(field_start + 1, path_length + 1):
                    # get the value of the field from the rel_path
                    value = rel_path[field_start:end]
                    # if allowed_values is provided, skip values that are not allowed
                    if allowed_values is not None and value not in allowed_values:
                        continue
                    # recursively try matching the next segment after this field
                    sub = solve(segment_idx + 1, end)
                    if sub is not None:
                        drop_count, leak_count, future_matches = sub
                        value = rel_path[field_start:end]
                        # the field is considered to have "leaked" if 
                        # the boundary character appears in its value
                        extra_leak = sum(value.count(d) for d in global_delimiters)
                        candidate = (drop_count, leak_count + extra_leak, 
                                     ((name, value),) + future_matches)
                        if best is None or candidate[:2] < best[:2]:
                            best = candidate
        return best

    # intial call for the recursive solve function
    result = solve(0, 0)
    # clear the cache to free memory after the search is complete
    solve.cache_clear()
    if result is None:
        return None, None

    drop_count, _leak_count, future_matches = result
    # build a dictionary of the matched field names and their values
    named = dict(future_matches)
    named.update(resolved_values)

    # return the matched named fields and the total number of dropped fields
    return named, drop_count + len(dropped_names)

def _match_file_against_fmts(rel_path: str, fmt_entries: list[dict]):
    """
    Find the best fmt entry for one file, across all of them at once.

    Args:
        rel_path: The file path to match.
        fmt_entries: The {"fmt", "db", "name"?} entry dicts.
 
    Returns:
        (entry_index, parse.Result), or (None, None) if nothing matches.
    """
    # list of tuples containing (index, fmt_entry, segments, plain_result)
    precomputed_fmt_data = []
    # precompute the segments and plain parse results for each fmt
    for i, fmt_entry in enumerate(fmt_entries):
        literal_char_count = len(re.sub(r"\{[^}]*\}", "", fmt_entry["fmt"]))
        # parse the format string by splitting it into literal and field segments
        # the tuple returned is (literal_text, field_name, format_spec, conversion)
        segments = list(Formatter().parse(fmt_entry["fmt"]))
        segments = [(lit, name, "|".join(KNOWN_FIELD_VALUES[name])
            if name in KNOWN_FIELD_VALUES and not fs else fs, conv)
            for lit, name, fs, conv in segments]
        # a plain parse result is one that doesn't use any greedy or dropped fields
        # most files will match this way, so it's a cheap first pass
        plain_result = parse.compile(fmt_entry["fmt"]).parse(rel_path)
        precomputed_fmt_data.append((i, fmt_entry, segments, plain_result,
                                      literal_char_count))
        
    # sort by literal_char_count descending so that longer fmts are preferred   
    precomputed_fmt_data.sort(key=lambda x: -x[4])
    # list of fmts that successfully matched the rel_path
    valid_fmts = [] # [(index, result, matched_literal_count, drop_count)]
    # track the highest literal char count among the results
    running_baseline_literal_char_count = -1

    # for every fmt, try a plain parse first, then a greedy parse if needed
    for i, fmt_entry, segments, plain_result, literal_char_count \
    in precomputed_fmt_data:
        result = None
        drop_count = 0

        # first pass: try the plain parse result, which is the cheapest and most common
        if plain_result is not None:
            # a leak score of 0 means that no non-greedy fields have "leaked" into the
            # matched value of a greedy field, which is ideal
            if _leak_score(segments, plain_result) == 0:
                result = plain_result.named
            else:
                # if the plain parse has a leak, we can still try a greedy parse
                greedy_result, greedy_drop_count = \
                    _drop_and_greedy_search(segments, rel_path)
                # if the greedy parse is successful and has no drops, we can use it
                if greedy_result is not None and greedy_drop_count == 0:
                    result = greedy_result

        # if the literal_char_count is greater than the running baseline, 
        # this fmt is more specific, so we should try a more expensive search 
        if result is None and literal_char_count > running_baseline_literal_char_count:
            # only track non-trivial literals (length >= 2) to avoid false negatives
            literals = [lit for lit, _n, _fs, _c in segments if len(lit) >= 2]
            # check if the fmt ends with a literal
            trailing_literal = segments[-1][0] if segments[-1][1] is None else ""
            # won't match if trailing lit or any non-trivial lits are not in path
            skip = (
                (len(trailing_literal) >= 2 and trailing_literal not in rel_path)
                or (bool(literals) and not any(lit in rel_path for lit in literals)))
            if not skip:
                # try dropping 0 to field_count fields
                result, drop_count =  _drop_and_greedy_search(segments, rel_path)
 
        # if no result was found for this fmt, continue to the next one
        if result is None:
            continue
 
        # more specific match found if drop_count 0 and literal_char_count > baseline
        if drop_count == 0:
            running_baseline_literal_char_count = \
                max(running_baseline_literal_char_count, literal_char_count)
 
        # number of matched literal characters in the result with respect to rel_path
        lit_count_matched_from_fmt = len(rel_path) - sum(
            len(str(v)) for v in result.values())
        # tracks raw fmt, valid parse result, matched literal count, and drop count
        valid_fmts.append((i, result, lit_count_matched_from_fmt, drop_count))

    if not valid_fmts:
        return None, None

    # the best format has the highest matched literal count with the lowest drop count
    best_fmt, best_parse, _lit_count_matched_from_fmt, _drop_count = max(
        valid_fmts, key=lambda m: (m[2], -m[3]))
    return best_fmt, best_parse


def list_remote_files(base_url: str) \
                                    -> dict[str, tuple[str | None, str | None]]:
    """
    Recursively list every file under a CyVerse WebDAV directory,
    collecting checksums along the way.

    When a directory has a sibling "<dirname>.<algorithm>sums" file, 
    that file already lists every file inside the directory with a checksum 
    whose entries are full base_url-relative paths.

    Args:
        base_url: A CyVerse WebDAV directory URL.

    Returns:
        A dictionary mapping relative paths to a tuple of (algorithm, checksum),
        where algorithm is the checksum algorithm used (e.g., "md5", "sha256"),
        and checksum is the corresponding checksum value. If no checksum is found,
        both values will be None.
    """
    # Ensure the base URL ends with a slash to correctly join with relative paths.
    if not base_url.endswith("/"):
        base_url += "/"

    # stores all files with their checksums, keyed by relative path, for all algorithms
    file_checksums: dict[str, tuple[str | None, str | None]] = {}

    directories_to_open = [""]
    while directories_to_open:
        # Pop the next directory to open from the stack
        rel_dir = directories_to_open.pop()
        # Fetch the HTML index page for the current directory to find its entries.
        index_response = requests.get(urljoin(base_url, rel_dir), timeout=(10, 30))
        # Raise an exception if the request failed
        index_response.raise_for_status()
        # Extract all entries (files and directories) from the HTML index page
        entries = _INDEX_ROW_RE.findall(index_response.text)
        # Separate entries into dirs and checksum files based on their type and naming
        dir_hrefs = {href for entry_type, href in entries if entry_type == "collection"}
        # Track which directories are covered by checksum files
        dirs_covered_by_sums = set()
        # track only files explicitly covered by parsed manifest lines
        files_covered_by_manifest: set[str] = set()

        # Iterate over each entry in the current directory
        for entry_type, href in entries:
            # if the entry is a collection (directory), skip it for now
            if entry_type == "collection":
                continue
            # Match against expected pattern to extract the covered directory and algo
            sibling_match = _SUMS_FILENAME_RE.match(href)
            if sibling_match:
                # unpack the matched groups to get the covered directory and algorithm
                covered_dir = sibling_match.group("name") + "/"
                algorithm = sibling_match.group("algorithm")
                if covered_dir in dir_hrefs:
                    dirs_covered_by_sums.add(covered_dir)
                file_checksums[rel_dir + href] = (None, None)
                # Fetch the checksum file, parse its contents to populate checksums
                sums_response = requests.get(urljoin(base_url, rel_dir + href),
                                          timeout=(10, 30))
                sums_response.raise_for_status()
                # add each path and its checksum to the file_checksums dictionary
                for checksum, filename in _SUMS_LINE_RE.findall(sums_response.text):
                    full_path = filename if "/" in filename else rel_dir + filename
                    full_path = full_path.lstrip("./")
                    file_checksums[full_path] = (algorithm, checksum)
                    files_covered_by_manifest.add(full_path)
                continue

            href_lower = href.lower()
            # skip if the entry name does not contain any of the checksum keywords
            if not any(keyword in href_lower for keyword in _CHECKSUM_NAME_KEYWORDS):
                continue
            # fetch the candidate checksum file and parse its contents
            candidate_response = requests.get(urljoin(base_url, rel_dir + href),
                                               timeout=(10, 30))
            candidate_response.raise_for_status()
            text = candidate_response.text
            lines = [line for line in text.splitlines() if line.strip()]
            matches = _SUMS_LINE_RE.findall(text)
            # if the file is empty or has too few valid checksum lines, skip it
            if not lines or len(matches) < _MANIFEST_LINE_MATCH_RATIO * len(lines):
                continue
            name_match = _ALGORITHM_IN_NAME_RE.search(href)
            algorithm = name_match.group(1).lower() if name_match \
                        else _UNKNOWN_CHECKSUM_ALGORITHM
            file_checksums[rel_dir + href] = (None, None)
            # add each file and its checksum to the file_checksums dictionary
            for checksum, filename in matches:
                full_path = filename if "/" in filename else rel_dir + filename
                full_path = full_path.lstrip("./")
                file_checksums[full_path] = (algorithm, checksum)
                files_covered_by_manifest.add(full_path)
 
        # After processing all entries, add any uncovered directories to the stack
        for entry_type, href in entries:
            rel_path = rel_dir + href
            if entry_type == "collection":
                if href not in dirs_covered_by_sums:
                    directories_to_open.append(rel_path)
            else:
                # add files not explicitly covered by any manifest line with None
                if rel_path not in files_covered_by_manifest:
                    file_checksums.setdefault(rel_path, (None, None))
    # return the complete mapping of relative paths to their checksums organized by algo
    return file_checksums


def build_repo(
    repo_path: Path,
    dataset_name: str,
    fmt_entries: list[dict] | None = None,
    remotes: list[dict | str] | dict | str | None = None,
) -> "Repo":
    """
    Build a hallmark repository from the given dataset and format entries.
    Creates separate TSV files for each fmt, and one config.yml file with the manifest.

    Args:
        repo_path: Path where the hallmark repo will be created.
        fmt_entries: dict entries with "fmt", "db", and optional "name" keys. 
         If None, the function will attempt to detect the format entries automatically.
        remotes: Optional list of remote repos to add to the repo. Each remote can be a
         dict with "name" and "url" keys, or a str representing the name of the remote.

    Returns:
        The initialized Repo object, sitting on the main branch.
    """
    # CyVerse's curated Data Commons datasets live at a predictable URL,
    # built directly from dataset_name.
    base_url = _CYVERSE_CURATED_BASE + dataset_name.strip("/") + "/"

    # normalize remotes input to a list of dicts with "name" and "url" keys
    if remotes is None:
        remotes = []
    elif isinstance(remotes, str):
        remotes = [{"name": remotes}]
    elif isinstance(remotes, dict):
        remotes = [remotes]
    else:
        remotes = [({"name": r} if isinstance(r, str) else dict(r)) for r in remotes]

    # repo build always starts fresh
    repo_path = Path(repo_path).expanduser().resolve()
    if repo_path.exists():
        # if the repo path already exists, remove it to start fresh
        shutil.rmtree(repo_path)
    repo = Repo.init(repo_path)

    # list every file in the dataset from the remote index along with their checksums
    file_checksums = list_remote_files(base_url)
    remote_files = sorted(file_checksums)

    # if no fmt_entries are provided
    if fmt_entries is None:
        # prompt the user to either detect formats automatically or input them manually
        choice = input(
            "No fmt_entries provided. Detect fmts automatically from this "
            "dataset, or input them yourself? [detect/input]: "
        ).strip().lower()
        if choice == "detect":
            # ask the user if they want to include drive files during fmt detection
            include_drives_answer = input(
                "Include drive/archive files during fmt detection? [yes/no]: "
            ).strip().lower()
            # only accept "yes" or "no" as valid input for include_drives
            if include_drives_answer not in {"yes", "no"}:
                raise ValueError(
                    "Invalid input for include_drives. Expected 'yes' or 'no'.")
            include_drives = (include_drives_answer == "yes")

            detected_fmts = detect_fmt(remote_files, include_drives=include_drives)
            if not detected_fmts:
                raise ValueError(
                    "No fmts could be automatically detected from this dataset.")
            fmt_entries = []
            # create a fmt entry for each detected format
            if len(detected_fmts) == 1:
                # if there is only one detected format, assume it is "data.tsv"
                print(f"Detected fmt: {detected_fmts[0]!r}\n"
                      f"  Only one fmt detected; using db name 'data.tsv'.")
                fmt_entries.append({"fmt": detected_fmts[0], "db": "data.tsv"})
            else:
                for fmt in detected_fmts:
                    db_name = input(
                        f"Detected fmt: {fmt!r}\n"
                        f"  Enter a db name for this fmt (e.g. 'data.tsv'): ").strip()
                    # ensure the db name ends with ".tsv"
                    if not db_name.endswith(".tsv"):
                        db_name += ".tsv"
                    fmt_entries.append({"fmt": fmt, "db": db_name})
        elif choice == "input":
            fmt_entries = []
            print("Enter fmt entries one at a time. Leave the fmt blank to finish.")
            # allow the user to input multiple fmt entries manually
            while True:
                fmt = input("fmt (blank to finish): ").strip()
                # if the user inputs a blank fmt, exit the loop
                if not fmt:
                    break
                db_name = input("  db name for this fmt: ").strip()
                # ensure the db name ends with ".tsv"
                if not db_name.endswith(".tsv"):
                    db_name += ".tsv"
                # append the user-provided fmt and db name to the fmt_entries list
                fmt_entries.append({"fmt": fmt, "db": db_name})
        else:
            raise ValueError(f"Unrecognized choice: {choice!r}")
        
    # safeguard: if fmt_entries is still None, initialize it as an empty list
    if fmt_entries is None:
        fmt_entries = []

    # make rows for each fmt entry to be filled with parsed data from matching files
    rows_by_fmt: list[list[dict]] = [[] for _ in fmt_entries]

    # list of paths that could not be matched to any format, to be processed later
    unmatched_paths: list[str] = []
    #for rel_path in remote_files:
    for file_index, rel_path in enumerate(remote_files):
        # measure the time taken to match the file against all formats
        start_time = time.time()
        # attempt to match the file against all formats and get the best match
        i, result = _match_file_against_fmts(rel_path, fmt_entries)
        elapsed_time = time.time() - start_time
        # print a note if matching took longer than 1 second, including the file index
        if elapsed_time > 1.0:
            print(f"Note: matching \"{rel_path}\" took {elapsed_time:.1f}s "
                  f"(file {file_index + 1}/{len(remote_files)})")
        if result is not None:
            # append the parsed data to the corresponding rows_by_fmt list
            rows_by_fmt[i].append({"path": rel_path, **result})
        else:
            unmatched_paths.append(rel_path)

    # create the manifest for each format and organize rows by database
    fmt_manifest: list[dict] = []
    rows_by_db: dict[str, list[dict]] = {}
    # iterate over each format entry and its corresponding rows to build the manifest
    for fmt_entry, rows in zip(fmt_entries, rows_by_fmt):
        db = fmt_entry["db"]
        rows_by_db[db] = rows
        entry = {"fmt": fmt_entry["fmt"], "db": db}
        # include the name in the manifest entry if it exists in the fmt_entry
        if "name" in fmt_entry:
            entry = {"name": fmt_entry["name"], **entry}
        fmt_manifest.append(entry)

    # look up and attach checksums for each row based on the available algorithms
    for rows in rows_by_fmt:
        for row in rows:
            algo, checksum = file_checksums[row["path"]]
            row["checksum_algorithm"] = algo
            row["checksum"] = checksum

    # process unmatched paths to identify static files and the meta file
    static_file_entries = []
    meta_file_entry: dict | None = None
    for rel_path in unmatched_paths:
        path = Path(rel_path)
        stem_name = path.stem.split(".")[-1]

        if stem_name.lower() == "meta":
            meta_file_entry = {"file": rel_path}
            continue

        # for each unmatched path, look up its checksum
        algo, checksum = file_checksums.get(rel_path)
        # if not available, download and compute md5 checksum for small files
        if checksum is None:
            file_url = urljoin(base_url, rel_path)
            head_response = requests.head(file_url, timeout=(10, 30))
            head_response.raise_for_status()
            content_length = head_response.headers.get("Content-Length")
            file_size = int(content_length) if content_length is not None else None
            # only download if the file is less than 10 MB to avoid excessive bandwidth
            if file_size is not None and file_size <= _MAX_DOWNLOAD_SIZE_FOR_CHECKSUM:
                file_response = requests.get(file_url, timeout=(10, 30))
                file_response.raise_for_status()
                algo = "md5"
                checksum = hashlib.md5(file_response.content).hexdigest()
            else:
                algo = _UNKNOWN_CHECKSUM_ALGORITHM
                checksum = _UNKNOWN_CHECKSUM_ALGORITHM

        # create an entry for the static file with its relative path
        entry = {"file": rel_path}
        # if the stem name matches a known static file, include it in the entry
        if stem_name.lower() in KNOWN_STATIC_FILES:
            entry = {"name": stem_name.lower(), **entry}

        # if a valid checksum algorithm and checksum are available, include them
        if (
            algo is not None
            and checksum is not None
            and algo in (_VALID_CHECKSUM_ALGORITHMS | {_UNKNOWN_CHECKSUM_ALGORITHM})
        ):
            entry[algo] = checksum
        static_file_entries.append(entry)

    # hallmark's bookkeeping: create and commit the meta.yml file
    meta_dict: dict = {"dataset": dataset_name}
    repo.dothm.dump_yml(meta_dict, "meta")
    repo.dothm.index.add(["meta.yml"])
    repo.dothm.index.commit(f"Initialize dataset: {dataset_name}")

    # organize rows by their target database and keep track of the corresponding format
    rows_by_target_db: dict[str, list[dict]] = {}
    fmt_by_target_db: dict[str, str] = {}
    # group all rows by their target database to write them to separate TSV files later
    for fmt_entry, rows in zip(fmt_entries, rows_by_fmt):
        db = fmt_entry["db"]
        rows_by_target_db.setdefault(db, []).extend(rows)
        fmt_by_target_db.setdefault(db, fmt_entry["fmt"])

    # write each target database's rows to its own TSV file
    for db, rows in rows_by_target_db.items():
        if rows:
            df = pd.DataFrame(rows)
            ordered_cols = ["path", "checksum_algorithm", "checksum"] + [
                c for c in df.columns
                if c not in {"path", "checksum_algorithm", "checksum"}]
            df = df[ordered_cols]
        else:
            # if there are no rows, create an empty DataFrame with the right columns
            df = pd.DataFrame(columns=["path", "checksum_algorithm", "checksum"]
                               + fmt_fields(fmt_by_target_db[db]))
        # write the DataFrame to a TSV file and add it to the git index
        df.to_csv(repo.dothm.path / db, sep="\t", index=False)
        repo.dothm.index.add([db])

    # config.yml: static files, then fmt entries, then remote/meta
    repo.state.config["data"] = [*static_file_entries, *fmt_manifest]

    final_remotes = []
    # add remotes to the config, defaulting to base_url if no URL is provided
    for remote in remotes:
        entry = dict(remote)
        if "url" not in entry:
            entry["url"] = base_url
        final_remotes.append(entry)
    repo.state.config["remote"] = final_remotes

    # if a meta file entry exists, add it to the config
    if meta_file_entry is not None:
        repo.state.config["meta"] = [meta_file_entry]

    # write the updated config to the config.yml file and commit it
    repo.dothm.dump_yml(repo.state.config, "config")
    repo.dothm.index.add(["config.yml"])
    repo.dothm.index.commit(f"Add dataset manifest: {dataset_name}")

    # reload the repo state from the .dothm directory to reflect the latest changes
    repo.state = repo.dothm.load()
    return repo