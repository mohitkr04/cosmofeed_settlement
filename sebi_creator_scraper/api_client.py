"""
Thread-safe, rate-paced API client with authentication, token refresh, and retries.
"""

import os
import json
import time
import socket
import threading
from urllib import request as urlreq
from urllib import parse as urlparse
from urllib.error import HTTPError, URLError
from typing import Dict, Any, Optional

from . import config

socket.setdefaulttimeout(config.DEFAULT_REQUEST_TIMEOUT)


class RatePacer:
    """Thread-safe rate pacer to prevent rate limiting (HTTP 429)."""
    def __init__(self, max_per_second: float = config.RATE_LIMIT_PER_SEC):
        self.interval = 1.0 / max(0.1, max_per_second)
        self.lock = threading.Lock()
        self.last_time = 0.0

    def wait(self) -> None:
        to_sleep = 0.0
        with self.lock:
            now = time.time()
            if self.last_time < now:
                self.last_time = now
            scheduled = self.last_time + self.interval
            to_sleep = scheduled - now
            if to_sleep > 2.0:
                scheduled = now + self.interval
                to_sleep = self.interval
            self.last_time = scheduled
        if to_sleep > 0:
            time.sleep(to_sleep)


class CosmofeedApiClient:
    """Authenticated API client for Cosmofeed internal dashboard."""

    def __init__(self, token: Optional[str] = None, refresh_token: Optional[str] = None, rate_pacer: Optional[RatePacer] = None):
        self._load_env()
        self.token = token or os.environ.get("COSMOFEED_TOKEN", "")
        self.refresh_token = refresh_token or os.environ.get("COSMOFEED_REFRESH_TOKEN", "")
        self.rate_pacer = rate_pacer or RatePacer()
        self.auth_lock = threading.Lock()

        self.headers_base = {
            "accept": "application/json, text/plain, */*",
            "origin": config.ADMIN_BASE_URL,
            "referer": f"{config.ADMIN_BASE_URL}/",
            "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
        }

    def _load_env(self) -> None:
        """Load environment variables from project root .env if present."""
        env_path = os.path.join(config.PROJECT_ROOT, ".env")
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k, v = k.strip(), v.strip().strip('"').strip("'")
                            if k and k not in os.environ:
                                os.environ[k] = v
            except Exception:
                pass

    def refresh_access_token(self) -> bool:
        """Attempt to refresh an expired access token."""
        with self.auth_lock:
            # First check if .env has an updated token
            self._load_env()
            fresh_env_tok = os.environ.get("COSMOFEED_TOKEN", "")
            if fresh_env_tok and fresh_env_tok != self.token:
                self.token = fresh_env_tok
                return True

            if not self.refresh_token:
                return False

            refresh_url = "https://prod.api.cosmofeed.com/api/user/refreshToken"
            try:
                payload = json.dumps({"refreshToken": self.refresh_token}).encode("utf-8")
                req = urlreq.Request(
                    refresh_url,
                    data=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Origin": config.ADMIN_BASE_URL,
                        "Referer": f"{config.ADMIN_BASE_URL}/"
                    },
                    method="POST"
                )
                with urlreq.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    new_token = data.get("data", {}).get("token") or data.get("token")
                    if new_token:
                        self.token = new_token
                        os.environ["COSMOFEED_TOKEN"] = new_token
                        return True
            except Exception:
                pass
            return False

    def get(self, endpoint_path: str, params: Optional[Dict[str, Any]] = None, retries: int = config.DEFAULT_MAX_RETRIES) -> Dict[str, Any]:
        """Execute a GET request to the internal dashboard API."""
        if not endpoint_path.startswith("/"):
            endpoint_path = "/" + endpoint_path

        query_str = ""
        if params:
            query_str = "?" + urlparse.urlencode({k: v for k, v in params.items() if v is not None})

        url = config.API_BASE_URL + endpoint_path + query_str
        last_error = "unknown_error"

        for attempt in range(retries):
            self.rate_pacer.wait()
            headers = dict(self.headers_base)
            if self.token:
                headers["authorization"] = f"Bearer {self.token.strip()}"

            try:
                req = urlreq.Request(url, headers=headers, method="GET")
                with urlreq.urlopen(req, timeout=config.DEFAULT_REQUEST_TIMEOUT) as resp:
                    resp_data = resp.read().decode("utf-8")
                    return json.loads(resp_data)
            except HTTPError as e:
                last_error = f"HTTP {e.code}"
                if e.code == 401:
                    # Token expired: try refresh once
                    if attempt == 0 and self.refresh_access_token():
                        continue
                    return {"__error__": "HTTP 401 Unauthorized"}
                elif e.code == 429:
                    # Rate limited: exponential backoff
                    backoff = (attempt + 1) * 3.0
                    time.sleep(backoff)
                    continue
                elif e.code in (500, 502, 503, 504):
                    time.sleep((attempt + 1) * 1.5)
                    continue
                return {"__error__": last_error}
            except (URLError, socket.timeout) as e:
                last_error = f"Network Timeout/Error: {str(e)}"
                time.sleep((attempt + 1) * 1.0)
            except Exception as e:
                last_error = f"Unexpected Error: {str(e)}"
                time.sleep(1.0)

        return {"__error__": last_error}

    def get_creator_kundli(self, creator_id: str, requested_action: Optional[str] = None) -> Dict[str, Any]:
        """Query getCreatorKundli for a specific creator ID."""
        if not creator_id:
            return {"__error__": "missing_creator_id"}

        params = {"type": "userId", "value": creator_id}
        if requested_action:
            params["requestedAction"] = requested_action

        return self.get("/getCreatorKundli", params=params)

    def get_product_details(self, product_id: str, product_type: str = "page") -> Dict[str, Any]:
        """Query IDviewProductDetails for a specific product ID and product type."""
        if not product_id:
            return {"__error__": "missing_product_id"}

        params = {"id": product_id, "productType": product_type or "page"}
        return self.get("/IDviewProductDetails", params=params)

    def get_settlements_page(self, page: int = 1, request_type: str = "pending") -> Dict[str, Any]:
        """Fetch a page of settlements from IDgetSettlements."""
        params = {
            "requestType": request_type,
            "page": page,
            "sortField": "",
            "onlyFlagged": 0,
            "AmountGreaterThan": 0,
            "AmountLessThan": 0,
            "filter": "",
            "paymentVerified": ""
        }
        return self.get("/IDgetSettlements", params=params)
