"""Run the HUD's signal rule: silent when good, a badge when weak or lost."""

import os
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
LUA = os.path.join(ROOT, "player", "scripts", "tv_hud.lua")


def _signal_source() -> str:
    with open(LUA, encoding="utf-8") as f:
        src = f.read()
    start = src.index("local signal_busy = false")
    end = src.index("local function poll_signal")
    return src[start:end]


HARNESS = r"""
local badge = { data = "" }
function badge:update() end
local hud_visible = false
local blanking = false
local signal_label = ""
local signal_bgr = ""
local theme = { urgent = "&H3333F0&", warn = "&H30C0F0&" }
local update_badge
local function picture_ready() return true end
local function is_library_playback() return false end
local function render_hud() end

%s

local function fail(msg)
    io.stderr:write(msg .. "\n")
    os.exit(1)
end

note_reading(31)
if signal_label ~= "" or badge.data ~= "" then fail("good signal shows something") end
note_reading(22)
note_reading(22)
if signal_label ~= "" then fail("22 dB is a good picture") end

note_reading(16)
if signal_label ~= "" then fail("one weak reading shows") end
note_reading(16)
if signal_label ~= "Weak signal" then fail("two weak readings: " .. signal_label) end
if not badge.data:find("Weak signal", 1, true) then fail("no badge while the HUD is hidden") end
if not badge.data:find("30C0F0", 1, true) then fail("weak is not amber") end

note_reading(18.5)
if signal_label ~= "Weak signal" then fail("18.5 dB cleared it; needs 19") end
note_reading(20)
if signal_label ~= "" or badge.data ~= "" then fail("good again still shows") end

note_reading(nil)
note_reading(nil)
if signal_label ~= "No signal" then fail("lost: " .. signal_label) end
if not badge.data:find("3333F0", 1, true) then fail("lost is not red") end

hud_visible = true
update_badge()
if badge.data ~= "" then fail("badge stays while the HUD is up") end
"""


class TestHudSignal(unittest.TestCase):
    def test_good_is_silent_weak_and_lost_show(self):
        script = HARNESS % _signal_source()
        res = subprocess.run(["luajit", "-e", script], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr or res.stdout)


if __name__ == "__main__":
    unittest.main()
