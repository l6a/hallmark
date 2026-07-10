# Copyright 2025 the Hallmark Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from dataclasses import dataclass, field

import pandas as pd


COLUMNS = ["sha1"]


@dataclass
class State:
    """
    In-memory Hallmark state database.

    Attributes:
        config: Repository configuration values.
        meta: Repository metadata.
        data: Tabular file index containing indexed object checksums
        (``sha1``) and associated metadata.
    """

    config:    dict         = field(default_factory=dict)
    meta:      dict         = field(default_factory=dict)
    data:      pd.DataFrame = field(
        default_factory=lambda: pd.DataFrame(columns=COLUMNS)
    )

    def update(self, pf):
        """
        Merge ``ParaFrame`` rows into the state database.

        Existing rows with matching keys are updated, while new rows are
        appended.

        Args:
            pf (ParaFrame): ``ParaFrame`` containing rows to add or update.

        Returns:
            None.
        """
        if pf.empty:
            incoming = pd.DataFrame(columns=self.data.columns 
                                if len(self.data.columns) else COLUMNS)
        else:
            incoming_columns = ["sha1"] + [
                col for col in pf.columns
                if col not in {"sha1", "path"}
            ]
            incoming = pf.loc[:, incoming_columns].copy()
            for column in incoming.columns:
                if column != "sha1":
                    incoming[column] = incoming[column].astype(str)
        # Merge the incoming rows with the existing state.
        merged = pd.concat([self.data, incoming], ignore_index=True, sort=False)

        key_columns = [column for column in merged.columns if column != "sha1"]
        if key_columns:
            # Remove duplicate entries while keeping the most recent row.
            deduped = merged.drop_duplicates(subset=key_columns, keep="last")
        else:
            deduped = merged

        self.data = deduped.loc[:, ["sha1", *key_columns]]

    def replace(self, pf):
        """
        Replace the contents of the state database.

        Existing rows are discarded and replaced with the rows from the
        provided ``ParaFrame``.

        Args:
            pf (ParaFrame): ``ParaFrame`` containing the replacement rows.

        Returns:
            None.
        """
        if pf.empty:
            self.data = pd.DataFrame(columns=self.data.columns 
                                     if len(self.data.columns) else COLUMNS)
        else:
            columns = ["sha1"] + [
                col for col in pf.columns
                if col not in {"sha1", "path"}
            ]
            self.data = pf.loc[:, columns].copy()
            for column in self.data.columns:
                if column != "sha1":
                    self.data[column] = self.data[column].astype(str)
