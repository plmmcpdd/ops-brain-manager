"""Configuration and secret loading; neither is stored in the Registry."""
from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .errors import PublishOSError


@dataclass(frozen=True)
class PublishOSConfig:
    profile: str
    base_url: str
    timeout_seconds: int
    verify_tls: bool


@dataclass(frozen=True)
class TokenStatus:
    value: str | None
    source: str


def _profile(value: str | None) -> str:
    result = value or os.environ.get("OPS_BRAIN_PUBLISHOS_PROFILE") or "development"
    if not result.replace("-", "").replace("_", "").isalnum():
        raise PublishOSError("configuration_error", "invalid PublishOS profile")
    return result


def _bool(value: object, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    raise PublishOSError("configuration_error", f"{field} must be boolean")


def _timeout(value: object) -> int:
    if isinstance(value, bool):
        raise PublishOSError("configuration_error", "timeout_seconds must be an integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise PublishOSError("configuration_error", "timeout_seconds must be an integer") from exc
    if not 1 <= result <= 120:
        raise PublishOSError("configuration_error", "timeout_seconds must be between 1 and 120")
    return result


def normalise_base_url(value: object, profile: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PublishOSError("configuration_error", "base_url is required")
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"https", "http"} or not parsed.netloc or parsed.query or parsed.fragment:
        raise PublishOSError("configuration_error", "base_url must be an absolute URL without query or fragment")
    if parsed.username or parsed.password:
        raise PublishOSError("configuration_error", "base_url must not contain credentials")
    if profile == "production" and parsed.scheme != "https":
        raise PublishOSError("configuration_error", "production profile requires HTTPS")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def load_config(manager_root: Path, *, profile: str | None = None, config_path: Path | None = None) -> PublishOSConfig:
    selected_profile = _profile(profile)
    source = config_path or (manager_root / ".ops-brain" / "integrations" / f"publishos.{selected_profile}.json")
    payload: dict[str, object] = {}
    if source.exists():
        try:
            loaded = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PublishOSError("configuration_error", f"cannot read PublishOS configuration: {exc}") from exc
        if not isinstance(loaded, dict) or loaded.get("version") != 1:
            raise PublishOSError("configuration_error", "unsupported PublishOS configuration")
        payload = loaded
    env_base = os.environ.get("OPS_BRAIN_PUBLISHOS_BASE_URL")
    env_timeout = os.environ.get("OPS_BRAIN_PUBLISHOS_TIMEOUT_SECONDS")
    env_tls = os.environ.get("OPS_BRAIN_PUBLISHOS_VERIFY_TLS")
    base = env_base if env_base is not None else payload.get("base_url")
    timeout = env_timeout if env_timeout is not None else payload.get("timeout_seconds", 20)
    tls = env_tls if env_tls is not None else payload.get("verify_tls", True)
    verify_tls = _bool(tls, "verify_tls")
    if selected_profile == "production" and not verify_tls:
        raise PublishOSError("configuration_error", "production profile requires verify_tls=true")
    return PublishOSConfig(selected_profile, normalise_base_url(base, selected_profile), _timeout(timeout), verify_tls)


def load_token(manager_root: Path, profile: str) -> TokenStatus:
    env = os.environ.get("OPS_BRAIN_PUBLISHOS_TOKEN")
    if env is not None:
        token, source = env.strip(), "environment"
    else:
        path = manager_root / ".ops-brain" / "secrets" / f"publishos.{profile}.token"
        if not path.is_file():
            return TokenStatus(None, "missing")
        if os.name == "posix" and path.stat().st_mode & (stat.S_IRGRP | stat.S_IROTH):
            raise PublishOSError("configuration_error", "PublishOS secret file is readable by group or others")
        try:
            token = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise PublishOSError("configuration_error", "cannot read PublishOS secret file") from exc
        source = "file"
    if len(token.encode("utf-8")) < 32:
        raise PublishOSError("configuration_error", "PublishOS token is missing or too short")
    return TokenStatus(token, source)
