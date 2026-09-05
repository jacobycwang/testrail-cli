import time
from typing import Any
from urllib.parse import quote

import httpx

from tr.output import hint

API_PREFIX = "/api/v2/"
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
DEFAULT_RETRY_AFTER = 60.0
MAX_RETRY_AFTER = 120.0
LIST_META_KEYS = frozenset({"_links", "offset", "limit", "size"})
MAX_ERROR_BODY = 400
DEFAULT_MAX_PAGES = 50


def build_url(host: str | None, uri: str, params: dict[str, Any] | None = None) -> str:
    query = uri.lstrip("/")
    for key, value in (params or {}).items():
        query += f"&{key}={quote(str(value), safe=',')}"
    return f"{(host or '<host>').rstrip('/')}/index.php?{API_PREFIX}{query}"


class APIError(Exception):
    """Transport or API failure. status 0 means the request never reached TestRail."""

    def __init__(self, status: int, body: str) -> None:
        detail = body[:MAX_ERROR_BODY]
        super().__init__(detail if status == 0 else f"TestRail returned {status}: {detail}")
        self.status = status
        self.body = body


class APIClient:
    def __init__(
        self,
        host: str,
        email: str,
        api_key: str,
        sleep_s: float = 0.0,
        max_retries: int = 5,
        client: httpx.Client | None = None,
    ) -> None:
        self.host = host.rstrip("/")
        self.email = email
        self.api_key = api_key
        self.sleep_s = sleep_s
        self.max_retries = max_retries
        self.client = client or httpx.Client(timeout=60.0)

    def url(self, uri: str, params: dict[str, Any] | None = None) -> str:
        return build_url(self.host, uri, params)

    def get(self, uri: str, params: dict[str, Any] | None = None) -> Any:
        return self._request("GET", uri, params=params)

    def post(self, uri: str, body: Any = None) -> Any:
        return self._request("POST", uri, json=body)

    def paginate(
        self,
        uri: str,
        params: dict[str, Any] | None = None,
        max_pages: int = DEFAULT_MAX_PAGES,
        sleep_s: float | None = None,
    ) -> Any:
        throttle = self.sleep_s if sleep_s is None else sleep_s
        merged: list[Any] = []
        list_key: str | None = None
        size = 0
        pages = 0
        next_uri: str | None = uri
        next_params = params

        while next_uri and pages < max_pages:
            payload = self._request("GET", next_uri, params=next_params)
            pages += 1
            if isinstance(payload, list):
                return payload if pages == 1 else merged
            list_key = list_key or _list_key(payload)
            if list_key is None:
                return payload
            merged.extend(payload.get(list_key) or [])
            size = payload.get("size", size)
            next_uri = _next_uri(payload)
            next_params = None
            if next_uri and throttle:
                time.sleep(throttle)

        return {
            list_key or "items": merged,
            "size": size,
            "pages": pages,
            "_links": {"next": None, "prev": None},
        }

    def _request(self, method: str, uri: str, **kwargs: Any) -> Any:
        url = self.url(uri, kwargs.pop("params", None))
        hint(f"-> {method} {url.split(API_PREFIX, 1)[-1]}")
        attempt = 0
        while True:
            attempt += 1
            if self.sleep_s and attempt == 1:
                time.sleep(self.sleep_s)
            try:
                response = self.client.request(
                    method,
                    url,
                    auth=(self.email, self.api_key),
                    headers={"Content-Type": "application/json"},
                    **kwargs,
                )
            except httpx.HTTPError as exc:
                raise APIError(0, f"could not reach {self.host}: {type(exc).__name__}") from exc
            if response.status_code < 300:
                return _decode(response)
            if response.status_code not in RETRY_STATUSES or attempt >= self.max_retries:
                raise APIError(response.status_code, response.text)
            time.sleep(_backoff(response, attempt))

    def close(self) -> None:
        self.client.close()


def _decode(response: httpx.Response) -> Any:
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError:
        return {"raw": response.text}


def _backoff(response: httpx.Response, attempt: int) -> float:
    if response.status_code == 429:
        raw = response.headers.get("Retry-After")
        try:
            wait = DEFAULT_RETRY_AFTER if raw is None else float(raw)
        except ValueError:
            wait = DEFAULT_RETRY_AFTER
        return min(max(wait, 0.0), MAX_RETRY_AFTER)
    return float(2 ** (attempt - 1))


def _list_key(payload: dict) -> str | None:
    for key, value in payload.items():
        if key not in LIST_META_KEYS and isinstance(value, list):
            return key
    return None


def _next_uri(payload: dict) -> str | None:
    links = payload.get("_links") or {}
    nxt = links.get("next")
    if not nxt:
        return None
    return nxt[len(API_PREFIX):] if nxt.startswith(API_PREFIX) else nxt.lstrip("/")
