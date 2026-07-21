import pytest
from pathlib import Path
from hallmark.fmt_detection import (
    scan_inventory,
    detect_fmt,
    _stems_to_fmts,
    combine_alike_fmts,
    _is_drive_path,)

### scan_inventory tests ###

def test_scan_inventory_raises_if_root_not_found(tmp_path):
    """
    Test that scan_inventory raises a FileNotFoundError when the root directory 
    does not exist.
    Args:
        tmp_path: A temporary directory provided by pytest.
    """
    with pytest.raises(FileNotFoundError):
        scan_inventory(tmp_path / "nonexistent")


def test_scan_inventory_finds_nested_files(tmp_path):
    """
    Test that scan_inventory correctly finds nested files in the directory structure.
    Args:
        tmp_path: A temporary directory provided by pytest.
    """
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "file1.csv").write_text("data", encoding="utf-8")
    (tmp_path / "file2.csv").write_text("data", encoding="utf-8")
    result = scan_inventory(tmp_path)
    
    assert set(result) == {"a/file1.csv", "file2.csv"}, \
        f"expected nested files to be found, got {result}"


def test_scan_inventory_ignores_dot_hm(tmp_path):
    """
    Test that scan_inventory ignores the .hm directory and its contents.
    Args:
        tmp_path: A temporary directory provided by pytest.
    """
    (tmp_path / ".hm").mkdir()
    (tmp_path / ".hm" / "config.yml").write_text("x", encoding="utf-8")
    (tmp_path / "visible.csv").write_text("data", encoding="utf-8")
    result = scan_inventory(tmp_path)

    assert result == ["visible.csv"], f"expected only visible.csv, got {result}"

def test_scan_inventory_returns_empty_list_for_empty_root(tmp_path):
    """
    Test that scan_inventory returns an empty list for an empty directory.
    Args:
        tmp_path: A temporary directory provided by pytest.
    """
    result = scan_inventory(tmp_path)

    assert result == [], f"expected empty inventory for empty root, got {result}"


### _is_drive_path tests ###

def test_is_drive_path_handles_multipart_archive_suffixes():
    """
    _is_drive_path should detect multi-part archive suffixes.
    """
    assert _is_drive_path(Path("x.tar.gz")), \
        f"expected .tar.gz to be detected as a drive path, got {Path('x.tar.gz')}"
    assert _is_drive_path(Path("x.tar.bz2")), \
        f"expected .tar.bz2 to be detected as a drive path, got {Path('x.tar.bz2')}"
    assert _is_drive_path(Path("x.tar.xz")), \
        f"expected .tar.xz to be detected as a drive path, got {Path('x.tar.xz')}"
    assert not _is_drive_path(Path("x.fits")), \
        f"expected .fits not to be detected as a drive path, got {Path('x.fits')}"

### _stems_to_fmts ###

def test_stems_to_fmts_merges_when_one_position_is_globally_fixed():
    """
    Test that _stems_to_fmts merges stems into a single format when one position 
    is globally fixed.
    """
    stems = ["sgra_20170406_nustar", "sgra_20170411_nustar",
             "sgra_20170406_chandra", "sgra_20170407_chandra"]
    fmts = _stems_to_fmts(stems)

    assert fmts == ["sgra_{p0}_{p1}"], \
        f"expected one merged fmt via shared 'sgra' token, got {fmts}"


def test_stems_to_fmts_falls_back_to_anchor_clustering_for_unrelated_stems():
    """
    Test that _stems_to_fmts falls back to anchor clustering for unrelated stems.
    """
    stems = ["A_B_C_D", "A_E_F_G", "H_I_J_K", "L_I_M_N"]
    fmts = _stems_to_fmts(stems)

    assert sorted(fmts) == sorted(["A_{p0}_{p1}_{p2}", "{p0}_I_{p1}_{p2}"]), \
        f"expected two separate fmts for unrelated schemes, got {fmts}"


def test_stems_to_fmts_single_stem_returns_literal_fmt():
    """
    Test that _stems_to_fmts returns a literal format for a single stem.
    """
    fmts = _stems_to_fmts(["uniquefile_v1"])

    assert fmts == ["uniquefile_v1"], \
        f"expected literal fmt for single stem, got {fmts}"


def test_stems_to_fmts_dot_delimited_eht_style():
    """
    Test that _stems_to_fmts correctly handles dot-delimited EHT-style stems.
    """
    stems = ["AA.B.1", "AA.B.2", "AP.B.3", "AX.B.7", "XX.B.17"]
    fmts = _stems_to_fmts(stems)

    assert fmts == ["{p0}.B.{p1}"], f"expected dot-preserving merged fmt, got {fmts}"


def test_stems_to_fmts_empty_input_returns_empty_list():
    """
    Test that _stems_to_fmts returns [] for empty input.
    """
    fmts = _stems_to_fmts([])

    assert fmts == [], f"expected empty output for empty input, got {fmts}"


### _combine_alike_fmts tests ###


def test_combine_alike_fmts_respects_exclude_tokens():
    """
    Excluded literals should remain literals during merge.
    """
    fmts = [
        "ER6_SGRA_2017_{p0}_{p1}_netcal_{p2}_StokesI",
        "ER6_SGRA_2017_{p0}_{p1}_netcal_StokesI",]
    result = combine_alike_fmts(fmts, exclude_tokens={"StokesI"})

    assert len(result) == 1, f"expected one merged fmt, got {result}"
    assert "StokesI" in result[0],\
          f"expected StokesI to remain literal, got {result[0]}"


def test_combine_alike_fmts_promotes_literal_to_match_existing_param():
    """
    Test that combine_alike_fmts promotes a literal token to a parameter when merging
    """
    fmts = ["sgra_{p0}_chandra", 
            "sgra_{p0}_{p1}"]
    result = combine_alike_fmts(fmts)

    assert len(result) == 1, \
        f"expected sgra_{{p0}}_{{p1}} as merged fmt, got {result}"
    assert "sgra" in result[0], \
        f"merged fmt should preserve 'sgra' literal anchor, got {result[0]}"


def test_combine_alike_fmts_preserves_constant_literal_anchor():
    """
    Regression test for a bug where a constant lit anchor was being lost during merging.
    """
    fmts = [
        "ER6_SGRA_2017_{p0}_{p1}_netcal_{p2}_StokesI",
        "ER6_SGRA_2017_{p0}_{p1}_netcal_StokesI",]
    result = combine_alike_fmts(fmts)

    assert len(result) == 1, f"expected one merged fmt, got {result}"
    assert "StokesI" in result[0], \
        f"StokesI should remain literal in merged fmt, got {result[0]}"
    assert "ER6_SGRA_2017" in result[0], \
        f"prefix literals should be preserved, got {result[0]}"


def test_combine_alike_fmts_rejects_zero_literal_anchor_merge():
    """
    Test that combine_alike_fmts rejects merging when there is no literal anchor.
    """
    fmts = ["sgra_{p0}_{p1}_{p2}", 
            "{p0}_{p1}_{p2}"]
    result = combine_alike_fmts(fmts)

    assert len(result) == 2, \
        f"expected rejection of fully-parameterized merge, got {result}"


def test_combine_alike_fmts_handles_different_token_counts():
    """
    Test that combine_alike_fmts correctly merges formats with different token counts.
    """
    fmts = [
        "ER6_SGRA_2017_{p0}_{p1}_netcal_StokesI",
        "ER6_SGRA_2017_{p0}_{p1}_{p2}_netcal_StokesI",]
    result = combine_alike_fmts(fmts)

    assert len(result) == 1, \
        f"expected single merged fmt for fmts with shared literals, got {result}"
    assert "ER6_SGRA_2017" in result[0], \
        f"shared prefix should be preserved in merged fmt, got {result[0]}"
    

def test_combine_alike_fmts_empty_input_returns_empty_list():
    """
    Test that combine_alike_fmts returns [] for empty input.
    """
    result = combine_alike_fmts([])

    assert result == [], f"expected empty output for empty input, got {result}"


def test_combine_alike_fmts_keeps_single_format_as_is():
    """
    Test that combine_alike_fmts leaves a single format unchanged.
    """
    result = combine_alike_fmts(["sgra_{p0}_chandra"])

    assert result == ["sgra_{p0}_chandra"], \
        f"expected single fmt to remain unchanged, got {result}"


### detect_fmt tests ###

def test_detect_fmt_excludes_drive_files_by_default():
    """
    Drive/archive files should be ignored unless include_drives=True.
    """
    fmts = detect_fmt(["bundle_a.tar", "bundle_b.tar"])

    assert fmts == [], f"expected no fmts when only drives are present, got {fmts}"


def test_detect_fmt_includes_drive_files_when_flag_enabled():
    """
    Drive/archive files should be considered when include_drives=True.
    """
    fmts = detect_fmt(["bundle_a.tar", "bundle_b.tar"], include_drives=True)

    assert fmts, "expected at least one fmt when include_drives=True, got none"
    assert any(".tar" in fmt for fmt in fmts), f"expected a .tar-based fmt, got {fmts}"


def test_detect_fmt_meta_filename_filter_is_case_insensitive():
    """
    Meta filenames should be ignored regardless of case.
    """
    files = ["ReadMe.md", "readme.txt", "DATA_01.fits", "DATA_02.fits"]
    fmts = detect_fmt(files)

    assert len(fmts) == 1, f"expected one fmt from non-meta files, got {fmts}"
    assert "DATA" in fmts[0] and ".fits" in fmts[0], \
        f"expected DATA fits fmt, got {fmts}"
    

def test_detect_fmt_rejects_single_file_with_no_siblings():
    """
    Test that detect_fmt returns an empty list when given a single file with no siblings
    """
    fmts = detect_fmt(["uniquefile_v1.dat"])

    assert fmts == [], f"expected no fmt for single file with no siblings, got {fmts}"


def test_detect_fmt_finds_single_shared_format():
    """
    Test that detect_fmt infers one format from multiple matching filenames.
    """
    files = [
        "sgra_20170406_nustar.fits",
        "sgra_20170411_nustar.fits",
        "sgra_20170406_chandra.fits",
        "sgra_20170407_chandra.fits",]
    fmts = detect_fmt(files)

    assert fmts == ["sgra_{p0}_{p1}.fits"], f"expected one shared fmt, got {fmts}"


def test_detect_fmt_handles_dot_delimited_names():
    """
    Test that detect_fmt preserves dot-delimited structure in inferred formats.
    """
    files = ["AA.B.1", "AA.B.2", "AP.B.3", "AX.B.7"]
    fmts = detect_fmt(files)

    assert fmts == ["{p0}.B.{pass}"], f"expected dot-delimited fmt, got {fmts}"


def test_decimal_point_is_treated_as_a_delimiter():
    """
    Test that the decimal point is treated as a delimiter in tokenization, 
    which can lead to unexpected tokenization of decimal numbers. Known limitation.
    """
    import re
    from hallmark.fmt_detection import _DELIM_PATTERN
    tokens = re.split(_DELIM_PATTERN, "a0.75_i30")

    assert tokens == ["a0", "75", "i30"], \
        f"expected the decimal point to fracture '0.75' into two tokens, got {tokens}"