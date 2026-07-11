from __future__ import annotations

import logging
from typing import Any

import aiohttp

from bot.catalog import set_category_names
from bot.kufar_params import normalize_params_for_api

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
        await self.load_category_tree()
        api_params = normalize_params_for_api({k: str(v) for k, v in params.items() if v})

        cat = api_params.get("cat")
        if cat:
            cat_id = int(cat)
            if self.get_category_children(cat_id):
                leaf_ids = self._leaf_category_ids(cat_id)
                if len(leaf_ids) > 1:
                    return await self._search_merged(query, leaf_ids, api_params)

        return await self._search_once(query, **api_params)

    def _leaf_category_ids(self, cat_id: int) -> list[int]:
        children = self.get_category_children(cat_id)
        if not children:
            return [cat_id]
        ids: list[int] = []
        for child in children:
            ids.extend(self._leaf_category_ids(int(child["id"])))
        return ids

    async def _search_merged(
        self,
        query: str,
        cat_ids: list[int],
        params: dict[str, str],
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[int] = set()
        base = {k: v for k, v in params.items() if k != "cat"}

        for cat_id in cat_ids:
            ads = await self._search_once(query, cat=str(cat_id), **base)
            for ad in ads:
                ad_id = ad.get("ad_id")
                if not ad_id:
                    continue
                aid = int(ad_id)
                if aid in seen:
                    continue
                seen.add(aid)
                merged.append(ad)

        merged.sort(key=lambda ad: ad.get("list_time", ""), reverse=True)
        return merged[: self.search_size]

    async def _search_once(self, query: str = "", **params: str) -> list[dict[str, Any]]:
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
        headers = {
            "User-Agent": USER_AGENT,
            "Referer": "https://www.kufar.by/",
        }
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

    path = (image.get("path") or "").strip().lstrip("/")
    if path:
        return [f"https://rms.kufar.by/v1/gallery/{path}"]

    if image.get("yams_storage") and image.get("id") and image["id"] != "0000":
        image_id = str(image["id"])
        return [
            f"https://yams.kufar.by/api/v1/kufar-ads/images/"
            f"{image_id[:2]}/{image_id}.jpg?rule=gallery"
        ]

    return []


def get_image_urls(ad: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for image in ad.get("images") or []:
        for url in get_image_urls_from_image(image):
            if url not in urls:
                urls.append(url)
    return urls


def build_search_url(query: str = "", **params: str) -> str:
    from bot.kufar_params import build_search_url as _build_search_url

    return _build_search_url(query, **params)
