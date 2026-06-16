"""CLI wrapper for collect params audit."""

from __future__ import annotations

import json

from app.services.tia.collect_params_audit import run_audit

if __name__ == "__main__":
    print(json.dumps(run_audit("stock_a"), ensure_ascii=False, indent=2))
