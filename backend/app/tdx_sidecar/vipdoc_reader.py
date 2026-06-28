"""Parse TongDaXin vipdoc binary files (.day / .lc1 / .lc5)."""

from __future__ import annotations

import struct
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

_DAY_STRUCT = struct.Struct("<IIIIIfII")
_MIN_STRUCT = struct.Struct("<HHfffffII")


def day_filename_to_stock_code(filename: str) -> str | None:
    stem = Path(filename).stem.lower()
    if len(stem) < 8:
        return None
    prefix = stem[:2]
    digits = stem[2:]
    if prefix == "sh" and len(digits) == 6:
        return f"{digits}.SH"
    if prefix == "sz" and len(digits) == 6:
        return f"{digits}.SZ"
    return None


def _read_day_file(path: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(32)
            if len(chunk) < 32:
                break
            ymd, o, h, low, c, amount, volume, _reserved = _DAY_STRUCT.unpack(chunk)
            try:
                trade_date = date(ymd // 10000, (ymd // 100) % 100, ymd % 100)
            except ValueError:
                continue
            rows.append(
                {
                    "trade_date": trade_date,
                    "open": o / 100.0,
                    "high": h / 100.0,
                    "low": low / 100.0,
                    "close": c / 100.0,
                    "amount": float(amount),
                    "volume": float(volume),
                }
            )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def _read_lc_min_file(path: Path, period: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(_MIN_STRUCT.size)
            if len(chunk) < _MIN_STRUCT.size:
                break
            unpacked = _MIN_STRUCT.unpack(chunk)
            ymd = unpacked[0]
            hm = unpacked[1]
            o, h, low, c, amount = unpacked[2:7]
            volume = unpacked[7]
            try:
                bar_time = datetime(
                    ymd // 10000,
                    (ymd // 100) % 100,
                    ymd % 100,
                    hm // 60,
                    hm % 60,
                )
            except ValueError:
                continue
            rows.append(
                {
                    "bar_time": bar_time,
                    "period": period,
                    "open": float(o),
                    "high": float(h),
                    "low": float(low),
                    "close": float(c),
                    "amount": float(amount),
                    "volume": float(volume),
                }
            )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def read_day_file(path: Path, stock_code: str | None = None) -> pd.DataFrame:
    """Read single .day file; prefer pytdx reader when available."""
    code = stock_code or day_filename_to_stock_code(path.name)
    try:
        from pytdx.reader import TdxDailyBarReader

        reader = TdxDailyBarReader()
        df = reader.get_df(str(path))
        if df is None or df.empty:
            return _read_day_file(path)
        out = df.reset_index()
        out.rename(columns={"date": "trade_date"}, inplace=True)
        if "trade_date" in out.columns:
            out["trade_date"] = pd.to_datetime(out["trade_date"]).dt.date
        if code:
            out["stock_code"] = code
        return out
    except Exception:
        df = _read_day_file(path)
        if code and not df.empty:
            df["stock_code"] = code
        return df


def iter_lday_files(vipdoc_root: Path) -> Iterator[tuple[Path, str]]:
    for market in ("sh", "sz"):
        lday = vipdoc_root / market / "lday"
        if not lday.is_dir():
            continue
        for path in sorted(lday.glob("*.day")):
            code = day_filename_to_stock_code(path.name)
            if code:
                yield path, code


def scan_vipdoc_status(vipdoc_root: str) -> dict[str, Any]:
    root = Path(vipdoc_root)
    file_count = 0
    max_trade_date: date | None = None
    latest_mtime = 0.0
    if root.is_dir():
        for market in ("sh", "sz"):
            lday = root / market / "lday"
            if not lday.is_dir():
                continue
            for path in lday.glob("*.day"):
                file_count += 1
                try:
                    st = path.stat()
                    latest_mtime = max(latest_mtime, st.st_mtime)
                except OSError:
                    pass
                try:
                    with path.open("rb") as fh:
                        fh.seek(-32, 2)
                        chunk = fh.read(32)
                    if len(chunk) == 32:
                        ymd = _DAY_STRUCT.unpack(chunk)[0]
                        td = date(ymd // 10000, (ymd // 100) % 100, ymd % 100)
                        if max_trade_date is None or td > max_trade_date:
                            max_trade_date = td
                except OSError:
                    continue
    return {
        "lday_file_count": file_count,
        "max_trade_date": max_trade_date.isoformat() if max_trade_date else None,
        "latest_mtime_ms": int(latest_mtime * 1000) if latest_mtime else None,
    }


def import_vipdoc_bars(
    vipdoc_root: str,
    *,
    period: str = "1d",
    start_date: date | None = None,
    end_date: date | None = None,
    stock_codes: list[str] | None = None,
    incremental: bool = False,
    last_sync_date: date | None = None,
    limit_files: int | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Import bars from vipdoc; returns raw dataframe + meta."""
    root = Path(vipdoc_root)
    if not root.is_dir():
        raise FileNotFoundError(f"vipdoc_root not found: {vipdoc_root}")

    allowed = {c.upper() for c in stock_codes} if stock_codes else None
    frames: list[pd.DataFrame] = []
    files_read = 0
    eff_start = start_date
    if incremental and last_sync_date:
        eff_start = last_sync_date

    if period == "1d":
        file_iter = iter_lday_files(root)
        read_fn = lambda path, code: read_day_file(path, code)
        date_col = "trade_date"
    elif period in ("1m", "5m"):
        ext = ".lc1" if period == "1m" else ".lc5"
        file_iter = _iter_min_files(root, ext)
        read_fn = lambda path, code: _read_lc_min_file(path, period).assign(stock_code=code)
        date_col = "bar_time"
    else:
        raise ValueError(f"vipdoc import period {period} not supported")

    for path, code in file_iter:
        if allowed and code.upper() not in allowed:
            continue
        df = read_fn(path, code)
        if df.empty:
            continue
        if eff_start is not None and date_col in df.columns:
            if date_col == "trade_date":
                df = df[df[date_col] >= eff_start]
            else:
                start_dt = datetime.combine(eff_start, datetime.min.time())
                df = df[df[date_col] >= start_dt]
        if end_date is not None and date_col in df.columns:
            if date_col == "trade_date":
                df = df[df[date_col] <= end_date]
            else:
                end_dt = datetime.combine(end_date, datetime.max.time())
                df = df[df[date_col] <= end_dt]
        if df.empty:
            continue
        frames.append(df)
        files_read += 1
        if limit_files and files_read >= limit_files:
            break

    if not frames:
        return pd.DataFrame(), {"files_read": 0, "source": "file", "period": period}
    merged = pd.concat(frames, ignore_index=True)
    meta = {"files_read": files_read, "source": "file", "rows": len(merged), "period": period}
    return merged, meta


def _iter_min_files(vipdoc_root: Path, ext: str) -> Iterator[tuple[Path, str]]:
    for market in ("sh", "sz"):
        min_dir = vipdoc_root / market / "minline"
        if not min_dir.is_dir():
            min_dir = vipdoc_root / market / "fzline"
        if not min_dir.is_dir():
            continue
        for path in sorted(min_dir.glob(f"*{ext}")):
            code = day_filename_to_stock_code(path.name.replace(ext, ".day"))
            if code:
                yield path, code
