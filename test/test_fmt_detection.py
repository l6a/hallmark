import pytest
from hallmark.fmt_detection import (
    scan_inventory, detect_fmt, _stems_to_fmts, combine_alike_fmts,
)


### scan_inventory tests ###

def test_scan_inventory_raises_if_root_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        scan_inventory(tmp_path / "nonexistent")


def test_scan_inventory_finds_nested_files(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "file1.csv").write_text("data", encoding="utf-8")
    (tmp_path / "file2.csv").write_text("data", encoding="utf-8")
    result = scan_inventory(tmp_path)
    assert set(result) == {"a/file1.csv", "file2.csv"}, \
        f"expected nested files to be found, got {result}"


def test_scan_inventory_ignores_dot_hm(tmp_path):
    (tmp_path / ".hm").mkdir()
    (tmp_path / ".hm" / "config.yml").write_text("x", encoding="utf-8")
    (tmp_path / "visible.csv").write_text("data", encoding="utf-8")
    result = scan_inventory(tmp_path)
    assert result == ["visible.csv"], f"expected only visible.csv, got {result}"


### _stems_to_fmts ###

def test_stems_to_fmts_merges_when_one_position_is_globally_fixed(tmp_path):
    stems = ["sgra_20170406_nustar", "sgra_20170411_nustar",
             "sgra_20170406_chandra", "sgra_20170407_chandra"]
    fmts = _stems_to_fmts(stems)
    assert fmts == ["sgra_{p0}_{p1}"], \
        f"expected one merged fmt via shared 'sgra' token, got {fmts}"


def test_stems_to_fmts_falls_back_to_anchor_clustering_for_unrelated_stems(tmp_path):
    stems = ["A_B_C_D", "A_E_F_G", "H_I_J_K", "L_I_M_N"]
    fmts = _stems_to_fmts(stems)
    assert sorted(fmts) == sorted(["A_{p0}_{p1}_{p2}", "{p0}_I_{p1}_{p2}"]), \
        f"expected two separate fmts for unrelated schemes, got {fmts}"


def test_stems_to_fmts_single_stem_returns_literal_fmt():
    # _stems_to_fmts returns a literal fmt for a single stem —
    # zero-parameter filtering happens at the detect_fmt level, not here
    fmts = _stems_to_fmts(["uniquefile_v1"])
    assert fmts == ["uniquefile_v1"], \
        f"expected literal fmt for single stem, got {fmts}"
    

def test_detect_fmt_rejects_single_file_with_no_siblings(tmp_path):
    (tmp_path / "uniquefile_v1.dat").write_text("data", encoding="utf-8")
    fmts = detect_fmt(tmp_path)
    assert fmts == [], "expected no fmt for single file with no siblings, got {fmts}"


def test_stems_to_fmts_dot_delimited_eht_style():
    stems = ["AA.B.1", "AA.B.2", "AP.B.3", "AX.B.7", "XX.B.17"]
    fmts = _stems_to_fmts(stems)
    assert fmts == ["{p0}.B.{p1}"], f"expected dot-preserving merged fmt, got {fmts}"


### _combine_alike_fmts tests ###

def test_combine_alike_fmts_promotes_literal_to_match_existing_param():
    # fmts sharing literal tokens should merge, parameterizing differing positions
    fmts = ["sgra_{p0}_chandra", 
            "sgra_{p0}_{p1}"]
    result = combine_alike_fmts(fmts)
    assert len(result) == 1, \
        f"expected sgra_{{p0}}_{{p1}} as merged fmt, got {result}"
    assert "sgra" in result[0], \
        f"merged fmt should preserve 'sgra' literal anchor, got {result[0]}"


def test_combine_alike_fmts_preserves_constant_literal_anchor():
    # regression test for bug where literal token was being dropped from the merged fmt
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
    # two fmts with no shared literal tokens should not merge
    fmts = ["sgra_{p0}_{p1}_{p2}", 
            "{p0}_{p1}_{p2}"]
    result = combine_alike_fmts(fmts)
    assert len(result) == 2, \
        f"expected rejection of fully-parameterized merge, got {result}"


def test_combine_alike_fmts_handles_different_token_counts():
    # fmts with different token counts that share literals should still merge
    fmts = [
        "ER6_SGRA_2017_{p0}_{p1}_netcal_StokesI",
        "ER6_SGRA_2017_{p0}_{p1}_{p2}_netcal_StokesI",]
    result = combine_alike_fmts(fmts)
    assert len(result) == 1, \
        f"expected single merged fmt for fmts with shared literals, got {result}"
    assert "ER6_SGRA_2017" in result[0], \
        f"shared prefix should be preserved in merged fmt, got {result[0]}"


### detect_fmt: known limitations ###

def test_decimal_point_is_treated_as_a_delimiter():
    # documents the underlying cause of the decimal-value limitation:
    # a literal "." inside a number is indistinguishable from a real
    # path/field delimiter, so it gets split apart during tokenization
    import re
    from hallmark.fmt_detection import _DELIM_PATTERN
    tokens = re.split(_DELIM_PATTERN, "a0.75_i30")
    assert tokens == ["a0", "75", "i30"], \
        f"expected the decimal point to fracture '0.75' into two tokens, got {tokens}"