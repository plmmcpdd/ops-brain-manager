import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AuthorityContractTests(unittest.TestCase):
    def setUp(self):
        self.contract = json.loads((ROOT / "runtime" / "authority-contract.json").read_text(encoding="utf-8"))
        self.core = (ROOT / "runtime" / "ops-brain-runtime" / "agents" / "ops-brain-core.md").read_text(encoding="utf-8")
        self.doctor = (ROOT / "runtime" / "ops-brain-runtime" / "agents" / "doctor-evidence.md").read_text(encoding="utf-8")
        self.launcher = (ROOT / "windows-entry" / "launcher" / "launch_ops_agent.sh").read_text(encoding="utf-8")

    def test_cheat_is_primary_and_client_workspace_owns_state(self):
        primary = self.contract["primary"]
        self.assertEqual(primary["id"], "xbuilderlab-cheat-on-content")
        self.assertTrue(primary["final_authority"])
        self.assertEqual(primary["state_owner"], "client-workspace")

    def test_all_collision_operations_are_core_owned(self):
        expected = {"benchmark", "next-post", "topic-selection", "draft-adoption", "account-diagnosis", "viral-decomposition", "status", "retrospective", "trends"}
        self.assertEqual(set(self.contract["primary"]["owned_operations"]), expected)

    def test_doctor_is_nonfinal_stateless_provider(self):
        provider = self.contract["providers"]["social-account-doctor"]
        self.assertFalse(provider["final_authority"])
        self.assertFalse(provider["state_write"])
        self.assertEqual(provider["return_to"], self.contract["primary"]["id"])
        self.assertIn("final_authority: false", self.doctor)
        self.assertIn("Return only to the parent Core agent", self.doctor)

    def test_launcher_isolates_global_skills_and_selects_primary_agent(self):
        self.assertIn('"--setting-sources", "project"', self.launcher)
        self.assertIn('"--plugin-dir"', self.launcher)
        self.assertIn('"--agent"', self.launcher)
        self.assertIn("ops-brain-runtime:ops-brain-core", self.launcher)
        self.assertNotIn("--disable-slash-commands", self.launcher)

    def test_core_requires_doctor_return_before_final_judgment(self):
        self.assertIn("Invoke the `ops-brain-runtime:doctor-evidence` agent", self.core)
        self.assertIn("through the Agent tool", self.core)
        self.assertIn("Resume the relevant Cheat protocol", self.core)
        self.assertIn("You own the user-facing final answer", self.core)
        self.assertIn("Never let the Doctor rediscover or guess a client path", self.core)

    def test_doctor_cannot_discover_client_or_skill_paths(self):
        self.assertIn("Never scan or discover Skills", self.doctor)
        self.assertIn("Never guess a client path", self.doctor)
        self.assertIn("Do not open client Cheat state", self.doctor)
        self.assertIn("immediately return an unavailable result", self.doctor)

    def test_missing_state_policy_is_fail_closed(self):
        self.assertEqual(self.contract["missing_state"], "fail-closed")
        self.assertIn("OPS_BRAIN_RUNTIME_NOT_READY", self.core)


if __name__ == "__main__":
    unittest.main()
