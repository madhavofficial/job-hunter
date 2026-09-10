"""API-backed web search for dynamic ATS and career-board discovery."""

from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dotenv import load_dotenv


load_dotenv()


class SearchProviderError(RuntimeError):
    """A search provider failed for this query."""


class SearchRateLimitError(SearchProviderError):
    """The provider rejected the request because of rate limits."""


def _request_json(url: str, headers: dict[str, str], params: dict[str, str | int]) -> dict:
    request = Request(f"{url}?{urlencode(params)}", headers=headers)
    try:
        with urlopen(request, timeout=20) as response:
            return json.load(response)
    except HTTPError as exc:
        if exc.code == 429:
            raise SearchRateLimitError(f"search provider returned HTTP 429 for {url}") from exc
        raise SearchProviderError(f"search provider returned HTTP {exc.code} for {url}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise SearchProviderError(f"search provider request failed for {url}: {exc}") from exc


def _brave(query: str, api_key: str, count: int) -> list[str]:
    payload = _request_json(
        "https://api.search.brave.com/res/v1/web/search",
        {"Accept": "application/json", "X-Subscription-Token": api_key},
        {"q": query, "count": count, "country": "IN", "search_lang": "en"},
    )
    return [item.get("url", "") for item in payload.get("web", {}).get("results", [])]


def _bing(query: str, api_key: str, count: int) -> list[str]:
    payload = _request_json(
        "https://api.bing.microsoft.com/v7.0/search",
        {"Accept": "application/json", "Ocp-Apim-Subscription-Key": api_key},
        {"q": query, "count": count, "mkt": "en-IN", "responseFilter": "Webpages"},
    )
    return [item.get("url", "") for item in payload.get("webPages", {}).get("value", [])]


def _serpapi(query: str, api_key: str, count: int) -> list[str]:
    payload = _request_json(
        "https://serpapi.com/search.json",
        {},
        {"engine": "google", "q": query, "api_key": api_key, "num": count, "gl": "in", "hl": "en"},
    )
    return [item.get("link", "") for item in payload.get("organic_results", [])]


def configured_provider() -> str | None:
    requested = os.getenv("ATS_SEARCH_PROVIDER", "auto").lower().strip()
    keys = {
        "brave": os.getenv("BRAVE_SEARCH_API_KEY"),
        "bing": os.getenv("BING_SEARCH_API_KEY"),
        "serpapi": os.getenv("SERPAPI_API_KEY"),
    }
    if requested in keys:
        return requested if keys[requested] else None
    if requested not in {"", "auto"}:
        raise SearchProviderError(f"Unsupported ATS_SEARCH_PROVIDER: {requested}")
    return next((name for name in ("brave", "bing", "serpapi") if keys[name]), None)


def search_urls(query: str, count: int = 50) -> list[str]:
    provider = configured_provider()
    if not provider:
        raise SearchProviderError(
            "No ATS search provider configured. Set BRAVE_SEARCH_API_KEY, "
            "BING_SEARCH_API_KEY, or SERPAPI_API_KEY."
        )
    api_key = os.getenv({"brave": "BRAVE_SEARCH_API_KEY", "bing": "BING_SEARCH_API_KEY", "serpapi": "SERPAPI_API_KEY"}[provider], "")
    searchers = {"brave": _brave, "bing": _bing, "serpapi": _serpapi}
    return [url for url in searchers[provider](query, api_key, count) if url]
