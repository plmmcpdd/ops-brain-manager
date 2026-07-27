"""A small GET-only standard-library HTTP client for the bridge."""
from __future__ import annotations

import json
import socket
import ssl
from http.client import HTTPConnection, HTTPSConnection, HTTPResponse
from urllib.parse import urlencode, urlsplit

from .config import PublishOSConfig
from .errors import PublishOSError

API_PATH = "/v1/integrations/ops-brain/performance"
MAX_RESPONSE_BYTES = 5 * 1024 * 1024


def is_loopback(host: str | None) -> bool:
    return host in {"localhost", "127.0.0.1", "::1"}


class PerformanceClient:
    def __init__(self, config: PublishOSConfig, token: str, *, allow_external: bool = True) -> None:
        self.config, self.token, self.allow_external = config, token, allow_external

    def get_performance(self, client_id: str, content_ref: str, days: int) -> object:
        parsed = urlsplit(self.config.base_url)
        if not self.allow_external and not is_loopback(parsed.hostname):
            raise PublishOSError("external_network_blocked", "non-loopback network access is disabled")
        if parsed.scheme != "https" and not (self.config.profile == "development" and is_loopback(parsed.hostname)):
            raise PublishOSError("configuration_error", "PublishOS requires HTTPS outside development loopback")
        query = urlencode({"clientId": client_id, "contentRef": content_ref, "days": days})
        path = (parsed.path or "") + API_PATH + "?" + query
        context = ssl.create_default_context() if self.config.verify_tls else ssl._create_unverified_context()
        try:
            connection: HTTPConnection
            if parsed.scheme == "https":
                connection = HTTPSConnection(parsed.hostname, parsed.port, timeout=self.config.timeout_seconds, context=context)
            else:
                connection = HTTPConnection(parsed.hostname, parsed.port, timeout=self.config.timeout_seconds)
            connection.request("GET", path, headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"})
            response = connection.getresponse()
            return self._response(response)
        except (OSError, socket.timeout, ssl.SSLError) as exc:
            raise PublishOSError("network_error", "PublishOS request failed") from exc

    @staticmethod
    def _response(response: HTTPResponse) -> object:
        status = response.status
        if status != 200:
            code = {401: "authentication_error", 403: "authorization_error", 404: "not_found", 429: "rate_limited"}.get(status, "server_error" if status >= 500 else "http_error")
            raise PublishOSError(code, f"PublishOS returned HTTP {status}", status=status)
        content_type = response.getheader("Content-Type", "")
        if "json" not in content_type.lower():
            raise PublishOSError("content_type_error", "PublishOS response is not JSON")
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise PublishOSError("response_too_large", "PublishOS response exceeds size limit")
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PublishOSError("invalid_json", "PublishOS response is invalid JSON") from exc
