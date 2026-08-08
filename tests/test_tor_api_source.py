"""Source-level smoke tests for the TOR integration API."""

from __future__ import annotations

import unittest
from pathlib import Path


class TorApiSourceTests(unittest.TestCase):
    def test_existing_turnover_share_base_api_is_still_present(self) -> None:
        source = Path("/workspace/app.py").read_text(encoding="utf-8")

        self.assertIn("def get_turnover_share_base(ticker_obj):", source)
        self.assertIn("return get_turnover_share_lookup(ticker_obj).share_base", source)

    def test_turnover_formula_is_shared_in_helper(self) -> None:
        source = Path("/workspace/turnover_utils.py").read_text(encoding="utf-8")

        self.assertIn(
            'result_df["Turnover_Rate"] = (',
            source,
        )
        self.assertIn(
            'result_df[volume_column].astype(float) / float(share_base) * 100',
            source,
        )


if __name__ == "__main__":
    unittest.main()
