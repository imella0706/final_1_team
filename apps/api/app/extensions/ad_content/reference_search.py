from pydantic import BaseModel
import httpx

from app.core.config import settings


class ReferenceImageResult(BaseModel):
    title: str = ""
    page_url: str = ""
    image_url: str = ""
    thumbnail_url: str = ""
    license: str = ""
    source: str = ""
    attribution: str = ""


def build_reference_query(product_name: str, business_type: str) -> str:
    return f"{product_name} {business_type} product photo"


def _secret(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "get_secret_value"):
        return value.get_secret_value() or None
    return str(value) or None


async def _search_wikimedia(query: str, max_results: int) -> list[ReferenceImageResult]:
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": 6,
        "gsrlimit": max_results,
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "iiurlwidth": 480,
        "format": "json",
        "origin": "*",
    }
    async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
        response = await client.get(
            "https://commons.wikimedia.org/w/api.php",
            params=params,
        )
        response.raise_for_status()
        body = response.json()

    pages = body.get("query", {}).get("pages", {})
    results: list[ReferenceImageResult] = []
    for page in pages.values():
        imageinfo = (page.get("imageinfo") or [{}])[0]
        metadata = imageinfo.get("extmetadata") or {}
        license_name = metadata.get("LicenseShortName", {}).get("value", "")
        artist = metadata.get("Artist", {}).get("value", "")
        results.append(
            ReferenceImageResult(
                title=page.get("title", ""),
                page_url=imageinfo.get("descriptionurl", ""),
                image_url=imageinfo.get("url", ""),
                thumbnail_url=imageinfo.get("thumburl", ""),
                license=license_name,
                source="wikimedia",
                attribution=artist,
            )
        )
    return results


async def _search_pexels(query: str, max_results: int) -> list[ReferenceImageResult]:
    api_key = _secret(settings.pexels_api_key)
    if not api_key:
        return []
    async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
        response = await client.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": api_key},
            params={"query": query, "per_page": max_results},
        )
        response.raise_for_status()
        body = response.json()
    return [
        ReferenceImageResult(
            title=photo.get("alt") or "",
            page_url=photo.get("url") or "",
            image_url=(photo.get("src") or {}).get("large") or "",
            thumbnail_url=(photo.get("src") or {}).get("medium") or "",
            license="Pexels License",
            source="pexels",
            attribution=(photo.get("photographer") or ""),
        )
        for photo in body.get("photos", [])
    ]


async def _search_unsplash(query: str, max_results: int) -> list[ReferenceImageResult]:
    access_key = _secret(settings.unsplash_access_key)
    if not access_key:
        return []
    async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
        response = await client.get(
            "https://api.unsplash.com/search/photos",
            headers={"Authorization": f"Client-ID {access_key}"},
            params={"query": query, "per_page": max_results},
        )
        response.raise_for_status()
        body = response.json()
    return [
        ReferenceImageResult(
            title=photo.get("alt_description") or photo.get("description") or "",
            page_url=(photo.get("links") or {}).get("html") or "",
            image_url=(photo.get("urls") or {}).get("regular") or "",
            thumbnail_url=(photo.get("urls") or {}).get("small") or "",
            license="Unsplash License",
            source="unsplash",
            attribution=((photo.get("user") or {}).get("name") or ""),
        )
        for photo in body.get("results", [])
    ]


async def search_reference_images(
    product_name: str,
    business_type: str,
) -> tuple[str, list[ReferenceImageResult]]:
    if not settings.reference_search_enabled:
        return "", []

    query = build_reference_query(product_name, business_type)
    max_results = settings.reference_max_results
    provider = settings.reference_source.lower().strip()

    try:
        if provider == "pexels":
            return query, await _search_pexels(query, max_results)
        if provider == "unsplash":
            return query, await _search_unsplash(query, max_results)
        return query, await _search_wikimedia(query, max_results)
    except httpx.HTTPError:
        return query, []
