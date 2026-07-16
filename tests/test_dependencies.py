from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DependencyDeclarationTests(unittest.TestCase):
    def test_faster_whisper_stack_does_not_install_openai_whisper(self):
        requirements = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")

        self.assertIn("stable-ts-whisperless==2.19.1", requirements)
        self.assertIn("faster-whisper==1.2.1", requirements)
        self.assertNotIn("stable-ts[fw]", requirements)
        self.assertNotIn("openai-whisper", requirements)


if __name__ == "__main__":
    unittest.main()
