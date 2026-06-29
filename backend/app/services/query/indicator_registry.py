"""Indicator registry — catalog columns + YAML overrides."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.catalog.registry import DOMAINS, CATALOG_REGISTRY, DataTypeEntry
from app.schemas.query_browser import IndicatorRef, IndicatorTreeNode
from app.services.tia.constants import is_legacy_data_type
from app.services.tia.schema_inference import _field_label

_OHLC_KEYS = frozenset({"open", "high", "low", "close", "pre_close"})
_DAILY_DT_SUFFIX = ("daily", "weekly", "monthly", "basic")
_SPINE_DATA_TYPE = "tushare_stock_basic"
_CONFIG_PATH = Path(__file__).resolve().parents[2] / "catalog" / "browser_indicators.yaml"
_FIELD_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    "stock_code": ("ts_code",),
    "ts_code": ("stock_code",),
    "pct_chg": ("pct_change",),
    "pct_change": ("pct_chg",),
    "change_amount": ("change",),
    "change": ("change_amount",),
}
_HTML_TAG_RE = re.compile(r"<[^>]+>")


@lru_cache(maxsize=1)
def _load_yaml_config() -> dict[str, Any]:
    if not _CONFIG_PATH.is_file():
        return {"overrides": {}, "system_templates": []}
    with _CONFIG_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=1)
def _load_api_field_labels() -> dict[tuple[str, str], str]:
    """api_name + field → Chinese label from Tushare wctapi doc cache."""
    from app.services.tia.scan.api_spec_store import build_api_spec_by_name_index

    labels: dict[tuple[str, str], str] = {}
    for api, spec in build_api_spec_by_name_index().items():
        for param in spec.get("output_params") or []:
            if not isinstance(param, dict):
                continue
            name = str(param.get("name") or "").strip()
            desc = _clean_param_description(str(param.get("description") or ""))
            if name and desc:
                labels[(api, name)] = desc
    return labels


def _clean_param_description(text: str) -> str:
    text = _HTML_TAG_RE.sub("", text).strip()
    if "【" in text:
        text = text.split("【", 1)[0].strip()
    if "（" in text:
        text = text.split("（", 1)[0].strip()
    if "(" in text:
        text = text.split("(", 1)[0].strip()
    return text


def _api_from_data_type(data_type: str) -> str:
    if data_type.startswith("tushare_"):
        return data_type[len("tushare_") :]
    return data_type


def _doc_field_label(api_name: str, column_key: str) -> str | None:
    index = _load_api_field_labels()
    api = api_name.lower()
    for key in (column_key, *_FIELD_KEY_ALIASES.get(column_key, ())):
        label = index.get((api, key))
        if label:
            return label
    return None


def _resolve_column_label(
    entry: DataTypeEntry,
    column_key: str,
    *,
    yaml_label: str | None,
    catalog_label: str | None,
) -> str:
    """Label priority: YAML override → Tushare doc → catalog → schema inference → key."""
    if yaml_label:
        return yaml_label
    doc_label = _doc_field_label(_api_from_data_type(entry.data_type), column_key)
    if doc_label:
        return doc_label
    if catalog_label and catalog_label != column_key:
        return catalog_label
    inferred = _field_label(column_key)
    if inferred != column_key:
        return inferred
    return column_key


def _domain_label(domain: str) -> str:
    for key, label in DOMAINS:
        if key == domain:
            return label
    return domain


def _infer_freq(entry: DataTypeEntry, column_key: str) -> str:
    if entry.data_type == _SPINE_DATA_TYPE:
        return "static"
    col_keys = {c.key for c in entry.columns}
    if "trade_date" in col_keys or any(entry.data_type.endswith(s) for s in _DAILY_DT_SUFFIX):
        if column_key in _OHLC_KEYS or "trade_date" in col_keys:
            return "daily"
    if "end_date" in col_keys:
        return "period"
    if "ann_date" in col_keys:
        return "period"
    return "static"


def _date_column_for_freq(freq: str, entry: DataTypeEntry) -> str | None:
    col_keys = {c.key for c in entry.columns}
    if freq == "daily" and "trade_date" in col_keys:
        return "trade_date"
    if freq == "period":
        if "end_date" in col_keys:
            return "end_date"
        if "ann_date" in col_keys:
            return "ann_date"
    return None


def _table_available(entry: DataTypeEntry) -> bool:
    return bool(entry.is_activated and entry.table_name)


class IndicatorRegistry:
    def list_indicators(self) -> list[IndicatorRef]:
      overrides = _load_yaml_config().get("overrides") or {}
      refs: list[IndicatorRef] = []
      for entry in CATALOG_REGISTRY.values():
          if not entry.is_activated:
              continue
          if is_legacy_data_type(entry.data_type):
              continue
          for col in entry.columns:
              if col.key in ("id", "created_at"):
                  continue
              ind_id = f"{entry.data_type}.{col.key}"
              ov = overrides.get(ind_id) or {}
              freq = _infer_freq(entry, col.key)
              refs.append(
                  IndicatorRef(
                      id=ind_id,
                      data_type=entry.data_type,
                      column_key=col.key,
                      label=_resolve_column_label(
                          entry,
                          col.key,
                          yaml_label=ov.get("label"),
                          catalog_label=col.label,
                      ),
                      domain=entry.domain,
                      data_type_label=entry.label,
                      type=col.type,
                      unit=ov.get("unit"),
                      freq=freq,
                      date_column=_date_column_for_freq(freq, entry),
                      supports_adjust=freq == "daily" and col.key in _OHLC_KEYS,
                      tags=list(ov.get("tags") or []),
                      available=_table_available(entry),
                      group=ov.get("group"),
                      pinyin=ov.get("pinyin"),
                  )
              )
      refs.sort(key=lambda r: (r.domain, r.group or "", r.data_type, r.label))
      return refs

    def get_indicator(self, indicator_id: str) -> IndicatorRef | None:
      for ref in self.list_indicators():
          if ref.id == indicator_id:
              return ref
      return None

    def enrich_with_coverage(
        self,
        table_counts: dict[str, int],
        column_counts: dict[tuple[str, str], int] | None = None,
    ) -> list[IndicatorRef]:
        column_counts = column_counts or {}
        refs: list[IndicatorRef] = []
        for ref in self.list_indicators():
            entry = CATALOG_REGISTRY.get(ref.data_type)
            table_name = entry.table_name if entry else None
            table_ok = bool(table_name and table_counts.get(table_name, 0) > 0)
            if ref.freq == "static" and table_name:
                col_cnt = column_counts.get((table_name, ref.column_key), 0)
                ready = table_ok and col_cnt > 0
            else:
                ready = table_ok
            refs.append(ref.model_copy(update={"data_ready": ready}))
        return refs

    def build_tree(self, refs: list[IndicatorRef] | None = None) -> list[IndicatorTreeNode]:
      if refs is None:
          refs = self.list_indicators()
      domain_map: dict[str, IndicatorTreeNode] = {}
      for d_key, d_label in DOMAINS:
          domain_map[d_key] = IndicatorTreeNode(
              id=f"domain:{d_key}",
              label=d_label,
              node_type="domain",
              children=[],
          )

      # domain -> group? -> datatype -> indicators
      grouped: dict[str, dict[str, dict[str, list[IndicatorRef]]]] = {}
      for ref in refs:
          grouped.setdefault(ref.domain, {}).setdefault(ref.group or "", {}).setdefault(
              ref.data_type, []
          ).append(ref)

      for domain, groups in grouped.items():
          root = domain_map.get(domain)
          if root is None:
              continue
          has_any_group = any(g for g in groups if g)
          for group_name, dtypes in sorted(groups.items()):
              parent = root
              if has_any_group and group_name:
                  group_node = IndicatorTreeNode(
                      id=f"group:{domain}:{group_name}",
                      label=group_name,
                      node_type="group",
                      children=[],
                  )
                  root.children.append(group_node)
                  parent = group_node
              elif has_any_group and not group_name:
                  pass
              for dt, indicators in sorted(dtypes.items()):
                  dt_label = indicators[0].data_type_label if indicators else dt
                  dt_node = IndicatorTreeNode(
                      id=f"datatype:{dt}",
                      label=dt_label,
                      node_type="datatype",
                      children=[],
                  )
                  for ref in indicators:
                      dt_node.children.append(
                          IndicatorTreeNode(
                              id=ref.id,
                              label=ref.label,
                              node_type="indicator",
                              indicator=ref,
                          )
                      )
                  parent.children.append(dt_node)
      return [domain_map[k] for k, _ in DOMAINS if k in domain_map and domain_map[k].children]

    def search_indicators(
      self,
      q: str | None = None,
      domain: str | None = None,
      tags: str | None = None,
      available_only: bool = False,
      data_ready_only: bool = False,
  ) -> list[IndicatorRef]:
      items = self.list_indicators()
      if available_only:
          items = [i for i in items if i.available]
      if data_ready_only:
          items = [i for i in items if i.data_ready]
      if domain:
          items = [i for i in items if i.domain == domain]
      if tags:
          tag_set = {t.strip() for t in tags.split(",") if t.strip()}
          items = [i for i in items if tag_set.intersection(i.tags)]
      if q:
          ql = q.lower()
          items = [
              i
              for i in items
              if ql in i.label.lower()
              or ql in i.id.lower()
              or (i.pinyin and ql in i.pinyin.lower())
              or any(ql in t.lower() for t in i.tags)
          ]
      return items

    def system_templates(self) -> list[dict[str, Any]]:
      return list(_load_yaml_config().get("system_templates") or [])
