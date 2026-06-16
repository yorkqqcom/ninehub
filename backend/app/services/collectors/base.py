"""Abstract collector base."""

from abc import ABC, abstractmethod
from datetime import date
from typing import List

import pandas as pd


class BaseCollector(ABC):
    source_type: str = "unknown"

    @abstractmethod
    def fetch_daily(
        self,
        stock_codes: List[str],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        raise NotImplementedError
