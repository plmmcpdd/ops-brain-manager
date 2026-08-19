import json
import runpy
import unittest
from pathlib import Path

from ops_brain_provenance import content_identity


ROOT = Path(__file__).resolve().parents[1]
DOCTOR = Path("/home/rong/.claude/skills/social-account-doctor")


class VisualIntegrationTests(unittest.TestCase):
    def test_manifest_declares_complete_visual_environment_contract(self):
        manifest = json.loads((ROOT / "shared-capabilities" / "manifest.json").read_text(encoding="utf-8"))
        doctor = next(item for item in manifest["capabilities"] if item["id"] == "social-account-doctor")
        visual = next(item for item in doctor["components"] if item["id"] == "Visual Analysis")
        self.assertEqual(
            visual["config_keys"],
            ["VIDEO_ANALYSIS_API_KEY", "VIDEO_ANALYSIS_BASE_URL", "VIDEO_ANALYSIS_MODEL_NAME"],
        )

    def test_installed_visual_scripts_have_doubao_api_v3_endpoint_patch(self):
        expected = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
        for name in ("analyze_image", "analyze_video", "ocr_screenshot"):
            namespace = runpy.run_path(str(DOCTOR / "scripts" / f"{name}.py"))
            self.assertEqual(namespace["chat_completions_url"]("https://ark.cn-beijing.volces.com/api/v3"), expected)
            self.assertEqual(namespace["chat_completions_url"]("https://ark.cn-beijing.volces.com/api/v3/"), expected)

    def test_provenance_hash_matches_current_patched_install(self):
        manifest = json.loads((ROOT / "shared-capabilities" / "manifest.json").read_text(encoding="utf-8"))
        doctor = next(item for item in manifest["capabilities"] if item["id"] == "social-account-doctor")
        digest, count = content_identity(DOCTOR)
        self.assertEqual(digest, doctor["expected_installed_content_sha256"])
        self.assertEqual(count, doctor["expected_hashed_file_count"])


if __name__ == "__main__":
    unittest.main()
