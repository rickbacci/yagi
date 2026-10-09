import json
import os
import socket
import struct
import tempfile
import threading
import time
import unittest

from engine import tower_dump
from engine.timeshift import Timeshift
from engine.tower_dump import TowerDump


class FakeTuner:
    def __init__(self, lock=True):
        self.lock = lock
        self.events = []
        self.chunks = []

    def tune(self, freq, timeout):
        self.events.append(("tune", freq))
        return self.lock

    def start(self):
        self.events.append("start")

    def stop(self):
        self.events.append("stop")

    def drain(self):
        self.events.append("drain")

    def read(self):
        return self.chunks.pop(0) if self.chunks else b""

    def fileno(self):
        return -1

    def snr(self):
        return 223

    def close(self):
        self.events.append("close")


class TestTowerDumpBytes(unittest.TestCase):
    def test_a_property_is_76_packed_bytes(self):
        raw = tower_dump.dtv_property(tower_dump.DTV_FREQUENCY, 551028615)
        self.assertEqual(len(raw), 76)
        self.assertEqual(struct.unpack_from("<I", raw, 0)[0], tower_dump.DTV_FREQUENCY)
        self.assertEqual(struct.unpack_from("<I", raw, 16)[0], 551028615)

    def test_atsc_tune_is_8vsb_on_that_frequency_then_tune(self):
        props = tower_dump.atsc_props(503028615)
        self.assertIn((tower_dump.DTV_DELIVERY_SYSTEM, tower_dump.SYS_ATSC), props)
        self.assertIn((tower_dump.DTV_FREQUENCY, 503028615), props)
        self.assertIn((tower_dump.DTV_MODULATION, tower_dump.VSB_8), props)
        self.assertEqual(props[-1][0], tower_dump.DTV_TUNE)

    def test_filter_takes_every_pid_to_the_dvr(self):
        pid, source, output, kind, flags = struct.unpack("<HxxiiiI", tower_dump.whole_tower_filter())
        self.assertEqual(pid, 0x2000)
        self.assertEqual(source, tower_dump.DMX_IN_FRONTEND)
        self.assertEqual(output, tower_dump.DMX_OUT_TS_TAP)
        self.assertEqual(kind, tower_dump.DMX_PES_OTHER)
        self.assertEqual(flags, 0)

    def test_ioctl_numbers(self):
        self.assertEqual(tower_dump.FE_SET_PROPERTY, 0x40106F52)
        self.assertEqual(tower_dump.DMX_SET_PES_FILTER, 0x40146F2C)
        self.assertEqual(tower_dump.DMX_START, 0x6F29)
        self.assertEqual(tower_dump.DMX_STOP, 0x6F2A)


class TestTowerDump(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dest = os.path.join(self.tmp.name, "live.ts")
        self.log = os.path.join(self.tmp.name, "dump.log")
        self.tuner = FakeTuner()
        self.dump = TowerDump(self.tuner, self.dest, self.log)

    def tearDown(self):
        self.dump.close()
        self.tmp.cleanup()

    def size(self):
        return os.path.getsize(self.dest)

    def test_start_locks_then_writes_what_the_tower_sends(self):
        self.assertTrue(self.dump.start(551028615))
        self.assertEqual(self.tuner.events, [("tune", 551028615), "start"])
        self.tuner.chunks = [b"\x47" * 376]
        self.assertEqual(self.dump.pump(), 376)
        self.assertEqual(self.size(), 376)

    def test_start_without_lock_fails(self):
        self.tuner.lock = False
        self.assertFalse(self.dump.start(551028615))
        self.assertNotIn("start", self.tuner.events)

    def test_tune_restarts_the_file_on_the_new_tower(self):
        self.dump.start(551028615)
        self.tuner.chunks = [b"\x47" * 188 * 10]
        self.dump.pump()
        self.tuner.events.clear()
        reply = self.dump.handle(["tune", 503028615])
        self.assertEqual(reply, {"error": "success", "data": {"mark": 0}})
        self.assertEqual(self.size(), 0)
        self.assertEqual(self.tuner.events, ["stop", "drain", ("tune", 503028615), "drain", "start"])
        self.tuner.chunks = [b"\x47" * 188]
        self.dump.pump()
        self.assertEqual(self.size(), 188)

    def test_tune_without_lock_says_so(self):
        self.dump.start(551028615)
        self.tuner.lock = False
        self.assertEqual(self.dump.handle(["tune", 503028615]), {"error": "no lock"})

    def test_bad_commands(self):
        self.assertEqual(self.dump.handle(["tune"]), {"error": "invalid parameter"})
        self.assertEqual(self.dump.handle(["dvbin-prog", "FOX"]), {"error": "unknown command"})

    def test_quit_stops_the_loop(self):
        self.assertTrue(self.dump.running)
        self.assertEqual(self.dump.handle(["quit"]), {"error": "success"})
        self.assertFalse(self.dump.running)

    def test_signal_lines_read_back_as_tenths_of_a_db(self):
        self.dump.note_signal()
        self.assertEqual(Timeshift._snr_db_from_log(self.log), 22.3)

    def test_socket_answers_one_json_line_per_command(self):
        sock_path = os.path.join(self.tmp.name, "dump.sock")
        self.dump.start(551028615)
        thread = threading.Thread(target=self.dump.serve, args=(sock_path, 0.05), daemon=True)
        thread.start()
        deadline = time.time() + 2
        while not os.path.exists(sock_path) and time.time() < deadline:
            time.sleep(0.01)

        def ask(command):
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(2)
                s.connect(sock_path)
                s.sendall((json.dumps({"command": command}) + "\n").encode())
                return json.loads(s.recv(4096).decode().split("\n")[0])

        self.assertEqual(ask(["tune", 479028615])["data"], {"mark": 0})
        self.assertEqual(ask(["quit"]), {"error": "success"})
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertFalse(os.path.exists(sock_path))
        self.assertEqual(oct(os.stat(self.dest).st_mode & 0o777), "0o600")


if __name__ == "__main__":
    unittest.main()
