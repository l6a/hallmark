from __future__ import annotations
from pathlib import Path
import shutil
from hallmark import ParaFrame
from .fmt_detection import detect_fmt, DRIVE_EXTENSIONS
import parse
import re

def _extract_drive(drive_path: Path) -> Path:
    # remove extension from drive name to create the extraction directory
    extract_dir = drive_path.parent / drive_path.stem
    # check that the drive has not already been extracted
    if not extract_dir.exists():
        shutil.unpack_archive(str(drive_path), str(extract_dir))
    return extract_dir

# private function used by build_tree to create nested data branch
def _build_data_branches(root: Path, fmt: str | list[str] | None, tracked: set[str],) \
                            -> dict:
    """
    Build the fmt/stem data structure for files matching the given fmt(s).

    Args:
        root:    Path to search for matching files.
        fmt:     Format string(s) for parsing data files. If None,
                 fmts are auto-detected from files list
        tracked: Set of relative file paths already accounted for.

    Returns:
        Dict of {fmt_str: {stem_key: ParaFrame, ..., "all": ParaFrame}}.
    """
    ### FMT STEMS OUTER DICT ###
    # if no fmt was entered, parse the files to find them
    if fmt is None:
        fmts = detect_fmt(root)
    else:
        # check if there is only one fmt
        fmts = [fmt] if isinstance(fmt, str) else fmt
    # make a parser for each fmt with normalized deliminators
    parsers = []
    # normalize the deliminators for parsing
    for f in fmts:
        # normalize the deliminators for parsing
        stem = re.sub(r"[\-.]", "_", f)
        tokens = stem.split("_")
        # keep the full stem in the variants list
        variants = [stem]
        for i, token in enumerate(tokens):
            if re.fullmatch(r"\{p\d+\}", token):
                # remove one parameter token at a time to create a variant
                dropped = tokens[:i] + tokens[i + 1:]
                variants.append("_".join(dropped))

        for v in variants:
            # create a parser for each variant
            parsers.append((f, len(v.split("_")), parse.compile(v)))

    # dict of the different fmt stems initialization
    fmt_stems = {}
    # search all subdirectories from root
    for file in root.rglob("*"):
        # if the file isn't a dir or a drive
        relative_path = str(file.relative_to(root))
        if relative_path in tracked or not file.is_file():
            continue
        # reset parse and fmt for each file
        parsed = None
        matched_fmt = None

        stem_only = re.sub(r"[\-.]", "_", file.stem)
        stem_with_ext = stem_only + re.sub(r"[\-.]", "_", file.suffix)
        # counts to see if ext was included in fmt
        stem_only_token_count = len(stem_only.split("_"))
        stem_with_ext_token_count = len(stem_with_ext.split("_")) 

        # parse the file name to extract fields, skip if it doesn't match the format
        for fmt_str, variant_token_count, parser in parsers:
            # if these are equal, there was no ext in the fmt
            if variant_token_count == stem_only_token_count:
                candidate = stem_only
            # if these are equal, there was an ext in the fmt
            elif variant_token_count == stem_with_ext_token_count:
                candidate = stem_with_ext
            # if neither are equal, this fmt is not compatible with this file
            else:
                continue
            parsed = parser.parse(candidate)
            # break out once correct parser is found
            if parsed:
                matched_fmt = fmt_str
                break

        if parsed:
            # get path to file from data root
            relative_path = str(file.relative_to(root))
            # create unique stem name based on fmt parameters excluding extension
            stem_key = "_".join(str(value) for key, value in parsed.named.items() 
                                if key != "ext")
            # create a row for this file to add to relevant Paraframe
            row = {
                "path": relative_path,
                # normalize ext to not have period
                "ext": Path(relative_path).suffix.lstrip("."),
                # one column for each different parsed field
                **{key: value for key, value in parsed.named.items() if key != "ext"},}
            # add row to dict, and create the dict if it doesn't exist yet
            fmt_stems.setdefault(matched_fmt, {}).setdefault(stem_key, []).append(row)
            tracked.add(relative_path)

    ### FMT STEMS INNER DICTS ###
    # data structure initialization
    data_branches = {}
    # for every fmt and its stem dict
    for fmt_str, stems in fmt_stems.items():
        fmt_dict = {}
        all_rows = []
        # loop thru every stem for this fmt
        for stem_key, rows in stems.items():
            # create a Paraframe for each different stem
            stem_pf = ParaFrame(rows, base_path=root)
            # stem Paraframes are nested inside the fmt dict
            fmt_dict[stem_key] = stem_pf
            all_rows.extend(rows)
        # create a Paraframe with all the stems for this dict merged
        fmt_dict["all"] = ParaFrame(all_rows, base_path=root)
        # each fmt broken into different data branches
        data_branches[fmt_str] = fmt_dict

    return data_branches


def build_tree(root: Path, fmt: str | list[str] | None = None, data_type: str = "L2")\
                 -> dict:
    """
    Build an in-memory pytree for an EHT dataset directory.

    Args:
        root: Path to the EHT dataset root directory.
        fmt: Format string for parsing data files.
        data_type: Type of data to build ("L1" or "L2")

    Returns:
        A dictionary with keys:
        - "meta"   : ParaFrame of housekeeping files
        - "drives" : ParaFrame of compressed archives
        - "data"   : dict of {stem -> ParaFrame}
    """
    # create clean root path
    root = Path(root).expanduser().resolve()
    # track files that are included in the tree to avoid double counting
    tracked = set()

    # L1 data makes recursive calls for each directory, so use glob instead of rglob
    glob_fn = root.glob if data_type == "L1" else root.rglob

    ### DRIVES ###
    # collect all drive paths matching any supported extension
    drive_paths = []
    extracted_dir_names = set()
    for ext in DRIVE_EXTENSIONS:
        # add any file that has this ext to the drive paths list and tracked set
        for path in glob_fn(f"*{ext}"):
            extract_dir = _extract_drive(path)
            # only L1 data needs to track the extracted directory names for recursion
            if data_type == "L1":
                extracted_dir_names.add(extract_dir.name)
            drive_paths.append(str(path.relative_to(root)))
            tracked.add(str(path.relative_to(root)))
    # build a single ParaFrame from all drive paths with extensions column
    drives_pf = ParaFrame(
    [{"path": path, "ext": Path(path).suffix.lstrip(".")} 
     for path in sorted(drive_paths)],
    base_path=root,)

    ### DATA ###
    data_branches = _build_data_branches(root, fmt, tracked) \
                    if data_type == "L2" else {}

    ### META ###
    # create a list of all files under root that aren't tracked
    meta_files = {
        str(file.relative_to(root))
        for file in glob_fn("*")
        # add inventory item if its not a dir, not the .hm, and not in tracked
        if file.is_file() 
           and ".hm" not in file.parts
           and str(file.relative_to(root)) not in tracked
    }
    # create a paraframe for the meta files with extensions column
    meta_pf = ParaFrame(
    [{"path": file, "ext": Path(file).suffix.lstrip(".")} 
     for file in sorted(meta_files)],
    base_path=root,)
    for _, row in meta_pf.iterrows():
        tracked.add(row["path"])
        
    # create dict with three keys, only data has subbranches
    tree = {}
    if not meta_pf.empty:
        tree["meta"] = meta_pf
    if not drives_pf.empty:
        tree["drives"] = drives_pf
    if data_branches:
        tree["data"] = data_branches
 
    # recursive L1 tree construction
    if data_type == "L1":
        # call build_tree for each subdirectory
        for subdir in sorted(p for p in root.iterdir() if p.is_dir()):
            # calls with drives will end recursion
            next_level = "L2" if subdir.name in extracted_dir_names else "L1"
            # append each subdirectory to the tree
            tree[subdir.name] = build_tree(subdir, fmt, data_type=next_level)
 
    return tree