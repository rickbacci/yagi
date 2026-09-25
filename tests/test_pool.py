"""Two tuners, one pool: who gets which tuner, and when the Guide gives way."""

import os
import tempfile
import unittest
from unittest import mock

from engine import pool


class TestPick(unittest.TestCase):
    def test_nothing_on_keeps_the_old_split(self):
        self.assertEqual(pool.pick_live({}), 0)
        self.assertEqual(pool.pick_work({}), 1)

    def test_live_keeps_its_tuner_on_a_channel_change(self):
        self.assertEqual(pool.pick_live({1: "live", 0: "record"}), 1)

    def test_live_takes_whichever_tuner_is_free(self):
        self.assertEqual(pool.pick_live({0: "record"}), 1)
        self.assertEqual(pool.pick_live({1: "record"}), 0)

    def test_live_takes_a_guide_tuner_when_nothing_else_is_free(self):
        self.assertEqual(pool.pick_live({0: "record", 1: "guide"}), 1)

    def test_both_recording_asks_you(self):
        with self.assertRaises(pool.BothTunersBusy):
            pool.pick_live({0: "record", 1: "record"})
        with self.assertRaises(pool.BothTunersBusy):
            pool.pick_live({0: "record", 1: "scan"})

    def test_work_uses_tuner_0_when_you_are_not_watching(self):
        self.assertEqual(pool.pick_work({1: "record"}), 0)
        self.assertIsNone(pool.pick_work({1: "record", 0: "live"}))

    def test_work_waits_on_a_guide_tuner_only_when_asked(self):
        self.assertEqual(pool.pick_work({1: "guide", 0: "live"}), 1)
        self.assertIsNone(pool.pick_work({1: "guide", 0: "live"}, wait_for_guide=False))

    def test_free_count(self):
        self.assertEqual(pool.free_count({}), 2)
        self.assertEqual(pool.free_count({1: "guide"}), 1)


class TestYield(unittest.TestCase):
    def test_guide_yields_only_its_own_tuner(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("XDG_RUNTIME_DIR")) as d:
            with mock.patch.object(pool, "YIELD_PATH", os.path.join(d, "yield")):
                self.assertFalse(pool.guide_must_yield(1))
                pool.ask_guide_to_yield(1)
                self.assertTrue(pool.guide_must_yield(1))
                self.assertFalse(pool.guide_must_yield(0))
                pool.clear_yield()
                self.assertFalse(pool.guide_must_yield(1))


class TestGuideTakesAFreeTuner(unittest.TestCase):
    def test_guide_runs_on_tuner_0_while_1_records(self):
        from engine.psip import _guide_tuner

        with mock.patch("engine.pool.claims", return_value={1: "record"}):
            self.assertEqual(_guide_tuner(None, None), 0)
        with mock.patch("engine.pool.claims", return_value={1: "record", 0: "live"}):
            self.assertIsNone(_guide_tuner(None, None))
        with mock.patch("engine.pool.claims", return_value={0: "guide"}):
            self.assertEqual(_guide_tuner(None, None), 1)


if __name__ == "__main__":
    unittest.main()
