"""CLI play, pause, seek, and live against a fake mpv socket. No tuner."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
CLI_BIN = os.path.join(PROJECT_ROOT, "bin", "omarchy-tv")
PACKET = 188
RATE = 188000
CURSOR = PACKET * 1000
DUMP_BYTES = RATE * 30


class _LineServer:
    def __init__(self, path, on_line):
        self.path = path
        self.on_line = on_line
        self._stop = threading.Event()
        if os.path.exists(path):
            os.unlink(path)
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(path)
        self._server.listen(8)
        self._server.settimeout(0.2)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        try:
            self._server.close()
        except OSError:
            pass
        self._thread.join(timeout=1.5)
        if os.path.exists(self.path):
            try:
                os.unlink(self.path)
            except OSError:
                pass

    def _run(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with conn:
                conn.settimeout(1.0)
                try:
                    data = conn.recv(4096)
                    if data:
                        self.on_line(conn, data.decode("utf-8"))
                except Exception:
                    pass


class TestCliWindow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        config = os.path.join(root, "config", "omarchy", "tv")
        cache = os.path.join(root, "cache")
        runtime = os.path.join(root, "runtime")
        os.makedirs(config, mode=0o700)
        os.makedirs(os.path.join(cache, "omarchy", "tv", "timeshift"), mode=0o700)
        os.makedirs(runtime, mode=0o700)
        os.chmod(runtime, 0o700)
        self.dump = os.path.join(cache, "omarchy", "tv", "timeshift", "live.ts")
        with open(self.dump, "wb") as handle:
            handle.write(b"\x47" + b"\x00" * 187)
            handle.truncate(DUMP_BYTES)
        with open(os.path.join(config, "channels.json"), "w", encoding="utf-8") as handle:
            json.dump({"channels": [{"name": "Quest", "tune_name": "Quest"}]}, handle)
        self.mpv_sock = os.path.join(runtime, "omarchy-tv-mpv.sock")
        self.follow_sock = os.path.join(runtime, "omarchy-tv-follow.sock")
        self.state_path = os.path.join(config, "timeshift_active.json")
        self.mpv_cmds = []
        self.follow_lines = []
        self.mpv = _LineServer(self.mpv_sock, self._on_mpv)
        self.follow = _LineServer(self.follow_sock, self._on_follow)
        self.env = dict(os.environ)
        self.env["XDG_CONFIG_HOME"] = os.path.join(root, "config")
        self.env["XDG_CACHE_HOME"] = cache
        self.env["XDG_RUNTIME_DIR"] = runtime
        self.env["XDG_VIDEOS_DIR"] = os.path.join(root, "Videos")
        fakes = os.path.join(PROJECT_ROOT, "tests", "cli_fakes")
        self.env["PYTHONPATH"] = fakes + os.pathsep + self.env.get("PYTHONPATH", "")
        self._write_state()

    def tearDown(self):
        self._reap_follow()
        self.follow.stop()
        self.mpv.stop()
        self.tmp.cleanup()

    def _write_state(self, **extra):
        state = {
            "view": "delayed",
            "paused": False,
            "skip_busy": False,
            "playhead_byte": CURSOR,
            "mux_bps": RATE,
            "follow_socket": self.follow_sock,
            "follow_pid": 0,
            "pid": 0,
            "channel": "Quest",
            "tune_name": "Quest",
        }
        state.update(extra)
        with open(self.state_path, "w", encoding="utf-8") as handle:
            json.dump(state, handle)

    def _on_mpv(self, conn, line):
        msg = json.loads(line)
        self.mpv_cmds.append(msg.get("command") or [])
        cmd = msg.get("command") or []
        reply = {"error": "success", "request_id": msg.get("request_id")}
        if cmd[:2] == ["get_property", "path"]:
            reply["data"] = "fd://0"
        elif cmd[:2] == ["get_property", "pid"]:
            reply["data"] = 4242
        conn.sendall((json.dumps(reply) + "\n").encode("utf-8"))

    def _on_follow(self, conn, line):
        text = line.strip()
        if text == "POS":
            conn.sendall(f"{CURSOR}\n".encode("utf-8"))
            return
        self.follow_lines.append(text)

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, CLI_BIN, *args],
            capture_output=True,
            text=True,
            env=self.env,
        )

    def _reap_follow(self):
        try:
            with open(self.state_path, encoding="utf-8") as handle:
                pid = int(json.load(handle).get("follow_pid") or 0)
        except (OSError, ValueError, json.JSONDecodeError):
            return
        if pid > 1:
            os.kill(pid, 15)

    def test_pause_freezes_the_cursor(self):
        res = self._run("pause")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("PAUSE", self.follow_lines)
        self.assertIn(["set_property", "pause", True], self.mpv_cmds)
        self.assertNotIn("loadfile", [cmd[0] for cmd in self.mpv_cmds if cmd])

    def test_seek_jumps_ten_seconds(self):
        res = self._run("seek", "10")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn(f"SEEK {CURSOR + 10 * RATE}", self.follow_lines)
        self.assertIn(["drop-buffers"], self.mpv_cmds)
        self.assertNotIn("loadfile", [cmd[0] for cmd in self.mpv_cmds if cmd])

    def test_live_seeks_the_join_point(self):
        res = self._run("live")
        self.assertEqual(res.returncode, 0, res.stderr)
        join = (DUMP_BYTES - 512 * 1024) // PACKET * PACKET
        self.assertIn(f"SEEK {join}", self.follow_lines)
        self.assertIn(["drop-buffers"], self.mpv_cmds)
        self.assertNotIn("loadfile", [cmd[0] for cmd in self.mpv_cmds if cmd])

    def test_play_reopens_the_fifo_on_the_fake_window(self):
        res = self._run("play", "Quest")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn(["script-message", "tv-blank"], self.mpv_cmds)
        self.assertIn(["loadfile", "fd://0", "replace"], self.mpv_cmds)


if __name__ == "__main__":
    unittest.main()
