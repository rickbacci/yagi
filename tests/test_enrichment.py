"""
Unit tests for Omarchy TV - Channel Metadata Enrichment & Station Mapping
"""

import unittest
from engine.enrichment import enrich_channel, enrich_and_sort_channels, match_channel


class TestEnrichment(unittest.TestCase):
    def test_enrich_known_stations(self):
        # NBC 3.1 (WKYC)
        wkyc_raw = {"name": "WKYC-HD", "raw_name": "WKYC-HD", "frequency": 503028615, "service_id": 1}
        wkyc_enriched = enrich_channel(wkyc_raw)
        self.assertEqual(wkyc_enriched["channel_number"], "3.1")
        self.assertEqual(wkyc_enriched["major"], 3)
        self.assertEqual(wkyc_enriched["minor"], 1)
        self.assertEqual(wkyc_enriched["network"], "NBC")
        self.assertEqual(wkyc_enriched["callsign"], "WKYC")
        self.assertEqual(wkyc_enriched["kind"], "network")

        grit = enrich_channel({"name": "GRIT", "raw_name": "GRIT", "frequency": 479028615, "service_id": 4})
        self.assertEqual(grit["kind"], "movies")
        kids = enrich_channel({"name": "KIDS", "raw_name": "KIDS", "frequency": 599028615, "service_id": 7})
        self.assertEqual(kids["kind"], "kids")
        shop = enrich_channel({"name": "HSN", "raw_name": "HSN", "frequency": 479028615, "service_id": 7})
        self.assertEqual(shop["kind"], "shop")

        # ABC 5.1 (WEWS)
        wews_raw = {"name": "WEWSHD", "raw_name": "WEWSHD", "frequency": 479028615, "service_id": 3}
        wews_enriched = enrich_channel(wews_raw)
        self.assertEqual(wews_enriched["channel_number"], "5.1")
        self.assertEqual(wews_enriched["network"], "ABC")
        self.assertEqual(wews_enriched["callsign"], "WEWS")

        # FOX 8.1 (WJW)
        fox_raw = {"name": "FOX", "raw_name": "FOX", "frequency": 183028615, "service_id": 3}
        fox_enriched = enrich_channel(fox_raw)
        self.assertEqual(fox_enriched["channel_number"], "8.1")
        self.assertEqual(fox_enriched["network"], "FOX")

        # CBS 19.1 (WOIO)
        woio_raw = {"name": "WOIO-HD", "raw_name": "WOIO-HD", "frequency": 195028615, "service_id": 2}
        woio_enriched = enrich_channel(woio_raw)
        self.assertEqual(woio_enriched["channel_number"], "19.1")
        self.assertEqual(woio_enriched["network"], "CBS")
        self.assertFalse(woio_enriched.get("is_translator"))

        # CBS 19.10 translator / DRT duplicate
        drt_raw = {"name": "WOIO-HD", "raw_name": "WOIO-HD", "frequency": 509028615, "service_id": 4}
        drt_enriched = enrich_channel(drt_raw)
        self.assertEqual(drt_enriched["channel_number"], "19.10")
        self.assertTrue(drt_enriched["is_translator"])
        self.assertEqual(drt_enriched["callsign"], "WOIO-DRT")

        # CW 43.1 (WUAB)
        wuab_raw = {"name": "WUAB", "raw_name": "WUAB", "frequency": 195028615, "service_id": 4}
        wuab_enriched = enrich_channel(wuab_raw)
        self.assertEqual(wuab_enriched["channel_number"], "43.1")
        self.assertEqual(wuab_enriched["network"], "CW")

        # CW 55.1 (WBNX)
        wbnx_raw = {"name": "WBNX-HD", "raw_name": "WBNX-HD", "frequency": 183028615, "service_id": 7}
        wbnx_enriched = enrich_channel(wbnx_raw)
        self.assertEqual(wbnx_enriched["channel_number"], "55.1")
        self.assertEqual(wbnx_enriched["network"], "CW")

    def test_enrich_and_sort_channels(self):
        raw_list = [
            {"name": "WBNX-HD", "frequency": 183028615, "service_id": 7},  # 55.1
            {"name": "WKYC-HD", "frequency": 503028615, "service_id": 1},  # 3.1
            {"name": "WUAB", "frequency": 195028615, "service_id": 4},     # 43.1
            {"name": "WEWSHD", "frequency": 479028615, "service_id": 3},   # 5.1
            {"name": "FOX", "frequency": 183028615, "service_id": 3},      # 8.1
        ]
        sorted_list = enrich_and_sort_channels(raw_list)
        channel_numbers = [c["channel_number"] for c in sorted_list]
        self.assertEqual(channel_numbers, ["3.1", "5.1", "8.1", "43.1", "55.1"])

    def test_match_channel_by_various_queries(self):
        channels = enrich_and_sort_channels([
            {"name": "WKYC-HD", "frequency": 503028615, "service_id": 1},
            {"name": "WEWSHD", "frequency": 479028615, "service_id": 3},
            {"name": "FOX", "frequency": 183028615, "service_id": 3},
            {"name": "WUAB", "frequency": 195028615, "service_id": 4},
            {"name": "WBNX-HD", "frequency": 183028615, "service_id": 7},
        ])

        # By channel number string
        self.assertEqual(match_channel("3.1", channels)["callsign"], "WKYC")
        self.assertEqual(match_channel("5.1", channels)["callsign"], "WEWS")
        self.assertEqual(match_channel("8.1", channels)["callsign"], "WJW")
        self.assertEqual(match_channel("43.1", channels)["callsign"], "WUAB")
        self.assertEqual(match_channel("55.1", channels)["callsign"], "WBNX")

        # By integer channel number
        self.assertEqual(match_channel("3", channels)["callsign"], "WKYC")
        self.assertEqual(match_channel("5", channels)["callsign"], "WEWS")
        self.assertEqual(match_channel("8", channels)["callsign"], "WJW")
        self.assertEqual(match_channel("43", channels)["callsign"], "WUAB")
        self.assertEqual(match_channel("55", channels)["callsign"], "WBNX")

        # By network name
        self.assertEqual(match_channel("NBC", channels)["callsign"], "WKYC")
        self.assertEqual(match_channel("ABC", channels)["callsign"], "WEWS")
        self.assertEqual(match_channel("FOX", channels)["callsign"], "WJW")
        self.assertEqual(match_channel("CW", channels)["callsign"], "WUAB")

        # By raw name
        self.assertEqual(match_channel("WKYC-HD", channels)["channel_number"], "3.1")
        self.assertEqual(match_channel("WEWSHD", channels)["channel_number"], "5.1")


if __name__ == "__main__":
    unittest.main()
