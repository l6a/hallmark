
from glob import glob
import re
import parse
import pandas as pd
import numpy as np
import pytest
from pathlib import Path
import sys
from io import StringIO

from hallmark import ParaFrame

@pytest.fixture
def create_temp_data(tmp_path):
    data_dir = tmp_path / "data"
    for a in range(10):
        subdir = data_dir / f"a_{a}"
        subdir.mkdir(parents=True)
        for b in range(10, 20):
            (subdir / f"b_{b}.txt").touch()
    return data_dir

@pytest.fixture
def create_ParaFrame(create_temp_data):
    fmt = str(create_temp_data / "a_{a:d}/b_{b:d}.txt")
    return ParaFrame(fmt, debug = True)

# def test_type_of_ParaFrame(create_ParaFrame):
#     assert isinstance(create_ParaFrame, ParaFrame)

def test_shape_of_ParaFrame(create_ParaFrame):
    pf = create_ParaFrame
    assert pf.shape == (100,3)

def test_column_names_in_ParaFrame(create_ParaFrame):
    pf = create_ParaFrame
    assert set(pf.columns) == {"path","a","b"}

def test_all_subdirectories_a0_through_a9_get_created(create_ParaFrame):
    pf = create_ParaFrame
    assert all(pf["a"].unique() == range(10))

def test_all_txt_files_b10_through_b19_get_created(create_ParaFrame):
    pf = create_ParaFrame
    assert all(pf["b"].unique() == range(10,20))


def test_pandas_method_on_pf(create_ParaFrame):
    pf = create_ParaFrame
    # assert isinstance(pf.head(), ParaFrame)
    assert isinstance(pf.head(), pd.DataFrame)

def test_strings_in_debug(create_temp_data, capsys, tmp_path):
    fmt = str(create_temp_data / "a_{a:d}/b_{b:d}.txt")
    ParaFrame(fmt, debug = True)
    captured = capsys.readouterr()  # gets stdout and stderr
    print(captured.out)
    expected = (
        '0 ' + str(tmp_path) + '/data/a_{a:d}/b_{b:d}.txt () {}\n' +
        "1 " + str(tmp_path) + "/data/a_{a:s}/b_{b:d}.txt () {'a': '*'}\n" +
        "2 " + str(tmp_path) + "/data/a_{a:s}/b_{b:s}.txt () {'a': '*', 'b': '*'}\n" +
        'Pattern: "' + str(tmp_path) + '/data/a_*/b_*.txt"\n' +
        '100 matches, e.g., "' + str(tmp_path) + '/data/a_0/b_10.txt"\n'
    )
    assert captured.out == expected
