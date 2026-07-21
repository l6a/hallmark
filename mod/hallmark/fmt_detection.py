import re
from pathlib import Path
from itertools import combinations

# common meta extensions to look for when building the fmts
META_EXTENSIONS = [".py", ".sh", ".md", ".pdf", ".rst", ".cfg", ".ini", ".yml", ".yaml"\
                   , ".sl", ".par", ".xcm", ".codes", ".swp"]
# common meta files to look for when building fmts
KNOWN_META_FILES = {"README", "LICENSE", "LICENCE", "INVENTORY", "run"}
# common drive extensions to look for when building fmts
DRIVE_EXTENSIONS = [".tgz", ".tar", ".zip", ".bz2", ".xz", ".zst", ".7z", ".rar"]
# delimiter characters fmt detection splits on
_DELIM_PATTERN = r"[_\-./]"
# treat common multi-part archive suffixes explicitly
_MULTI_PART_DRIVE_EXTS = (".tar.gz", ".tar.bz2", ".tar.xz")

# convert the extensions to lowercase and remove the leading dot for easier comparison
DRIVE_EXTS_LOWER = {ext.lstrip(".").lower() for ext in DRIVE_EXTENSIONS}
META_EXTS_LOWER = {ext.lstrip(".").lower() for ext in META_EXTENSIONS}
KNOWN_META_FILES_UPPER = {name.upper() for name in KNOWN_META_FILES}

_PARAM_PATTERNS: dict[str, str] = {
    "experiment": r"e\d{2}[a-z]\d{2}",   # e.g. e17a10, e17d05
    "band":       r"^(hi|lo)$",           # hi or lo
    "pass":       r"^\d$",                # single digit, e.g. 7
    "scan":       r"^\d{3}$",             # three-digit day, e.g. 097
    "doy":        r"^\d{3}$",             # alias for scan
}

# Known-value lookup — EHT domain knowledge
_KNOWN_PARAM_VALUES: dict[str, set[str]] = {
    "band":     {"hi", "lo"},
    "pipeline": {"hops", "casa", "smili", "difmap"},
    "stage":    {"4fit", "dxin", "fits", "haxp", "hops",
                 "pcin", "pcqk", "swin"},
    "source":   {"M87", "SgrA", "3C279", "OJ287", "1055-018",
                 "1055+018", "3C273", "SGRA", "sgra"},
    "stokes":   {"I", "Q", "U", "V", "StokesI"},
    "method":   {"besttime", "norm", "scan"},
}

def _infer_param(observed: set[str], used_names: set[str], 
                        fallback: str) -> str:
    """
    Infer a parameter name from a set of observed values.

    Args:
        observed: Set of observed values for a parameter.
        used_names: Set of parameter names that have been used by other parameters
        fallback: Fallback parameter name to use if no match is found.

    Returns:
        Inferred parameter name, or the fallback if no match is found.
    """
    # pattern matching
    for name, pattern in _PARAM_PATTERNS.items():
        if name in used_names:
            continue
        if all(re.fullmatch(pattern, v) for v in observed):
            return name
    # known value lookup
    for name, known in _KNOWN_PARAM_VALUES.items():
        if name in used_names:
            continue
        if observed.issubset(known):
            return name
    return fallback

def _stems_to_fmts(stems: list[str]) -> list[str]:
    """
    Cluster same-token-count stems into one fmt per shared literal pattern.

    Args:
        stems: Stems (with extension reattached if present) that all have
               the same number of tokens.

    Returns:
        List of fmt strings, one per distinct cluster found.
    """
    tokenized = {s: re.split(_DELIM_PATTERN, s) for s in stems}
    # keep track of delimiters for fmt reconstruction
    delimiters = {s: re.findall(_DELIM_PATTERN, s) for s in stems}
    remaining_stems = list(stems)
    fmts = []

    while remaining_stems:
        # check that every stem shares at least one token
        reference_tokens = tokenized[remaining_stems[0]]
        token_count = len(reference_tokens)
        global_has_fixed = any(
            # set will be length 1 if all stems have the same token at this index
            len({tokenized[s][index] for s in remaining_stems}) == 1
            for index in range(token_count))
        
        # cluster found
        if global_has_fixed:
            cluster = list(remaining_stems)
        else:
            # base the anchor around the first non-assigned stem
            anchor = remaining_stems[0]
            anchor_tokens = tokenized[anchor]

            # group remaining stems by which token positions they share with the anchor
            stems_by_shared_positions : dict[tuple, list[str]] = {}
            for stem in remaining_stems[1:]:
                tokens = tokenized[stem]
                shared_positions = tuple(
                    i for i in range(len(anchor_tokens))
                    if tokens[i] == anchor_tokens[i])
                # if there are any tokens that match the anchor
                if shared_positions:
                    stems_by_shared_positions.setdefault(shared_positions, \
                                                         []).append(stem)

            if not stems_by_shared_positions:
                # anchor matches nobody on any position and stem doesn't contain fmt
                remaining_stems.remove(anchor)
                continue

            # find the cluster with most members that share positions with the anchor
            _, best_members = max(stems_by_shared_positions.items(), \
                                  key=lambda kv: len(kv[1]))
            cluster = [anchor] + best_members

        # build the fmt directly from the cluster
        cluster_tokenized = [tokenized[stem] for stem in cluster]
        fmt_tokens = []
        used_names = set()
        field_count = 0
        has_fixed = False
        for index, token in enumerate(cluster_tokenized[0]):
            values = [tokens[index] for tokens in cluster_tokenized]
            # if every stem has the same token at this position
            if len(set(values)) == 1:
                fmt_tokens.append(token)
                has_fixed = True
            # if the token is different for any, its a parameter
            else:
                observed = set(values)
                # try to infer a parameter name from the observed values
                inferred_name = _infer_param(
                    observed, used_names, fallback=f"p{field_count}"
                )
                fmt_tokens.append(f"{{{inferred_name}}}")
                used_names.add(inferred_name)
                field_count += 1

        # reconstruct the fmt from tokens and delimiters
        cluster_delims = delimiters[cluster[0]]
        fmt_parts = [fmt_tokens[0]]
        for token, delim in zip(fmt_tokens[1:], cluster_delims):
            fmt_parts.append(delim)
            fmt_parts.append(token)
        fmt_candidate = "".join(fmt_parts)

        # only add the fmt if it has at least one fixed token or more than one stem
        if has_fixed or len(cluster) > 1:
            fmts.append(fmt_candidate)

        # remove all the stems that fit this fmt
        for stem in cluster:
            remaining_stems.remove(stem)

    return fmts

def _align(longer_tokens: list[str], shorter_tokens: list[str]):
    """
    Find the best way to drop tokens from `longer_tokens` so its length
    matches `shorter_tokens`, marking any position that differs between
    them (literal mismatch or an existing parameter) for parameterization.

    Returns:
        (diff_positions, genuine_literal_match) or None if incompatible.
    """
    # double check that the longer fmt is actually longer than the shorter one
    gap = len(longer_tokens) - len(shorter_tokens)
    if gap < 0:
        return None
    
    # list of every possible way to drop `gap` tokens from the longer fmt
    candidates = []
    # iterate over every combination of indices to drop from the longer fmt
    for drop_set in combinations(range(len(longer_tokens)), gap):
        # list of tokens from the longer fmt after dropping the selected indices
        candidate = [tok for i, tok in enumerate(longer_tokens) if i not in drop_set]
        genuine = False
        # find the positions where the candidate and shorter fmt differ
        diff_positions = set(drop_set)
        # list of tokens that should stay in the longer fmt
        kept_indices = [i for i in range(len(longer_tokens)) if i not in drop_set]
        # compare the candidate tokens to the shorter fmt tokens
        for k, (ct, st) in enumerate(zip(candidate, shorter_tokens)):
            longer_idx = kept_indices[k]
            # if either token is a parameter, mark this position for parameterization
            if re.fullmatch(r"\{.*?\}", ct) or re.fullmatch(r"\{.*?\}", st):
                diff_positions.add(longer_idx)
                continue
            # if the tokens are different, mark this position for parameterization
            if ct != st:
                diff_positions.add(longer_idx)
            else:
                genuine = True
        # create a tuple of (num of diff positions, diff positions, match status)
        candidates.append((len(diff_positions), diff_positions, genuine))

    if not candidates:
        return None
    # find the candidate with the fewest differing positions
    min_count = min(c[0] for c in candidates)
    # find the best candidate(s) with the fewest differing positions and a match
    best = [c for c in candidates if c[0] == min_count]
    best = [c for c in best if c[2]] or best
    # return the first best candidate's diff positions and match status
    return best[0][1], best[0][2]

def _is_drive_path(path: Path) -> bool:
    """
    Return True if path looks like a drive/archive file.

    Args:
        path: Path object representing the file or directory to check.

    Returns:
        True if the path looks like a drive/archive file, False otherwise.
    """
    lower_name = path.name.lower()
    # check for multi-part archive suffixes first
    if any(lower_name.endswith(ext) for ext in _MULTI_PART_DRIVE_EXTS):
        return True
    # check for single-part archive suffixes
    return path.suffix.lstrip(".").lower() in DRIVE_EXTS_LOWER

def combine_alike_fmts(fmts: list[str], exclude_tokens: set[str] | None = None) \
                                    -> list[str]:
    """
    Merge fmts that share at least one literal token into a single fmt.

    For each group of fmts sharing a literal token, the longest fmt in
    the group is used as the frame. Any position that differs across
    the group's members (whether due to a literal mismatch or a token
    count gap) becomes a new parameter; positions identical across the
    entire group remain literal.

    Args:
        fmts: List of fmt strings to merge.
        exclude_tokens: Set of tokens to exclude from consideration when merging.

    Returns:
        List of fmt strings, with alike fmts combined into one.
    """
    fmts = list(fmts)
    result = []
    used = [False] * len(fmts)
    exclude_tokens = exclude_tokens or set()

    # tokenize every fmt once
    tokens_cache = {idx: re.split(_DELIM_PATTERN, f) for idx, f in enumerate(fmts)}
    literal_tokens_cache = {
        idx: {t for t in tokens if not re.fullmatch(r"\{.*?\}", t)} - exclude_tokens
        for idx, tokens in tokens_cache.items()}

    # for each fmt, find all other fmts that share at least one literal token
    for i in range(len(fmts)):
        # skip if this fmt has already been merged into a previous group
        if used[i]:
            continue
        # group every fmt sharing at least one literal token with fmts[i]
        group = [i]
        # tokens for the current fmt, excluding any parameter tokens
        i_tokens = literal_tokens_cache[i]
        for j in range(len(fmts)):
            # don't compare the fmt to itself or any fmt that has already been merged
            if i == j or used[j]:
                continue
            # tokens for the other fmt, excluding any parameter tokens
            j_tokens = literal_tokens_cache[j]
            # append to the group if the two fmts share at least one literal token
            if i_tokens & j_tokens:
                group.append(j)

        # if the group only contains one fmt, it won't be merged with anything else
        if len(group) == 1:
            result.append(fmts[i])
            used[i] = True
            continue

        # use the longest fmt in the group as the frame to align everything else
        frame_idx = max(group, key=lambda idx: len(tokens_cache[idx]))
        frame_tokens = tokens_cache[frame_idx]

        # positions that differ to turn into parameters
        all_diff_positions = set()
        any_genuine = False
        for idx in group:
            # don't compare the frame to itself
            if idx == frame_idx:
                continue
            # align the frame fmt to the other fmt, marking any differing positions
            diff_positions, genuine = _align(frame_tokens, tokens_cache[idx])
            # the union of previously differing positions and the new positions
            all_diff_positions |= diff_positions
            any_genuine = any_genuine or genuine

        # no genuine matches or every position differs
        if not any_genuine or len(all_diff_positions) == len(frame_tokens):
            # append the frame fmt as-is, since it can't be merged with anything else
            result.append(fmts[i])
            used[i] = True
            continue

        new_tokens = []
        param_count = 0
        # collect the names of any parameters to avoid duplicates
        used_names = {re.sub(r"[\{\}]", "", t) for t in frame_tokens 
                        if re.fullmatch(r"\{.*?\}", t)}
        for idx, token in enumerate(frame_tokens):
            # if this position differs across the group, make it a parameter
            if idx in all_diff_positions:
                # if already a parameter, keep it as-is
                if re.fullmatch(r"\{.*?\}", token):
                    new_tokens.append(token)
                else:
                    # new parameter position
                    fallback = f"p{param_count}"
                    # avoid duplicate parameter names by incrementing the fallback name
                    while fallback in used_names:
                        param_count += 1
                        fallback = f"p{param_count}"
                    new_tokens.append(f"{{{fallback}}}")
                    used_names.add(fallback)
                    param_count += 1  
            else:
                new_tokens.append(token)
        delims = re.findall(_DELIM_PATTERN, fmts[frame_idx])
        parts = [new_tokens[0]]
        for tok, delim in zip(new_tokens[1:], delims):
            # reconstruct the fmt string with the delimiters in between the tokens
            parts.append(delim)
            parts.append(tok)
        # append the merged fmt to the result list
        result.append("".join(parts))
        for idx in group:
            used[idx] = True

    return result

def scan_inventory(root: Path) -> list[str]:
    """
    Scan a directory and return all file paths found, recursively.

    Args:
        root: Path to the dataset root directory to scan.

    Returns:
        List of relative file path strings found under root.

    Raises:
        FileNotFoundError: If root does not exist.
    """
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"{root} is not a directory")

    return sorted(
        # convert to relative path strings for consistency with fmt detection
        str(file.relative_to(root))
        for file in root.rglob("*")
        # only include files, and ignore any hallmark meta files
        if file.is_file() and ".hm" not in file.parts
    )


def detect_fmt(rel_paths: list[str], include_drives: bool = False) -> list[str]:
    """
    Auto-detect the fmt(s) of a list of relative file paths.

    Args:
        rel_paths: List of relative file path strings to detect formats from.
        include_drives: If True, include drive/archive files in the fmt detection.

    Returns:
        List of detected fmt strings, one per distinct pattern found.
    """
    data_stems = []
    seen = set()
    # filter out any meta files or meta extensions from the list of relative paths
    for file in rel_paths:
        path = Path(file)
        # separate the extension from the stem
        extension = path.suffix.lstrip(".").lower()
        # separate the last piece of the stem from the rest of the path
        last_piece = path.stem.split(".")[-1]

        # skip drive files unless explicitly requested
        if not include_drives and _is_drive_path(path):
            continue
        # skip any files that are known meta files or have known meta extensions
        if extension in META_EXTS_LOWER:
            continue
        if last_piece.upper() in KNOWN_META_FILES_UPPER:
            continue
        stem = file
        # check this stem hasn't already been added to the list
        if stem not in seen:
            seen.add(stem)
            data_stems.append(stem)

    ### FMTS THAT MATCH A SINGLE ANCHOR TOKEN ###

    stem_tokens_cache = {stem: re.split(_DELIM_PATTERN, stem) for stem in data_stems}
    # find all files with one token that can be used as an anchor for fmt detection
    anchors = [stem for stem in data_stems if len(stem_tokens_cache[stem]) == 1]
    anchor_fmts = []
    consumed = set()

    for anchor in anchors:
        # skip if this anchor has already been used by a previous anchor (identical)
        if anchor in consumed:
            continue
        matches = []
        for stem in data_stems:
            # if there are no other parts besides the anchor
            if stem == anchor or stem in consumed:
                continue
            tokens = stem_tokens_cache[stem]
            # if the anchor is anywhere in the stem
            if anchor in tokens:
                matches.append(stem)
        if not matches:
            continue

        # build the fmt from whichever match has the most extra tokens
        longest = max(matches, key=len)
        longest_tokens = stem_tokens_cache[longest]
        longest_delims = re.findall(_DELIM_PATTERN, longest)
        fmt_tokens = []
        field_count = 0
        for token in longest_tokens:
            if token == anchor:
                fmt_tokens.append(token)
            else:
                fmt_tokens.append(f"{{p{field_count}}}")
                field_count += 1
        fmt_parts = [fmt_tokens[0]]
        # reconstruct the fmt string with the delimiters in between the tokens
        for token, delim in zip(fmt_tokens[1:], longest_delims):
            fmt_parts.append(delim)
            fmt_parts.append(token)
        anchor_fmts.append("".join(fmt_parts))        

        consumed.add(anchor)
        consumed.update(matches)

    # remove any stems that have already been consumed by the anchor fmt detection
    data_stems = [stem for stem in data_stems if stem not in consumed]

    # filter stems by token count to group them for fmt detection
    by_token_count: dict[int, list[str]] = {}
    for stem in data_stems:
        # split the stem up by delimiters
        token_count = len(stem_tokens_cache[stem])
        # add the stem to the list of stems with the same token count
        by_token_count.setdefault(token_count, []).append(stem)

    group_fmts = []
    for token_count, same_count_stems in sorted(by_token_count.items()):
        # create the fmt strings for each group of stems with the same token count
        group_fmts.extend(_stems_to_fmts(same_count_stems))

    # find tokens that are present in every stem to avoid making them parameters
    always_present_tokens: set[str] = set()
    if data_stems:
        # find the intersection of all token sets
        token_sets = [set(stem_tokens_cache[stem]) for stem in data_stems]
        always_present_tokens = set.intersection(*token_sets)

    fmts = combine_alike_fmts(group_fmts, exclude_tokens=always_present_tokens)
    # only keep fmts that have at least 1 parameter        
    fmts = [f for f in fmts if re.search(r"\{.*?\}", f)]

    return anchor_fmts + fmts