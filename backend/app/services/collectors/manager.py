"""Collector plugin registry."""

from typing import Dict, Type

from app.services.collectors.base import BaseCollector


class CollectorManager:
    _collectors: Dict[str, Type[BaseCollector]] = {}

    @classmethod
    def register(cls, name: str, collector_cls: Type[BaseCollector]) -> None:
        cls._collectors[name] = collector_cls

    @classmethod
    def get(cls, name: str) -> BaseCollector:
        collector_cls = cls._collectors.get(name)
        if collector_cls is None:
            raise KeyError(f"Collector not registered: {name}")
        return collector_cls()
