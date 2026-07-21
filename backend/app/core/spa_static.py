"""StaticFiles with SPA history-fallback to index.html."""

from __future__ import annotations

from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope


class SPAStaticFiles(StaticFiles):
    """Serve index.html for missing paths (SPA deep links).

    Starlette html=True only serves directory index / 404.html — not SPA fallback.
    Never SPA-fallback API-looking paths (misrouted /api/... or /watch/api/...).
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        normalized = (path or "").lstrip("/")
        # Root mount sees "api/v1/..."; /watch mount sees "api/..."
        if normalized == "api" or normalized.startswith("api/"):
            return JSONResponse(
                {
                    "detail": (
                        "Not Found — API routes must be registered on the app; "
                        "static SPA fallback will not serve /api/*"
                    )
                },
                status_code=404,
            )
        try:
            resp = await super().get_response(path, scope)
            return self._apply_cache_headers(normalized, resp)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
        index = Path(str(self.directory or "")) / "index.html"
        if index.is_file():
            return self._apply_cache_headers("index.html", FileResponse(index))
        raise HTTPException(status_code=404)

    @staticmethod
    def _apply_cache_headers(path: str, resp: Response) -> Response:
        """index.html 禁止缓存，避免盯盘仍加载旧 chunk；带 hash 的 assets 可长缓存。"""
        norm = (path or "").replace("\\", "/").lstrip("/")
        base = Path(norm).name.lower()
        if base == "index.html" or norm in {"", "."}:
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            resp.headers["Pragma"] = "no-cache"
        elif "/assets/" in f"/{norm}" or norm.startswith("assets/"):
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return resp
