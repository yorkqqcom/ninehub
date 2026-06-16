"""Collector plugin registry."""

from app.services.collectors.akshare import AkShareCollector
from app.services.collectors.manager import CollectorManager
from app.services.collectors.tushare import TushareCollector

CollectorManager.register("akshare", AkShareCollector)
CollectorManager.register("tushare", TushareCollector)

__all__ = ["CollectorManager", "AkShareCollector", "TushareCollector"]
