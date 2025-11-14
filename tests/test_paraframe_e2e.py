import os
import shutil
import pandas as pd
import pytest
import numpy as np
from hallmark import ParaFrame
from test_conftest import create_temp_data

def test_paraframe_class_functionality(create_temp_data):
    # a user wants to create a paraframe
    fmt = str(create_temp_data / "a_{a:d}/b_{b:d}.txt")
    pf = ParaFrame(fmt)

    # users wants to filter files to see those with a = 0
    scalar_filter = pf(a=0)
    # checking that the correct number of files and column values are filtered
    assert len(scalar_filter) == 10
    assert scalar_filter["a"].unique() == 0

    # users wants to filter files to see those with a = 0 or 1
    list_filter = pf(a=[0,1])
    # checking that the correct number of files and column values are filtered
    assert len(list_filter) == 20
    assert all(list_filter["a"].unique() == [0,1])

    # users want to filter files to see those with a = 0 or b = 10
    tuple_filter = pf(a=0, b=10)
    # splitting columns with a=0 value and b=10 value to check that the correct number of 
    # files and column values are filtered
    a_filter = tuple_filter(a=0)
    b_filter = tuple_filter(b = 10)
    assert len(tuple_filter) == 19
    assert len(a_filter) == 10
    assert len(set(a_filter["a"])) == 1
    assert len(b_filter) == 10
    assert len(set(b_filter["b"])) == 1

    # users want to filter files to see those with a=0 and b=10
    and_filter = pf(a=0)(b=10)
    assert len(and_filter) == 1
    assert len(set(and_filter["a"])) == 1
    assert len(set(and_filter["b"])) == 1
    assert all(and_filter["a"] == [0])
    assert all(and_filter["b"] == [10])

    # users want to filter files to see those with a >= 1 and a <=4
    mask_filter = pf[(1 <= pf.a) & (pf.a <= 4)]
    assert len(mask_filter) == 40
    assert all(mask_filter["a"].unique() == [1,2,3,4])
