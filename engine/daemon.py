"""
Omarchy TV - Core Daemon & Local IPC Server
Exposes JSON-RPC / socket API for Quickshell UI and CLI tools.
"""

import os
import sys
import json
import time
import socket
import threading
from typing import Dict, Any, Optional
from engine.tuner import TunerManager
from engine.scanner import AtscScanner
from engine.paths import DAEMON_SOCKET_PATH, CHANNELS_JSON_PATH
from player.controller import MpvController


class TvDaemon:
    def __init__(self, socket_path: str = DAEMON_SOCKET_PATH):
        self.socket_path = socket_path
        self.running = False
        self.server_sock: Optional[socket.socket] = None
        self.player = MpvController()
        self.scanner = AtscScanner()
        self.active_scan_thread: Optional[threading.Thread] = None
        self.last_scan_progress: Dict[str, Any] = {"status": "idle", "percent": 0}

    def start(self):
        self.running = True
        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass

        self.server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server_sock.bind(self.socket_path)
        self.server_sock.listen(5)
        print(f"[omarchy-tv-daemon] Listening on {self.socket_path}")

        while self.running:
            try:
                conn, _ = self.server_sock.accept()
                client_thread = threading.Thread(target=self._handle_client, args=(conn,))
                client_thread.daemon = True
                client_thread.start()
            except Exception as e:
                if not self.running:
                    break
                print(f"[omarchy-tv-daemon] accept error: {e}")

    def _handle_client(self, conn: socket.socket):
        conn.settimeout(30.0)
        try:
            data = conn.recv(8192).decode("utf-8")
            if not data:
                return

            req = json.loads(data.strip())
            cmd = req.get("command", "")
            args = req.get("args", {})

            res = self._dispatch(cmd, args)
            conn.sendall((json.dumps(res) + "\n").encode("utf-8"))
        except Exception as e:
            err_res = {"error": str(e), "success": False}
            try:
                conn.sendall((json.dumps(err_res) + "\n").encode("utf-8"))
            except Exception:
                pass
        finally:
            conn.close()

    def _dispatch(self, cmd: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if cmd == "status":
            tuners = [t.to_dict() for t in TunerManager.list_tuners()]
            channels = self._load_channels()
            return {
                "success": True,
                "tuners": tuners,
                "player_running": self.player.is_running(),
                "total_channels": len(channels),
                "scan_progress": self.last_scan_progress
            }

        elif cmd == "channels":
            return {
                "success": True,
                "channels": self._load_channels()
            }

        elif cmd == "tune":
            channel_name = args.get("channel", "")
            success = self.player.tune(channel_name)
            return {"success": success, "channel": channel_name}

        elif cmd == "channel_up":
            self.player.channel_up()
            return {"success": True}

        elif cmd == "channel_down":
            self.player.channel_down()
            return {"success": True}

        elif cmd == "stop_player":
            self.player.stop()
            return {"success": True}

        elif cmd == "scan":
            quick = args.get("quick", True)
            if self.active_scan_thread and self.active_scan_thread.is_alive():
                return {"success": False, "error": "Scan already in progress"}

            def _run_scan():
                for event in self.scanner.scan(quick_mode=quick):
                    self.last_scan_progress = event

            self.active_scan_thread = threading.Thread(target=_run_scan)
            self.active_scan_thread.daemon = True
            self.active_scan_thread.start()
            return {"success": True, "message": "Scan started in background"}

        elif cmd == "scan_status":
            return {
                "success": True,
                "progress": self.last_scan_progress
            }

        return {"success": False, "error": f"Unknown command: {cmd}"}

    def _load_channels(self):
        if os.path.exists(CHANNELS_JSON_PATH):
            try:
                with open(CHANNELS_JSON_PATH, "r", encoding="utf-8") as f:
                    return json.load(f).get("channels", [])
            except Exception:
                pass
        return []

    def stop(self):
        self.running = False
        if self.server_sock:
            self.server_sock.close()
        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass


def send_daemon_request(cmd: str, args: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Helper for CLI and client scripts to talk to daemon."""
    if not os.path.exists(DAEMON_SOCKET_PATH):
        return None
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(5.0)
        s.connect(DAEMON_SOCKET_PATH)
        payload = json.dumps({"command": cmd, "args": args or {}}) + "\n"
        s.sendall(payload.encode("utf-8"))
        res = s.recv(16384).decode("utf-8")
        s.close()
        return json.loads(res.strip())
    except Exception:
        return None


if __name__ == "__main__":
    daemon = TvDaemon()
    try:
        daemon.start()
    except KeyboardInterrupt:
        daemon.stop()
