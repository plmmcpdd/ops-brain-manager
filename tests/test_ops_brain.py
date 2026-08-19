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
from ops_brain_runtime import RuntimeProfile, initialize_runtime
from ops_brain_publishos.config import load_config, load_token
from ops_brain_publishos.contract import validate_response
from ops_brain_publishos.errors import PublishOSError
from ops_brain_publishos.storage import write_normalized
from ops_brain_publishos.report import write_report
from ops_brain_publishos.sync import is_due, pending_content_refs


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.registry = self.root / "registry.json"

    def tearDown(self):
        self.temp.cleanup()

    def args(self, **values):
        return SimpleNamespace(registry=self.registry, **values)

    def initialize_workspace(self, workspace):
        return initialize_runtime(
            workspace,
            Path("/home/rong/tools/cheat-on-content"),
            RuntimeProfile("short-text", None, 2, "manual", "none", "none", True),
        )

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
        self.initialize_workspace(workspace)
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
        self.initialize_workspace(workspace)
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
        with self.assertRaisesRegex(ops_brain.RegistryError, "workspace does not exist"):
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
        self.initialize_workspace(workspace)
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

    def test_create_json_creates_once_and_emits_one_pure_object(self):
        workspace = self.root / "json-created"
        output, errors = io.StringIO(), io.StringIO()
        with patch("ops_brain.save_registry", wraps=ops_brain.save_registry) as save, redirect_stdout(output), patch("sys.stderr", errors):
            exit_code = ops_brain.main(["--registry", str(self.registry), "create", "--name", "JSON Client", "--workspace", str(workspace), "--json"])
        self.assertEqual(exit_code, 0)
        save.assert_called_once()
        raw = output.getvalue()
        self.assertEqual(len(raw.splitlines()), 1)
        payload = json.loads(raw)
        self.assertEqual(payload, {"ok": True, "code": "ok", "data": {"client_id": "json-client", "display_name": "JSON Client", "workspace": ops_brain.canonical_path(workspace), "status": "active", "origin": "created"}, "error": None})
        self.assertEqual(errors.getvalue(), "")
        self.assertTrue(workspace.is_dir())
        self.assertEqual(len(ops_brain.load_registry(self.registry)["clients"]), 1)
        self.assertNotIn("已创建", raw)
        self.assertNotIn("directory_created", raw)

    def test_attach_json_commits_once_and_emits_one_pure_object(self):
        workspace = self.root / "json-attached"
        workspace.mkdir()
        output, errors = io.StringIO(), io.StringIO()
        with patch("ops_brain.save_registry", wraps=ops_brain.save_registry) as save, redirect_stdout(output), patch("sys.stderr", errors):
            exit_code = ops_brain.main(["--registry", str(self.registry), "attach", "--name", "Attached Client", "--workspace", str(workspace), "--json"])
        self.assertEqual(exit_code, 0)
        save.assert_called_once()
        raw = output.getvalue()
        self.assertEqual(len(raw.splitlines()), 1)
        payload = json.loads(raw)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["origin"], "attached")
        self.assertEqual(payload["data"]["workspace"], ops_brain.canonical_path(workspace))
        self.assertEqual(errors.getvalue(), "")
        self.assertEqual(len(ops_brain.load_registry(self.registry)["clients"]), 1)
        self.assertNotIn("已挂接", raw)

    def test_duplicate_create_json_is_valid_error_without_second_mutation(self):
        first = self.root / "first"
        second = self.root / "second"
        self.assertEqual(ops_brain.main(["--registry", str(self.registry), "create", "--name", "Duplicate", "--workspace", str(first), "--json"]), 0)
        before = self.registry.read_bytes()
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), patch("sys.stderr", errors):
            exit_code = ops_brain.main(["--registry", str(self.registry), "create", "--name", "Duplicate", "--workspace", str(second), "--json"])
        self.assertNotEqual(exit_code, 0)
        payload = json.loads(output.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["code"], "registry_error")
        self.assertIsNone(payload["data"])
        self.assertTrue(payload["error"])
        self.assertEqual(before, self.registry.read_bytes())
        self.assertFalse(second.exists())
        self.assertEqual(len(ops_brain.load_registry(self.registry)["clients"]), 1)
        self.assertNotEqual(errors.getvalue(), "")

    def test_attach_conflict_json_is_valid_error_without_mutation(self):
        workspace = self.root / "attached"
        workspace.mkdir()
        self.assertEqual(ops_brain.main(["--registry", str(self.registry), "attach", "--name", "First", "--workspace", str(workspace), "--json"]), 0)
        before = self.registry.read_bytes()
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), patch("sys.stderr", errors):
            exit_code = ops_brain.main(["--registry", str(self.registry), "attach", "--name", "Second", "--workspace", str(workspace), "--json"])
        self.assertNotEqual(exit_code, 0)
        payload = json.loads(output.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["code"], "registry_error")
        self.assertIsNone(payload["data"])
        self.assertEqual(before, self.registry.read_bytes())
        self.assertEqual(len(ops_brain.load_registry(self.registry)["clients"]), 1)
        self.assertNotEqual(errors.getvalue(), "")

    def test_create_and_attach_text_mode_remain_human_readable(self):
        created = self.root / "text-created"
        attached = self.root / "text-attached"
        attached.mkdir()
        create_output = io.StringIO()
        with redirect_stdout(create_output):
            self.assertEqual(ops_brain.main(["--registry", str(self.registry), "create", "--name", "Text Create", "--workspace", str(created)]), 0)
        self.assertIn("已创建并登记 Text Create", create_output.getvalue())
        self.assertIn("directory_created=yes; registry_committed=yes", create_output.getvalue())
        attach_output = io.StringIO()
        with redirect_stdout(attach_output):
            self.assertEqual(ops_brain.main(["--registry", str(self.registry), "attach", "--name", "Text Attach", "--workspace", str(attached)]), 0)
        self.assertIn("已挂接 Text Attach", attach_output.getvalue())
        self.assertEqual(len(ops_brain.load_registry(self.registry)["clients"]), 2)

    def test_unicode_client_identity_works_across_manager_read_contracts(self):
        workspace = self.root / "小红书一号测试客户"
        create_output = io.StringIO()
        with redirect_stdout(create_output):
            self.assertEqual(ops_brain.main(["--registry", str(self.registry), "create", "--name", "小红书一号测试客户", "--workspace", str(workspace), "--json"]), 0)
        created = json.loads(create_output.getvalue())["data"]
        self.assertEqual(created["client_id"], "小红书一号测试客户")
        self.assertEqual(created["display_name"], "小红书一号测试客户")
        for arguments in (
            ["list", "--all", "--json"],
            ["show", "--client", "小红书一号测试客户", "--json"],
            ["resolve-launch", "--client", "小红书一号测试客户", "--json"],
            ["doctor", "--json"],
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(ops_brain.main(["--registry", str(self.registry), *arguments]), 0)
            payload = json.loads(output.getvalue())
            self.assertTrue(payload["ok"], arguments)
        self.assertEqual(len(ops_brain.load_registry(self.registry)["clients"]), 1)

    def test_client_id_contract_accepts_unicode_words_and_rejects_unsafe_segments(self):
        expected = {
            "ABC": "abc",
            "123": "123",
            "client_01": "client_01",
            "客户-01": "客户-01",
            "美国移民项目": "美国移民项目",
            "a b": "a-b",
            "a/b": "a-b",
            "a\\b": "a-b",
            "a.b": "a-b",
            "a😀b": "a-b",
            "a\nb": "a-b",
        }
        for source, identifier in expected.items():
            self.assertEqual(ops_brain.client_id(source), identifier)
            self.assertTrue(ops_brain.is_safe_client_id(identifier))
        for unsafe in ("", ".", "..", "../escape", "a/b", "a\\b", "a\nb", "a\rb", "a\x01b", "-leading", "trailing-", "_leading", "trailing_", "😀", "con", "NUL", "com1", "lpt9"):
            self.assertFalse(ops_brain.is_safe_client_id(unsafe), repr(unsafe))

    def test_doctor_and_write_validation_reject_unsafe_stored_client_id(self):
        workspace = self.root / "unsafe"
        workspace.mkdir()
        payload = {"version": 1, "clients": [{"id": "../escape", "name": "Unsafe", "workspace": str(workspace), "status": "active", "origin": "created"}]}
        self.registry.write_text(json.dumps(payload), encoding="utf-8")
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(ops_brain.main(["--registry", str(self.registry), "doctor", "--json"]), 1)
        report = json.loads(output.getvalue())
        self.assertFalse(report["ok"])
        self.assertTrue(any("safe single path segment" in finding for finding in report["data"]["findings"]))
        with self.assertRaisesRegex(ops_brain.RegistryError, "安全的单一路径段"):
            ops_brain.validate_registry_for_write(ops_brain.load_registry(self.registry))


class SharedCapabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.install = self.root / "skill"
        self.manifest = self.root / "manifest.json"

    def tearDown(self):
        self.temp.cleanup()

    def write_manifest(self):
        self.manifest.write_text(json.dumps({"version": 1, "capabilities": [{
            "id": "test-capability", "display_name": "Test capability", "runtime": "claude",
            "install_location": str(self.install), "configuration_file": ".env", "pinned_commit": "abc",
            "executables": [{"id": "python3", "command": "python3"}], "components": [
                {"id": "Data", "required": True, "config_keys": ["DATA_KEY"], "executables": ["python3"]},
                {"id": "Visual", "required": False, "config_keys": ["VISUAL_KEY"], "executables": []},
            ],
        }]}), encoding="utf-8")

    def test_capability_status_is_separate_and_never_exposes_secret_values(self):
        self.write_manifest()
        self.install.mkdir()
        (self.install / "SKILL.md").write_text("name: test", encoding="utf-8")
        secret = "secret-value-must-not-appear"
        (self.install / ".env").write_text(f"DATA_KEY={secret}\n", encoding="utf-8")
        report = ops_brain.capabilities_report(self.manifest)
        self.assertEqual(report["core_health"], "SEPARATE")
        capability = report["capabilities"][0]
        self.assertEqual(capability["status"], "READY")
        self.assertEqual(capability["components"], [
            {"id": "Data", "status": "READY"},
            {"id": "Visual", "status": "OPTIONAL_NOT_CONFIGURED"},
        ])
        self.assertNotIn(secret, json.dumps(report))

    def test_missing_install_is_reported_without_failing_json_command(self):
        self.write_manifest()
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = ops_brain.main(["capabilities", "--manifest", str(self.manifest), "--json"])
        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["core_health"], "SEPARATE")
        self.assertEqual(payload["data"]["capabilities"][0]["status"], "MISSING")

    def test_example_placeholders_are_not_reported_as_configured(self):
        self.write_manifest()
        self.install.mkdir()
        (self.install / "SKILL.md").write_text("name: test", encoding="utf-8")
        (self.install / ".env").write_text(
            "DATA_KEY=your-data-key\nVISUAL_KEY=https://your-vision.example.com/v1\n", encoding="utf-8"
        )
        components = ops_brain.capabilities_report(self.manifest)["capabilities"][0]["components"]
        self.assertEqual(components, [
            {"id": "Data", "status": "NOT_CONFIGURED"},
            {"id": "Visual", "status": "OPTIONAL_NOT_CONFIGURED"},
        ])

    def test_optional_degraded_transport_is_visible_without_degrading_capability(self):
        self.write_manifest()
        data = json.loads(self.manifest.read_text(encoding="utf-8"))
        data["capabilities"][0]["components"].append({
            "id": "MCP", "required": False, "config_keys": [], "executables": [],
            "status_override": "DEGRADED",
        })
        self.manifest.write_text(json.dumps(data), encoding="utf-8")
        self.install.mkdir()
        (self.install / "SKILL.md").write_text("name: test", encoding="utf-8")
        (self.install / ".env").write_text("DATA_KEY=configured\n", encoding="utf-8")
        capability = ops_brain.capabilities_report(self.manifest)["capabilities"][0]
        self.assertEqual(capability["status"], "READY")
        self.assertIn({"id": "MCP", "status": "DEGRADED"}, capability["components"])


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


class PublishOSBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.registry = self.root / "registry.json"
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        ops_brain.attach(SimpleNamespace(registry=self.registry, name="Test Client", workspace=str(self.workspace)))

    def tearDown(self):
        self.temp.cleanup()

    def _payload(self):
        return {"schemaVersion": "publishos.ops-brain.performance.v1", "generatedAt": "2026-01-01T00:00:00Z", "clientId": "pub-test", "content": {"id": "content-id", "contentRef": "2026-01-01_test", "title": "Test", "status": "published"}, "collection": {"status": "success", "lastAttemptAt": None, "lastSuccessAt": None, "reauthorizationRequired": False, "errorCode": None, "errorMessage": None}, "latestTotals": {"views": 1, "likes": 2, "comments": 3, "shares": 4, "saves": None, "reach": None, "impressions": None, "engagementRate": 0.1}, "posts": [], "availability": {"views": "available"}, "unknown": "ignored"}

    def test_link_unlink_and_duplicate_protection(self):
        args = SimpleNamespace(registry=self.registry, client="Test Client", publishos_client_id="pub-test")
        self.assertEqual(ops_brain.publishos_link(args), 0)
        self.assertEqual(ops_brain._publishos_mapping(ops_brain.load_registry(self.registry)["clients"][0]), "pub-test")
        second = self.root / "second"
        second.mkdir()
        ops_brain.attach(SimpleNamespace(registry=self.registry, name="Second", workspace=str(second)))
        with self.assertRaises(ops_brain.RegistryError):
            ops_brain.publishos_link(SimpleNamespace(registry=self.registry, client="Second", publishos_client_id="pub-test"))
        self.assertEqual(ops_brain.publishos_unlink(SimpleNamespace(registry=self.registry, client="Test Client")), 0)
        self.assertNotIn("integrations", ops_brain.load_registry(self.registry)["clients"][0])

    def test_config_token_and_contract_redaction(self):
        config_dir = self.root / ".ops-brain" / "integrations"
        config_dir.mkdir(parents=True)
        (config_dir / "publishos.development.json").write_text(json.dumps({"version": 1, "base_url": "http://127.0.0.1:4567/", "timeout_seconds": 20, "verify_tls": True}), encoding="utf-8")
        self.assertEqual(load_config(self.root).base_url, "http://127.0.0.1:4567")
        with patch.dict(os.environ, {"OPS_BRAIN_PUBLISHOS_TOKEN": "T" * 32}, clear=False):
            token = load_token(self.root, "development")
        self.assertEqual(token.source, "environment")
        normalized = validate_response(self._payload(), "pub-test", "2026-01-01_test")
        self.assertNotIn("unknown", normalized)
        self.assertEqual(normalized["content"]["id"], "content-id")
        bad = self._payload()
        bad["latestTotals"]["views"] = True
        with self.assertRaisesRegex(PublishOSError, "finite number"):
            validate_response(bad, "pub-test", "2026-01-01_test")

    def test_normalized_storage_is_idempotent(self):
        normalized = validate_response(self._payload(), "pub-test", "2026-01-01_test")
        digest, changed, latest = write_normalized(self.workspace, "2026-01-01_test", normalized)
        self.assertTrue(changed)
        mtime = latest.stat().st_mtime_ns
        second, changed, latest = write_normalized(self.workspace, "2026-01-01_test", normalized)
        self.assertEqual(digest, second)
        self.assertFalse(changed)
        self.assertEqual(mtime, latest.stat().st_mtime_ns)

    def test_pending_due_and_managed_report_preservation(self):
        predictions = self.workspace / "predictions"
        video = self.workspace / "videos" / "2026-01-01_test"
        predictions.mkdir()
        video.mkdir(parents=True)
        prediction = predictions / "2026-01-01_test.md"
        prediction.write_text("Published at: 2026-01-01T00:00:00Z\n", encoding="utf-8")
        (self.workspace / ".cheat-state.json").write_text(json.dumps({"pending_retros": ["predictions/2026-01-01_test.md"]}), encoding="utf-8")
        self.assertEqual(pending_content_refs(self.workspace), ["2026-01-01_test"])
        self.assertTrue(is_due(self.workspace, "2026-01-01_test", 3))
        normalized = validate_response(self._payload(), "pub-test", "2026-01-01_test")
        self.assertTrue(write_report(self.workspace, "2026-01-01_test", normalized))
        report = video / "report.md"
        report.write_text(report.read_text(encoding="utf-8") + "A manual note\n", encoding="utf-8")
        self.assertTrue(write_report(self.workspace, "2026-01-01_test", normalized))
        self.assertIn("A manual note", report.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
