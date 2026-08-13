#!/usr/bin/env python3
"""Harmless cwd/output and shared-install inheritance smoke."""
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
manifest = json.loads((ROOT / "shared-capabilities" / "manifest.json").read_text(encoding="utf-8"))
skill = Path(manifest["capabilities"][0]["install_location"]).expanduser()
assert (skill / "SKILL.md").is_file()

with tempfile.TemporaryDirectory(prefix="ops-brain-social-doctor-") as temp:
    root = Path(temp)
    workspaces = [root / "client-a", root / "client-b"]
    for workspace in workspaces:
        workspace.mkdir()
        subprocess.run(
            ["python3", str(skill / "scripts" / "analyze_document.py"), "--json", str(ROOT / "README.md")],
            cwd=workspace, check=True, stdout=subprocess.DEVNULL,
        )
        reports = workspace / "reports"
        reports.mkdir()
        (reports / "shared-capability-smoke.json").write_text(
            json.dumps({"skill": str(skill), "cwd": os.getcwd() if False else str(workspace)}), encoding="utf-8"
        )
    assert (workspaces[0] / "reports" / "shared-capability-smoke.json").is_file()
    assert (workspaces[1] / "reports" / "shared-capability-smoke.json").is_file()
    assert not (workspaces[0] / "reports" / "client-b").exists()
    assert not (workspaces[1] / "reports" / "client-a").exists()
    assert not (skill / "reports").exists()
    print("CLIENT_A_OUTPUT=" + str(workspaces[0] / "reports"))
    print("CLIENT_B_OUTPUT=" + str(workspaces[1] / "reports"))
    print("SHARED_SKILL=" + str(skill))
    print("ISOLATION=PASS")
