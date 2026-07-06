from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

import aiohttp

logger = logging.getLogger(__name__)

SEARCH_URL = "https://api.kufar.by/search-api/v2/search/rendered-paginated"
CATEGORY_URL = "https://api.kufar.by/category-tree/v1/category_tree"

REGIONS = {
    1: "Брестская область",
    2: "Витебская область",
    3: "Гомельская область",
    4: "Гродненская область",
    5: "Могилёвская область",
    6: "Минская область",
    7: "Минск",
}

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class KufarClient:
    def __init__(self, session: aiohttp.ClientSession, search_size: int = 30) -> None:
        self.session = session
        self.search_size = search_size
        self._categories: dict[int, str] | None = None

    async def search(self, query: str = "", **params: str) -> list[dict[str, Any]]:
        search_params = {
            "sort": "lst.d",
            "size": str(self.search_size),
            "lang": "ru",
        }
        if query:
            search_params["query"] = query
        search_params.update({k: v for k, v in params.items() if v})

        headers = {"User-Agent": USER_AGENT}
        try:
            async with self.session.get(
                SEARCH_URL, params=search_params, headers=headers, timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
        except Exception:
            logger.exception("Kufar search failed: %s", search_params)
            raise

        return data.get("ads") or []

    async def get_categories(self) -> dict[int, str]:
        if self._categories is not None:
            return self._categories

        headers = {"User-Agent": USER_AGENT}
        async with self.session.get(CATEGORY_URL, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            resp.raise_for_status()
            tree = await resp.json()

        categories: dict[int, str] = {}

        def walk(nodes: list[dict[str, Any]]) -> None:
            for node in nodes:
                cat_id = node.get("id")
                name = node.get("name")
                if cat_id is not None and name:
                    categories[int(cat_id)] = str(name)
                subs = node.get("subcategories") or []
                if subs:
                    walk(subs)

        walk(tree if isinstance(tree, list) else [])
        self._categories = categories
        return categories

    def category_name(self, cat_id: int | str | None) -> str:
        if cat_id is None:
            return ""
        if self._categories:
            return self._categories.get(int(cat_id), str(cat_id))
        return str(cat_id)

    def region_name(self, region_id: int | str | None) -> str:
        if region_id is None:
            return ""
        try:
            return REGIONS.get(int(region_id), str(region_id))
        except (TypeError, ValueError):
            return str(region_id)


def get_image_url(image: dict[str, Any]) -> str | None:
    if not image:
        return None

    if image.get("yams_storage") and image.get("id") and image["id"] != "0000":
        image_id = str(image["id"])
        return (
            f"https://yams.kufar.by/api/v1/kufar-ads/images/"
            f"{image_id[:2]}/{image_id}.jpg?rule=gallery"
        )

    path = image.get("path") or ""
    if path:
        filename = path.split("/")[-1]
        return f"https://content.kufar.by/gallery/ad/{filename}"

    return None


def format_price(ad: dict[str, Any]) -> str:
    price = ad.get("price_byn")
    if price in (None, "", "0"):
        return "Договорная"
    try:
        value = int(price)
        return f"{value:,}".replace(",", " ") + " BYN"
    except (TypeError, ValueError):
        return f"{price} BYN"


def get_param_value(ad: dict[str, Any], param_name: str) -> str:
    for param in ad.get("ad_parameters") or []:
        if param.get("p") == param_name:
            return str(param.get("vl") or "")
    return ""


def format_ad_message(ad: dict[str, Any], kufar: KufarClient) -> str:
    subject = ad.get("subject") or "Без названия"
    price = format_price(ad)
    link = ad.get("ad_link") or f"https://www.kufar.by/item/{ad.get('ad_id')}"
    region = get_param_value(ad, "region") or get_param_value(ad, "area")
    category = get_param_value(ad, "category")

    lines = [
        f"<b>{subject}</b>",
        f"💰 {price}",
    ]
    if region:
        lines.append(f"📍 {region}")
    if category:
        lines.append(f"📂 {category}")
    lines.append(f'🔗 <a href="{link}">Открыть на Kufar</a>')
    return "\n".join(lines)


def build_search_url(query: str = "", **params: str) -> str:
    search_params: dict[str, str] = {"sort": "lst.d"}
    if query:
        search_params["query"] = query
    search_params.update({k: v for k, v in params.items() if v})
    return f"https://www.kufar.by/l?{urlencode(search_params)}"
