"""Run the HUD's show-on-now pick. It must agree with the flyout's GPS rule."""

import os
import subprocess
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
LUA = os.path.join(ROOT, "player", "scripts", "tv_hud.lua")
GPS_UNIX_OFFSET = 315964800 - 18


def _on_now_source() -> str:
    with open(LUA, encoding="utf-8") as f:
        src = f.read()
    start = src.index("local function parse_clock_minutes")
    end = src.index("\nlocal function guide_for_channel")
    return src[start:end].replace("local function program_on_now", "function program_on_now", 1)


HARNESS = r"""
%s

local function fail(msg)
    io.stderr:write(msg .. "\n")
    os.exit(1)
end

local now = os.time()
local gps_now = now - %d

-- Clock labels say the late show; the broadcast times say the news. GPS wins.
local row = { programs = {
    { title = "Late Show", start = "1:00 AM", ["end"] = "1:00 PM" },
    { title = "Evening News", gps_start = gps_now - 600, duration_sec = 1800 },
    { title = "Next Up", gps_start = gps_now + 1200, duration_sec = 1800 },
} }
local pick = program_on_now(row)
if not pick or pick.title ~= "Evening News" then
    fail("gps pick got " .. tostring(pick and pick.title))
end

-- Dated listings with nothing on now: no show, not a clock guess.
local ended = { programs = {
    { title = "Over", gps_start = gps_now - 7200, duration_sec = 1800 },
} }
if program_on_now(ended) ~= nil then fail("ended listing still on") end
"""


class TestHudOnNow(unittest.TestCase):
    def test_broadcast_start_time_wins(self):
        script = HARNESS % (_on_now_source(), GPS_UNIX_OFFSET)
        res = subprocess.run(["luajit", "-e", script], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr or res.stdout)


if __name__ == "__main__":
    unittest.main()
