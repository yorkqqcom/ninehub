#!/usr/bin/env python3
"""Fill pinyin fields in browser_indicators.yaml overrides (build-time helper)."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

BACKEND = Path(__file__).resolve().parents[1]
YAML_PATH = BACKEND / "app" / "catalog" / "browser_indicators.yaml"


def _pinyin_abbr(label: str) -> str:
    try:
        from pypinyin import lazy_pinyin

        return "".join(p[0] for p in lazy_pinyin(label) if p)
    except ImportError:
        return ""


def main() -> int:
    if not YAML_PATH.is_file():
        print(f"Missing {YAML_PATH}", file=sys.stderr)
        return 1
    data = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8")) or {}
    overrides = data.get("overrides") or {}
    updated = 0
    for ind_id, ov in overrides.items():
        if not isinstance(ov, dict):
            continue
        if ov.get("pinyin"):
            continue
        label = ov.get("label") or ind_id.split(".")[-1]
        abbr = _pinyin_abbr(str(label))
        if abbr:
            ov["pinyin"] = abbr
            updated += 1
    data["overrides"] = overrides
    YAML_PATH.write_text(
        yaml.dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    print(f"Updated pinyin for {updated} indicators in {YAML_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
