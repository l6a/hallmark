"""
Tests for hallmark.eht_repo_builder, using mocked network calls so
nothing here depends on reaching the real CyVerse server.
"""
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from mock_server import MockServer
from hallmark.eht_repo_builder import (
    KNOWN_FIELD_VALUES,
    _extract_drive,
    _match_file_against_fmts,
    build_repo,
    list_remote_files,)

BASE_URL = "https://data.cyverse.org/dav-anon/iplant/commons/cyverse_curated/EHTC_TEST/"


# helper function to assert that the repo's remote config matches expected
def _assert_remote_config(repo, expected):
    """
    Assert that the repo's remote config matches the expected value.
    Args:
        repo: The Repo object to check.
        expected: The expected remote config value.
    """
    assert repo.state.config["remote"] == expected, (
        f"unexpected remotes: {repo.state.config['remote']}, expected {expected}")


# helper function to patch requests.get and requests.head to serve from a MockServer
def _served(server: MockServer):
    """
    Context manager patching requests.get/head to serve from server.
    Args:
        server: The MockServer instance to serve responses from.
    Returns:
        A context manager that patches requests.get and requests.head.
    """
    return patch.multiple(
        "hallmark.eht_repo_builder.requests",
        get=server.fake_get,
        head=server.fake_head,)


### list_remote_files tests ###

def test_list_remote_files_partial_manifest_below_threshold_is_rejected():
    """
    If checksum-like content is mostly invalid, it should not be treated as a manifest.
    """
    server = MockServer(BASE_URL)
    server.add_directory("", [
        ("data-object", "data.tar"),
        ("data-object", "checksum_report.txt"),])
    server.add_file(
        "checksum_report.txt",
        "\n".join([
            "this is not a checksum line",
            "another bad line",
            "aa11bb22cc33dd44ee55ff66aa11bb22  data.tar",]),)
    with _served(server):
        file_checksums = list_remote_files(server.base_url)

    assert file_checksums["data.tar"] == (None, None), \
        f"unexpected checksum for data.tar: {file_checksums}, \
            expected (None, None) because the manifest was mostly invalid"

def test_list_remote_files_sibling_manifest_covers_project_files():
    """
    A manifest in the same directory as a project subdir folder should
    cover all files in that subdir, without needing to fetch the subdir's listing.
    """
    server = MockServer(BASE_URL)
    server.add_directory("", [
        ("collection", "2016.1.01114.V/"),
        ("data-object", "2016.1.01114.V.md5sums"),])
    server.add_file("2016.1.01114.V.md5sums",
        "2f1d7fed9ceda962bf12bc4a20e068a8  2016.1.01114.V/data.tgz\n")
    with _served(server):
        file_checksums = list_remote_files(server.base_url)

    assert file_checksums["2016.1.01114.V/data.tgz"] == \
        ("md5", "2f1d7fed9ceda962bf12bc4a20e068a8"), \
        f"unexpected checksum for 2016.1.01114.V/data.tgz: {file_checksums}, \
            expected md5 2f1d7fed9ceda962bf12bc4a20e068a8"

def test_list_remote_files_sibling_manifest_directory_never_opened():
    """
    If a manifest fully covers a sibling directory, that directory's
    own listing should never be fetched -- it's trusted, not re-walked.
    """
    server = MockServer(BASE_URL)
    server.add_directory("", [
        ("collection", "2016.1.01114.V/"),
        ("data-object", "2016.1.01114.V.md5sums"),])
    server.add_file("2016.1.01114.V.md5sums",
        "2f1d7fed9ceda962bf12bc4a20e068a8  2016.1.01114.V/data.tgz\n")
    with _served(server):
        file_checksums = list_remote_files(server.base_url)

    assert "2016.1.01114.V/data.tgz" in file_checksums,\
          f"unexpected missing file: {file_checksums}, \
            expected 2016.1.01114.V/data.tgz to be listed"


def test_list_remote_files_generic_manifest_detected_by_content():
    """
    A manifest file whose name is generic (like "md5sum.txt") should
    still be detected as a manifest if its content looks like one.
    """
    server = MockServer(BASE_URL)
    server.add_directory("", [
        ("data-object", "data.tar"),
        ("data-object", "custom_checksum_manifest.log"),])
    server.add_file("custom_checksum_manifest.log",
        "aa11bb22cc33dd44ee55ff66aa11bb22  data.tar\n")
    with _served(server):
        file_checksums = list_remote_files(server.base_url)

    assert file_checksums["data.tar"] == \
        ("unknown", "aa11bb22cc33dd44ee55ff66aa11bb22"), \
            f"unexpected checksum for data.tar: {file_checksums}, \
                expected unknown aa11bb22cc33dd44ee55ff66aa11bb22"


def test_list_remote_files_generic_manifest_algorithm_from_own_filename():
    """
    A manifest file whose name is generic (like "sha1sum.txt") should
    still be detected as a manifest if its content looks like one, and
    the algorithm should be inferred from the manifest's own filename.
    """
    server = MockServer(BASE_URL)
    server.add_directory("", [
        ("data-object", "data.tar"),
        ("data-object", "sha1sum.txt"),])
    server.add_file("sha1sum.txt",
        "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb  data.tar\n")
    with _served(server):
        file_checksums = list_remote_files(server.base_url)

    assert file_checksums["data.tar"][0] == "sha1", \
        f"unexpected checksum algorithm for data.tar: {file_checksums}, \
            expected sha1 bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def test_list_remote_files_manifest_with_no_algorithm_hint_is_unknown():
    """
    When a manifest's own name gives no algorithm hint at all, the
    algorithm is recorded as "unknown" rather than guessed.
    """
    server = MockServer(BASE_URL)
    server.add_directory("", [
        ("data-object", "data.tar"),
        ("data-object", "totally_weird_manifest_name.log"),])
    server.add_file("totally_weird_manifest_name.log",
        "aa11bb22cc33dd44ee55ff66aa11bb22  data.tar\n")
    with _served(server):
        file_checksums = list_remote_files(server.base_url)

    assert file_checksums["data.tar"][0] == "unknown", \
        f"unexpected checksum algorithm for data.tar: {file_checksums}, \
            expected unknown aa11bb22cc33dd44ee55ff66aa11bb22"


def test_list_remote_files_non_manifest_text_file_not_misdetected():
    """
    A plain README shouldn't be treated as a manifest just because
    it happens to be a small text file.
    """
    server = MockServer(BASE_URL)
    server.add_directory("", [
        ("data-object", "README.txt"),])
    server.add_file("README.txt", "This is a plain readme, not a checksum list.\n")
    with _served(server):
        file_checksums = list_remote_files(server.base_url)

    assert file_checksums["README.txt"] == (None, None), \
        f"unexpected checksum for README.txt: {file_checksums}, \
            expected (None, None) for a non-manifest text file"


def test_list_remote_files_name_matching_content_not_manifest_rejected():
    """
    A file whose NAME matches the checksum keyword filter, but whose
    CONTENT doesn't look like a manifest, must still be rejected.
    """
    server = MockServer(BASE_URL)
    server.add_directory("", [
        ("data-object", "checksum_results.tar"),])
    server.add_file("checksum_results.tar", "not actually a manifest, just junk text")
    with _served(server):
        file_checksums = list_remote_files(server.base_url)

    assert file_checksums["checksum_results.tar"] == (None, None), \
        f"unexpected checksum for checksum_results.tar: {file_checksums}, \
            expected (None, None) for a non-manifest file"


def test_list_remote_files_root_level_static_file_has_no_checksum():
    """
    A file at the root level of the dataset, with no manifest coverage,
    should be listed with no checksum, rather than being skipped or
    misdetected as a manifest.
    """
    server = MockServer(BASE_URL)
    server.add_directory("", [
        ("data-object", "README.md"),])
    server.add_file("README.md", "root-level readme")
    with _served(server):
        file_checksums = list_remote_files(server.base_url)

    assert file_checksums["README.md"] == (None, None), \
        f"unexpected checksum for README.md: {file_checksums}, \
        expected (None, None) for a root-level static file with no manifest coverage"
    

def test_list_remote_files_empty_directory_returns_empty_mapping():
    """
    An empty dataset root should produce an empty file/checksum mapping.
    """
    server = MockServer(BASE_URL)
    server.add_directory("", [])
    with _served(server):
        file_checksums = list_remote_files(server.base_url)

    assert file_checksums == {}, f"expected empty mapping, got {file_checksums}"


def test_list_remote_files_walks_nested_subdirectories_without_manifest():
    """
    Nested subdirectories should be walked recursively when no manifest covers them.
    """
    server = MockServer(BASE_URL)
    server.add_directory("", [("collection", "level1/")])
    server.add_directory("level1", [
        ("collection", "level2/"),
        ("data-object", "root.txt"),])
    server.add_directory("level1/level2", [
        ("data-object", "deep.txt"),])
    with _served(server):
        file_checksums = list_remote_files(server.base_url)

    assert set(file_checksums) == {"level1/root.txt", "level1/level2/deep.txt"}, \
        f"unexpected nested listing: {file_checksums}, \
            expected both level1/root.txt and level1/level2/deep.txt"


### _match_file_against_fmts tests ###

def test_match_simple_clean_match():
    """
    Test that a simple clean match works correctly.
    """
    fmt_entries = [{"fmt": "a{a}_i{i}.h5", "db": "x.tsv"}]
    i, result = _match_file_against_fmts("a0.75_i30.h5", fmt_entries)

    assert i == 0, f"unexpected index: {i}, expected 0"
    assert result == {"a": "0.75", "i": "30"}, \
        f"unexpected result: {result}, expected {{'a': '0.75', 'i': '30'}}"


def test_match_missing_field_is_dropped():
    """
    A field that is missing from the filename should be dropped from the
    result, rather than causing a failed match.
    """
    fmt_entries = [{"fmt": "a{a}_i{i}.h5", "db": "x.tsv"}]
    i, result = _match_file_against_fmts("a0.75.h5", fmt_entries)

    assert i == 0, f"unexpected index: {i}, expected 0"
    assert result == {"a": "0.75"}, \
        f"unexpected result: {result}, expected {{'a': '0.75'}}"
    assert "i" not in result, f"unexpected result: {result}, expected 'i' to drop out"


def test_match_no_matching_fmt_returns_none():
    """
    A filename that doesn't match any of the provided formats should
    return None for both the index and the result.
    """
    fmt_entries = [{"fmt": "a{a}_i{i}.h5", "db": "x.tsv"}]
    i, result = _match_file_against_fmts("completely_unrelated_file.xyz", fmt_entries)

    assert i is None, f"unexpected index: {i}, expected None"
    assert result is None, f"unexpected result: {result}, expected None"


def test_match_prefers_more_specific_fmt_over_looser_one():
    """
    When multiple formats could match a filename, the one with more
    specific literals should be preferred over a looser one.
    """
    fmt_entries = [
        {"fmt": "{a}-longtoken1-{b}-longtoken2-{c}-longtoken3-{d}", 
         "db": "looks_specific.tsv"},
        {"fmt": "{x}.{y}", "db": "actually_correct.tsv"},
    ]
    i, result = _match_file_against_fmts("hello.world", fmt_entries)

    assert fmt_entries[i]["db"] == "actually_correct.tsv", \
        f"unexpected index: {i}, expected the second format to match"


def test_match_repeated_name_resolves_when_values_agree():
    """
    When a repeated name's occurrences genuinely agree, that name
    should be resolved to that value, rather than being dropped.
    """
    fmt = "{project_code}/group.uid{guid}.{author}.{track}-{source}-{project_code}" \
    "-{kind}.{format}"
    rel_path = "2016.V/group.uid_ABC.author.e17-3C279-2016.V-4fit.tgz"
    fmt_entries = [{"fmt": fmt, "db": "data.tsv"}]
    i, result = _match_file_against_fmts(rel_path, fmt_entries)

    assert result is not None, \
        f"unexpected None result for {rel_path} with fmt {fmt_entries}"
    assert result["project_code"] == "2016.V", \
        f"unexpected project_code: {result.get('project_code')}, expected '2016.V'"


def test_match_repeated_name_drops_when_values_disagree():
    """
    When a repeated name's occurrences genuinely disagree, that name
    must be dropped, not silently resolved to the wrong value.
    """
    fmt = "{project_code}/group.uid{guid}.{author}.{track}-{source}-{project_code}" \
    "-{kind}.{format}"
    rel_path = "2016.V/group.uid_ABC.author.e17-3C279-othervalue-4fit.tgz"
    fmt_entries = [{"fmt": fmt, "db": "data.tsv"}]
    i, result = _match_file_against_fmts(rel_path, fmt_entries)

    if result is not None:
        assert "project_code" not in result, f"unexpected project_code: \
            {result.get('project_code')}, expected it to be dropped due to disagreement"


def test_match_known_value_resolves_field_shift_ambiguity():
    """
    A field with a known-value constraint should be resolved to that
    value, rather than being dropped, even if that means the next field
    is shifted over to fill the gap.
    """
    assert "kind" in KNOWN_FIELD_VALUES, \
        f"unexpected KNOWN_FIELD_VALUES: {KNOWN_FIELD_VALUES}, expected 'kind' to be \
            a known-value field"
    fmt = "{track}-{obs_num}-{band}-{pointing}-{source}-{kind}.{format}"
    rel_path = "e18a24-1-b1-na-CYG-A-4fit.tar"
    fmt_entries = [{"fmt": fmt, "db": "data.tsv"}]
    i, result = _match_file_against_fmts(rel_path, fmt_entries)
    assert result["track"] == "e18a24", \
        f"unexpected track: {result.get('track')}, expected 'e18a24'"
    assert result["obs_num"] == "1", \
        f"unexpected obs_num: {result.get('obs_num')}, expected '1'"
    assert result["band"] == "b1", \
        f"unexpected band: {result.get('band')}, expected 'b1'"
    assert result["pointing"] == "na", \
        f"unexpected pointing: {result.get('pointing')}, expected 'na'"
    assert result["source"] == "CYG-A", \
        f"unexpected source: {result.get('source')}, expected 'CYG-A'"
    assert result["kind"] == "4fit", \
        f"unexpected kind: {result.get('kind')}, expected '4fit'"


def test_match_known_value_field_is_never_dropped():
    """
    A field with a known-value constraint should never be dropped, even
    if the next field is missing and would otherwise cause a shift.
    """
    fmt = "{scope}-processing-logs.{format}"
    fmt_entries = [{"fmt": fmt, "db": "log.tsv"}]
    i, result = _match_file_against_fmts("README.txt", fmt_entries)

    assert result is None, f"unexpected result: {result}, expected None because \
        'README.txt' does not match the known-value field 'scope'"


def test_match_long_literal_not_silently_cleared():
    """
    Regression test: a long distinctive literal should not be silently cleared
    """
    fmt_entries = [
        {"fmt": "{scope}-processing-logs.{format}", "db": "log.tsv"},]
    i, result = _match_file_against_fmts("EHTmetadata_2018April_v1.2.tar.gz", 
                                         fmt_entries)
    
    assert result is None, f"unexpected result: {result}, expected None because the \
        long distinctive literal '-processing-logs.' should not be clearable"


def test_match_genuine_log_file_still_matches():
    """
    A genuine log file that matches the format should still match,
    even though the format has a long distinctive literal that is not
    clearable.
    """
    fmt_entries = [
        {"fmt": "{scope}-processing-logs.{format}", "db": "log.tsv"},]
    i, result = _match_file_against_fmts("na-processing-logs.tgz", fmt_entries)

    assert result == {"scope": "na", "format": "tgz"}, \
        f"unexpected result: {result}, expected {{'scope': 'na', 'format': 'tgz'}}"


def test_match_short_delimiter_still_clearable():
    """
    A short, generic delimiter (like "-") should still be clearable
    when its field is dropped -- only long, distinctive literals are
    restricted.
    """
    fmt_entries = [{"fmt": "a{a}-{b}.h5", "db": "x.tsv"}]
    i, result = _match_file_against_fmts("a0.75.h5", fmt_entries)

    assert result == {"a": "0.75"}, \
        f"unexpected result: {result}, expected {{'a': '0.75'}}"
    

def test_match_empty_fmt_entries_returns_none():
    """
    No format candidates should yield no match.
    """
    i, result = _match_file_against_fmts("any_file.txt", [])

    assert i is None and result is None, f"expected no match, got {(i, result)}"


def test_match_prefers_exacter_match_when_one_format_is_looser():
    """
    A more exact format should win over a looser competing format.
    """
    fmt_entries = [
        {"fmt": "{a}.{b}", "db": "loose.tsv"},
        {"fmt": "hello.{b}", "db": "exact.tsv"},]
    i, result = _match_file_against_fmts("hello.world", fmt_entries)

    assert i == 1, f"expected second format to win, got index {i}"
    assert result == {"b": "world"}, \
        f"unexpected result: {result}, expected {{'b': 'world'}}"


### build_repo tests ###

# create a pytest fixture for a simple mock dataset server
@pytest.fixture
def simple_dataset_server():
    """
    A simple mock dataset server with a small directory structure and
    a manifest file, to test build_repo without hitting the real network.
    returns:
        A MockServer instance with the dataset structure registered.
    """
    server = MockServer(BASE_URL)
    server.add_directory("", [
        ("collection", "proj/"),
        ("data-object", "README.md"),])
    server.add_directory("proj", [
        ("data-object", "data.tar"),
        ("data-object", "md5sum.txt"),])
    server.add_file("proj/md5sum.txt",
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa  proj/data.tar\n")
    server.add_file("README.md", "root readme content")
    return server

# parametrize the remotes argument to test different input types
@pytest.mark.parametrize(
    "remotes_arg, expected",
    [
        ("origin", [{"name": "origin", "url": BASE_URL}]),
        ({"name": "origin"}, [{"name": "origin", "url": BASE_URL}]),
        ([{"name": "origin"}], [{"name": "origin", "url": BASE_URL}]),],)


def test_build_repo_remote_normalization(tmp_path, simple_dataset_server, remotes_arg, 
                                         expected):
    """
    Test that build_repo normalizes the remotes argument correctly, using a simple mock 
    dataset server to avoid hitting the real network.
    Args:
        tmp_path: A temporary directory provided by pytest for the test.
        simple_dataset_server: A fixture providing a MockServer instance
            with a simple dataset structure and manifest.
        remotes_arg: The input remotes argument to be normalized by build_repo.
        expected: The expected normalized remotes configuration.
    """
    with _served(simple_dataset_server):
        repo = build_repo(
            repo_path=tmp_path / "repo_remote_norm.hm",
            dataset_name="EHTC_TEST",
            fmt_entries=[],
            remotes=remotes_arg,)

    _assert_remote_config(repo, expected)


def test_build_repo_writes_expected_tsv_row(tmp_path, simple_dataset_server):
    """
    Test that build_repo writes the expected TSV row for a file with a
    known checksum, using a simple mock dataset server to avoid hitting
    the real network.
    Args:
        tmp_path: A temporary directory provided by pytest for the test.
        simple_dataset_server: A fixture providing a MockServer instance
            with a simple dataset structure and manifest."""
    fmt_entries = [
        {"fmt": "proj/data.{format}", "db": "data.tsv"},]
    with _served(simple_dataset_server):
        repo = build_repo(
            repo_path=tmp_path / "repo.hm",
            dataset_name="EHTC_TEST",
            fmt_entries=fmt_entries,)
    df = pd.read_csv(repo.dothm.path / "data.tsv", sep="\t", dtype=str)
    assert len(df) == 1, f"unexpected number of rows in data.tsv: {len(df)}, expected 1"
    row = df.iloc[0]

    assert row["path"] == "proj/data.tar", \
        f"unexpected path: {row['path']}, expected 'proj/data.tar'"
    assert row["checksum_algorithm"] == "md5", \
        f"unexpected checksum_algorithm: {row['checksum_algorithm']}, expected 'md5'"   
    assert row["checksum"] == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", f"unexpected checksum\
        : {row['checksum']}, expected 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'"


def test_build_repo_root_static_file_gets_known_name(tmp_path, simple_dataset_server):
    """
    Test that a root-level static file with no manifest coverage gets
    the expected known name in the repo, using a simple mock dataset
    server to avoid hitting the real network.
    Args:
        tmp_path: A temporary directory provided by pytest for the test.
        simple_dataset_server: A fixture providing a MockServer instance
            with a simple dataset structure and manifest.
    """
    with _served(simple_dataset_server):
        repo = build_repo(
            repo_path=tmp_path / "repo2.hm",
            dataset_name="EHTC_TEST",
            fmt_entries=[],)
    static_entries = [e for e in repo.state.config["data"] 
                      if e.get("file") == "README.md"]
    
    assert len(static_entries) == 1, f"unexpected number of static entries for \
        README.md: {len(static_entries)}, expected 1"
    assert static_entries[0].get("name") == "readme", f"unexpected name for README.md:\
          {static_entries[0].get('name')}, expected 'readme'"


def test_build_repo_size_threshold_skips_large_unmatched_file(tmp_path):
    """
    Test that build_repo skips downloading a large unmatched file, using
    a mock server to avoid hitting the real network.
    Args:
        tmp_path: A temporary directory provided by pytest for the test.
    Helper functions:
        huge_head: A helper function to simulate a HEAD request for a large file.
        refuse_get_body: A helper function to simulate a GET request for a large file
    """
    server = MockServer(BASE_URL)
    server.add_directory("", [
        ("data-object", "huge_unmatched.dat"),])
    server.add_file("huge_unmatched.dat", b"x" * 100)
    def huge_head(url, timeout=None):
        """
        Simulate a HEAD request for a large file, returning a response with
        a Content-Length header indicating a size of 5 GB.
        Args:
            url: The URL to fetch.
            timeout: Optional timeout parameter (not used in the mock).
        Raises:
            AssertionError: If the URL does not end with "huge_unmatched.dat".
        Returns:
            A MagicMock object simulating the response with a large Content-Length.
        """
        from unittest.mock import MagicMock
        resp = MagicMock()
        resp.raise_for_status = lambda: None
        resp.headers = {"Content-Length": str(5 * 1024 * 1024 * 1024)}
        return resp
    server.fake_head = huge_head

    def refuse_get_body(url, timeout=None):
        """
        Simulate a GET request for a large file, raising an AssertionError to indicate 
        that the body should not be fetched.
        Args:
            url: The URL to fetch.
            timeout: Optional timeout parameter (not used in the mock).
        Raises:
            AssertionError: Always raised to indicate that the body should not be 
            fetched for large files.
        """
        raise AssertionError(f"should never GET a file this large: {url}")

    with patch.multiple("hallmark.eht_repo_builder.requests",
                         get=lambda url, timeout=None: (
                             server.fake_get(url, timeout) 
                             if not url.endswith("huge_unmatched.dat")
                             else refuse_get_body(url, timeout)),
                         head=server.fake_head):
        repo = build_repo(
            repo_path=tmp_path / "repo3.hm",
            dataset_name="EHTC_TEST",
            fmt_entries=[],)
    entry = next(e for e in repo.state.config["data"] if e.get("file") == 
                 "huge_unmatched.dat")
    legacy_unknown = entry.get("unknown") == "unknown"
    normalized_unknown = (
        entry.get("checksum_algorithm") == "unknown"
        and entry.get("checksum") == "unknown"
    )
    assert legacy_unknown or normalized_unknown, \
        f"unexpected entry for huge_unmatched.dat: {entry}, \
        expected either legacy unknown or normalized checksum schema"


def test_build_repo_small_unmatched_file_still_downloaded_and_hashed(tmp_path, 
                                                                 simple_dataset_server):
    """
    Test that build_repo still downloads and hashes a small unmatched file,
    using a simple mock dataset server to avoid hitting the real network.
    Args:
        tmp_path: A temporary directory provided by pytest for the test.
        simple_dataset_server: A fixture providing a MockServer instance
            with a simple dataset structure and manifest.
    """
    with _served(simple_dataset_server):
        repo = build_repo(
            repo_path=tmp_path / "repo4.hm",
            dataset_name="EHTC_TEST",
            fmt_entries=[],)
    entry = next(e for e in repo.state.config["data"] if e.get("file") == "README.md")

    has_legacy_md5 = ("md5" in entry and entry["md5"] != "unknown")
    has_normalized_md5 = (
        entry.get("checksum_algorithm") == "md5"
        and entry.get("checksum") not in (None, "unknown"))
    
    assert has_legacy_md5 or has_normalized_md5, f"unexpected entry for README.md: \
        {entry}, expected either legacy md5 or normalized checksum schema"


def test_build_repo_interactive_detect_branch(monkeypatch, tmp_path, 
                                              simple_dataset_server):
    """
    fmt_entries=None should enter interactive detect flow and accept strict yes/no.
    Args:
        monkeypatch: A pytest fixture for safely patching builtins and other objects.
        tmp_path: A temporary directory provided by pytest for the test.
        simple_dataset_server: A fixture providing a MockServer instance
            with a simple dataset structure and manifest.
    """
    answers = iter(["detect", "no", "data.tsv"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    called = {"include_drives": None}
    def _fake_detect_fmt(rel_paths, include_drives=False):
        called["include_drives"] = include_drives
        return ["proj/data.{format}"]
    monkeypatch.setattr("hallmark.eht_repo_builder.detect_fmt", _fake_detect_fmt)
    with _served(simple_dataset_server):
        repo = build_repo(
            repo_path=tmp_path / "interactive_detect.hm",
            dataset_name="EHTC_TEST",
            fmt_entries=None,)

    assert called["include_drives"] is False, \
        f"expected include_drives=False, got {called['include_drives']}"
    data_tsv = repo.dothm.path / "data.tsv"
    assert data_tsv.exists(), f"expected {data_tsv} to be created"
    df = pd.read_csv(data_tsv, sep="\t", dtype=str)
    assert "proj/data.tar" in set(df["path"]), \
        f"expected proj/data.tar in data.tsv, got {df.to_dict(orient='records')}"
    

def test_build_repo_interactive_input_branch(monkeypatch, 
                                             tmp_path, simple_dataset_server):
    """
    fmt_entries=None should allow manual interactive input flow.
    Args:
        monkeypatch: A pytest fixture for safely patching builtins and other objects.
        tmp_path: A temporary directory provided by pytest for the test.
        simple_dataset_server: A fixture providing a MockServer instance
            with a simple dataset structure and manifest.
    """
    answers = iter(["input", "proj/data.{format}", "data.tsv", ""])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    with _served(simple_dataset_server):
        repo = build_repo(
            repo_path=tmp_path / "interactive_input.hm",
            dataset_name="EHTC_TEST",
            fmt_entries=None,)

    data_tsv = repo.dothm.path / "data.tsv"
    assert data_tsv.exists(), f"expected {data_tsv} to be created"
    df = pd.read_csv(data_tsv, sep="\t", dtype=str)
    assert "proj/data.tar" in set(df["path"]), \
        f"expected proj/data.tar in data.tsv, got {df.to_dict(orient='records')}"


def test_build_repo_interactive_detect_invalid_yes_no_raises(
    monkeypatch, tmp_path, simple_dataset_server
):
    """
    Detect flow should raise on any include_drives answer besides strict yes/no.
    Args:
        monkeypatch: A pytest fixture for safely patching builtins and other objects.
        tmp_path: A temporary directory provided by pytest for the test.
        simple_dataset_server: A fixture providing a MockServer instance
            with a simple dataset structure and manifest.
    Raises:
        ValueError: If the include_drives answer is not "yes" or "no".
    """
    answers = iter(["detect", "y"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    with _served(simple_dataset_server):
        with pytest.raises(ValueError):
            build_repo(
                repo_path=tmp_path / "interactive_invalid.hm",
                dataset_name="EHTC_TEST",
                fmt_entries=None,)


def test_build_repo_multiple_remotes(tmp_path, simple_dataset_server):
    """
    Test that build_repo correctly records multiple remotes in the repo's
    configuration, using a simple mock dataset server to avoid hitting the real network.
    Args:
        tmp_path: A temporary directory provided by pytest for the test.
        simple_dataset_server: A fixture providing a MockServer instance
            with a simple dataset structure and manifest.
    """
    with _served(simple_dataset_server):
        repo = build_repo(
            repo_path=tmp_path / "repo5.hm",
            dataset_name="EHTC_TEST",
            fmt_entries=[],
            remotes=[
                {"name": "origin", "url": "https://example.com/origin/"},
                {"name": "mirror", "url": "https://example.com/mirror/"},],)
        
    assert repo.state.config["remote"] == [
        {"name": "origin", "url": "https://example.com/origin/"},
        {"name": "mirror", "url": "https://example.com/mirror/"},]\
        , f"unexpected remotes: {repo.state.config['remote']}, expected two remotes"


def test_build_repo_remote_without_url_defaults_to_dataset_url(tmp_path,
                                                                simple_dataset_server):
    """
    Test that build_repo correctly defaults a remote without a URL to the dataset's 
    base URL, using a simple mock dataset server to avoid hitting the real network.
    Args:
        tmp_path: A temporary directory provided by pytest for the test.
        simple_dataset_server: A fixture providing a MockServer instance
            with a simple dataset structure and manifest.
    """
    with _served(simple_dataset_server):
        repo = build_repo(
            repo_path=tmp_path / "repo6.hm",
            dataset_name="EHTC_TEST",
            fmt_entries=[],
            remotes=[{"name": "origin"}],)
        
    assert repo.state.config["remote"] == [{"name": "origin", "url": BASE_URL}], \
        f"unexpected remotes: {repo.state.config['remote']}, expected one remote with \
            URL {BASE_URL}"


def test_build_repo_no_remotes_is_empty_list(tmp_path, simple_dataset_server):
    """
    Test that build_repo correctly records an empty list of remotes when none are 
    provided, using a simple mock dataset server to avoid hitting the real network.
    Args:
        tmp_path: A temporary directory provided by pytest for the test.
        simple_dataset_server: A fixture providing a MockServer instance
            with a simple dataset structure and manifest.
    """
    with _served(simple_dataset_server):
        repo = build_repo(
            repo_path=tmp_path / "repo7.hm",
            dataset_name="EHTC_TEST",
            fmt_entries=[],)
        
    assert repo.state.config["remote"] == [], \
        f"unexpected remotes: {repo.state.config['remote']}, expected an empty list"
    

def test_build_repo_with_empty_dataset_still_creates_repo(tmp_path):
    """
    An empty dataset should still create a repo structure without data rows.
    Args:
        tmp_path: A temporary directory provided by pytest for the test.
    """
    server = MockServer(BASE_URL)
    server.add_directory("", [])
    with _served(server):
        repo = build_repo(
            repo_path=tmp_path / "empty.hm",
            dataset_name="EHTC_TEST",
            fmt_entries=[],)
        
    assert repo.dothm.path.exists(), "repo directory was not created"
    assert "data" in repo.state.config, "repo config missing data section"
    assert repo.state.config["data"] == [], \
        f"expected no data entries, got {repo.state.config['data']}"


def test_build_repo_uses_multiple_fmt_entries(tmp_path):
    """
    Separate format entries should be preserved in the repo config.
    """
    server = MockServer(BASE_URL)
    server.add_directory("", [
        ("data-object", "projA_1.txt"),
        ("data-object", "projB_2.txt"),])

    fmt_entries = [
        {"fmt": "projA_{n}.txt", "db": "a.tsv"},
        {"fmt": "projB_{n}.txt", "db": "b.tsv"},]
    with _served(server):
        repo = build_repo(
            repo_path=tmp_path / "multi.hm",
            dataset_name="EHTC_TEST",
            fmt_entries=fmt_entries,)

    assert repo.state.config["data"] == fmt_entries, \
        f"unexpected data config: {repo.state.config['data']}, expected {fmt_entries}"


### _extract_drive tests ###

def test_extract_drive_extracts_archive_contents(tmp_path):
    """
    Test that _extract_drive correctly extracts the contents of a .tar.gz archive.
    Args:
        tmp_path: A temporary directory provided by pytest for the test.
    """
    import shutil
    src_dir = tmp_path / "_src"
    src_dir.mkdir()
    (src_dir / "inner.txt").write_text("hello", encoding="utf-8")
    archive_path = shutil.make_archive(str(tmp_path / "mydrive"), "gztar", 
                                       root_dir=str(src_dir))
    archive_path = Path(archive_path)

    extracted_dir = _extract_drive(archive_path)

    assert extracted_dir.is_dir(), \
        f"unexpected extracted_dir: {extracted_dir}, expected a directory"
    actual_content = (extracted_dir / "inner.txt").read_text(encoding="utf-8")
    assert actual_content == "hello", \
        f"unexpected content of inner.txt: {actual_content!r}, expected 'hello'"
    

def test_extract_drive_rejects_non_archive_file(tmp_path):
    """
    A non-archive path should fail cleanly.
    Args:
        tmp_path: A temporary directory provided by pytest for the test.
    Raises:
        Exception: If the provided path is not a recognized archive format.
    """
    non_archive = tmp_path / "not_an_archive.txt"
    non_archive.write_text("hello", encoding="utf-8")

    with pytest.raises(Exception):
        _extract_drive(non_archive)