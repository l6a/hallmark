from pathlib import Path

import pandas as pd
import pytest

from hallmark import Repo
from hallmark import ParaFrame


### Ensure ParaFrame type
def test_standard_pf_is_paraframe(hallmark_test_suite_dictionary):
    assert isinstance(hallmark_test_suite_dictionary["standard_pf"], ParaFrame)

def test_encoded_pf_is_paraframe(hallmark_test_suite_dictionary):
    assert isinstance(hallmark_test_suite_dictionary["encoded_pf"], ParaFrame)

### Test Standard pf
def test_standard_pf_shape(hallmark_test_suite_dictionary):
    pf = hallmark_test_suite_dictionary["standard_pf"]
    assert pf.shape == (12, 3)

def test_standard_pf_column_names(hallmark_test_suite_dictionary):
    pf = hallmark_test_suite_dictionary["standard_pf"]
    assert set(pf.columns) == {"path", "a", "i"}

def test_standard_pf_column_value_types(hallmark_test_suite_dictionary):
    pf = hallmark_test_suite_dictionary["standard_pf"]
    assert pd.api.types.is_float_dtype(pf["a"])
    # i values are whole numbers so they convert to int64, not float64
    assert pd.api.types.is_numeric_dtype(pf["i"])

def test_standard_pf_values(hallmark_test_suite_dictionary):
    pf = hallmark_test_suite_dictionary["standard_pf"]
    assert set(pf["a"].unique()) == {0.0, 0.75, 0.975}
    assert set(pf["i"].unique()) == {0.0, 30.0, 60.0, 90.0}

def test_standard_pf_paths_match_created_files(hallmark_test_suite_dictionary):
    pf = hallmark_test_suite_dictionary["standard_pf"]
    assert sorted(pf["path"]) == sorted(
        hallmark_test_suite_dictionary["standard_files"])

def test_standard_pf_supports_pandas_methods(hallmark_test_suite_dictionary):
    pf = hallmark_test_suite_dictionary["standard_pf"]
    assert isinstance(pf.head(), pd.DataFrame)

def test_standard_glob_pattern_created_properly(hallmark_test_suite_dictionary):
    pattern = hallmark_test_suite_dictionary["standard_glob_pattern"].replace("\\", "/")
    assert pattern.endswith("/a*_i*.h5")

def test_standard_glob_returns_expected_files(hallmark_test_suite_dictionary):
    files = hallmark_test_suite_dictionary["standard_globbed_files"]
    assert len(files) == 12

def test_standard_pf_single_filter_argument(hallmark_test_suite_dictionary):
    pf = hallmark_test_suite_dictionary["standard_pf"]
    filtered = pf(a=0.75)
    assert len(filtered) == 4
    assert set(filtered["a"].unique()) == {0.75}

def test_standard_pf_filter_multiple_values(hallmark_test_suite_dictionary):
    pf = hallmark_test_suite_dictionary["standard_pf"]
    filtered = pf(a=[0.75, 0.975])
    assert len(filtered) == 8
    assert set(filtered["a"].unique()) == {0.75, 0.975}

def test_standard_pf_filter_multiple_conditions(hallmark_test_suite_dictionary):
    pf = hallmark_test_suite_dictionary["standard_pf"]
    filtered = pf(a=0.75)(i=0)
    assert len(filtered) == 1
    assert set(filtered["a"].unique()) == {0.75}
    assert set(filtered["i"].unique()) == {0}

### Test encoded pf
def test_encoded_pf_shape(hallmark_test_suite_dictionary):
    pf = hallmark_test_suite_dictionary["encoded_pf"]
    assert pf.shape == (4, 3)

def test_encoded_pf_column_names(hallmark_test_suite_dictionary):
    pf = hallmark_test_suite_dictionary["encoded_pf"]
    assert set(pf.columns) == {"path", "aspin", "i"}

def test_encoded_pf_has_custom_spin_type(hallmark_test_suite_dictionary):
    pf = hallmark_test_suite_dictionary["encoded_pf"]
    assert pd.api.types.is_float_dtype(pf["aspin"])

def test_encoded_pf_spin_values(hallmark_test_suite_dictionary):
    pf = hallmark_test_suite_dictionary["encoded_pf"]
    assert set(pf["aspin"].unique()) == {-0.5}

def test_encoded_pf_i_values(hallmark_test_suite_dictionary):
    pf = hallmark_test_suite_dictionary["encoded_pf"]
    assert set(pf["i"].unique()) == {0.0, 30.0, 60.0, 90.0}

def test_encoded_pf_filter_single_value(hallmark_test_suite_dictionary):
    pf = hallmark_test_suite_dictionary["encoded_pf"]
    filtered = pf(aspin=-0.5)
    assert len(filtered) == 4
    assert set(filtered["aspin"].unique()) == {-0.5}

def test_encoded_pf_filter_multiple_values(hallmark_test_suite_dictionary):
    pf = hallmark_test_suite_dictionary["encoded_pf"]
    filtered = pf(aspin=[-0.5, 0.0])
    assert len(filtered) == 4
    assert set(filtered["aspin"].unique()) == {-0.5}

def test_encoded_pf_filter_multiple_conditions(hallmark_test_suite_dictionary):
    pf = hallmark_test_suite_dictionary["encoded_pf"]
    filtered = pf(aspin=-0.5)(i=0)
    assert len(filtered) == 1
    assert set(filtered["aspin"].unique()) == {-0.5}
    assert set(filtered["i"].unique()) == {0}

def test_encoded_glob_pattern_created_properly(hallmark_test_suite_dictionary):
    pattern = hallmark_test_suite_dictionary["encoded_glob_pattern"].replace("\\", "/")
    assert pattern.endswith("/a*_i*.h5")

def test_encoded_glob_returns_expected_files(hallmark_test_suite_dictionary):
    files = hallmark_test_suite_dictionary["encoded_globbed_files"]
    assert len(files) == 4

# new tests for the two different subdirectories of encoded vs standard files
def test_encoded_pf_paths_are_in_encoded_subdirectory(hallmark_test_suite_dictionary):
    pf = hallmark_test_suite_dictionary["encoded_pf"]
    assert all(path.startswith("encoded/") for path in pf["path"])

def test_standard_pf_not_in_encoded_subdir(hallmark_test_suite_dictionary):
    pf = hallmark_test_suite_dictionary["standard_pf"]
    assert not any(path.startswith("encoded/") for path in pf["path"])

def test_standard_and_encoded_no_overlap(hallmark_test_suite_dictionary):
    standard_paths = set(hallmark_test_suite_dictionary["standard_pf"]["path"])
    encoded_paths = set(hallmark_test_suite_dictionary["encoded_pf"]["path"])
    assert standard_paths.isdisjoint(encoded_paths)

### Test repo behavior
def test_repo_init_created_dot_hm(hallmark_test_suite_dictionary):
    repo_path = hallmark_test_suite_dictionary["repo_path"]
    assert (repo_path / ".hm").is_dir()

def test_repo_add_result_has_expected_length(hallmark_test_suite_dictionary):
    result = hallmark_test_suite_dictionary["add_result"]
    assert len(result) == 12

def test_repo_add_result_paths_match_standard_files(hallmark_test_suite_dictionary):
    result = hallmark_test_suite_dictionary["add_result"]
    assert sorted(result["path"]) == sorted(
        hallmark_test_suite_dictionary["standard_files"])

def test_repo_commit_succeeds(hallmark_test_suite_dictionary):
    assert hallmark_test_suite_dictionary["commit_result"] is True

def test_data_tsv_and_worktree_reconstruction(hallmark_test_suite_dictionary):
    repo = Repo(hallmark_test_suite_dictionary["repo_path"])
    assert len(repo.state.data) == 12
    assert repo.worktree.stem == "repo"


def _write_files(root, names):
    for name in names:
        (root / name).write_text(f"{name}\n", encoding="utf-8")


def test_repo_add_persists_only_sha1_and_path(tmp_path):
    repo = Repo.init(tmp_path / "repo")
    _write_files(repo.worktree, ["a0_i0.h5", "a0_i30.h5"])

    result = repo.add("a{a}_i{i}.h5")

    assert list(result.columns) == ["path", "a", "i"]
    persisted = repo.dothm.load_tsv("data")
    assert repo.state.config["data"] == [{"fmt": "a{a}_i{i}.h5", "encoding": None}]
    assert list(persisted.columns) == ["sha1", "a", "i"]
    assert persisted.to_dict(orient="records") == [
        {"sha1": Repo.checksum(repo.worktree / "a0_i0.h5"), "a": "0", "i": "0"},
        {"sha1": Repo.checksum(repo.worktree / "a0_i30.h5"), "a": "0", "i": "30"},
    ]


def test_repo_add_dot_replaces_manifest_with_current_tree(tmp_path):
    repo = Repo.init(tmp_path / "repo")
    _write_files(repo.worktree, ["a0_i0.h5", "a0_i30.h5"])
    repo.add("a{a}_i{i}.h5")
    (repo.worktree / "a1_i45.h5").write_text("a1_i45.h5\n", encoding="utf-8")

    result = repo.add(".")

    assert sorted(result["path"]) == ["a0_i0.h5", "a0_i30.h5", "a1_i45.h5"]
    persisted = repo.dothm.load_tsv("data")
    assert persisted.to_dict(orient="records") == [
        {"sha1": Repo.checksum(repo.worktree / "a0_i0.h5"), "a": "0", "i": "0"},
        {"sha1": Repo.checksum(repo.worktree / "a0_i30.h5"), "a": "0", "i": "30"},
        {"sha1": Repo.checksum(repo.worktree / "a1_i45.h5"), "a": "1", "i": "45"},
    ]


def test_repo_add_dot_removes_deleted_files_from_manifest(tmp_path):
    repo = Repo.init(tmp_path / "repo")
    _write_files(repo.worktree, ["a0_i0.h5", "a0_i30.h5"])
    repo.add("a{a}_i{i}.h5")

    (repo.worktree / "a0_i0.h5").unlink()
    repo.add(".")

    assert repo.state.data.to_dict(orient="records") == [
        {"sha1": Repo.checksum(repo.worktree / "a0_i30.h5"), "a": "0", "i": "30"}
    ]


def test_repo_add_pattern_keeps_deleted_manifest_rows(tmp_path):
    repo = Repo.init(tmp_path / "repo")
    _write_files(repo.worktree, ["a0_i0.h5", "a0_i30.h5"])
    repo.add("a{a}_i{i}.h5")
    original_sha = repo.state.data.loc[
        (repo.state.data["a"] == "0") & (repo.state.data["i"] == "0"),
        "sha1",
    ].iloc[0]

    (repo.worktree / "a0_i0.h5").unlink()
    repo.add("a{a}_i{i}.h5")

    assert repo.state.data.to_dict(orient="records") == [
        {"sha1": original_sha, "a": "0", "i": "0"},
        {"sha1": Repo.checksum(repo.worktree / "a0_i30.h5"), "a": "0", "i": "30"},
    ]


def test_repo_add_pattern_replaces_manifest_when_fmt_changes(tmp_path):
    repo = Repo.init(tmp_path / "repo")
    _write_files(repo.worktree, ["a0.4_i30_w3.h5", "b0.4_i30_w3.h5"])

    repo.add("a{a}_i{i}_w{w}.h5")
    repo.commit("main a data")
    repo.checkout("experiment")
    repo.add("b{a}_i{i}_w{w}.h5")

    assert repo.state.config["data"] == [{"fmt": "b{a}_i{i}_w{w}.h5", "encoding": None}]
    assert repo.state.data.to_dict(orient="records") == [
        {
            "sha1": Repo.checksum(repo.worktree / "b0.4_i30_w3.h5"),
            "a": "0.4",
            "i": "30",
            "w": "3",
        }
    ]


def test_repo_add_paths_is_not_supported_yet(tmp_path):
    repo = Repo.init(tmp_path / "repo")
    _write_files(repo.worktree, ["a0_i0.h5", "a0_i30.h5", "b0_i45.h5"])
    repo.add("a{a}_i{i}.h5")

    with pytest.raises(RuntimeError, match="explicit path add is not supported"):
        repo.add_paths(["b0_i45.h5"])


def test_repo_add_preserves_config_order_and_remote_key(tmp_path):
    repo = Repo.init(tmp_path / "repo")
    _write_files(repo.worktree, ["a0_i0.h5"])

    repo.add("a{a}_i{i}.h5")

    config_text = (repo.dothm.path / "config.yml").read_text(encoding="utf-8")
    assert "data:\n- fmt: a{a}_i{i}.h5\n  encoding: null\n" in config_text
    assert "remote: null\n" in config_text


def test_repo_set_config_updates_only_requested_fields(tmp_path):
    repo = Repo.init(tmp_path / "repo")

    repo.set_config(fmt="b{a}_i{i}.h5", remote_name="origin")

    assert repo.state.config == {
        "data": [{"fmt": "b{a}_i{i}.h5", "encoding": None}],
        "remote": {"name": "origin"},
    }


def test_repo_set_config_preserves_encoding_and_updates_remote(tmp_path):
    repo = Repo.init(tmp_path / "repo")
    repo.state.config = {
        "data": [
            {
                "fmt": "{mag:d}a{aspin}_w{win:d}.h5",
                "encoding": {
                    "aspin": r"m([0-9]+(\.[0-9]+)?|\.[0-9]+)"
                },
            }
        ],
        "remote": {"name": "origin"},
    }
    repo.dothm.dump(repo.state)

    repo.set_config(fmt="b{a}_i{i}.h5", remote_url="https://example.com/path")

    assert repo.state.config == {
        "data": [
            {
                "fmt": "b{a}_i{i}.h5",
                "encoding": {
                    "aspin": r"m([0-9]+(\.[0-9]+)?|\.[0-9]+)"
                },
            }
        ],
        "remote": {"name": "origin", "url": "https://example.com/path"},
    }


def test_repo_set_config_creates_or_updates_encoding_map(tmp_path):
    repo = Repo.init(tmp_path / "repo")

    repo.set_config(encoding_updates={"aspin": r"m([0-9]+(\.[0-9]+)?|\.[0-9]+)"})

    assert repo.state.config == {
        "data": [
            {
                "encoding": {
                    "aspin": r"m([0-9]+(\.[0-9]+)?|\.[0-9]+)"
                },
            }
        ],
        "remote": None,
    }


def test_repo_status_reports_staged_worktree_and_untracked_changes(tmp_path):
    repo = Repo.init(tmp_path / "repo")
    _write_files(repo.worktree, ["a0_i0.h5", "a0_i30.h5"])
    repo.add("a{a}_i{i}.h5")
    repo.commit("main data")

    (repo.worktree / "a0_i0.h5").write_text("changed\n", encoding="utf-8")
    (repo.worktree / "a0_i30.h5").unlink()
    (repo.worktree / "extra.h5").write_text("extra\n", encoding="utf-8")

    snapshot = repo.status()

    assert snapshot["branch"] == "main"
    assert snapshot["staged"] == {
        "state": [],
        "added": [],
        "modified": [],
        "deleted": [],
    }
    assert snapshot["worktree"]["modified"] == ["a0_i0.h5"]
    assert snapshot["worktree"]["deleted"] == ["a0_i30.h5"]
    assert snapshot["untracked"] == ["extra.h5"]


def test_repo_status_reports_staged_manifest_changes(tmp_path):
    repo = Repo.init(tmp_path / "repo")
    _write_files(repo.worktree, ["a0_i0.h5", "a0_i30.h5"])
    repo.add("a{a}_i{i}.h5")
    repo.commit("main data")

    (repo.worktree / "a1_i45.h5").write_text("a1_i45.h5\n", encoding="utf-8")
    repo.add(".")

    snapshot = repo.status()

    assert snapshot["staged"]["added"] == ["a1_i45.h5"]
    assert snapshot["staged"]["modified"] == []
    assert snapshot["staged"]["deleted"] == []


def test_checkout_rewrites_tracked_files_and_shares_objects(tmp_path):
    repo = Repo.init(tmp_path / "repo")
    _write_files(repo.worktree, ["a0_i0.h5", "a0_i30.h5"])
    repo.add("a{a}_i{i}.h5")
    repo.commit("main data")

    main_objects = sorted(p.relative_to(repo.dothm.path) 
            for p in (repo.dothm.path / "objects").rglob("*") if p.is_file())
    assert len(main_objects) == 2

    repo.checkout("experiment")
    (repo.worktree / "a0_i0.h5").unlink()
    (repo.worktree / "a0_i30.h5").unlink()
    _write_files(repo.worktree, ["a1_i45.h5", "a1_i90.h5"])
    repo.add(".")
    repo.commit("experiment data")

    experiment_files = sorted(path.name 
                for path in Path(str(repo.worktree)).glob("*.h5"))
    assert experiment_files == ["a1_i45.h5", "a1_i90.h5"]

    repo.checkout("main")
    main_files = sorted(path.name 
                for path in Path(str(repo.worktree)).glob("*.h5"))
    assert main_files == ["a0_i0.h5", "a0_i30.h5"]

    objects_after = [p for p in (repo.dothm.path / 
                            "objects").rglob("*") if p.is_file()]
    assert len(objects_after) == 4

    repo.checkout("experiment")
    roundtrip_files = sorted(path.name 
                            for path in Path(str(repo.worktree)).glob("*.h5"))
    assert roundtrip_files == ["a1_i45.h5", "a1_i90.h5"]


def test_checkout_leaves_untracked_files(tmp_path):
    repo = Repo.init(tmp_path / "repo")
    _write_files(repo.worktree, ["a0_i0.h5"])
    repo.add("a{a}_i{i}.h5")
    repo.commit("main data")

    repo.checkout("experiment")
    (repo.worktree / "a0_i0.h5").unlink()
    _write_files(repo.worktree, ["a1_i45.h5"])
    repo.add(".")
    repo.commit("experiment data")
    (repo.worktree / "notes.txt").write_text("keep me\n", encoding="utf-8")

    repo.checkout("main")

    assert (repo.worktree / "notes.txt").read_text(encoding="utf-8") == "keep me\n"
    assert sorted(path.name 
            for path in Path(str(repo.worktree)).glob("*.h5")) == ["a0_i0.h5"]


def test_checkout_rebuilds_worktree_for_branch_specific_nested_fmt(tmp_path):
    repo = Repo.init(tmp_path / "repo")
    (repo.worktree / "main").mkdir()
    _write_files(repo.worktree, ["main/a0_i0.h5"])
    repo.add("main/a{a}_i{i}.h5")
    repo.commit("main data")

    repo.checkout("experiment")
    (repo.worktree / "exp" / "run1").mkdir(parents=True)
    _write_files(repo.worktree, ["exp/run1/b0_i0.h5"])
    repo.add("exp/run{run}/b{a}_i{i}.h5")
    repo.commit("experiment data")

    repo.checkout("main")
    root = Path(str(repo.worktree))
    assert sorted(str(path.relative_to(root)) for path in root.rglob("*.h5")) == [
        "main/a0_i0.h5",
    ]
    assert not (repo.worktree / "exp").exists()

    repo.checkout("experiment")
    assert sorted(str(path.relative_to(root)) for path in root.rglob("*.h5")) == [
        "exp/run1/b0_i0.h5",
    ]
    assert not (repo.worktree / "main").exists()


def test_checkout_aborts_on_dirty_tracked_file(tmp_path):
    repo = Repo.init(tmp_path / "repo")
    _write_files(repo.worktree, ["a0_i0.h5"])
    repo.add("a{a}_i{i}.h5")
    repo.commit("main data")
    repo.checkout("experiment")
    repo.checkout("main")
    (repo.worktree / "a0_i0.h5").write_text("changed\n", encoding="utf-8")

    with pytest.raises(RuntimeError, 
                match='tracked file "a0_i0.h5" has uncommitted changes'):
        repo.checkout("experiment")


def test_checkout_aborts_on_untracked_path_conflict(tmp_path):
    repo = Repo.init(tmp_path / "repo")
    _write_files(repo.worktree, ["a0_i0.h5"])
    repo.add("a{a}_i{i}.h5")
    repo.commit("main data")

    repo.checkout("experiment")
    (repo.worktree / "a0_i0.h5").unlink()
    _write_files(repo.worktree, ["a1_i45.h5"])
    repo.add(".")
    repo.commit("experiment data")
    repo.checkout("main")

    (repo.worktree / "a1_i45.h5").write_text("untracked blocker\n", encoding="utf-8")

    with pytest.raises(RuntimeError, 
        match='target tracked path "a1_i45.h5" already exists as an untracked file'):
        repo.checkout("experiment")


def test_checkout_allows_return_to_branch_when_target_files_already_match(tmp_path):
    repo = Repo.init(tmp_path / "repo")
    _write_files(repo.worktree, ["a0_i0.h5", "b0_i0.h5"])
    repo.add("a{a}_i{i}.h5")
    repo.commit("main data")

    repo.checkout("experiment")
    repo.add("b{a}_i{i}.h5")
    repo.commit("experiment data")

    repo.checkout("main")

    assert sorted(path.name for path in Path(str(repo.worktree)).glob("*.h5")) == [
        "a0_i0.h5",
    ]


def test_repo_clone_downloads_remote_data_by_default(monkeypatch, tmp_path):
    source = Repo.init(tmp_path / "source")
    _write_files(source.worktree, ["a0_i0.h5"])
    source.add("a{a}_i{i}.h5")
    source.set_config(remote_url="https://example.com/data/")
    expected_sha1 = Repo.checksum(source.worktree / "a0_i0.h5")
    source.commit("add source data")

    captured = {}

    def fake_download_file(url, destination, sha1, chunk_size=8192):
        captured["url"] = url
        captured["sha1"] = sha1
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("downloaded\n", encoding="utf-8")
        return destination.stat().st_size

    monkeypatch.setattr("hallmark.downloader._download_file", fake_download_file)

    clone = Repo.clone(str(source.dothm.path), tmp_path / "clone")

    assert captured == {
        "url": "https://example.com/data/a0_i0.h5",
        "sha1": expected_sha1,
    }
    assert (clone.worktree / "a0_i0.h5").read_text(encoding="utf-8") == \
        "downloaded\n"
    assert clone.download_result["succeeded"] == 1
    assert clone.download_result["failed"] == 0


def test_repo_clone_can_skip_remote_data_download(monkeypatch, tmp_path):
    source = Repo.init(tmp_path / "source")
    _write_files(source.worktree, ["a0_i0.h5"])
    source.add("a{a}_i{i}.h5")
    source.set_config(remote_url="https://example.com/data/")
    source.commit("add source data")

    def fail_download(*args, **kwargs):
        raise AssertionError("download should not be attempted")

    monkeypatch.setattr("hallmark.downloader._download_file", fail_download)

    clone = Repo.clone(str(source.dothm.path), tmp_path / "clone", fetch_data=False)

    assert not (clone.worktree / "a0_i0.h5").exists()
    assert clone.download_result is None
