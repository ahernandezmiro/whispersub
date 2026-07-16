import sys
import unittest

from src.model_registry import valid_model_names, validate_model_name


class ModelTests(unittest.TestCase):
    def test_turbo_is_supported(self):
        self.assertIn("turbo", valid_model_names())
        self.assertEqual(validate_model_name("turbo"), "turbo")

    def test_custom_faster_whisper_model_is_supported(self):
        custom = "org/custom-faster-whisper-model"
        self.assertEqual(validate_model_name(custom), custom)

    def test_blank_model_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_model_name("  ")

    def test_transcription_module_does_not_eagerly_import_ml_stack(self):
        __import__("src.transcription")
        self.assertNotIn("stable_whisper", sys.modules)


if __name__ == "__main__":
    unittest.main()
