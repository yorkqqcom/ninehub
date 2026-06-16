"""TIA naming and domain constants."""

DEFAULT_PROVIDER = "tushare"
LEGACY_DATA_TYPE_PREFIX = "tia"

API_TO_DOMAIN: dict[str, str] = {
    "stock_basic": "basic",
    "daily": "market",
    "income": "financial",
    "top_inst": "feature",
    "share_float": "reference",
}

API_TO_LABEL: dict[str, str] = {
    "stock_basic": "股票列表",
    "daily": "日线行情",
    "income": "利润表",
    "top_inst": "龙虎榜机构",
    "share_float": "限售股解禁",
}


def api_to_data_type(api_name: str, provider: str = DEFAULT_PROVIDER) -> str:
    """Platform data_type: {provider}_{api_name}."""
    return f"{provider}_{api_name}"


def legacy_data_type(api_name: str) -> str:
    """Read-only alias tia_{api_name} for backward compatibility."""
    return f"{LEGACY_DATA_TYPE_PREFIX}_{api_name}"


def api_to_table_name(api_name: str, provider: str = DEFAULT_PROVIDER) -> str:
    """Default fact table name (equals data_type unless overridden at L3)."""
    return api_to_data_type(api_name, provider)


def data_type_aliases(api_name: str, provider: str = DEFAULT_PROVIDER) -> list[str]:
    """All equivalent data_type strings (canonical first, then legacy)."""
    canonical = api_to_data_type(api_name, provider)
    legacy = legacy_data_type(api_name)
    if canonical == legacy:
        return [canonical]
    return [canonical, legacy]


def is_legacy_data_type(data_type: str) -> bool:
    return data_type.startswith(f"{LEGACY_DATA_TYPE_PREFIX}_")


def resolve_canonical_data_type(data_type: str, provider: str = DEFAULT_PROVIDER) -> str:
    """Map legacy tia_{api} to {provider}_{api} when applicable."""
    if is_legacy_data_type(data_type):
        api_name = data_type[len(LEGACY_DATA_TYPE_PREFIX) + 1 :]
        if api_name:
            return api_to_data_type(api_name, provider)
    return data_type


def api_to_domain(api_name: str) -> str:
    return API_TO_DOMAIN.get(api_name, "financial")


def api_to_label(api_name: str) -> str:
    return API_TO_LABEL.get(api_name, api_name)


def resolve_catalog_data_types(data_type: str, api_name: str | None = None) -> list[str]:
    """Catalog registry lookup keys: canonical first, then legacy aliases."""
    ordered: list[str] = []
    seen: set[str] = set()

    def add(dt: str | None) -> None:
        if dt and dt not in seen:
            seen.add(dt)
            ordered.append(dt)

    if data_type:
        add(resolve_canonical_data_type(data_type))
        add(data_type)
    if api_name:
        for alias in data_type_aliases(api_name):
            add(alias)
    return ordered
