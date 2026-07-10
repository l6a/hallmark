import re
from pathlib import Path

# common meta extensions to look for when building the fmts
META_EXTENSIONS = [".py", ".sh", ".md", ".pdf", ".rst", ".cfg", ".ini", ".yml", ".yaml"\
                   , ".sl", ".par", ".xcm"]
# common meta files to look for when building fmts
KNOWN_META_FILES = {"README", "LICENSE", "LICENCE", "INVENTORY", "run"}
# common drive extensions to look for when building fmts
DRIVE_EXTENSIONS = [".tgz", ".tar", ".gz", ".zip", ".bz2", ".xz", ".zst", ".7z", ".rar"]
# delimiter characters fmt detection splits on
_DELIM_PATTERN = r"[_\-.]"


def _stems_to_fmts(stems: list[str]) -> list[str]:
    """Cluster same-token-count stems into one fmt per shared literal pattern.
       
        Recursively call until all fmts are found

    Args:
        stems: Stems (with extension reattached if present) that all have
               the same number of tokens.

    Returns:
        List of fmt strings, one per distinct cluster found.
    """
    tokenized = {s: re.split(_DELIM_PATTERN, s) for s in stems}
    # keep track of delimitors for fmt reconstruction
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
        field_count = 0
        has_fixed = False
        for index, token in enumerate(cluster_tokenized[0]):
            values = [tokens[index] for tokens in cluster_tokenized]
            # if every stem has the same token at this position
            if len(set(values)) == 1:
                fmt_tokens.append(token)
                has_fixed = True
            else:
                # if the token is different for any, its a parameter
                fmt_tokens.append(f"{{p{field_count}}}")
                field_count += 1

        # concatenate the fmt from the tokens and delimiters
        if has_fixed and field_count > 0:
            cluster_delims = delimiters[cluster[0]]
            fmt_parts = [fmt_tokens[0]]
            for token, delim in zip(fmt_tokens[1:], cluster_delims):
                fmt_parts.append(delim)
                fmt_parts.append(token)
            fmts.append("".join(fmt_parts))
        # remove all the stems that fit this fmt
        for stem in cluster:
            remaining_stems.remove(stem)

    return fmts

def _is_extendable_variant(longer: str, shorter: str) -> str | None:
    """
    Check if `shorter` and `longer` are compatible fmt strings, where `longer` 
    has one additional token that can be removed to match `shorter`.

    Args:
        longer: A fmt string with one more token than `shorter`.
        shorter: A fmt string with one less token than `longer`.

        Returns:
            A new fmt string with the additional token in `longer` replaced by a
            parameter placeholder, if the two fmt strings are compatible. Otherwise,
            return None.
    """
    longer_tokens = re.split(_DELIM_PATTERN, longer)
    shorter_tokens = re.split(_DELIM_PATTERN, shorter)

    # if longer doesn't have a single extra token, they can't be compatible
    if len(longer_tokens) != len(shorter_tokens) + 1:
        return None
    
    # collect every compatible dropped position
    candidates = []
    # check each token position in the longer fmt for compatibility with the shorter fmt
    for i in range(len(longer_tokens)):
        # remove the token at index i from longer and compare to shorter
        candidate = longer_tokens[:i] + longer_tokens[i + 1:]
        compatible = True
        param_positions = {i}
        # check that every token in candidate matches the corresponding token in shorter
        for k, (candidate_token, shorter_token) in enumerate(
                zip(candidate, shorter_tokens)):
            # correcting for the removed token index
            longer_idx = k if k < i else k + 1
 
            # check if either token is already a parameter placeholder
            if re.fullmatch(r"\{p\d+\}", candidate_token) or \
                re.fullmatch(r"\{p\d+\}", shorter_token):
                # track the index of the parameter placeholder
                param_positions.add(longer_idx)
                continue
            # if the tokens are not equal, they are incompatible
            if candidate_token != shorter_token:
                compatible = False
                break
        if compatible:
            # record the num of params, the index, and the positions
            candidates.append((len(param_positions), i, param_positions))
        # don't merge if it will result in a fmt with no fixed tokens
    if not candidates:
        # the shorter fmt is not a compatible variant of the longer fmt
        return None

    # find the candidate with the fewest parameter placeholders
    min_params = min(count for count, _, _ in candidates)
    # only keep candidates with the minimum number of parameter placeholders
    best = [c for c in candidates if c[0] == min_params]
    # sort by the index of the dropped token in the longer fmt, descending
    best.sort(key=lambda c: c[1], reverse=True)
    # select the candidate with the highest dropped token index to keep leftmost tokens
    _, _, param_positions = best[0]
 
    # safety check that they aren't the same length, meaning there is no variance
    if len(param_positions) == len(longer_tokens):
        return None    
    
    # rebuild the fmt string with the parameter placeholders renumbered
    new_tokens = []
    field_count = 0
    for index, token in enumerate(longer_tokens):
        # if we are at the removed token index or a parameter placeholder
        if index in param_positions:
            new_tokens.append(f"{{p{field_count}}}")
            field_count += 1
        else:
            new_tokens.append(token)
 
    # get the delimiters from the longer fmt string to reconstruct the final fmt
    delims = re.findall(_DELIM_PATTERN, longer)
    tokens = [new_tokens[0]]
    # reconstruct the fmt string with the delimiters in between the tokens
    for token, delim in zip(new_tokens[1:], delims):
        tokens.append(delim)
        tokens.append(token)
    return "".join(tokens)


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


def detect_fmt(root: Path) -> list[str]:
    """
    Auto-detect format strings from the files in the directory.

    Args:
        root: Path to the dataset root directory containing the files.

    Returns:
        List of fmt strings without extensions, one per distinct file
        structure found in the files list.
    """
    root = Path(root).expanduser().resolve()
    inventory_files = scan_inventory(root)

    drive_exts = {ext.lstrip(".").lower() for ext in DRIVE_EXTENSIONS}
    meta_exts = {ext.lstrip(".").lower() for ext in META_EXTENSIONS}

    data_stems = []
    seen = set()
    for file in inventory_files:
        path = Path(file)
        # separate the extension from the stem
        extension = path.suffix.lstrip(".").lower()
        stem = path.stem

        # skip any files that are known meta files or have known meta/drive extensions
        if extension in drive_exts or extension in meta_exts:
            continue
        if stem.split(".")[0] in KNOWN_META_FILES:
            continue
        # check this stem hasn't already been added to the list
        if stem not in seen:
            seen.add(stem)
            data_stems.append(stem)

    # filter stems by token count to group them for fmt detection
    by_token_count: dict[int, list[str]] = {}
    for stem in data_stems:
        # split the stem up by delimiters
        token_count = len(re.split(_DELIM_PATTERN, stem))
        # add the stem to the list of stems with the same token count
        by_token_count.setdefault(token_count, []).append(stem)

    group_fmts = []
    for token_count, same_count_stems in sorted(by_token_count.items()):
        # create the fmt strings for each group of stems with the same token count
        group_fmts.extend(_stems_to_fmts(same_count_stems))
        
    # merge fmts that are the same except for an optional param
    group_fmts.sort(key=lambda f: len(re.split(_DELIM_PATTERN, f)), reverse=True)
    merged = []
    # check if the fmt has already been merged to avoid duplicates
    used = [False] * len(group_fmts)
    for i, longer in enumerate(group_fmts):
        if used[i]:
            continue
        current = longer
        for j, shorter in enumerate(group_fmts):
            # skip if the fmt is the same or has already been merged
            if i == j or used[j]:
                continue
            # check if the shorter fmt is an extendable variant of the current fmt
            extended = _is_extendable_variant(current, shorter)
            if extended is not None:
                current = extended
                used[j] = True
        merged.append(current)
        used[i] = True

    fmts = []
    for fmt in merged:
        # avoid adding duplicate fmts to the final list
        if fmt not in fmts:
            fmts.append(fmt)
    return fmts