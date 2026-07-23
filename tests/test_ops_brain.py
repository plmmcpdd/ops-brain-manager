import hashlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import ops_brain


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.registry = self.root / "registry.json"

    def tearDown(self):
        self.temp.cleanup()

    def args(self, **values):
        return SimpleNamespace(registry=self.registry, **values)

    def test_create_makes_empty_directory_and_record_without_git(self):
        workspace = self.root / "new-parent" / "created"
        with patch("ops_brain.subprocess.run") as git_run:
            self.assertEqual(ops_brain.create(self.args(name="客户甲", workspace=str(workspace))), 0)
        git_run.assert_not_called()
        self.assertTrue(workspace.is_dir())
        self.assertEqual(list(workspace.iterdir()), [])
        client = ops_brain.load_registry(self.registry)["clients"][0]
        self.assertEqual(client["origin"], "created")

    def test_create_workspace_root_uses_manager_client_id(self):
        root = self.root / "clients"
        self.assertEqual(ops_brain.main(["--registry", str(self.registry), "create", "--name", "客户 A", "--workspace-root", str(root)]), 0)
        client = ops_brain.load_registry(self.registry)["clients"][0]
        self.assertEqual(client["workspace"], ops_brain.canonical_path(root / "客户-a"))

    def test_attach_does_not_modify_external_directory(self):
        workspace = self.root / "external"
        workspace.mkdir()
        marker = workspace / "keep.txt"
        marker.write_text("unchanged", encoding="utf-8")
        before = (sorted(path.name for path in workspace.iterdir()), marker.read_text(encoding="utf-8"))
        ops_brain.attach(self.args(name="客户甲", workspace=str(workspace)))
        self.assertEqual(before, (sorted(path.name for path in workspace.iterdir()), marker.read_text(encoding="utf-8")))
        self.assertEqual(ops_brain.load_registry(self.registry)["clients"][0]["origin"], "attached")

    def test_same_and_symlink_alias_paths_cannot_be_reused(self):
        workspace = self.root / "client"
        workspace.mkdir()
        data = ops_brain.new_registry()
        ops_brain.add_client(data, "客户甲", str(workspace), "attached")
        with self.assertRaisesRegex(ops_brain.RegistryError, "冲突"):
            ops_brain.add_client(data, "客户乙", str(workspace), "attached")
        alias = self.root / "alias"
        alias.symlink_to(workspace, target_is_directory=True)
        with self.assertRaisesRegex(ops_brain.RegistryError, "冲突"):
            ops_brain.add_client(data, "客户丙", str(alias), "attached")

    def test_attach_rejects_child_and_parent_workspace_paths(self):
        parent = self.root / "parent"
        child = parent / "child"
        child.mkdir(parents=True)
        ops_brain.attach(self.args(name="父客户", workspace=str(parent)))
        with self.assertRaisesRegex(ops_brain.RegistryError, "父子目录"):
            ops_brain.attach(self.args(name="子客户", workspace=str(child)))

        reverse_registry = self.root / "reverse.json"
        ops_brain.attach(SimpleNamespace(registry=reverse_registry, name="子客户", workspace=str(child)))
        with self.assertRaisesRegex(ops_brain.RegistryError, "父子目录"):
            ops_brain.attach(SimpleNamespace(registry=reverse_registry, name="父客户", workspace=str(parent)))

    def test_create_and_archived_customer_reject_containment(self):
        parent = self.root / "parent"
        parent.mkdir()
        ops_brain.attach(self.args(name="父客户", workspace=str(parent)))
        child = parent / "new-child"
        with self.assertRaisesRegex(ops_brain.RegistryError, "父子目录"):
            ops_brain.create(self.args(name="子客户", workspace=str(child)))
        self.assertFalse(child.exists())
        ops_brain.change_status(self.args(client="父客户"), "archived")
        existing_child = parent / "existing-child"
        existing_child.mkdir()
        with self.assertRaisesRegex(ops_brain.RegistryError, "包括归档客户"):
            ops_brain.attach(self.args(name="归档冲突", workspace=str(existing_child)))

    def test_symlink_child_containment_is_rejected(self):
        parent = self.root / "parent"
        child = parent / "child"
        child.mkdir(parents=True)
        alias = self.root / "parent-alias"
        alias.symlink_to(parent, target_is_directory=True)
        ops_brain.attach(self.args(name="父客户", workspace=str(parent)))
        with self.assertRaisesRegex(ops_brain.RegistryError, "父子目录"):
            ops_brain.attach(self.args(name="符号链接子客户", workspace=str(alias / "child")))

    def test_archived_path_stays_reserved_archive_keeps_directory_and_restore_works(self):
        workspace = self.root / "client"
        workspace.mkdir()
        ops_brain.attach(self.args(name="客户甲", workspace=str(workspace)))
        self.assertEqual(ops_brain.change_status(self.args(client="客户甲"), "archived"), 0)
        self.assertTrue(workspace.is_dir())
        data = ops_brain.load_registry(self.registry)
        with self.assertRaisesRegex(ops_brain.RegistryError, "包括归档"):
            ops_brain.add_client(data, "客户乙", str(workspace), "created")
        self.assertEqual(ops_brain.change_status(self.args(client="客户甲"), "active"), 0)
        self.assertEqual(ops_brain.load_registry(self.registry)["clients"][0]["status"], "active")

    def test_open_default_prints_commands_without_starting_process(self):
        workspace = self.root / "space name"
        workspace.mkdir()
        ops_brain.attach(self.args(name="客户甲", workspace=str(workspace)))
        output = io.StringIO()
        with patch("ops_brain.subprocess.Popen") as popen, redirect_stdout(output):
            self.assertEqual(ops_brain.open_workspace(self.args(client="客户甲", app=None)), 0)
        popen.assert_not_called()
        self.assertIn("cd ", output.getvalue())
        self.assertIn("claude-deepseek", output.getvalue())

    def test_open_explicit_failure_does_not_change_registry(self):
        workspace = self.root / "client"
        workspace.mkdir()
        ops_brain.attach(self.args(name="客户甲", workspace=str(workspace)))
        before = self.registry.read_bytes()
        with patch("ops_brain.subprocess.Popen", side_effect=OSError("missing")):
            with self.assertRaises(ops_brain.RegistryError):
                ops_brain.open_workspace(self.args(client="客户甲", app="not-installed"))
        self.assertEqual(before, self.registry.read_bytes())

    def test_open_fails_when_registered_workspace_has_been_deleted(self):
        workspace = self.root / "client"
        workspace.mkdir()
        ops_brain.attach(self.args(name="客户甲", workspace=str(workspace)))
        workspace.rmdir()
        with self.assertRaisesRegex(ops_brain.RegistryError, "已不存在"):
            ops_brain.open_workspace(self.args(client="客户甲", app=None))

    def test_create_rejects_an_existing_regular_file(self):
        target = self.root / "not-a-directory"
        target.write_text("file", encoding="utf-8")
        with self.assertRaisesRegex(ops_brain.RegistryError, "创建目标必须不存在或为空目录"):
            ops_brain.create(self.args(name="客户甲", workspace=str(target)))
        self.assertEqual(target.read_text(encoding="utf-8"), "file")

    def test_legacy_is_preserved_without_inference(self):
        old_workspace = self.root / "old"
        old_workspace.mkdir()
        legacy = {"version": 1, "clients": [{"id": "old", "name": "Old", "workspace": str(old_workspace), "status": "active"}]}
        self.registry.write_text(json.dumps(legacy), encoding="utf-8")
        loaded = ops_brain.load_registry(self.registry)
        self.assertNotIn("origin", loaded["clients"][0])
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(ops_brain.doctor(self.args()), 1)
        self.assertIn("legacy origin is unknown", output.getvalue())
        self.assertNotIn("origin", json.loads(self.registry.read_text(encoding="utf-8"))["clients"][0])
        second = self.root / "second"
        second.mkdir()
        ops_brain.attach(self.args(name="New", workspace=str(second)))
        preserved = ops_brain.load_registry(self.registry)["clients"][0]
        self.assertEqual({key: preserved[key] for key in ("id", "name", "workspace", "status")}, legacy["clients"][0])
        self.assertNotIn("origin", preserved)

    def test_doctor_reports_archived_reservation_without_failing_a_healthy_registry(self):
        workspace = self.root / "client"
        workspace.mkdir()
        ops_brain.create(self.args(name="客户甲", workspace=str(workspace)))
        ops_brain.change_status(self.args(client="客户甲"), "archived")
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(ops_brain.doctor(self.args()), 0)
        self.assertIn("NOTICE: client[0]: archived workspace remains reserved", output.getvalue())

    def test_corrupt_registry_fails_closed_and_is_not_overwritten(self):
        self.registry.write_text("{not json", encoding="utf-8")
        original = self.registry.read_bytes()
        with self.assertRaises(ops_brain.RegistryError):
            ops_brain.create(self.args(name="客户甲", workspace=str(self.root / "client")))
        self.assertEqual(original, self.registry.read_bytes())
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(ops_brain.doctor(self.args()), 2)

    def test_doctor_returns_two_for_wrong_version_or_missing_clients(self):
        for payload in ({"version": 99, "clients": []}, {"version": 1}):
            self.registry.write_text(json.dumps(payload), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(ops_brain.doctor(self.args()), 2)

    def test_atomic_write_uses_temporary_file_and_preserves_old_file_on_replace_failure(self):
        self.registry.write_text('{"old": true}\n', encoding="utf-8")
        original = self.registry.read_bytes()
        with patch("ops_brain.os.replace", side_effect=OSError("replace failed")) as replace:
            with self.assertRaises(OSError):
                ops_brain.save_registry(self.registry, ops_brain.new_registry())
        temporary, destination = replace.call_args.args
        self.assertEqual(Path(destination), self.registry)
        self.assertEqual(Path(temporary).parent, self.registry.parent)
        self.assertEqual(original, self.registry.read_bytes())

    def test_create_rolls_back_new_empty_directory_when_registry_write_fails(self):
        workspace = self.root / "new-client"
        with patch("ops_brain.save_registry", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(ops_brain.RegistryError, "directory_created=yes; rollback=completed; registry_committed=no"):
                ops_brain.create(self.args(name="客户甲", workspace=str(workspace)))
        self.assertFalse(workspace.exists())
        self.assertFalse(self.registry.exists())

    def test_create_never_deletes_preexisting_empty_directory_on_write_failure(self):
        workspace = self.root / "existing"
        workspace.mkdir()
        with patch("ops_brain.save_registry", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(ops_brain.RegistryError, "directory_created=no; rollback=not-needed; registry_committed=no"):
                ops_brain.create(self.args(name="客户甲", workspace=str(workspace)))
        self.assertTrue(workspace.is_dir())
        self.assertEqual(list(workspace.iterdir()), [])

    def test_doctor_finds_invalid_paths_attached_state_and_upstream_containment(self):
        attached = self.root / "attached"
        attached.mkdir()
        alias = self.root / "alias"
        alias.symlink_to(attached, target_is_directory=True)
        upstream = self.root / "runtime"
        upstream.mkdir()
        bad = {
            "version": 1,
            "clients": [
                {"id": "a", "name": "A", "workspace": str(attached), "status": "active", "origin": "attached"},
                {"id": "b", "name": "B", "workspace": str(alias), "status": "archived", "origin": "created"},
                {"id": "c", "name": "C", "workspace": "relative", "status": "active", "origin": "created"},
                {"id": "d", "name": "D", "workspace": str(upstream / "inside"), "status": "active", "origin": "created"},
            ],
        }
        self.registry.write_text(json.dumps(bad), encoding="utf-8")
        output = io.StringIO()
        with patch("ops_brain.UPSTREAM_RUNTIME", upstream), redirect_stdout(output):
            self.assertEqual(ops_brain.doctor(self.args()), 1)
        report = output.getvalue()
        self.assertIn("missing .cheat-state.json", report)
        self.assertIn("symlink alias", report)
        self.assertIn("not absolute", report)
        self.assertIn("containment relationship", report)
        self.assertIn("archived workspace remains reserved", report)

    def test_doctor_reports_each_containment_pair_once(self):
        parent = self.root / "parent"
        child = parent / "child"
        child.mkdir(parents=True)
        data = {
            "version": 1,
            "clients": [
                {"id": "parent", "name": "Parent", "workspace": str(parent), "status": "active", "origin": "created"},
                {"id": "child", "name": "Child", "workspace": str(child), "status": "active", "origin": "created"},
            ],
        }
        self.registry.write_text(json.dumps(data), encoding="utf-8")
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(ops_brain.doctor(self.args()), 1)
        conflicts = [line for line in output.getvalue().splitlines() if "conflicts with" in line]
        self.assertEqual(len(conflicts), 1)
        self.assertIn("Parent", conflicts[0])
        self.assertIn("Child", conflicts[0])

    def test_json_contract_is_single_ascii_object_and_resolve_launch_is_read_only(self):
        workspace = self.root / "客户 工作区"
        workspace.mkdir()
        ops_brain.attach(self.args(name="中文 客户", workspace=str(workspace)))
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), patch("sys.stderr", errors):
            self.assertEqual(ops_brain.main(["--registry", str(self.registry), "list", "--json"]), 0)
        raw = output.getvalue()
        self.assertTrue(raw.endswith("\n"))
        self.assertTrue(raw[:-1].isascii())
        self.assertEqual(errors.getvalue(), "")
        self.assertEqual(json.loads(raw)["data"]["clients"][0]["display_name"], "中文 客户")
        before = self.registry.read_bytes()
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(ops_brain.main(["--registry", str(self.registry), "resolve-launch", "--client", "中文 客户", "--json"]), 0)
        resolved = json.loads(output.getvalue())["data"]
        self.assertTrue(resolved["launch_allowed"])
        self.assertTrue(resolved["workspace_exists"])
        self.assertEqual(before, self.registry.read_bytes())

    def test_json_doctor_failure_keeps_stdout_json_only(self):
        self.registry.write_text("{broken", encoding="utf-8")
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), patch("sys.stderr", errors):
            self.assertEqual(ops_brain.main(["--registry", str(self.registry), "doctor", "--json"]), 2)
        self.assertTrue(output.getvalue()[:-1].isascii())
        self.assertFalse(json.loads(output.getvalue())["ok"])
        self.assertNotEqual(errors.getvalue(), "")


class ExternalIntegrityTests(unittest.TestCase):
    UPSTREAM = Path("/home/rong/tools/cheat-on-content")
    HVAC = Path("/home/rong/projects/content-ops-lab/hvac-demo")
    HASHES = {
        ".cheat-state.json": "4855bb26490e3b563f2d361b80a2b226bf12fd4b1c90175916b1a02fd9880f5b",
        "rubric_notes.md": "624f808f5e79dc7d29ce9d16520d244d7c053c490c6ac26c3ddc1544d942cc61",
        ".claude/settings.json": "cc7135569c80cf6effdab058e012af4bd383874757e9195e6c9193b35f1e3b81",
    }

    def test_upstream_and_hvac_remain_at_the_approved_baseline(self):
        for repository in (self.UPSTREAM, self.HVAC):
            status = subprocess.run(["git", "-C", str(repository), "status", "--short"], check=True, text=True, capture_output=True)
            self.assertEqual(status.stdout, "")
        for relative, expected in self.HASHES.items():
            actual = hashlib.sha256((self.HVAC / relative).read_bytes()).hexdigest()
            self.assertEqual(actual, expected, relative)


if __name__ == "__main__":
    unittest.main()
