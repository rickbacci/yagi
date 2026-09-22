"""
Unit tests for Omarchy TV - Channel Metadata Enrichment & Station Mapping
"""

import os
import tempfile
import unittest

from engine.enrichment import (
    enrich_and_sort_channels,
    enrich_channel,
    load_station_map,
    match_channel,
    station_map,
)


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLEVELAND_PATH = os.path.join(REPO, "markets", "cleveland.json")
CLEVELAND = load_station_map(CLEVELAND_PATH)


class TestEnrichment(unittest.TestCase):
    def test_cleveland_fixture_maps_known_stations(self):
        self.assertGreaterEqual(len(CLEVELAND), 50)
        wkyc = enrich_channel(
            {"name": "WKYC-HD", "raw_name": "WKYC-HD", "frequency": 503028615, "service_id": 1},
            known=CLEVELAND,
        )
        self.assertEqual(wkyc["channel_number"], "3.1")
        self.assertEqual(wkyc["major"], 3)
        self.assertEqual(wkyc["minor"], 1)
        self.assertEqual(wkyc["network"], "NBC")
        self.assertEqual(wkyc["callsign"], "WKYC")
        self.assertEqual(wkyc["kind"], "network")

        grit = enrich_channel(
            {"name": "GRIT", "raw_name": "GRIT", "frequency": 479028615, "service_id": 4},
            known=CLEVELAND,
        )
        self.assertEqual(grit["kind"], "movies")
        kids = enrich_channel(
            {"name": "KIDS", "raw_name": "KIDS", "frequency": 599028615, "service_id": 7},
            known=CLEVELAND,
        )
        self.assertEqual(kids["kind"], "kids")
        shop = enrich_channel(
            {"name": "HSN", "raw_name": "HSN", "frequency": 479028615, "service_id": 7},
            known=CLEVELAND,
        )
        self.assertEqual(shop["kind"], "shop")

        wews = enrich_channel(
            {"name": "WEWSHD", "raw_name": "WEWSHD", "frequency": 479028615, "service_id": 3},
            known=CLEVELAND,
        )
        self.assertEqual(wews["channel_number"], "5.1")
        self.assertEqual(wews["network"], "ABC")
        self.assertEqual(wews["callsign"], "WEWS")

        fox = enrich_channel(
            {"name": "FOX", "raw_name": "FOX", "frequency": 183028615, "service_id": 3},
            known=CLEVELAND,
        )
        self.assertEqual(fox["channel_number"], "8.1")
        self.assertEqual(fox["network"], "FOX")

        woio = enrich_channel(
            {"name": "WOIO-HD", "raw_name": "WOIO-HD", "frequency": 195028615, "service_id": 2},
            known=CLEVELAND,
        )
        self.assertEqual(woio["channel_number"], "19.1")
        self.assertEqual(woio["network"], "CBS")
        self.assertFalse(woio.get("is_translator"))

        drt = enrich_channel(
            {"name": "WOIO-HD", "raw_name": "WOIO-HD", "frequency": 509028615, "service_id": 4},
            known=CLEVELAND,
        )
        self.assertEqual(drt["channel_number"], "19.10")
        self.assertTrue(drt["is_translator"])
        self.assertEqual(drt["callsign"], "WOIO-DRT")

        wuab = enrich_channel(
            {"name": "WUAB", "raw_name": "WUAB", "frequency": 195028615, "service_id": 4},
            known=CLEVELAND,
        )
        self.assertEqual(wuab["channel_number"], "43.1")
        self.assertEqual(wuab["network"], "CW")

        wbnx = enrich_channel(
            {"name": "WBNX-HD", "raw_name": "WBNX-HD", "frequency": 183028615, "service_id": 7},
            known=CLEVELAND,
        )
        self.assertEqual(wbnx["channel_number"], "55.1")
        self.assertEqual(wbnx["network"], "CW")

    def test_empty_map_uses_name_heuristic(self):
        fox = enrich_channel(
            {"name": "FOX", "raw_name": "FOX", "frequency": 183028615, "service_id": 3},
            known={},
        )
        self.assertEqual(fox["network"], "FOX")
        self.assertNotEqual(fox["channel_number"], "8.1")

    def test_missing_station_map_file_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "station_map.json")
            self.assertEqual(load_station_map(path), {})
            self.assertEqual(station_map(path), {})

    def test_engine_does_not_ship_a_baked_in_rf_map(self):
        src = os.path.join(REPO, "engine", "enrichment.py")
        with open(src, encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("503028615", text)
        self.assertNotIn("KNOWN_STATION_MAP", text)

    def test_enrich_and_sort_channels(self):
        raw_list = [
            {"name": "WBNX-HD", "frequency": 183028615, "service_id": 7},
            {"name": "WKYC-HD", "frequency": 503028615, "service_id": 1},
            {"name": "WUAB", "frequency": 195028615, "service_id": 4},
            {"name": "WEWSHD", "frequency": 479028615, "service_id": 3},
            {"name": "FOX", "frequency": 183028615, "service_id": 3},
        ]
        sorted_list = enrich_and_sort_channels(raw_list, known=CLEVELAND)
        channel_numbers = [c["channel_number"] for c in sorted_list]
        self.assertEqual(channel_numbers, ["3.1", "5.1", "8.1", "43.1", "55.1"])

    def test_match_channel_by_various_queries(self):
        channels = enrich_and_sort_channels(
            [
                {"name": "WKYC-HD", "frequency": 503028615, "service_id": 1},
                {"name": "WEWSHD", "frequency": 479028615, "service_id": 3},
                {"name": "FOX", "frequency": 183028615, "service_id": 3},
                {"name": "WUAB", "frequency": 195028615, "service_id": 4},
                {"name": "WBNX-HD", "frequency": 183028615, "service_id": 7},
            ],
            known=CLEVELAND,
        )

        self.assertEqual(match_channel("3.1", channels)["callsign"], "WKYC")
        self.assertEqual(match_channel("5.1", channels)["callsign"], "WEWS")
        self.assertEqual(match_channel("8.1", channels)["callsign"], "WJW")
        self.assertEqual(match_channel("43.1", channels)["callsign"], "WUAB")
        self.assertEqual(match_channel("55.1", channels)["callsign"], "WBNX")

        self.assertEqual(match_channel("3", channels)["callsign"], "WKYC")
        self.assertEqual(match_channel("5", channels)["callsign"], "WEWS")
        self.assertEqual(match_channel("8", channels)["callsign"], "WJW")
        self.assertEqual(match_channel("43", channels)["callsign"], "WUAB")
        self.assertEqual(match_channel("55", channels)["callsign"], "WBNX")

        self.assertEqual(match_channel("NBC", channels)["callsign"], "WKYC")
        self.assertEqual(match_channel("ABC", channels)["callsign"], "WEWS")
        self.assertEqual(match_channel("FOX", channels)["callsign"], "WJW")
        self.assertEqual(match_channel("CW", channels)["callsign"], "WUAB")

        self.assertEqual(match_channel("WKYC-HD", channels)["channel_number"], "3.1")
        self.assertEqual(match_channel("WEWSHD", channels)["channel_number"], "5.1")


if __name__ == "__main__":
    unittest.main()
