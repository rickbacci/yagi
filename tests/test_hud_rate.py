"""The HUD turns seconds into bytes at the recording's own rate, not the tower's."""

import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
LUA = os.path.join(ROOT, "player", "scripts", "tv_hud.lua")


def _rate_source() -> str:
    with open(LUA, encoding="utf-8") as f:
        src = f.read()
    start = src.index("local function read_sidecar")
    end = src.index("local function align_ts")
    body = src[start:end]
    return body[:body.index("local function virt_update")]


HARNESS = r"""
local ATSC_BPS = 19390000
local PATH = "%s"
local SIDE = nil
local SIZE = 0
mp = { get_property = function(name) if name == "path" then return PATH end return nil end }
utils = { parse_json = function(s) return SIDE end }
local function file_bytes() return SIZE end

%s

local function fail(msg) io.stderr:write(msg .. "\n") os.exit(1) end
local function near(a, b) return math.abs(a - b) < 1 end

SIZE = 450000000
SIDE = { start = 1000, ["end"] = 1000 + 3600, full_mux = false }
if not near(atsc_duration(), 3600) then fail("SD hour reads " .. atsc_duration()) end

lib_side_path = nil
SIDE = { byte_rate = 125000 }
if not near(library_rate(), 125000) then fail("byte_rate ignored") end

lib_side_path = nil
SIDE = { full_mux = true, start = 1, ["end"] = 2 }
if not near(library_rate(), ATSC_BPS / 8) then fail("full mux is not the tower rate") end

-- M*A*S*H started recording 33 s before its listing: open at 23 s.
lib_side_path = nil
SIDE = { start = 1790378949, episodes = { { start_unix = 1790379100 }, { start_unix = 1790378982 } } }
if listed_offset() ~= 23 then fail("episodes open at " .. listed_offset()) end
lib_side_path = nil
SIDE = { start = 1000, listed_start = 1060 }
if listed_offset() ~= 50 then fail("a split episode opens at " .. listed_offset()) end
lib_side_path = nil
SIDE = { start = 1000, listed_start = 1012 }
if listed_offset() ~= 0 then fail("a couple of seconds is not worth a seek") end
lib_side_path = nil
SIDE = { start = 1000, kept_from = "pause" }
if listed_offset() ~= 0 then fail("a saved pause has no listing") end
"""


def _skip_source() -> str:
    with open(LUA, encoding="utf-8") as f:
        src = f.read()
    return src[src.index("-- Same test as Model.isGameTitle"):src.index("local function seek_rel")]


SKIP_HARNESS = r"""
local virt_pos = 0
local seeks = 0
local shown = ""
local SIDE = { title = "M*A*S*H", ads = { {600, 750}, {1500, 1620} } }
mp = {
    get_property = function(name) return "/v/show.ts" end,
    osd_message = function(text) shown = text end,
}
local function library_side() return SIDE end
local function apply_virt_seek() seeks = seeks + 1 end
local function is_library_playback() return true end
local function virt_update() end
local function show_hud() end
local function fmt_clock(sec) return string.format("%%d:%%02d", math.floor(sec / 60), math.floor(sec %% 60)) end

%s

local function fail(msg) io.stderr:write(msg .. "\n") os.exit(1) end

virt_pos = 599
if skip_ads() then fail("skipped before the break") end
virt_pos = 600.3
if not skip_ads() then fail("did not skip into the break") end
if virt_pos ~= 750 or seeks ~= 1 then fail("landed at " .. virt_pos) end
if not shown:find("2:30", 1, true) then fail("osd: " .. shown) end
virt_pos = 740
if skip_ads() then fail("backing up into a skipped break skipped again") end
virt_pos = 1500.5
if not skip_ads() or virt_pos ~= 1620 then fail("second break") end

-- PgUp and PgDn walk the marks without skipping anything on their own.
virt_pos = 100
jump_break(1)
if virt_pos ~= 750 then fail("PgUp from 100 landed at " .. virt_pos) end
jump_break(1)
if virt_pos ~= 1620 then fail("second PgUp landed at " .. virt_pos) end
jump_break(-1)
if virt_pos ~= 1500 then fail("PgDn landed at " .. virt_pos) end
virt_pos = 1500.5
if skip_ads() then fail("PgDn into a break should let it play") end

-- A game only jumps when you press PgUp.
skipped_path = nil
SIDE = { title = "NFL Football", ads = { {600, 750} } }
virt_pos = 600.3
if skip_ads() then fail("a game skipped on its own") end
jump_break(1)
if virt_pos ~= 750 then fail("PgUp in a game landed at " .. virt_pos) end
"""


def _theme_source() -> str:
    with open(LUA, encoding="utf-8") as f:
        src = f.read()
    end = src.index("\nload_theme()\n") + len("\nload_theme()\n")
    return src[src.index("-- ASS colors are &HBBGGRR&"):end]


THEME_HARNESS = r"""
local THEME_COLORS_PATH = "%s"
local STAMP = 1
utils = { file_info = function(p) return { mtime = STAMP } end }

%s

local function fail(msg) io.stderr:write(msg .. "\n") os.exit(1) end
if theme.accent ~= "&H418AD2&" then fail("accent " .. tostring(theme.accent)) end
if theme.bg ~= "&H0D121C&" then fail("bg " .. tostring(theme.bg)) end
if theme.urgent ~= "&H4F5AD6&" then fail("red " .. tostring(theme.urgent)) end
if theme.warn ~= "&H30C0F0&" then fail("a missing key keeps the default: " .. tostring(theme.warn)) end
"""


def _byte_start_source() -> str:
    with open(LUA, encoding="utf-8") as f:
        src = f.read()
    return src[src.index("local function byte_start"):src.index("apply_virt_seek = function")]


@unittest.skipUnless(shutil.which("mpv") and shutil.which("ffmpeg") and shutil.which("lua"), "no mpv, ffmpeg, or lua")
class TestByteSeekInMpv(unittest.TestCase):
    def test_the_seek_option_lands_on_that_byte(self):
        import json
        import socket
        import time

        with tempfile.TemporaryDirectory(dir=os.environ.get("XDG_RUNTIME_DIR")) as d:
            path = os.path.join(d, "show.ts")
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-f", "lavfi", "-i",
                 "testsrc=s=160x120:r=30:d=60", "-c:v", "mpeg2video", "-b:v", "800k", "-minrate", "800k",
                 "-maxrate", "800k", "-bufsize", "400k", "-muxrate", "1000k", "-output_ts_offset", "29000",
                 "-f", "mpegts", path],
                check=True, capture_output=True, timeout=120,
            )
            size = os.path.getsize(path)
            script = os.path.join(d, "t.lua")
            with open(script, "w", encoding="utf-8") as f:
                f.write(_byte_start_source() + f"\nio.write(byte_start({size * 40 // 60}, {size}))\n")
            start = subprocess.run(["lua", script], capture_output=True, text=True, check=True).stdout
            self.assertNotIn("#", start)
            sock = os.path.join(d, "m.sock")
            proc = subprocess.Popen(
                ["mpv", "--no-config", "--vo=null", "--ao=null", "--pause", f"--start={start}",
                 f"--input-ipc-server={sock}", path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            try:
                pos = None
                for _ in range(100):
                    time.sleep(0.1)
                    try:
                        with socket.socket(socket.AF_UNIX) as s:
                            s.connect(sock)
                            s.sendall(b'{"command":["get_property","time-pos"]}\n')
                            pos = json.loads(s.recv(4096).split(b"\n")[0]).get("data")
                    except (OSError, ValueError):
                        continue
                    if pos:
                        break
            finally:
                proc.kill()
                proc.wait()
        self.assertIsNotNone(pos)
        self.assertAlmostEqual(pos, 40, delta=3)


class TestHudRate(unittest.TestCase):
    def test_hud_reads_the_omarchy_theme(self):
        lua = shutil.which("lua") or shutil.which("luajit")
        if not lua:
            self.skipTest("no lua")
        with tempfile.TemporaryDirectory() as d:
            colors = os.path.join(d, "colors.toml")
            with open(colors, "w", encoding="utf-8") as f:
                f.write('mode = "dark"\naccent = "#d28a41"\nbackground = "#1c120d"\nred = "#d65a4f"\n')
            script = os.path.join(d, "t.lua")
            with open(script, "w", encoding="utf-8") as f:
                f.write(THEME_HARNESS % (colors, _theme_source()))
            res = subprocess.run([lua, script], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_skip_ads_once(self):
        lua = shutil.which("lua") or shutil.which("luajit")
        if not lua:
            self.skipTest("no lua")
        with tempfile.TemporaryDirectory() as d:
            script = os.path.join(d, "t.lua")
            with open(script, "w", encoding="utf-8") as f:
                f.write(SKIP_HARNESS % _skip_source())
            res = subprocess.run([lua, script], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_library_rate(self):
        lua = shutil.which("lua") or shutil.which("luajit") or shutil.which("lua5.4")
        if not lua:
            self.skipTest("no lua")
        with tempfile.TemporaryDirectory() as d:
            media = os.path.join(d, "show.ts")
            with open(os.path.join(d, "show.json"), "w", encoding="utf-8") as f:
                f.write("{}")
            script = os.path.join(d, "t.lua")
            with open(script, "w", encoding="utf-8") as f:
                f.write(HARNESS % (media, _rate_source()))
            res = subprocess.run([lua, script], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)


if __name__ == "__main__":
    unittest.main()
