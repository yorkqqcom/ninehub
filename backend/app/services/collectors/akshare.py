"""AkShare collector (C-05)."""

from datetime import date
from typing import List

import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential

from app.services.collectors.base import BaseCollector


class AkShareCollector(BaseCollector):
    source_type = "akshare"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def fetch_daily(
        self,
        stock_codes: List[str],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        import akshare as ak

        frames: list[pd.DataFrame] = []
        start_s = start_date.strftime("%Y%m%d")
        end_s = end_date.strftime("%Y%m%d")
        for code in stock_codes:
            symbol = code.split(".")[0]
            df = ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_s,
                end_date=end_s,
                adjust="",
            )
            if df is None or df.empty:
                continue
            df = df.rename(
                columns={
                    "日期": "trade_date",
                    "开盘": "open",
                    "最高": "high",
                    "最低": "low",
                    "收盘": "close",
                    "成交量": "vol",
                }
            )
            df["stock_code"] = code
            df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
            frames.append(df[["stock_code", "trade_date", "open", "high", "low", "close", "vol"]])
        if not frames:
            return pd.DataFrame(
                columns=["stock_code", "trade_date", "open", "high", "low", "close", "vol"]
            )
        return pd.concat(frames, ignore_index=True)
