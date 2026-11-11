"""The HUD prefers English when a station sends a Spanish track first."""

import os
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
LUA = os.path.join(ROOT, "player", "scripts", "tv_hud.lua")


def _audio_source() -> str:
    with open(LUA, encoding="utf-8") as f:
        src = f.read()
    start = src.index("local AUDIO_NAMES")
    end = src.index("\nlocal function cycle_audio")
    text = src[start:end]
    for name in (
        "audios_for_program", "audio_for_program", "next_audio", "audio_label",
        "audio_option", "hint_controls",
    ):
        text = text.replace(f"local function {name}", f"function {name}", 1)
    return text


HARNESS = r"""
%s

local function fail(msg)
    io.stderr:write(msg .. "\n")
    os.exit(1)
end

local tracks = {
    { id = 2, type = "audio", lang = "spa", ["program-id"] = 2 },
    { id = 5, type = "audio", lang = "eng", ["program-id"] = 2 },
    { id = 7, type = "video", ["program-id"] = 2 },
    { id = 9, type = "audio", lang = "eng", ["program-id"] = 3 },
}
if audio_for_program(tracks, 2) ~= 5 then fail("spanish sap won") end
if audio_for_program(tracks, 3) ~= 9 then fail("other station") end

local only = {
    { id = 1, type = "audio", lang = "spa", ["program-id"] = 4 },
}
if audio_for_program(only, 4) ~= 1 then fail("only spanish") end
if audio_for_program(tracks, 9) ~= nil then fail("missing program") end

local from_eng = next_audio(tracks, 2, 5)
if not from_eng or from_eng.id ~= 2 then fail("cycle left english") end
local from_spa = next_audio(tracks, 2, 2)
if not from_spa or from_spa.id ~= 5 then fail("cycle left spanish") end
if next_audio(only, 4, 1).id ~= 1 then fail("single track moved") end
local lost = next_audio(tracks, 2, 9)
if not lost or lost.id ~= 5 then fail("foreign track should land on english") end
if audio_label(from_eng) ~= "Spanish" then fail("spanish label") end
if audio_label(from_spa) ~= "English" then fail("english label") end
if audio_label({}) ~= "Audio" then fail("blank label") end
if audio_option(tracks, 2, 5) ~= "a Spanish" then fail("hint while english") end
if audio_option(tracks, 2, 2) ~= "a English" then fail("hint while spanish") end
if audio_option(only, 4, 1) ~= nil then fail("single track listed") end
if audio_option(tracks, 3, 9) ~= nil then fail("one track on the other station") end

local function joined(row)
    local parts = {}
    for _, item in ipairs(row) do parts[#parts + 1] = item[1] .. " " .. item[2] end
    return table.concat(parts, " | ")
end
local move, set = hint_controls({ volume = 130 })
if joined(move) ~= "j k Channel | Space Pause | ← → 10s | ↑ ↓ 1 min" then
    fail("live move " .. joined(move))
end
if joined(set) ~= "c Captions | r Record | l Live | m Vol 130" then
    fail("live set " .. joined(set))
end
move, set = hint_controls({ paused = true, recording = true, other = "Spanish", volume = 130 })
if joined(move) ~= "j k Channel | Space Play | ← → 10s | ↑ ↓ 1 min" then
    fail("paused move " .. joined(move))
end
if joined(set) ~= "a Spanish | c Captions | r Stop | y Save | l Live | m Vol 130" then
    fail("paused set " .. joined(set))
end
move, set = hint_controls({ library = true, muted = true, volume = 130 })
if joined(move) ~= "Space Pause | ← → 10s | ↑ ↓ 1 min | PgUp Ads" then
    fail("library move " .. joined(move))
end
if joined(set) ~= "c Captions | l Live | m Muted" then
    fail("library set " .. joined(set))
end
"""


class TestHudAudio(unittest.TestCase):
    def test_english_beats_the_first_sap(self):
        script = HARNESS % _audio_source()
        res = subprocess.run(["luajit", "-e", script], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr or res.stdout)


if __name__ == "__main__":
    unittest.main()
