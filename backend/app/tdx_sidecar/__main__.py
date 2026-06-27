"""Run TDX sidecar: uvicorn app.tdx_sidecar.main:app --host 127.0.0.1 --port 8090"""

from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run(
        "app.tdx_sidecar.main:app",
        host="127.0.0.1",
        port=int(__import__("os").environ.get("TDX_SIDECAR_PORT", "8090")),
        reload=False,
    )


if __name__ == "__main__":
    main()
