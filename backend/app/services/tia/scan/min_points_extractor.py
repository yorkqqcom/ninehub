"""Extract Tushare interface **access** min_points from document/2 page plain text.

Only parses the interface page body (积分段落), never sidebar link labels or bundled JSON hints.
Ignores frequency-tier points after 「频次」 and trial lines like 「120积分可以试用」 when a
higher explicit access threshold is present.
"""

from __future__ import annotations

import re

from app.services.tia.scan.doc_points_pattern_registry import NOT_ACCESS_MARKERS  # noqa: F401

# Section headers that end the points block on document/2 pages.
_POINTS_SECTION_END_MARKERS = (
    "频次",
    "限量",
    "输入参数",
    "输出参数",
    "获取方式",
    "使用说明",
    "接口示例",
    "数据样例",
    "权限说明",
)

# Ordered by specificity; first match wins within the points section.
_FORMAL_ACCESS_MIN_POINTS_PATTERNS: tuple[str, ...] = (
    r"用户需要至少(\d+)积分",
    r"最少需要(\d+)积分",
    r"需要至少(\d+)积分",
    r"用户积(?:[\u4e00-\u9fff]{0,8})?(\d+)积分后可用",
    r"(\d+)积分后可用",
    r"(\d+)积分以上才可以调取",
    r"(\d+)积分以上才可以",
    r"(\d+)积分以上可调取",
    r"(\d+)积分可以使用",
    r"(\d+)积分可重复调取",
    r"(\d+)积分可一次获取",
    r"(\d+)积分每分钟",
    r"(\d+)积分无每天",
    r"(\d+)积分可多次",
    r"(\d+)积分/次",
    r"(\d+)积分/分钟",
    r"(\d+)积分/天",
    r"(\d+)积分/月",
    r"需(\d+)积分以上",
    r"需(\d+)积分才可以调取",
    r"需(\d+)积分可",
    r"需(\d+)积分",
    r"至少(\d+)积分才可以",
    r"达到(\d+)积分",
    r"拥有(\d+)积分",
    r"(\d+)积分起",
    r"(\d+)积分可调取",
    r"调用本接口需(\d+)积分",
    r"本接口需(\d+)积分",
    r"调取要求大于(\d+)积分",
    r"调取要求(?:至少)?(\d+)积分",
    r"大于(\d+)积分",
    r"(\d+)积分正常使用",
    r"积分有(\d+)分",
)

# Ambiguous when co-located with VIP / trial copy — skip under VIP gating.
_WEAK_ACCESS_MIN_POINTS_PATTERNS: tuple[str, ...] = (
    r"积分[：:\s]*需?(\d+)\s*积分",
    r"积分[：:\s]*至少(\d+)积分",
    r"积分要求[：:\s]*(\d+)\s*积分",
    r"积分[：:\s]*(\d+)\s*起",
)

_ACCESS_MIN_POINTS_PATTERNS: tuple[str, ...] = _FORMAL_ACCESS_MIN_POINTS_PATTERNS + _WEAK_ACCESS_MIN_POINTS_PATTERNS

# Non-numeric VIP / special access — do not guess a number (incl. trial lines).
_VIP_POINTS_MARKERS = (
    "VIP接口",
    "vip接口",
    "VIP数据",
    "单独开通",
    "请联系",
)


def normalize_doc_plain_text(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def extract_points_section(text: str) -> str | None:
    """Return the 积分… block from a document/2 interface page, excluding later sections."""
    normalized = normalize_doc_plain_text(text)
    if not normalized:
        return None

    for marker in ("积分：", "积分:", "积分要求：", "积分要求:", "积分权限", "积分 ", "权限：", "权限:"):
        idx = normalized.find(marker)
        if idx >= 0:
            section = normalized[idx:]
            for end in _POINTS_SECTION_END_MARKERS:
                end_idx = section.find(end)
                if end_idx > 0:
                    section = section[:end_idx]
            return section.strip()

    if "积分" in normalized:
        idx = normalized.find("积分")
        section = normalized[idx:]
        for end in _POINTS_SECTION_END_MARKERS:
            end_idx = section.find(end)
            if end_idx > 0:
                section = section[:end_idx]
        return section.strip()

    return None


def _is_vip_gated(text: str) -> bool:
    return any(m in text for m in _VIP_POINTS_MARKERS)


def _match_access_min_points(section: str, patterns: tuple[str, ...]) -> int | None:
    for pat in patterns:
        match = re.search(pat, section)
        if match:
            return int(match.group(1))
    return None


def _extract_formal_access_min_points(section: str) -> int | None:
    return _match_access_min_points(section, _FORMAL_ACCESS_MIN_POINTS_PATTERNS)


def _is_consumption_section(section: str | None) -> bool:
    return bool(section and "积分消耗" in section)


def _is_vip_only_section(section: str | None) -> bool:
    if not section:
        return False
    if not _is_vip_gated(section):
        return False
    return _extract_formal_access_min_points(section) is None


def extract_access_min_points_from_section(section: str) -> int | None:
    return _match_access_min_points(section, _ACCESS_MIN_POINTS_PATTERNS)


def extract_access_min_points(text: str) -> int | None:
    """Parse interface access threshold from document/2 page plain text."""
    if not text:
        return None

    section = extract_points_section(text)
    if _is_consumption_section(section):
        return None
    if _is_vip_only_section(section):
        return None

    search_text = section if section else normalize_doc_plain_text(text)
    if _is_vip_gated(search_text):
        formal_pts = _extract_formal_access_min_points(search_text)
        if formal_pts is not None:
            return formal_pts
        return None

    pts = extract_access_min_points_from_section(search_text)
    if pts is not None:
        return pts

    # Trial-only: 120积分可以试用 when no higher threshold and not VIP-gated.
    if section and "可以试用" in section and not any(m in section for m in _VIP_POINTS_MARKERS):
        trial = re.search(r"(\d+)积分可以试用", section)
        if trial:
            return int(trial.group(1))

    normalized = normalize_doc_plain_text(text)
    if "积分消耗" in normalized:
        return None

    # Trial line may sit after VIP block outside truncated 积分 section.
    trial_full = re.search(r"(\d+)积分可以试用", normalized)
    if (
        trial_full
        and extract_access_min_points_from_section(normalized) is None
        and not any(m in normalized for m in _VIP_POINTS_MARKERS)
        and not re.search(r"用户需要至少\d+积分", normalized)
    ):
        return int(trial_full.group(1))
    freq_idx = normalized.find("频次")
    head = normalized[:freq_idx] if freq_idx >= 0 else normalized
    if _is_vip_gated(head):
        return None
    match = re.search(r"(\d+)\s*积分", head)
    if match:
        return int(match.group(1))
    return None


def discover_point_audit(text: str) -> dict:
    """Return extraction audit row for one page plain text."""
    section = extract_points_section(text)
    candidates = []
    normalized = normalize_doc_plain_text(text)
    for match in re.finditer(r"(\d+)\s*积分[^\s，,。]{0,24}", normalized):
        snippet = match.group(0)
        candidates.append(
            {
                "value": int(match.group(1)),
                "snippet": snippet,
                "in_section": bool(section and snippet in section),
            }
        )
    return {
        "points_section": section,
        "candidates": candidates,
        "extracted_min_points": extract_access_min_points(text),
        "consumption": "积分消耗" in normalized,
        "vip_only": _is_vip_only_section(section),
    }


def extract_from_doc_page(raw_text: str) -> dict:
    """Return {min_points, points_section} for cache / audit tooling."""
    section = extract_points_section(raw_text)
    pts = extract_access_min_points(raw_text)
    out: dict = {}
    if section:
        out["points_section"] = section
    if pts is not None:
        out["min_points"] = pts
    return out

