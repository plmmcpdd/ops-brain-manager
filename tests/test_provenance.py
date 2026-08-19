import json
import tempfile
import unittest
from pathlib import Path

from ops_brain_provenance import build_attestation, content_identity


class ProvenanceTests(unittest.TestCase):
    def test_content_identity_excludes_secrets_and_is_stable(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "SKILL.md").write_text("public", encoding="utf-8")
            (root / ".env").write_text("SECRET=one", encoding="utf-8")
            first = content_identity(root)
            (root / ".env").write_text("SECRET=two", encoding="utf-8")
            second = content_identity(root)
            self.assertEqual(first, second)
            self.assertEqual(first[1], 1)

    def test_attestation_is_honest_about_copied_install(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            install = root / "skill"
            install.mkdir()
            (install / "SKILL.md").write_text("name: test", encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"capabilities": [{"id": "doctor", "install_location": str(install), "source": "https://example.invalid/doctor.git", "pinned_commit": "abc"}]}), encoding="utf-8")
            result = build_attestation(manifest, "doctor")
            self.assertEqual(result["declared_pinned_commit"], "abc")
            self.assertEqual(result["git_identity_status"], "DECLARED_UNVERIFIED_INSTALLED_COPY")
            self.assertNotIn("SECRET", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
