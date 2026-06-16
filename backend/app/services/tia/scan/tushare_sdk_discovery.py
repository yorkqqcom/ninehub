"""Tushare SDK introspection and batch API validation (scan phase P0/P2)."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from app.services.tia.scan.tushare_sdk_validate import list_pro_bar_apis, validate_api_via_sdk

ProgressFn = Callable[[int, str], None]


@dataclass
class SdkPackageInfo:
    tushare_version: str
    package_path: str
    access_model: str
    pro_bar_hardcoded_apis: list[str] = field(default_factory=list)
    top_level_exports_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SdkApiValidation:
    api: str
    sdk_valid: bool | None
    sdk_validation_code: int | None = None
    sdk_validation_msg: str | None = None
    reason: str | None = None
    doc_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def inspect_tushare_sdk() -> SdkPackageInfo:
    """Inspect installed tushare package (no network)."""
    import tushare as ts

    exports = [x for x in dir(ts) if not x.startswith("_")]
    return SdkPackageInfo(
        tushare_version=str(getattr(ts, "__version__", "unknown")),
        package_path=str(getattr(ts, "__file__", "")),
        access_model="dynamic __getattr__ + query() — no static API registry in package",
        pro_bar_hardcoded_apis=list_pro_bar_apis(),
        top_level_exports_count=len(exports),
    )


def merge_api_candidates(
    *,
    official_apis: list[str],
    local_apis: list[str] | None = None,
    include_pro_bar: bool = True,
) -> list[str]:
    """Union candidate API names for SDK batch validation."""
    merged: set[str] = set(official_apis)
    if local_apis:
        merged.update(local_apis)
    if include_pro_bar:
        merged.update(list_pro_bar_apis())
    return sorted(merged)


def batch_validate_apis(
    token: str | None,
    api_names: list[str],
    *,
    official_map: dict[str, Any] | None = None,
    max_calls_per_minute: int | None = None,
    sleep_seconds: float = 0.05,
    progress: ProgressFn | None = None,
) -> dict[str, Any]:
    """Batch validate API names via live pro_api (SDK/server ground truth)."""
    if not token:
        return {
            "skipped": True,
            "reason": "no_token",
            "validated_count": 0,
            "valid_count": 0,
            "invalid_count": 0,
            "unknown_count": len(api_names),
            "validations": [],
            "valid_apis": [],
            "invalid_apis": [],
        }

    validations: list[SdkApiValidation] = []
    valid_apis: list[str] = []
    invalid_apis: list[str] = []
    total = len(api_names)

    for idx, api in enumerate(api_names, start=1):
        if progress:
            progress(int(100 * idx / max(total, 1)), f"SDK validate {api}")

        entry = (official_map or {}).get(api)
        doc_id = getattr(entry, "doc_id", None) if entry is not None else None
        if doc_id is None and isinstance(entry, dict):
            doc_id = entry.get("doc_id")

        row = validate_api_via_sdk(
            token,
            api,
            {},
            max_calls_per_minute=max_calls_per_minute,
        )
        validation = SdkApiValidation(
            api=api,
            sdk_valid=row.get("sdk_valid"),
            sdk_validation_code=row.get("sdk_validation_code"),
            sdk_validation_msg=row.get("sdk_validation_msg"),
            reason=row.get("reason"),
            doc_id=int(doc_id) if doc_id is not None else None,
        )
        validations.append(validation)

        if validation.sdk_valid is True:
            valid_apis.append(api)
        elif validation.sdk_valid is False:
            invalid_apis.append(api)

        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    unknown = [v.api for v in validations if v.sdk_valid is None]
    return {
        "skipped": False,
        "validated_count": len(validations),
        "valid_count": len(valid_apis),
        "invalid_count": len(invalid_apis),
        "unknown_count": len(unknown),
        "validations": [v.to_dict() for v in validations],
        "valid_apis": valid_apis,
        "invalid_apis": invalid_apis,
        "valid_apis_sample": valid_apis[:30],
        "invalid_apis_sample": invalid_apis[:30],
    }


class TushareSdkDiscoveryService:
    """P0 SDK package inspect + P2 batch validation for TIA scan."""

    def run(
        self,
        *,
        official_apis: list[str],
        official_map: dict[str, Any] | None = None,
        local_apis: list[str] | None = None,
        token: str | None = None,
        max_calls_per_minute: int | None = None,
        sleep_seconds: float = 0.05,
        progress: ProgressFn | None = None,
    ) -> dict[str, Any]:
        package = inspect_tushare_sdk()
        if progress:
            progress(
                5,
                f"SDK package {package.tushare_version} "
                f"({len(package.pro_bar_hardcoded_apis)} pro_bar refs)",
            )

        candidates = merge_api_candidates(
            official_apis=official_apis,
            local_apis=local_apis,
            include_pro_bar=True,
        )
        if progress:
            progress(10, f"SDK batch validate {len(candidates)} candidate APIs")

        validation_report = batch_validate_apis(
            token,
            candidates,
            official_map=official_map,
            max_calls_per_minute=max_calls_per_minute,
            sleep_seconds=sleep_seconds,
            progress=progress,
        )

        return {
            "package": package.to_dict(),
            "candidate_count": len(candidates),
            "candidate_apis_sample": candidates[:30],
            **validation_report,
        }


def sdk_invalid_api_set(sdk_discovery: dict[str, Any] | None) -> set[str]:
    """APIs marked sdk_valid=False by batch validation."""
    if not sdk_discovery:
        return set()
    return set(sdk_discovery.get("invalid_apis") or [])
