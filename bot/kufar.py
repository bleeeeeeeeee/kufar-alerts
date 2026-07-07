from __future__ import annotations

import html
import logging
from typing import Any
from urllib.parse import urlencode

import aiohttp

from bot.catalog import set_category_names
from bot.price import prc_for_website

logger = logging.getLogger(__name__)

SEARCH_URL = "https://api.kufar.by/search-api/v2/search/rendered-paginated"
CATEGORY_URL = "https://api.kufar.by/category-tree/v1/category_tree"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class KufarClient:
    def __init__(self, session: aiohttp.ClientSession, search_size: int = 30) -> None:
        self.session = session
        self.search_size = search_size
        self._category_tree: list[dict[str, Any]] | None = None
        self._categories: dict[int, str] | None = None
        self._category_parent: dict[int, int | None] = {}
        self._category_index: dict[int, dict[str, Any]] = {}

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

    async def download_image(self, url: str) -> bytes | None:
        headers = {"User-Agent": USER_AGENT}
        try:
            async with self.session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    return None
                content_type = resp.headers.get("Content-Type", "")
                if content_type and not content_type.startswith("image/"):
                    return None
                data = await resp.read()
                return data if len(data) > 500 else None
        except Exception:
            logger.debug("Failed to download image %s", url, exc_info=True)
            return None

    async def load_category_tree(self) -> dict[int, str]:
        if self._categories is not None:
            return self._categories

        headers = {"User-Agent": USER_AGENT}
        async with self.session.get(CATEGORY_URL, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            resp.raise_for_status()
            data = await resp.json()

        self._category_tree = data.get("categories") if isinstance(data, dict) else data
        categories: dict[int, str] = {}
        self._category_parent = {}
        self._category_index = {}

        def walk(nodes: list[dict[str, Any]], parent_id: int | None = None) -> None:
            for node in nodes:
                cat_id = node.get("id")
                name = node.get("name")
                if cat_id is not None and name:
                    cat_id = int(cat_id)
                    categories[cat_id] = str(name)
                    self._category_parent[cat_id] = parent_id
                    self._category_index[cat_id] = node
                subs = node.get("subcategories") or []
                if subs and cat_id is not None:
                    walk(subs, int(cat_id))

        walk(self._category_tree or [])
        self._categories = categories
        set_category_names(categories)
        return categories

    async def get_categories(self) -> dict[int, str]:
        return await self.load_category_tree()

    def get_category_children(self, parent_id: int | None) -> list[dict[str, Any]]:
        if parent_id is None:
            return list(self._category_tree or [])
        node = self._category_index.get(parent_id)
        return list(node.get("subcategories") or []) if node else []

    def get_category_parent(self, cat_id: int) -> int | None:
        return self._category_parent.get(cat_id)

    def category_name(self, cat_id: int | str | None) -> str:
        if cat_id is None:
            return ""
        if self._categories:
            return self._categories.get(int(cat_id), str(cat_id))
        return str(cat_id)

    def region_name(self, region_id: int | str | None) -> str:
        from bot.locations import region_name as loc_region_name

        return loc_region_name(region_id)


def get_image_url(image: dict[str, Any]) -> str | None:
    urls = get_image_urls_from_image(image)
    return urls[0] if urls else None


def get_image_urls_from_image(image: dict[str, Any]) -> list[str]:
    if not image:
        return []

    if image.get("yams_storage") and image.get("id") and image["id"] != "0000":
        image_id = str(image["id"])
        return [
            f"https://yams.kufar.by/api/v1/kufar-ads/images/"
            f"{image_id[:2]}/{image_id}.jpg?rule=gallery"
        ]

    path = image.get("path") or ""
    if path:
        filename = path.split("/")[-1]
        return [f"https://content.kufar.by/gallery/ad/{filename}"]

    return []


def get_image_urls(ad: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for image in ad.get("images") or []:
        for url in get_image_urls_from_image(image):
            if url not in urls:
                urls.append(url)
    return urls


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
    subject = html.escape(ad.get("subject") or "Без названия")
    price = html.escape(format_price(ad))
    link = ad.get("ad_link") or f"https://www.kufar.by/item/{ad.get('ad_id')}"
    region = html.escape(get_param_value(ad, "region") or get_param_value(ad, "area"))
    category = html.escape(get_param_value(ad, "category"))

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
    for key, value in params.items():
        if not value:
            continue
        if key == "prc":
            value = prc_for_website(value) or ""
        if value:
            search_params[key] = value
    return f"https://www.kufar.by/l?{urlencode(search_params)}"
