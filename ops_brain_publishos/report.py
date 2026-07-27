"""Pure renderer for managed factual Performance reports."""
from __future__ import annotations

from typing import Any

from .errors import PublishOSError
from .storage import atomic_bytes, safe_workspace_path, validate_content_ref

START = "<!-- ops-brain:publishos:start -->"
END = "<!-- ops-brain:publishos:end -->"
MANUAL = "<!-- ops-brain:manual-comments -->"


def render(payload: dict[str, Any], content_ref: str, *, decreased: list[str] | None = None, manual: str = "") -> str:
    lines = ["---", "schema: ops-brain.publishos.report.v1", f"content_ref: {content_ref}", f"generated_at: {payload['generatedAt']}", "---", "", START, "# PublishOS performance facts", "", "## Latest totals"]
    for key, value in payload["latestTotals"].items():
        lines.append(f"- {key}: {value if value is not None else 'unavailable'}")
    if decreased:
        lines += ["", "## Warning", "- metric_decrease_detected: " + ", ".join(decreased), "- Review platform collection history manually; no value was corrected."]
    lines += ["", "## Collection", f"- status: {payload['collection'].get('status')}", f"- reauthorization_required: {payload['collection'].get('reauthorizationRequired')}", "", "## Posts"]
    for post in payload["posts"]:
        lines.append(f"- {post['platform']} / {post['publishedPostId']} ({len(post['snapshots'])} snapshot(s))")
        for snap in post["snapshots"]:
            lines.append(f"  - observed_at: {snap['observedAt']}; views: {snap['views']}")
    lines += [END, "", MANUAL, manual.rstrip(), ""]
    return "\n".join(lines)


def write_report(workspace, content_ref: str, payload: dict[str, Any], *, decreased: list[str] | None = None) -> bool:
    ref = validate_content_ref(content_ref)
    path = safe_workspace_path(workspace, "videos", ref, "report.md")
    manual = ""
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if START not in existing or END not in existing or MANUAL not in existing:
            raise PublishOSError("report_conflict", "report.md is not an Ops Brain managed report")
        manual = existing.split(MANUAL, 1)[1]
    rendered = render(payload, ref, decreased=decreased, manual=manual)
    if path.exists() and path.read_text(encoding="utf-8") == rendered:
        return False
    atomic_bytes(path, rendered.encode("utf-8"))
    return True
