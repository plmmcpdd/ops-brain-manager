import json
import tempfile
import unittest
from pathlib import Path

from ops_brain_runtime import RuntimeLifecycleError, RuntimeProfile, initialize_runtime, inspect_runtime, repair_runtime


UPSTREAM = Path("/home/rong/tools/cheat-on-content")
PROFILE = RuntimeProfile("short-text", None, 2, "manual", "markdown", "pending", True)


class RuntimeLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / "client"
        self.workspace.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_new_client_initialization_reaches_ready(self):
        before = inspect_runtime(self.workspace)
        self.assertEqual(before["status"], "NOT_INITIALIZED")
        result = initialize_runtime(self.workspace, UPSTREAM, PROFILE)
        self.assertTrue(result["changed"])
        self.assertEqual(result["status"], "READY")
        self.assertEqual(json.loads((self.workspace / ".cheat-state.json").read_text(encoding="utf-8"))["schema_version"], "1.4")

    def test_existing_business_files_are_preserved(self):
        marker = self.workspace / "账号档案.md"
        marker.write_text("business-owned", encoding="utf-8")
        initialize_runtime(self.workspace, UPSTREAM, PROFILE)
        self.assertEqual(marker.read_text(encoding="utf-8"), "business-owned")

    def test_repeated_initialization_is_idempotent(self):
        initialize_runtime(self.workspace, UPSTREAM, PROFILE)
        state_before = (self.workspace / ".cheat-state.json").read_bytes()
        result = initialize_runtime(self.workspace, UPSTREAM, PROFILE)
        self.assertFalse(result["changed"])
        self.assertEqual((self.workspace / ".cheat-state.json").read_bytes(), state_before)

    def test_partial_runtime_refuses_reinitialization(self):
        (self.workspace / "rubric_notes.md").write_text("partial", encoding="utf-8")
        self.assertEqual(inspect_runtime(self.workspace)["status"], "PARTIAL")
        with self.assertRaisesRegex(RuntimeLifecycleError, "PARTIAL"):
            initialize_runtime(self.workspace, UPSTREAM, PROFILE)

    def test_invalid_state_is_explicit(self):
        (self.workspace / ".cheat-state.json").write_text("{broken", encoding="utf-8")
        report = inspect_runtime(self.workspace)
        self.assertEqual(report["status"], "INVALID")
        self.assertIn("invalid state JSON", report["issues"][0])

    def test_repair_restores_missing_generated_file_without_overwrite(self):
        initialize_runtime(self.workspace, UPSTREAM, PROFILE)
        rubric = self.workspace / "rubric_notes.md"
        rubric_before = rubric.read_bytes()
        (self.workspace / "STATUS.md").unlink()
        self.assertEqual(inspect_runtime(self.workspace)["status"], "NEEDS_REPAIR")
        result = repair_runtime(self.workspace, UPSTREAM)
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["repaired"], ["STATUS.md"])
        self.assertEqual(rubric.read_bytes(), rubric_before)

    def test_repair_never_reconstructs_missing_state(self):
        (self.workspace / "STATUS.md").write_text("partial", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeLifecycleError, "no state was reconstructed"):
            repair_runtime(self.workspace, UPSTREAM)

    def test_two_clients_have_isolated_state_and_rubric(self):
        other = self.root / "other"
        other.mkdir()
        initialize_runtime(self.workspace, UPSTREAM, PROFILE)
        initialize_runtime(other, UPSTREAM, PROFILE)
        other_state_before = (other / ".cheat-state.json").read_bytes()
        other_rubric_before = (other / "rubric_notes.md").read_bytes()
        state = json.loads((self.workspace / ".cheat-state.json").read_text(encoding="utf-8"))
        state["calibration_samples"] = 7
        (self.workspace / ".cheat-state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        (self.workspace / "rubric_notes.md").write_text("client-a-only", encoding="utf-8")
        self.assertEqual((other / ".cheat-state.json").read_bytes(), other_state_before)
        self.assertEqual((other / "rubric_notes.md").read_bytes(), other_rubric_before)


if __name__ == "__main__":
    unittest.main()
