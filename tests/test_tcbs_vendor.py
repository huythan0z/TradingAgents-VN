import unittest
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from tradingagents.dataflows import router
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.vendors import tcbs
from tradingagents.dataflows.vendors.tcbs import _clean_symbol


@pytest.mark.unit
class TCBSVendorTests(unittest.TestCase):
    def test_clean_symbol(self):
        self.assertEqual(_clean_symbol("FPT"), "FPT")
        self.assertEqual(_clean_symbol("fpt"), "FPT")
        self.assertEqual(_clean_symbol("FPT.VN"), "FPT")
        self.assertEqual(_clean_symbol("HPG.HM"), "HPG")
        self.assertEqual(_clean_symbol("VCF.HN"), "VCF")

    def test_tcbs_routing_registered(self):
        self.assertIn("tcbs", router.VENDOR_METHODS["get_stock_data"])
        self.assertIn("tcbs", router.VENDOR_METHODS["get_indicators"])
        self.assertIn("tcbs", router.VENDOR_METHODS["get_fundamentals"])
        self.assertIn("tcbs", router.VENDOR_METHODS["get_balance_sheet"])
        self.assertIn("tcbs", router.VENDOR_METHODS["get_cashflow"])
        self.assertIn("tcbs", router.VENDOR_METHODS["get_income_statement"])
        self.assertIn("tcbs", router.VENDOR_METHODS["get_news"])
        self.assertIn("tcbs", router.VENDOR_METHODS["get_insider_transactions"])

    @patch("tradingagents.dataflows.vendors.tcbs._fetch_ohlcv_tcbs")
    def test_get_stock_data_tcbs_success(self, mock_fetch):
        mock_df = pd.DataFrame([
            {"Date": pd.to_datetime("2026-09-01"), "Open": 57000.0, "High": 58000.0, "Low": 56500.0, "Close": 57500.0, "Volume": 1000000.0}
        ])
        mock_fetch.return_value = mock_df

        csv_result = tcbs.get_stock_data("FPT", "2026-09-01", "2026-09-02")
        self.assertIn("# Stock data for FPT (Vietnam)", csv_result)
        self.assertIn("57500.0", csv_result)

    @patch("tradingagents.dataflows.vendors.tcbs.requests.get")
    def test_get_fundamentals_tcbs(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "name": "FPT Corporation",
            "exchange": "HOSE",
            "industry": "Software & IT Services",
            "marketCap": 150000000000000,
            "pe": 22.5,
            "roe": 0.28,
            "description": "Leading technology corporation in Vietnam."
        }
        mock_get.return_value = mock_response

        report = tcbs.get_fundamentals("FPT")
        self.assertIn("Fundamental Analysis for FPT", report)
        self.assertIn("FPT Corporation", report)
        self.assertIn("HOSE", report)

