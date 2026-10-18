"""TCInvest / TCBS (Techcom Securities) data vendor for Vietnamese stocks.

Provides OHLCV price history, technical indicators, company fundamentals,
financial statements (Balance Sheet, Income Statement, Cash Flow),
insider transactions, and company news for the Vietnamese stock market (HOSE, HNX, UPCoM).

Features seamless multi-layer fallback (TCBS API -> DNSE/EnTrade API -> Yahoo Finance .VN)
to ensure robust data delivery even when Cloudflare WAF or rate limits occur.
"""

from __future__ import annotations

import contextlib
import logging
import os
from datetime import datetime, timezone
from typing import Annotated

import pandas as pd
import requests
from dateutil.relativedelta import relativedelta
from stockstats import wrap

from tradingagents.dataflows.errors import NoMarketDataError, VendorUnavailableError

logger = logging.getLogger(__name__)

# Base URLs
TCBS_ANALYSIS_URL = "https://apipubaws.tcbs.com.vn/tcanalysis/v1"
TCBS_INSIGHT_URL = "https://apipubaws.tcbs.com.vn/stock-insight/v1"
DNSE_CHART_URL = "https://services.entrade.com.vn/chart-api/v2/ohlcs/stock"


def _clean_symbol(symbol: str) -> str:
    """Normalize Vietnamese ticker to uppercase without exchange suffixes."""
    s = symbol.strip().upper()
    if s.endswith(".VN") or s.endswith(".HM") or s.endswith(".HN"):
        s = s.rsplit(".", 1)[0]
    return s


def _get_headers() -> dict[str, str]:
    """Build headers for TCBS/TCInvest requests, incorporating optional bearer token/cookie."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://tcinvest.tcbs.com.vn/",
        "Origin": "https://tcinvest.tcbs.com.vn",
    }
    token = os.getenv("TCBS_BEARER_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}" if not token.startswith("Bearer ") else token

    cookie = os.getenv("TCBS_COOKIE")
    if cookie:
        headers["Cookie"] = cookie

    return headers


# ---------------------------------------------------------------------------
# 1. Core Stock Data (OHLCV)
# ---------------------------------------------------------------------------


def _fetch_ohlcv_tcbs(symbol: str, start_ts: int, end_ts: int) -> pd.DataFrame | None:
    """Fetch OHLCV data from TCBS stock-insight API."""
    url = f"{TCBS_INSIGHT_URL}/stock/bars-long-term"
    params = {
        "ticker": symbol,
        "type": "stock",
        "resolution": "D",
        "from": start_ts,
        "to": end_ts,
    }
    try:
        resp = requests.get(url, params=params, headers=_get_headers(), timeout=7)
        if resp.status_code == 200:
            data = resp.json().get("data", [])
            if data:
                rows = []
                for item in data:
                    # Item has tradingDate, open, high, low, close, volume
                    dt = item.get("tradingDate", "")[:10]
                    rows.append({
                        "Date": pd.to_datetime(dt),
                        "Open": float(item.get("open", 0)),
                        "High": float(item.get("high", 0)),
                        "Low": float(item.get("low", 0)),
                        "Close": float(item.get("close", 0)),
                        "Volume": float(item.get("volume", 0)),
                    })
                df = pd.DataFrame(rows)
                df = df.sort_values("Date").reset_index(drop=True)
                return df
    except Exception as exc:
        logger.debug("TCBS OHLCV fetch failed for %s: %s", symbol, exc)
    return None


def _fetch_ohlcv_dnse(symbol: str, start_ts: int, end_ts: int) -> pd.DataFrame | None:
    """Fetch OHLCV data from DNSE/EnTrade API as seamless fallback."""
    params = {
        "from": start_ts,
        "to": end_ts,
        "symbol": symbol,
        "resolution": "1D",
    }
    try:
        resp = requests.get(
            DNSE_CHART_URL,
            params=params,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=7,
        )
        if resp.status_code == 200:
            res = resp.json()
            timestamps = res.get("t", [])
            opens = res.get("o", [])
            highs = res.get("h", [])
            lows = res.get("l", [])
            closes = res.get("c", [])
            volumes = res.get("v", [])
            if timestamps and len(timestamps) > 0:
                rows = []
                for t, o, h, l, c, v in zip(timestamps, opens, highs, lows, closes, volumes, strict=False):
                    dt = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
                    # DNSE quotes prices in thousands (e.g. 57.1 -> 57,100 VND)
                    mult = 1000.0 if c < 1000 else 1.0
                    rows.append({
                        "Date": pd.to_datetime(dt),
                        "Open": round(float(o) * mult, 2),
                        "High": round(float(h) * mult, 2),
                        "Low": round(float(l) * mult, 2),
                        "Close": round(float(c) * mult, 2),
                        "Volume": float(v),
                    })
                df = pd.DataFrame(rows)
                df = df.sort_values("Date").reset_index(drop=True)
                return df
    except Exception as exc:
        logger.debug("DNSE OHLCV fetch failed for %s: %s", symbol, exc)
    return None


def _fetch_ohlcv_yahoo_fallback(symbol: str, start_date: str, end_date: str) -> pd.DataFrame | None:
    """Fetch OHLCV from Yahoo Finance (.VN suffix) as tertiary fallback."""
    import yfinance as yf

    vn_sym = f"{symbol}.VN"
    try:
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        end_inclusive = (end_dt + relativedelta(days=1)).strftime("%Y-%m-%d")
        data = yf.Ticker(vn_sym).history(start=start_date, end=end_inclusive)
        if data is not None and not data.empty:
            df = data.reset_index()
            # Clean Date column
            if "Date" in df.columns:
                df["Date"] = pd.to_datetime(df["Date"]).dt.tz_localize(None)
                return df[["Date", "Open", "High", "Low", "Close", "Volume"]]
    except Exception as exc:
        logger.debug("Yahoo Finance .VN fetch failed for %s: %s", vn_sym, exc)
    return None


def get_stock_data(
    symbol: Annotated[str, "ticker symbol of the company"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """Retrieve OHLCV stock price data for Vietnamese equities."""
    clean_sym = _clean_symbol(symbol)
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    start_ts = int(start_dt.timestamp())
    end_ts = int((end_dt + relativedelta(days=1)).timestamp())

    # 1. Try TCBS
    df = _fetch_ohlcv_tcbs(clean_sym, start_ts, end_ts)

    # 2. Fallback to DNSE
    if df is None or df.empty:
        df = _fetch_ohlcv_dnse(clean_sym, start_ts, end_ts)

    # 3. Fallback to Yahoo Finance .VN
    if df is None or df.empty:
        df = _fetch_ohlcv_yahoo_fallback(clean_sym, start_date, end_date)

    if df is None or df.empty:
        raise NoMarketDataError(symbol, clean_sym, f"No Vietnamese market data between {start_date} and {end_date}")

    # Format Date column and round
    df["Date"] = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d")
    df = df[(df["Date"] >= start_date) & (df["Date"] <= end_date)]

    for col in ["Open", "High", "Low", "Close"]:
        if col in df.columns:
            df[col] = df[col].round(2)

    df = df.set_index("Date")
    csv_string = df.to_csv()
    header = f"# Stock data for {clean_sym} (Vietnam) from {start_date} to {end_date}\n"
    header += f"# Total records: {len(df)}\n\n"

    return header + csv_string


# ---------------------------------------------------------------------------
# 2. Technical Indicators
# ---------------------------------------------------------------------------


def get_indicators(
    symbol: Annotated[str, "ticker symbol of the company"],
    indicator: Annotated[str, "technical indicator name, e.g. rsi, macd"],
    curr_date: Annotated[str, "current trading date, YYYY-mm-dd"],
    look_back_days: Annotated[int, "number of days to look back"] = 30,
) -> str:
    """Calculate technical indicators over a trailing window using OHLCV data."""
    clean_sym = _clean_symbol(symbol)
    end_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_dt = end_dt - relativedelta(days=look_back_days + 60)  # extra buffer for SMA200 / EMA
    start_date = start_dt.strftime("%Y-%m-%d")

    csv_data = get_stock_data(clean_sym, start_date, curr_date)
    # Parse back from CSV
    lines = [line for line in csv_data.splitlines() if not line.startswith("#") and line.strip()]
    if len(lines) <= 1:
        return f"Insufficient data for {indicator} calculation on {clean_sym}"

    import io
    df = pd.read_csv(io.StringIO("\n".join(lines)))
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").reset_index(drop=True)

    # Wrap with stockstats
    stock = wrap(df)
    ind = indicator.strip().lower()

    ind_lines = []
    window_df = df[df["Date"] >= (end_dt - relativedelta(days=look_back_days))]
    for _, row in window_df.iterrows():
        dt_str = row["Date"].strftime("%Y-%m-%d")
        try:
            val = stock.get(ind)[row.name]
            ind_lines.append(f"{dt_str}: {val:.2f}" if isinstance(val, (int, float)) else f"{dt_str}: {val}")
        except Exception:
            ind_lines.append(f"{dt_str}: N/A")

    result = f"## {indicator.upper()} values for {clean_sym} up to {curr_date}:\n\n"
    result += "\n".join(reversed(ind_lines[-look_back_days:])) + "\n"
    return result


# ---------------------------------------------------------------------------
# 3. Fundamentals & Company Profile
# ---------------------------------------------------------------------------


def get_fundamentals(
    ticker: Annotated[str, "ticker symbol of the company"],
    as_of_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Retrieve fundamental data and valuation ratios for Vietnamese equities."""
    clean_sym = _clean_symbol(ticker)

    # 1. Try TCBS overview and financial ratios
    overview = {}
    ratio = {}
    try:
        res_ov = requests.get(
            f"{TCBS_ANALYSIS_URL}/ticker/{clean_sym}/overview",
            headers=_get_headers(),
            timeout=5,
        )
        if res_ov.status_code == 200:
            overview = res_ov.json()
    except Exception as exc:
        logger.debug("TCBS overview failed for %s: %s", clean_sym, exc)

    try:
        res_ra = requests.get(
            f"{TCBS_ANALYSIS_URL}/finance/{clean_sym}/financial-ratio",
            headers=_get_headers(),
            timeout=5,
        )
        if res_ra.status_code == 200:
            r_data = res_ra.json()
            if isinstance(r_data, list) and r_data:
                ratio = r_data[0]
            elif isinstance(r_data, dict):
                ratio = r_data
    except Exception as exc:
        logger.debug("TCBS ratio failed for %s: %s", clean_sym, exc)

    # If TCBS overview responded
    if overview:
        name = overview.get("shortName") or overview.get("name") or clean_sym
        exchange = overview.get("exchange") or "HOSE/HNX"
        industry = overview.get("industry") or overview.get("sector") or "N/A"
        market_cap = overview.get("marketCap", 0)
        pe = ratio.get("priceToEarning") or overview.get("pe")
        pb = ratio.get("priceToBook") or overview.get("pb")
        roe = ratio.get("roe") or overview.get("roe")
        roa = ratio.get("roa") or overview.get("roa")
        eps = ratio.get("earningPerShare")
        div_yield = ratio.get("dividendYield")

        lines = [
            f"# Fundamental Analysis for {clean_sym} ({exchange})",
            f"- Company Name: {name}",
            f"- Exchange: {exchange}",
            f"- Industry / Sector: {industry}",
            f"- Market Cap: {market_cap:,.0f} VND" if market_cap else "- Market Cap: N/A",
            f"- P/E Ratio: {pe:.2f}" if pe else "- P/E Ratio: N/A",
            f"- P/B Ratio: {pb:.2f}" if pb else "- P/B Ratio: N/A",
            f"- ROE: {roe:.2%}" if isinstance(roe, (int, float)) and roe < 1 else f"- ROE: {roe}%",
            f"- ROA: {roa:.2%}" if isinstance(roa, (int, float)) and roa < 1 else f"- ROA: {roa}%",
            f"- EPS: {eps:,.0f} VND" if eps else "- EPS: N/A",
            f"- Dividend Yield: {div_yield:.2%}" if div_yield else "- Dividend Yield: N/A",
            "",
            "## Business Summary:",
            overview.get("summary") or overview.get("description") or f"Doanh nghiệp {name} niêm yết trên sàn {exchange}.",
        ]
        return "\n".join(lines)

    # Fallback to Yahoo Finance .VN info
    try:
        import yfinance as yf
        info = yf.Ticker(f"{clean_sym}.VN").info
        if info:
            name = info.get("longName", clean_sym)
            lines = [
                f"# Fundamental Analysis for {clean_sym} (HOSE/HNX via Yahoo)",
                f"- Company Name: {name}",
                f"- Sector: {info.get('sector', 'N/A')}",
                f"- Industry: {info.get('industry', 'N/A')}",
                f"- Market Cap: {info.get('marketCap', 'N/A')} VND",
                f"- P/E (TTM): {info.get('trailingPE', 'N/A')}",
                f"- P/B: {info.get('priceToBook', 'N/A')}",
                f"- Dividend Yield: {info.get('dividendYield', 'N/A')}",
                "",
                "## Summary:",
                info.get("longBusinessSummary", "No summary available."),
            ]
            return "\n".join(lines)
    except Exception as exc:
        logger.debug("Yahoo fundamentals fallback failed for %s: %s", clean_sym, exc)

    return f"Fundamental data unavailable for {clean_sym}"


# ---------------------------------------------------------------------------
# 4. Financial Statements (Balance Sheet, Cash Flow, Income Statement)
# ---------------------------------------------------------------------------


def get_balance_sheet(
    ticker: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "reporting frequency"] = "quarterly",
    curr_date: Annotated[str, "current date"] = None,
) -> str:
    """Retrieve balance sheet statement."""
    clean_sym = _clean_symbol(ticker)
    yearly = 1 if freq.lower().startswith("ann") else 0
    try:
        res = requests.get(
            f"{TCBS_ANALYSIS_URL}/finance/{clean_sym}/balancesheet?yearly={yearly}",
            headers=_get_headers(),
            timeout=5,
        )
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list) and data:
                recent = data[:4]  # latest 4 periods
                lines = [f"# Balance Sheet for {clean_sym} ({freq})", ""]
                header_cols = ["Metric"] + [f"{item.get('year', '')} Q{item.get('quarter', '')}" for item in recent]
                lines.append("| " + " | ".join(header_cols) + " |")
                lines.append("| " + " | ".join(["---"] * len(header_cols)) + " |")

                metrics = [
                    ("Total Assets", "asset"),
                    ("Current Assets", "shortAsset"),
                    ("Cash & Equivalents", "cash"),
                    ("Total Liabilities", "debt"),
                    ("Short-term Debt", "shortDebt"),
                    ("Long-term Debt", "longDebt"),
                    ("Owner's Equity", "equity"),
                ]
                for label, key in metrics:
                    row = [label] + [f"{item.get(key, 0):,.0f}" for item in recent]
                    lines.append("| " + " | ".join(row) + " |")
                return "\n".join(lines)
    except Exception as exc:
        logger.debug("TCBS balance sheet failed for %s: %s", clean_sym, exc)

    return f"Balance sheet data unavailable for {clean_sym} ({freq})"


def get_income_statement(
    ticker: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "reporting frequency"] = "quarterly",
    curr_date: Annotated[str, "current date"] = None,
) -> str:
    """Retrieve income statement."""
    clean_sym = _clean_symbol(ticker)
    yearly = 1 if freq.lower().startswith("ann") else 0
    try:
        res = requests.get(
            f"{TCBS_ANALYSIS_URL}/finance/{clean_sym}/incomestatement?yearly={yearly}",
            headers=_get_headers(),
            timeout=5,
        )
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list) and data:
                recent = data[:4]
                lines = [f"# Income Statement for {clean_sym} ({freq})", ""]
                header_cols = ["Metric"] + [f"{item.get('year', '')} Q{item.get('quarter', '')}" for item in recent]
                lines.append("| " + " | ".join(header_cols) + " |")
                lines.append("| " + " | ".join(["---"] * len(header_cols)) + " |")

                metrics = [
                    ("Revenue", "revenue"),
                    ("Cost of Goods Sold", "costOfGoodSold"),
                    ("Gross Profit", "grossProfit"),
                    ("Operating Profit", "operationProfit"),
                    ("Net Profit After Tax", "postTaxProfit"),
                ]
                for label, key in metrics:
                    row = [label] + [f"{item.get(key, 0):,.0f}" for item in recent]
                    lines.append("| " + " | ".join(row) + " |")
                return "\n".join(lines)
    except Exception as exc:
        logger.debug("TCBS income statement failed for %s: %s", clean_sym, exc)

    return f"Income statement data unavailable for {clean_sym} ({freq})"


def get_cashflow(
    ticker: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "reporting frequency"] = "quarterly",
    curr_date: Annotated[str, "current date"] = None,
) -> str:
    """Retrieve cash flow statement."""
    clean_sym = _clean_symbol(ticker)
    yearly = 1 if freq.lower().startswith("ann") else 0
    try:
        res = requests.get(
            f"{TCBS_ANALYSIS_URL}/finance/{clean_sym}/cashflow?yearly={yearly}",
            headers=_get_headers(),
            timeout=5,
        )
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list) and data:
                recent = data[:4]
                lines = [f"# Cash Flow Statement for {clean_sym} ({freq})", ""]
                header_cols = ["Metric"] + [f"{item.get('year', '')} Q{item.get('quarter', '')}" for item in recent]
                lines.append("| " + " | ".join(header_cols) + " |")
                lines.append("| " + " | ".join(["---"] * len(header_cols)) + " |")

                metrics = [
                    ("Operating Cash Flow", "fromSale"),
                    ("Investing Cash Flow", "fromInvest"),
                    ("Financing Cash Flow", "fromFinancial"),
                    ("Net Cash Change", "freeCashFlow"),
                ]
                for label, key in metrics:
                    row = [label] + [f"{item.get(key, 0):,.0f}" for item in recent]
                    lines.append("| " + " | ".join(row) + " |")
                return "\n".join(lines)
    except Exception as exc:
        logger.debug("TCBS cashflow failed for %s: %s", clean_sym, exc)

    return f"Cash flow statement unavailable for {clean_sym} ({freq})"


# ---------------------------------------------------------------------------
# 5. Insider Transactions & News
# ---------------------------------------------------------------------------


def get_insider_transactions(
    ticker: Annotated[str, "ticker symbol"],
    trade_date: Annotated[str, "analysis date"] = None,
) -> str:
    """Retrieve recent insider dealing transactions."""
    clean_sym = _clean_symbol(ticker)
    try:
        res = requests.get(
            f"{TCBS_ANALYSIS_URL}/company/{clean_sym}/insider-dealing",
            headers=_get_headers(),
            timeout=5,
        )
        if res.status_code == 200:
            data = res.json().get("listInsiderDealing", [])
            if data:
                lines = [f"# Insider Transactions for {clean_sym}", ""]
                lines.append("| Date | Insider Name | Position | Action | Shares | Post Shares |")
                lines.append("| --- | --- | --- | --- | --- | --- |")
                for item in data[:10]:
                    dt = item.get("dealDate") or item.get("tradingDate") or "N/A"
                    name = item.get("dealerName") or "N/A"
                    pos = item.get("dealerPosition") or "N/A"
                    action = item.get("dealAction") or item.get("actionType") or "Trade"
                    shares = item.get("dealQuantity", 0)
                    post = item.get("postQuantity", 0)
                    lines.append(f"| {dt} | {name} | {pos} | {action} | {shares:,.0f} | {post:,.0f} |")
                return "\n".join(lines)
    except Exception as exc:
        logger.debug("TCBS insider dealing failed for %s: %s", clean_sym, exc)

    return f"No insider transaction records found for {clean_sym}"


def get_news(
    ticker: Annotated[str, "ticker symbol"],
    start_date: Annotated[str, "start date"],
    end_date: Annotated[str, "end date"],
) -> str:
    """Retrieve company news headlines."""
    clean_sym = _clean_symbol(ticker)
    try:
        res = requests.get(
            f"{TCBS_ANALYSIS_URL}/company/{clean_sym}/news",
            headers=_get_headers(),
            timeout=5,
        )
        if res.status_code == 200:
            articles = res.json().get("listNews", [])
            if articles:
                lines = [f"# Recent News for {clean_sym}", ""]
                for item in articles[:10]:
                    title = item.get("title", "No Title")
                    date = item.get("publishDate", "")[:10]
                    lines.append(f"- [{date}] **{title}**")
                return "\n".join(lines)
    except Exception as exc:
        logger.debug("TCBS news failed for %s: %s", clean_sym, exc)

    # Fallback to generic news
    return f"No company news available for {clean_sym} between {start_date} and {end_date}"

