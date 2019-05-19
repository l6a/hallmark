# Copyright 2019 Chi-kwan Chan
# Copyright 2019 Steward Observatory
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from glob import glob

import re
import parse
import pandas as pd

def filter(self, **kwargs):
    mask = [False] * len(self)
    for k, v in kwargs.items():
        if isinstance(v, (tuple, list)):
            mask |= self[k].isin(v)
        else:
            mask |= self[k] == v
    return self[mask]

pd.DataFrame.__call__ = filter # monkey patch pandas DataFrame

def ParaFrame(fmt, *args, **kwargs):
    pattern = fmt
    for i in range(len(fmt) // 3):
        #print(i, pattern, args, kwargs)
        try:
            pattern = pattern.format(*args, **kwargs)
            break
        except KeyError as e:
            match   = r'\{' + e.args[0] + ':?.*?\}'
            pattern = re.sub(match, '{}', pattern, 1)
            args    = *args, '*'
    #print(pattern)

    files = sorted(glob(pattern))
    #print(len(files), files[0])

    p = parse.compile(fmt)
    return pd.DataFrame({'path':f, **p.parse(f).named} for f in files)
