from __future__ import annotations
from pathlib import Path
import shutil
from hallmark import ParaFrame
from .fmt_detection import detect_fmt, scan_inventory,KNOWN_META_FILES, _DELIM_PATTERN,\
                                 DRIVE_EXTS_LOWER, META_EXTS_LOWER
import parse
import re
from itertools import combinations
from .repo import Repo
from .repo_manifest import manifest_frame_from_pf

## Mapping of file extensions to archive formats for shutil.unpack_archive
_ARCHIVE_FORMAT_BY_EXT = {
    ".zip": "zip", ".tar": "tar", ".tgz": "gztar",
    ".gz": "gztar", ".bz2": "bztar", ".xz": "xztar",
}

def _sanitize_branch_name(name: str) -> str:
    """Replace characters git disallows in ref names."""
    for ch in ["{", "}", " ", "~", "^", ":", "?", "*", "[", "\\"]:
        name = name.replace(ch, "_")
    name = name.replace("..", "__")
    return name.strip("/")

def _compile_parsers(fmts: list[str], cache: dict) -> \
                        list[tuple[str, int, "parse.Parser"]]:
    """Compile every fmt and its trailing-dropped-parameter variants,
    reusing already-compiled parsers from `cache` when the exact same
    fmt string has been seen before."""
    parsers = []
    # normalize the deliminators for parsing
    for f in fmts:
        if f in cache:
            # reuse the parser from cache if this fmt has already been compiled
            parsers.extend(cache[f])
            continue
        # normalize the deliminators for parsing
        stem = re.sub(r"[\-.]", "_", f)
        tokens = stem.split("_")
        # find the indices of the tokens that are parameters
        param_indices = [i for i, t in enumerate(tokens)
                 if re.fullmatch(r"\{.*?\}", t)]
        # use set to avoid duplicates when dropping different combinations of parameters
        variants = set()
        # try dropping 0 to all parameters to create different fmt variants
        for drop_count in range(len(param_indices) + 1):
            # find the positions of the parameters to drop for this variant
            for drop_count in range(len(param_indices) + 1):
                for positions_to_drop in combinations(param_indices, drop_count):
                    positions_to_drop = set(positions_to_drop)
                    kept = [t for i, t in enumerate(tokens) 
                            if i not in positions_to_drop]
                    variants.add("_".join(kept))
            # create a new fmt variant with the selected parameters dropped
            kept = [t for i, t in enumerate(tokens) if i not in positions_to_drop]
            variants.add("_".join(kept))

        # compile a parser for each variant and store it in the cache
        f_parsers = [
            (f, len(v.split("_")), parse.compile(v, case_sensitive=True))
            for v in variants]
        cache[f] = f_parsers
        parsers.extend(f_parsers)

    return parsers

def _extract_drive(drive_path: Path) -> Path:
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
        kwargs = {"filter": "data"} if archive_format in \
                    ("tar", "gztar", "bztar", "xztar") else {}
        if archive_format:
            # avoid errors with shutil in Python 3.14+ 
            shutil.unpack_archive(str(drive_path), str(extract_dir),
                                   format=archive_format, **kwargs)
        else:
            shutil.unpack_archive(str(drive_path), str(extract_dir))
    return extract_dir


def build_repo(root: Path, repo_path: Path, dataset_name: str, fmt: str | list[str] | 
               None = None, data_type: str = "L2", overwrite: bool = False,) -> "Repo":
    """
    Build a hallmark repository directly from a dataset directory.

    Walks the dataset once via scan_inventory, classifies each file as
    meta/drive/data, buffers data rows by (fmt_str, stem_key), then
    commits one branch per stem to the hallmark repo.

    Args:
        root:         Path to the EHT dataset root directory.
        repo_path:    Path where the hallmark repo will be created.
        dataset_name: Human-readable name for this dataset.
        fmt:          Format string(s) for parsing data files.
                      If None, auto-detected via detect_fmt.
        data_type:    "L2" only for now; L1 support deferred.
        overwrite:    If True, delete and recreate an existing repo.

    Returns:
        The initialized Repo object, sitting on the main branch.
    """
    # intitalize the root for file scanning and check if it exists
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"{root} is not a directory")

    # intialize the repo path and check if it already exists
    repo_path = Path(repo_path).expanduser().resolve()
    if repo_path.exists():
        if overwrite:
            # remove the existing repo directory and its contents if overwrite is True
            shutil.rmtree(repo_path)
        else:
            raise FileExistsError(f'Repo already exists at "{repo_path}".')
    repo = Repo.init(repo_path)

    # detect the fmt(s) if not provided, and compile parsers for them
    fmts = detect_fmt(root) if fmt is None else ([fmt] if isinstance(fmt, str) else fmt)
    parser_cache = {}
    parsers = _compile_parsers(fmts, parser_cache)
    # group the parsers by their token count for efficient matching
    parsers_by_tc: dict[int, list] = {}
    parsers_by_fmt: dict[str, list] = {}
    for fmt_str, variant_token_count, parser in parsers:
        parsers_by_tc.setdefault(variant_token_count, []).append((fmt_str, parser))
        parsers_by_fmt.setdefault(fmt_str, []).append(parser)

    # initialize the tree meta branch and data stems
    stems: dict[tuple[str, str], list[dict]] = {}
    meta_files: list[str] = []
    unmatched: list[str] = []

    # match files to correct branch and stem, or add to meta if not a data file
    for file_path in scan_inventory(root):
        path = Path(file_path)
        ext = path.suffix.lstrip(".").lower()
        stem_name = path.stem.split(".")[0]

        # don't need to track drives
        if ext in DRIVE_EXTS_LOWER:
            continue

        # common meta file formats
        if ext in META_EXTS_LOWER or stem_name in KNOWN_META_FILES:
            meta_files.append(file_path)
            continue

        stem_only = re.sub(r"[\-.]", "_", path.stem)
        stem_with_ext = stem_only + re.sub(r"[\-.]", "_", path.suffix)
        # counts to see if ext was included in fmt
        stem_only_token_count = len(stem_only.split("_"))
        stem_with_ext_token_count = len(stem_with_ext.split("_")) 

        # reset flags for each file
        parsed = None
        matched_fmt = None
        # parse the file name to extract fields, skip if it doesn't match the format
        matched = False
        # iterate over each candidate and its token count
        for candidate, candidate_token_count in (
        (stem_only, stem_only_token_count),
        (stem_with_ext, stem_with_ext_token_count),):
            # iterate over each parser that matches this candidate's token count
            for fmt_str, parser in parsers_by_tc.get(candidate_token_count, []):
                parsed = parser.parse(candidate)
                if parsed:
                    matched_fmt = fmt_str
                    matched = True
                    break
            # break out once the correct parser has been found for this candidate
            if matched:
                break

        if parsed:
            # create unique stem name based on fmt parameters excluding extension
            stem_key = "_".join(str(value) for key, value in parsed.named.items() 
                                if key != "ext")
            # check the string isn't empty
            if not stem_key:
                continue
            # create a row for this file to add to relevant Paraframe
            row = {
                "path": file_path,
                # normalize ext to not have period
                "ext": Path(file_path).suffix.lstrip("."),
                # one column for each different parsed field
                **{key: value for key, value in parsed.named.items() if key != "ext"},}
            # add row to dict, and create the dict if it doesn't exist yet
            stems.setdefault((matched_fmt, stem_key), []).append(row)
        else:
            # failed to match the file to any fmt stem
            unmatched.append(file_path)

    # double check unmatched files to see if they match any fmt stems by literal tokens
    for file_path in unmatched:
        path = Path(file_path)
        stem_tokens = set(re.split(_DELIM_PATTERN, path.stem))
        stem_only = re.sub(r"[\-.]", "_", path.stem)
        for fmt_str in parsers_by_fmt:
            # tokens that are not parameters in the fmt string
            fmt_literals = {
                t for t in re.split(_DELIM_PATTERN, fmt_str)
                if not re.fullmatch(r"\{.*?\}", t)
            }
            # if there are no alike tokens they aren't a match
            if not (stem_tokens & fmt_literals):
                continue
            parsed = None
            # see what parser is for this fmt_str
            for parser in parsers_by_fmt[fmt_str]:
                parsed = parser.parse(stem_only)
                if parsed:
                    break
            if parsed:
                stem_key = "_".join(str(v) for k, v
                                    in parsed.named.items() if k != "ext")
                # check the string isn't empty
                if not stem_key:
                    continue
                row = {
                    "path": file_path,
                    "ext": path.suffix.lstrip("."),
                    **{k: v for k, v in parsed.named.items() if k != "ext"},}
            else:
                param_names = re.findall(r"\{(\w+)\}", fmt_str)
                # create a stem key with None for each parameter since it didn't match
                stem_key = "_".join(str(None) for _ in param_names)
                # double check the string isn't empty, if it is skip this file
                if not stem_key:
                    continue
                row = {
                    "path": file_path,
                    "ext": path.suffix.lstrip("."),
                    **{name: None for name in param_names},}
             
            stems.setdefault((fmt_str, stem_key), []).append(row)
            break
        # after rescue pass loop, add any remaining unmatched files to meta_files
        remaining_unmatched = [file for file in unmatched 
                                if not any(file == row["path"] 
                                for rows in stems.values() 
                                for row in rows)]
        meta_files.extend(remaining_unmatched)
    
    # root meta.yaml creation and commit
    meta_dict: dict = {"dataset": dataset_name}
    # find all meta files in the tree and add them to the meta_dict
    if meta_files:
        meta_dict["files"] = meta_files
    repo.dothm.dump_yml(meta_dict, "meta")
    repo.dothm.index.add(["meta.yml"])
    repo.dothm.index.commit(f"Initialize dataset: {dataset_name}")

    # one branch per stem
    for (fmt_str, stem_key), rows in stems.items():
        stem_pf = ParaFrame(rows, base_path=root)
        # skip empty ParaFrames
        if stem_pf.empty:
            continue

        branch_name = _sanitize_branch_name(f"{fmt_str}/{stem_key}")
        # check if the branch already exists, and create it if not
        existing = {h.name for h in repo.dothm.heads}
        if branch_name in existing:
            repo.dothm.git.checkout(branch_name)
        else:
            repo.dothm.git.checkout("-b", branch_name)
        repo.state = repo.dothm.load()

        repo.set_config(fmt=fmt_str)
        # add sha1 to stem ParaFrame
        stem_pf = stem_pf.copy()
        stem_pf["sha1"] = [Repo.checksum(root / path)
                            for path in stem_pf["path"]]

            # convert the ParaFrame to a manifest
        try:
            # compile parsers for the fmt and its variants with missing parameters
            manifest = manifest_frame_from_pf(stem_pf, fmt_str)
            repo.state.replace(manifest)
            repo.dothm.dump(repo.state)

            # store objects
            for _, row in repo.state.data.iterrows():
                match = stem_pf[stem_pf["sha1"] == row["sha1"]]
                if not match.empty:
                    # store the file in the repo objects using its sha1
                    repo.objects.store(root / match.iloc[0]["path"],
                                        row["sha1"])

        except Exception as e:
                # manifest build failed — write file list to meta.yml instead
                repo.dothm.dump_yml({
                    "error": str(e),
                    "stem_key": stem_key,
                    "files": stem_pf["path"].tolist(),
                }, "meta")
                repo.dothm.index.add(["meta.yml"])

        repo.dothm.index.commit(
                f"Add stem: {stem_key}\nFmt: {fmt_str}\nDataset: {dataset_name}")

    # return to main
    repo.dothm.git.checkout("main")
    repo.state = repo.dothm.load()
    return repo