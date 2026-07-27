"""Strict allow-list validation and normalization of Performance API data."""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from .errors import PublishOSError

SCHEMA_VERSION = "publishos.ops-brain.performance.v1"
NUMERIC = (int, float)


def _iso(value: Any, name: str, *, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise PublishOSError("contract_error", f"{name} must be an ISO 8601 string")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PublishOSError("contract_error", f"{name} must be an ISO 8601 string") from exc
    return value


def _number(value: Any, name: str) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, NUMERIC) or not math.isfinite(value):
        raise PublishOSError("contract_error", f"{name} must be a finite number or null")
    return value


def _string(value: Any, name: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value:
        raise PublishOSError("contract_error", f"{name} must be a non-empty string")
    return value


def validate_response(payload: Any, expected_client_id: str, expected_content_ref: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise PublishOSError("contract_error", "response must be an object")
    if payload.get("schemaVersion") != SCHEMA_VERSION:
        raise PublishOSError("unsupported_schema", "unsupported PublishOS schemaVersion")
    client_id = _string(payload.get("clientId"), "clientId")
    if client_id != expected_client_id:
        raise PublishOSError("tenant_mismatch", "response clientId does not match Registry mapping")
    content = payload.get("content")
    if not isinstance(content, dict):
        raise PublishOSError("contract_error", "content must be an object")
    content_ref = _string(content.get("contentRef"), "content.contentRef")
    if content_ref != expected_content_ref:
        raise PublishOSError("content_mismatch", "response contentRef does not match request")
    collection = payload.get("collection")
    totals = payload.get("latestTotals")
    availability = payload.get("availability")
    posts = payload.get("posts")
    if not isinstance(collection, dict) or not isinstance(totals, dict) or not isinstance(availability, dict) or not isinstance(posts, list):
        raise PublishOSError("contract_error", "collection, latestTotals, availability, and posts are required")
    metrics = ("views", "likes", "comments", "shares", "saves", "reach", "impressions", "engagementRate", "completionRate", "averageWatchTime")
    normal_posts: list[dict[str, Any]] = []
    for index, post in enumerate(posts):
        if not isinstance(post, dict) or not isinstance(post.get("snapshots"), list):
            raise PublishOSError("contract_error", f"posts[{index}] is invalid")
        snapshots: list[dict[str, Any]] = []
        for snap_index, snap in enumerate(post["snapshots"]):
            if not isinstance(snap, dict):
                raise PublishOSError("contract_error", f"posts[{index}].snapshots[{snap_index}] is invalid")
            normalized = {"observedAt": _iso(snap.get("observedAt"), "snapshot.observedAt"), "collectedAt": _iso(snap.get("collectedAt"), "snapshot.collectedAt")}
            for key in metrics:
                normalized[key] = _number(snap.get(key), f"snapshot.{key}")
            for key in ("source", "rawResponseHash"):
                normalized[key] = _string(snap.get(key), f"snapshot.{key}", nullable=True)
            snapshots.append(normalized)
        normal_posts.append({
            "publishedPostId": _string(post.get("publishedPostId"), "post.publishedPostId"),
            "platform": _string(post.get("platform"), "post.platform"),
            "platformPostId": _string(post.get("platformPostId"), "post.platformPostId", nullable=True),
            "platformPostUrl": _string(post.get("platformPostUrl"), "post.platformPostUrl", nullable=True),
            "publishedAt": _iso(post.get("publishedAt"), "post.publishedAt", required=False),
            "status": _string(post.get("status"), "post.status", nullable=True),
            "snapshots": snapshots,
        })
    normalized_totals = {key: _number(totals.get(key), f"latestTotals.{key}") for key in metrics[:8]}
    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": _iso(payload.get("generatedAt"), "generatedAt"),
        "clientId": client_id,
        "content": {"id": _string(content.get("id"), "content.id"), "contentRef": content_ref, "title": _string(content.get("title"), "content.title", nullable=True), "status": _string(content.get("status"), "content.status", nullable=True)},
        "collection": {key: collection.get(key) for key in ("status", "lastAttemptAt", "lastSuccessAt", "reauthorizationRequired", "errorCode", "errorMessage")},
        "latestTotals": normalized_totals,
        "posts": normal_posts,
        "availability": {str(key): value for key, value in availability.items() if isinstance(key, str) and isinstance(value, str)},
    }
