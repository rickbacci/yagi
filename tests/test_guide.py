"""
Unit tests for Omarchy TV - Electronic Program Guide (EPG)
"""

import os
import unittest
import tempfile
from engine.guide import load_guide, save_default_guide, get_channel_program


class TestGuide(unittest.TestCase):
    def test_default_guide_generation(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            guide_file = os.path.join(tmp_dir, "guide.json")
            data = save_default_guide(guide_path=guide_file)
            self.assertTrue(os.path.exists(guide_file))
            self.assertIn("channels", data)
            self.assertIn("3.1", data["channels"])
            self.assertEqual(data["channels"]["3.1"]["network"], "NBC")
            self.assertIn("title", data["channels"]["3.1"])

    def test_get_channel_program(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            guide_file = os.path.join(tmp_dir, "guide.json")
            data = load_guide(guide_path=guide_file)

            # Match by channel number
            nbc_prog = get_channel_program("3.1", guide_data=data)
            self.assertIsNotNone(nbc_prog)
            self.assertEqual(nbc_prog["network"], "NBC")

            # Match by station callsign
            fox_prog = get_channel_program("FOX", guide_data=data)
            self.assertIsNotNone(fox_prog)
            self.assertEqual(fox_prog["network"], "FOX")

            # Match by network
            abc_prog = get_channel_program("ABC", guide_data=data)
            self.assertIsNotNone(abc_prog)
            self.assertEqual(abc_prog["network"], "ABC")


if __name__ == "__main__":
    unittest.main()
