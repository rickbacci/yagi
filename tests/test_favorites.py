"""Favorites are channel numbers, so a main transmitter and its DRT can be starred apart."""

import json
import os
import tempfile
import unittest

from engine.favorites import favorite_key, favorite_label, is_favorite, load_favorites

CHANNELS = [
    {"channel_number": "8.1", "name": "FOX", "tune_name": "FOX", "display_name": "FOX 8"},
    {"channel_number": "19.1", "name": "WOIO-HD", "tune_name": "WOIO-HD", "display_name": "CBS 19 (WOIO)"},
    {"channel_number": "19.10", "name": "WOIO-HD", "tune_name": "WOIO-HD", "display_name": "CBS 19 (DRT)"},
]


class TestFavorites(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"))
        self.favs = os.path.join(self.dir.name, "favorites.json")
        self.chans = os.path.join(self.dir.name, "channels.json")
        with open(self.chans, "w", encoding="utf-8") as f:
            json.dump({"channels": CHANNELS}, f)

    def tearDown(self):
        self.dir.cleanup()

    def _write(self, favs):
        with open(self.favs, "w", encoding="utf-8") as f:
            json.dump(favs, f)

    def test_names_from_before_become_every_number_they_matched(self):
        self._write(["FOX", "WOIO-HD", "8.1"])
        self.assertEqual(load_favorites(self.favs, self.chans), ["8.1", "19.1", "19.10"])
        with open(self.favs, encoding="utf-8") as f:
            self.assertEqual(json.load(f), ["8.1", "19.1", "19.10"])

    def test_a_name_no_channel_has_stays(self):
        self._write(["Quest"])
        self.assertEqual(load_favorites(self.favs, self.chans), ["Quest"])

    def test_a_number_stars_only_its_channel(self):
        self.assertTrue(is_favorite(CHANNELS[2], ["19.10"]))
        self.assertFalse(is_favorite(CHANNELS[1], ["19.10"]))
        self.assertTrue(is_favorite(CHANNELS[1], ["woio-hd"]))

    def test_what_was_typed_becomes_a_number(self):
        self.assertEqual(favorite_key("FOX", self.chans), "8.1")
        self.assertEqual(favorite_key("19.10", self.chans), "19.10")
        self.assertEqual(favorite_label("19.10", self.chans), "19.10 CBS 19 (DRT)")
        self.assertEqual(favorite_label("Quest", self.chans), "'Quest'")


if __name__ == "__main__":
    unittest.main()
