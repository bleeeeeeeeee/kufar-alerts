from __future__ import annotations

from urllib.parse import urlencode

from bot.locations import region_slug_from_id
from bot.price import prc_for_website

# Kufar website puts seller type in `ot`; search API uses `cmp`.
_OT_TO_CMP = {"1": "0", "2": "1"}
_CMP_TO_OT = {"0": "1", "1": "2"}


def normalize_params_for_api(params: dict[str, str]) -> dict[str, str]:
    """Map website URL params to Kufar search API params."""
    result = {k: str(v) for k, v in params.items() if v and not str(k).startswith("_")}

    ot = result.pop("ot", None)
    if ot in _OT_TO_CMP and "cmp" not in result:
        result["cmp"] = _OT_TO_CMP[ot]

    return result


def normalize_params_for_url(params: dict[str, str]) -> dict[str, str]:
    """Map stored params to kufar.by link query string."""
    result = {k: str(v) for k, v in params.items() if v and not str(k).startswith("_")}

    cmp = result.pop("cmp", None)
    if cmp in _CMP_TO_OT and "ot" not in result:
        result["ot"] = _CMP_TO_OT[cmp]

    return result


def normalize_params_for_storage(params: dict[str, str]) -> dict[str, str]:
    """Canonical website-shaped params for DB storage."""
    return normalize_params_for_url(params)


def build_search_url(query: str = "", **params: str) -> str:
    """Build a kufar.by search URL matching the website format."""
    params = normalize_params_for_url(params)
    rgn = params.pop("rgn", None)
    ar = params.get("ar")

    path = "/l"
    if rgn and not ar:
        slug = region_slug_from_id(rgn)
        if slug:
            path = f"/l/r~{slug}"

    search_params: dict[str, str] = {"sort": "lst.d"}
    if query:
        search_params["query"] = query

    for key, value in params.items():
        if key == "prc":
            value = prc_for_website(value) or ""
        if value:
            search_params[key] = value

    return f"https://www.kufar.by{path}?{urlencode(search_params)}"
