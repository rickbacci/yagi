"""Run the HUD behind-clock. A string check does not catch a bad tick."""

import os
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
LUA = os.path.join(ROOT, "player", "scripts", "tv_hud.lua")


def _smooth_clock_source() -> str:
    with open(LUA, encoding="utf-8") as f:
        src = f.read()
    start = src.index("local function smooth_clock")
    end = src.index("\nlocal function timeshift_delay")
    body = src[start:end].replace("local function smooth_clock", "function smooth_clock", 1)
    return body


HARNESS = r"""
clock_shown = nil
clock_tick = nil
clock_raw = nil
clock_jump = nil
clock_jump_until = nil
cached_timeshift = { paused = false }
local now = 0
local paused = false
mp = {
    get_time = function() return now end,
    get_property_bool = function() return paused end,
}

%s

local function fail(msg)
    io.stderr:write(msg .. "\n")
    os.exit(1)
end

local function eq(got, want, msg)
    if got ~= want then
        fail(msg .. " got " .. tostring(got) .. " want " .. tostring(want))
    end
end

-- First sample takes the file.
now = 10
eq(smooth_clock(30), 30, "open")

-- Pause counts one wall second. A file that is only a second off does not yank it.
cached_timeshift.paused = true
paused = true
now = 11
eq(smooth_clock(31), 31, "pause tick")

-- Playing does not count up when the file is a second high.
cached_timeshift.paused = false
paused = false
now = 12
eq(smooth_clock(32), 31, "play holds")

-- A real drop of one second steps down by one.
now = 13
eq(smooth_clock(30), 30, "play steps down")

-- A skip snaps.
now = 14
eq(smooth_clock(10), 10, "skip snaps")

-- A right-arrow jump holds until the file is within a second.
clock_jump = 0
clock_jump_until = 17
clock_shown = 0
now = 15
eq(smooth_clock(8), 0, "jump holds")
now = 16
eq(smooth_clock(1), 1, "jump corrects")

-- Right, left, left, right guessed 20 s low; the file never gets there.
clock_jump = 30
clock_jump_until = 22
clock_shown = 30
now = 20
eq(smooth_clock(50), 30, "wrong guess holds")
now = 22
eq(smooth_clock(50), 50, "wrong guess lets go")

-- Paused after that, the count climbs again.
cached_timeshift.paused = true
paused = true
now = 23
eq(smooth_clock(51), 51, "pause climbs after a skip")
now = 24
eq(smooth_clock(52), 52, "pause keeps climbing")
"""


class TestHudClock(unittest.TestCase):
    def test_smooth_clock_ticks_and_snaps(self):
        script = HARNESS % _smooth_clock_source()
        res = subprocess.run(
            ["luajit", "-e", script],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, res.stderr or res.stdout)
