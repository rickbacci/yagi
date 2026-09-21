-- Omarchy TV - Modern Broadcast Heads-Up Display (Live TV OSD)
-- Replaces retro desktop seekbars with a sleek, glassmorphic TV banner and transport HUD.

local utils = require "mp.utils"

local overlay = mp.create_osd_overlay("ass-events")
overlay.res_x = 1280
overlay.res_y = 720
overlay.z = 10

-- Separate overlay so HUD redraws and file-loaded cannot swallow the LIVE flash.
local live_overlay = mp.create_osd_overlay("ass-events")
live_overlay.res_x = 1280
live_overlay.res_y = 720
live_overlay.z = 40

local hud_visible = false
local hide_timer = nil
local HIDE_DELAY = 3.5
local live_timer = nil
local live_flash_until = 0
local live_blink = true
local pending_live_flash = false
local LIVE_HOLD = 3.0
local LIVE_FLASH_STEP = 0.16
local LIVE_SLACK = 2.5

-- Paths
local xdg_config = os.getenv("XDG_CONFIG_HOME")
if not xdg_config or xdg_config == "" then
    xdg_config = (os.getenv("HOME") or "") .. "/.config"
end
local CHANNELS_PATH = xdg_config .. "/omarchy/tv/channels.json"
local GUIDE_PATH = xdg_config .. "/omarchy/tv/guide.json"
local RECORDINGS_PATH = xdg_config .. "/omarchy/tv/recordings_active.json"
local PLAYER_STATE_PATH = xdg_config .. "/omarchy/tv/player_state.json"
local FAVORITES_PATH = xdg_config .. "/omarchy/tv/favorites.json"
local UI_PREFS_PATH = xdg_config .. "/omarchy/tv/ui_prefs.json"
local TIMESHIFT_ACTIVE_PATH = xdg_config .. "/omarchy/tv/timeshift_active.json"
local xdg_cache = os.getenv("XDG_CACHE_HOME")
if not xdg_cache or xdg_cache == "" then
    xdg_cache = (os.getenv("HOME") or "") .. "/.cache"
end
local TIMESHIFT_DIR = xdg_cache .. "/omarchy/tv/timeshift"

local cached_channels = {}
local cached_guide = {}
local cached_recordings = {}
local cached_favorites = {}
local cached_prefs = {}
local cached_timeshift = {}

local function reload_data()
    -- Load channels.json
    local f_ch = io.open(CHANNELS_PATH, "r")
    if f_ch then
        local content = f_ch:read("*all")
        f_ch:close()
        local data = utils.parse_json(content)
        if data and data.channels then
            cached_channels = data.channels
        end
    end

    -- Load guide.json
    local f_gd = io.open(GUIDE_PATH, "r")
    if f_gd then
        local content = f_gd:read("*all")
        f_gd:close()
        local data = utils.parse_json(content)
        if data and data.channels then
            cached_guide = data.channels
        end
    end

    -- Load recordings_active.json
    cached_recordings = {}
    local f_rec = io.open(RECORDINGS_PATH, "r")
    if f_rec then
        local content = f_rec:read("*all")
        f_rec:close()
        local data = utils.parse_json(content)
        if data and type(data) == "table" then
            cached_recordings = data
        end
    end

    local f_fav = io.open(FAVORITES_PATH, "r")
    if f_fav then
        local content = f_fav:read("*all")
        f_fav:close()
        local data = utils.parse_json(content)
        if type(data) == "table" then
            cached_favorites = data
        end
    end

    local f_prefs = io.open(UI_PREFS_PATH, "r")
    if f_prefs then
        local content = f_prefs:read("*all")
        f_prefs:close()
        local data = utils.parse_json(content)
        if type(data) == "table" then
            cached_prefs = data
        end
    end

    cached_timeshift = {}
    local f_ts = io.open(TIMESHIFT_ACTIVE_PATH, "r")
    if f_ts then
        local content = f_ts:read("*all")
        f_ts:close()
        local data = utils.parse_json(content)
        if type(data) == "table" then
            cached_timeshift = data
        end
    end
end

local function json_escape(s)
    s = tostring(s or "")
    return s:gsub("\\", "\\\\"):gsub('"', '\\"'):gsub("\n", "\\n"):gsub("\r", "\\r")
end

local function timeshift_file_opt()
    local p = mp.get_opt("timeshift-file")
    if p and p ~= "" then return p end
    return nil
end

local function follow_sock_opt()
    local p = mp.get_opt("follow-sock")
    if p and p ~= "" then return p end
    local runtime = os.getenv("XDG_RUNTIME_DIR") or ""
    if runtime ~= "" then
        return runtime .. "/omarchy-tv-follow.sock"
    end
    return nil
end

local function is_file_playback()
    if timeshift_file_opt() then return true end
    local path = mp.get_property("path") or ""
    return path ~= "" and not path:match("^dvb://")
end

local function is_timeshift_playback()
    if timeshift_file_opt() then return true end
    local path = mp.get_property("path") or ""
    if follow_sock_opt() and (path == "-" or path:match("^fd://") or path:match("^fdclose://")) then
        return true
    end
    if path == "" or path:match("^dvb://") then return false end
    return path:sub(1, #TIMESHIFT_DIR) == TIMESHIFT_DIR
        or path:find("/omarchy/tv/timeshift/", 1, true) ~= nil
end

local function is_library_playback()
    return is_file_playback() and not is_timeshift_playback()
end

local function cache_window()
    local st = mp.get_property_native("demuxer-cache-state")
    local pos = mp.get_property_number("time-pos") or 0
    if type(st) == "table" then
        local ranges = st["seekable-ranges"]
        if type(ranges) == "table" and #ranges > 0 then
            local first = ranges[1]
            local last = ranges[#ranges]
            local t0 = tonumber(first.start) or 0
            local t1 = tonumber(last["end"]) or t0
            if t1 > t0 then
                return t0, t1
            end
        end
    end
    local dur = mp.get_property_number("demuxer-cache-duration") or 0
    return math.max(0, pos), pos + math.max(0, dur)
end

local function live_pts()
    local best = 0
    local st = mp.get_property_native("demuxer-cache-state")
    if type(st) == "table" then
        best = math.max(best, tonumber(st["cache-end"]) or 0)
        local ranges = st["seekable-ranges"]
        if type(ranges) == "table" and #ranges > 0 then
            best = math.max(best, tonumber(ranges[#ranges]["end"]) or 0)
        end
    end
    best = math.max(best, mp.get_property_number("duration") or 0)
    best = math.max(best, mp.get_property_number("demuxer-cache-time") or 0)
    local _, t1 = cache_window()
    return math.max(best, t1)
end

local function cache_ahead()
    local d = mp.get_property_number("demuxer-cache-duration")
    if d and d > 0 then return d end
    local pos = mp.get_property_number("time-pos") or 0
    return math.max(0, live_pts() - pos)
end

local function cache_end()
    return live_pts()
end

local function behind_live(slack)
    slack = slack or LIVE_SLACK
    local path = mp.get_property("path") or ""
    if path == "" or not path:match("^dvb://") then return false end
    return cache_ahead() > slack
end

-- ATSC 8VSB transport is ~19.39 Mbps. MPV duration/percent on raw .ts is often 0.
local ATSC_BPS = 19390000
local SEEK_STEP = 15
local virt_pos = 0
local virt_last = nil
local seek_reload = false
local saved_virt = 0

local function tv_cli()
    local cli = mp.get_opt("cli")
    if cli and cli ~= "" then return cli end
    local home = os.getenv("HOME") or ""
    local fallback = home .. "/Projects/personal/omarchy-tv/bin/omarchy-tv"
    local f = io.open(fallback, "r")
    if f then
        f:close()
        return fallback
    end
    return "omarchy-tv"
end

local function file_bytes()
    local path = timeshift_file_opt() or mp.get_property("path") or ""
    if path == "-" or path:match("^fd://") or path:match("^fdclose://") then
        path = timeshift_file_opt() or ""
    end
    local st = path ~= "" and utils.file_info(path)
    if st and st.size and st.size > 0 then
        return st.size
    end
    return mp.get_property_number("file-size") or 0
end

local function atsc_duration()
    local size = file_bytes()
    if size < 1024 then return 0 end
    return (size * 8) / ATSC_BPS
end

local function timeshift_behind(slack)
    slack = slack or LIVE_SLACK
    if not is_timeshift_playback() then return false end
    virt_update()
    local dur = atsc_duration()
    if dur <= 0 then return false end
    return (dur - virt_pos) > slack
end

local function virt_update()
    if not is_file_playback() then
        virt_last = nil
        return virt_pos
    end
    if mp.get_property_bool("pause", false) then
        virt_last = nil
        return virt_pos
    end
    local now = mp.get_time()
    if virt_last then
        virt_pos = virt_pos + (now - virt_last)
    end
    virt_last = now
    return virt_pos
end

local function reset_virt()
    virt_pos = 0
    if mp.get_property_bool("pause", false) then
        virt_last = nil
    else
        virt_last = mp.get_time()
    end
end

local function file_progress()
    virt_update()
    local dur = atsc_duration()
    if dur <= 0 then return 0 end
    return math.max(0, math.min(100, 100 * virt_pos / dur))
end

local function fmt_clock(sec)
    sec = math.max(0, math.floor(tonumber(sec) or 0))
    local m = math.floor(sec / 60)
    local s = sec % 60
    return string.format("%d:%02d", m, s)
end

local function read_last_live()
    local f = io.open(PLAYER_STATE_PATH, "r")
    if not f then return "" end
    local content = f:read("*all")
    f:close()
    local data = utils.parse_json(content)
    if type(data) == "table" and data.last_live then
        return tostring(data.last_live)
    end
    return ""
end

local function write_player_state(running, channel, station)
    local pid = 0
    local path = ""
    if running then
        pid = mp.get_property_number("pid", 0) or 0
        path = mp.get_property("path") or ""
    end
    local is_live = is_timeshift_playback() or path:match("^dvb://") ~= nil
    local mode = ""
    if running then
        if is_timeshift_playback() then
            mode = (timeshift_behind() or mp.get_property_bool("pause", false)) and "timeshift" or "live"
        elseif is_live then
            mode = (behind_live() or mp.get_property_bool("pause", false)) and "timeshift" or "live"
        else
            mode = "recording"
        end
    end
    local last_live = (running and is_live) and (channel or "") or read_last_live()
    local json = string.format(
        '{"running": %s, "channel": "%s", "station": "%s", "pid": %d, "mode": "%s", "last_live": "%s", "updated_at": %d}',
        running and "true" or "false",
        json_escape(channel),
        json_escape(station),
        pid,
        json_escape(mode),
        json_escape(last_live),
        os.time()
    )
    local tmp = PLAYER_STATE_PATH .. ".tmp." .. tostring(pid)
    local f = io.open(tmp, "w")
    if not f then return end
    f:write(json)
    f:close()
    os.rename(tmp, PLAYER_STATE_PATH)
end

local function get_active_info()
    local path = mp.get_property("path") or ""
    local tune_name = nil
    if is_timeshift_playback() then
        tune_name = tostring(cached_timeshift.tune_name or cached_timeshift.channel or "")
        if tune_name == "" then
            local f = io.open(PLAYER_STATE_PATH, "r")
            if f then
                local content = f:read("*all")
                f:close()
                local data = utils.parse_json(content)
                if type(data) == "table" then
                    tune_name = tostring(data.last_live or data.channel or "")
                end
            end
        end
    elseif path:match("^dvb://") then
        tune_name = path:gsub("^dvb://", "")
    end

    if tune_name and tune_name ~= "" then
        local matched_ch = nil
        for _, ch in ipairs(cached_channels) do
            if ch.name == tune_name or ch.tune_name == tune_name or ch.raw_name == tune_name then
                matched_ch = ch
                break
            end
        end

        if not matched_ch then
            matched_ch = {
                name = tune_name,
                tune_name = tune_name,
                channel_number = "OTA",
                network = "Live TV",
                display_name = tune_name
            }
        end

        local prog = nil
        if matched_ch.channel_number and cached_guide[matched_ch.channel_number] then
            prog = cached_guide[matched_ch.channel_number]
        else
            for k, p in pairs(cached_guide) do
                if p.station and (p.station == matched_ch.name or p.station == matched_ch.tune_name) then
                    prog = p
                    break
                elseif p.network and matched_ch.network and string.lower(p.network) == string.lower(matched_ch.network) then
                    prog = p
                    break
                end
            end
        end

        return matched_ch, prog
    end

    local name = path:match("([^/]+)$") or path
    name = name:gsub("%.ts$", ""):gsub("%.mkv$", ""):gsub("%.mp4$", ""):gsub("_", " ")
    return {
        name = name,
        tune_name = name,
        channel_number = "REC",
        network = "Recording",
        display_name = name
    }, { title = "Recording" }
end

local function sync_player_state()
    local ch = select(1, get_active_info())
    if ch then
        write_player_state(true, ch.tune_name or ch.name or "", ch.display_name or "")
    end
end

local function get_network_color(net)
    if not net then return "&HFA89B4&" end -- Sapphire
    local n = string.upper(net)
    if n == "NBC" then return "&HA1E3A6&"       -- Mint
    elseif n == "ABC" then return "&HAFE2F9&"   -- Warm Gold
    elseif n == "FOX" then return "&HFA89B4&"   -- Sapphire
    elseif n == "CBS" then return "&HF7A6CB&"   -- Mauve
    elseif n == "PBS" then return "&HD5E294&"   -- Teal
    elseif n == "CW" then return "&HA1E3A6&"    -- Green
    elseif n == "UNIVISION" then return "&HA88BF3&" -- Coral
    end
    return "&HFA89B4&"
end

local function render_hud()
    local ch, prog = get_active_info()
    if not ch then
        overlay.data = ""
        overlay:update()
        return
    end

    local ch_num = ch.channel_number or "OTA"
    local net = ch.network or "TV"
    local display_title = ch.display_name or ch.name or "Live Broadcast"
    local net_col = get_network_color(net)

    local prog_title = prog and prog.title or "Live Terrestrial Broadcast"
    local prog_start = prog and prog.start_time or ""
    local prog_end = prog and prog.end_time or ""
    local prog_time = "Over-The-Air"
    if prog_start ~= "" and prog_end ~= "" then
        prog_time = prog_start .. " - " .. prog_end
    elseif prog_start ~= "" then
        prog_time = prog_start
    end
    local prog_synopsis = (prog and prog.synopsis) or "Digital ATSC 8VSB Terrestrial Transmission"

    -- Stream quality tags
    local video_h = mp.get_property_number("height", 720)
    local v_quality = (video_h >= 1000) and "1080i HD" or "720p HD"
    local is_muted = mp.get_property_bool("mute", false)
    local vol = mp.get_property_number("volume", 100)
    local vol_str = is_muted and "󰝟 MUTED" or string.format("󰕾 %d%%", math.floor(vol))

    local ass = ""

    -- 1. Top Glass Banner Background
    -- Draw rounded frosted container: x=24, y=20, w=1232, h=108
    ass = ass .. "{\\an7\\pos(24,20)\\bord0\\shad0\\1c&H181825&\\1a&H28&}{\\p1}m 0 12 s 0 0 12 0 l 1220 0 s 1232 0 1232 12 l 1232 96 s 1232 108 1220 108 l 12 108 s 0 108 0 96{\\p0}\n"

    -- 2. Accent Pill for Channel Number & Network
    ass = ass .. "{\\an7\\pos(38,32)\\bord0\\shad0\\1c&H11111b&\\1a&H10&}{\\p1}m 0 6 s 0 0 6 0 l 96 0 s 102 0 102 6 l 102 38 s 102 44 96 44 l 6 44 s 0 44 0 38{\\p0}\n"
    ass = ass .. string.format("{\\an7\\pos(48,38)\\bord0\\shad0\\fnSans-Serif\\b1\\fs26\\1c%s}%s\\N{\\fs14\\1c&Hcdd6f4&}%s\n", net_col, ch_num, net)

    -- 3. Station & Program Title
    ass = ass .. string.format("{\\an7\\pos(154,34)\\bord0\\shad0\\fnSans-Serif\\b1\\fs24\\1c&Hcdd6f4&}%s  {\\b0\\fs18\\1c&Ha6adc8&}·  %s\n", display_title, prog_time)
    ass = ass .. string.format("{\\an7\\pos(154,66)\\bord0\\shad0\\fnSans-Serif\\b1\\fs19\\1c%s}%s  {\\b0\\fs15\\1c&Ha6adc8&}·  %s\n", net_col, prog_title, prog_synopsis:sub(1, 75))

    -- Check if active channel is recording
    local is_recording = false
    for _, rec in ipairs(cached_recordings) do
        if rec.channel_number == ch_num or (rec.station and string.lower(rec.station) == string.lower(display_title)) or (rec.tune_name and ch and rec.tune_name == ch.tune_name) then
            is_recording = true
            break
        end
    end
    local rec_badge = is_recording and "{\\b1\\fs16\\1c&H7B7BFA&}󰑈 REC  " or ""
    local any_rec = type(cached_recordings) == "table" and #cached_recordings > 0
    if any_rec and not is_recording then
        local r0 = cached_recordings[1] or {}
        rec_badge = string.format("{\\b1\\fs16\\1c&H7B7BFA&}󰑈 REC %s  ", tostring(r0.channel_number or r0.station or "DVR"))
    end
    local path = mp.get_property("path") or ""
    local is_file = not path:match("^dvb://")
    local is_ts = is_timeshift_playback()
    local is_library = is_library_playback()
    local paused = mp.get_property_bool("pause", false)
    local delayed = is_ts and (paused or timeshift_behind()) or ((not is_file) and (paused or behind_live()))
    local mode_badge
    if is_library then
        mode_badge = "{\\1c&H89b4fa&}󰐊 PLAYBACK"
    elseif delayed then
        mode_badge = "{\\1c&H89b4fa&}󰐊 TIMESHIFT"
    else
        mode_badge = "{\\1c&Ha6e3a1&}󰐊 LIVE"
    end

    -- 4. Right Status Badges
    ass = ass .. string.format("{\\an9\\pos(1240,40)\\bord0\\shad0\\fnSans-Serif\\b1\\fs16}%s%s  {\\1c&Hcdd6f4&}·  %s  ·  5.1 AC-3\n", rec_badge, mode_badge, v_quality)
    ass = ass .. string.format("{\\an9\\pos(1240,70)\\bord0\\shad0\\fnSans-Serif\\fs16\\1c&H89b4fa&}%s  {\\1c&Ha6adc8&}·  CC Sub (C)\n", vol_str)

    -- 5. Bottom Floating Quick Transport Bar
    -- Draw bottom pill: x=330, y=654, w=620, h=44
    ass = ass .. "{\\an7\\pos(330,654)\\bord0\\shad0\\1c&H181825&\\1a&H20&}{\\p1}m 0 10 s 0 0 10 0 l 610 0 s 620 0 620 10 l 620 34 s 620 44 610 44 l 10 44 s 0 44 0 34{\\p0}\n"
    local rec_prompt
    if is_library or is_ts then
        rec_prompt = paused and "{\\b1}󰐊 Play{\\b0} (Space)" or "{\\b1}󰏤 Pause{\\b0} (Space)"
        local pos, t1
        pos = virt_update()
        t1 = atsc_duration()
        if is_ts then
            local delay = math.max(0, t1 - pos)
            prog_time = delayed and (fmt_clock(delay) .. " behind") or "Live"
            prog_title = paused and "Paused" or (delayed and "Timeshift" or "Live")
            prog_synopsis = delayed and "Pause buffer" or "Live dump"
        else
            prog_time = fmt_clock(pos) .. " / " .. fmt_clock(t1)
            prog_title = paused and "Paused" or "Playing"
            prog_synopsis = "Recorded broadcast"
        end
        local pct
        if is_ts and t1 > 0 then
            pct = 100 * math.max(0, math.min(1, pos / t1))
        else
            pct = file_progress()
        end
        local bar_w = 1200
        local fill = math.max(0, math.min(bar_w, math.floor(bar_w * pct / 100.0)))
        ass = ass .. "{\\an7\\pos(40,628)\\bord0\\shad0\\1c&H11111b&\\1a&H20&}{\\p1}m 0 0 l 1200 0 l 1200 8 l 0 8{\\p0}\n"
        if fill > 0 then
            ass = ass .. string.format("{\\an7\\pos(40,628)\\bord0\\shad0\\1c&H5858F8&\\1a&H00&}{\\p1}m 0 0 l %d 0 l %d 8 l 0 8{\\p0}\n", fill, fill)
        end
    elseif delayed then
        rec_prompt = paused and "{\\b1}󰐊 Play{\\b0} (Space)" or "{\\b1}󰏤 Pause{\\b0} (Space)"
        local delay = cache_ahead()
        prog_time = fmt_clock(delay) .. " behind"
        prog_title = paused and "Paused" or "Timeshift"
        prog_synopsis = "Live dump"
        local pct = 100 * LIVE_SLACK / math.max(LIVE_SLACK, delay)
        local bar_w = 1200
        local fill = math.max(0, math.min(bar_w, math.floor(bar_w * pct / 100.0)))
        ass = ass .. "{\\an7\\pos(40,628)\\bord0\\shad0\\1c&H11111b&\\1a&H20&}{\\p1}m 0 0 l 1200 0 l 1200 8 l 0 8{\\p0}\n"
        if fill > 0 then
            ass = ass .. string.format("{\\an7\\pos(40,628)\\bord0\\shad0\\1c&H5858F8&\\1a&H00&}{\\p1}m 0 0 l %d 0 l %d 8 l 0 8{\\p0}\n", fill, fill)
        end
    elseif is_recording then
        rec_prompt = "{\\1c&H7B7BFA&}{\\b1}󰓛 Stop REC{\\b0} (r){\\1c&Hcdd6f4&}"
    else
        rec_prompt = "{\\b1}󰑈 Record{\\b0} (r)"
    end
    local pause_prompt = paused and "{\\b1}󰐊 Play{\\b0} (Space)" or "{\\b1}󰏤 Pause{\\b0} (Space)"
    local rec_tail = any_rec and "  ·  {\\1c&H7B7BFA&}{\\b1}Stop REC{\\b0} (r){\\1c&Hcdd6f4&}" or ""
    if is_library or is_ts then
        ass = ass .. string.format("{\\an5\\pos(640,676)\\bord0\\shad0\\fnSans-Serif\\fs16\\1c&Hcdd6f4&}{\\b1}󰒮 Prev{\\b0} (j)  ·  {\\b1}󰒭 Next{\\b0} (k)  ·  {\\b1}−15s{\\b0} (←)  ·  %s  ·  {\\b1}+15s{\\b0} (→)  ·  {\\b1}Live{\\b0} (l)  ·  {\\b1}󰕾 Vol{\\b0} (Wheel)%s\n", rec_prompt, rec_tail)
    elseif delayed then
        ass = ass .. string.format("{\\an5\\pos(640,676)\\bord0\\shad0\\fnSans-Serif\\fs16\\1c&Hcdd6f4&}{\\b1}󰒮 Prev{\\b0} (j)  ·  {\\b1}󰒭 Next{\\b0} (k)  ·  %s  ·  {\\b1}Live{\\b0} (l / →)  ·  {\\b1}󰕾 Vol{\\b0} (Wheel)%s\n", rec_prompt, rec_tail)
    else
        ass = ass .. string.format("{\\an5\\pos(640,676)\\bord0\\shad0\\fnSans-Serif\\fs16\\1c&Hcdd6f4&}{\\b1}󰒮 Prev{\\b0} (j)  ·  {\\b1}󰒭 Next{\\b0} (k)  ·  %s  ·  %s  ·  {\\b1}󰕾 Vol{\\b0} (Wheel)  ·  {\\b1}󰊓 Full{\\b0} (F)%s\n", pause_prompt, rec_prompt, rec_tail)
    end

    overlay.data = ass
    overlay:update()
end

local function hide_live_badge()
    live_flash_until = 0
    live_blink = true
    if live_timer then
        live_timer:kill()
        live_timer = nil
    end
    live_overlay.data = ""
    live_overlay:update()
    pcall(function()
        mp.set_property("osd-align-x", "left")
        mp.set_property("osd-align-y", "top")
        mp.set_property("osd-font-size", "55")
        mp.set_property("osd-color", "#FFFFFF")
        mp.set_property("osd-bold", "no")
    end)
end

local function hide_hud()
    if live_flash_until > mp.get_time() then
        return
    end
    overlay.data = ""
    overlay:update()
    hud_visible = false
    if hide_timer then
        hide_timer:kill()
        hide_timer = nil
    end
end

local function show_hud()
    local ok, err = pcall(function()
        reload_data()
        render_hud()
        hud_visible = true

        if hide_timer then
            hide_timer:kill()
            hide_timer = nil
        end
        if mp.get_property_bool("pause", false) then
            return
        end
        local delay = HIDE_DELAY
        if live_flash_until > mp.get_time() then
            delay = math.max(delay, live_flash_until - mp.get_time() + 0.1)
        end
        hide_timer = mp.add_timeout(delay, hide_hud)
    end)
    if not ok then
        mp.msg.error("show_hud: " .. tostring(err))
    end
end

local function render_live_badge()
    if live_flash_until <= mp.get_time() then
        live_overlay.data = ""
        live_overlay:update()
        return
    end
    -- Same vector path the transport pill uses. ASS 1c is BGR; 0000FF is red.
    local ass = "{\\an7\\pos(524,328)\\bord0\\shad0\\1c&H0000FF&}{\\p1}m 0 10 s 0 0 10 0 l 222 0 s 232 0 232 10 l 232 54 s 232 64 222 64 l 10 64 s 0 64 0 54{\\p0}\n"
    ass = ass .. "{\\an5\\pos(640,360)\\bord0\\shad0\\fnSans-Serif\\b1\\fs48\\1c&HFFFFFF&}LIVE\n"
    live_overlay.data = ass
    live_overlay:update()
end

local function show_live_badge()
    hide_live_badge()
    live_blink = true
    live_flash_until = mp.get_time() + LIVE_HOLD
    render_live_badge()
    -- This mpv paints show-text; osd-overlay on gpu-next did not show in probes.
    pcall(function()
        mp.set_property("osd-align-x", "center")
        mp.set_property("osd-align-y", "center")
        mp.set_property("osd-font-size", "72")
        mp.set_property("osd-color", "#FF0000")
        mp.set_property("osd-border-color", "#000000")
        mp.set_property("osd-bold", "yes")
    end)
    mp.osd_message("LIVE", LIVE_HOLD)
    live_timer = mp.add_periodic_timer(LIVE_FLASH_STEP, function()
        if mp.get_time() >= live_flash_until then
            hide_live_badge()
            return
        end
        render_live_badge()
    end)
    show_hud()
end

local function toggle_hud()
    if hud_visible then
        hide_hud()
    else
        show_hud()
    end
end

-- Channel surfing stays inside MPV. Spawning omarchy-tv here deadlocks:
-- Lua blocks on the subprocess, which waits on this same IPC socket.
local function is_translator(ch)
    if not ch then return false end
    if ch.is_translator == true or ch.translator == true then return true end
    local blob = string.upper((ch.callsign or "") .. " " .. (ch.display_name or "") .. " " .. (ch.name or ""))
    return blob:find("DRT", 1, true) ~= nil or blob:find("TRANSLATOR", 1, true) ~= nil
end

local function is_favorite(ch)
    if not ch or not cached_favorites then return false end
    local favs = {}
    for _, f in ipairs(cached_favorites) do
        favs[string.lower(tostring(f))] = true
    end
    local keys = {"name", "tune_name", "raw_name", "callsign", "channel_number", "network"}
    for _, key in ipairs(keys) do
        local ident = ch[key]
        if ident and favs[string.lower(tostring(ident))] then
            return true
        end
    end
    return false
end

local function surf_pool()
    local filter = tostring((cached_prefs and cached_prefs.channel_filter) or "all")
    local want_favs = filter == "favorites" or filter == "favs" or filter == "fav"
    local show_dupes = cached_prefs and cached_prefs.show_translators == true
    local pool = {}
    for _, ch in ipairs(cached_channels) do
        if want_favs and not is_favorite(ch) then
            -- skip
        elseif (not show_dupes) and is_translator(ch) then
            -- skip
        else
            pool[#pool + 1] = ch
        end
    end
    return pool
end

local function channel_index_for(pool, tune_name)
    for i, ch in ipairs(pool) do
        if ch.name == tune_name or ch.tune_name == tune_name or ch.raw_name == tune_name then
            return i
        end
    end
    return nil
end

local function surf(delta)
    mp.commandv("set", "pause", "no")
    if is_file_playback() then
        local cli = tv_cli()
        mp.command_native_async({
            name = "subprocess",
            playback_only = false,
            args = {cli, delta > 0 and "next" or "prev"}
        }, function()
            show_hud()
        end)
        return
    end
    if not cached_channels or #cached_channels == 0 then
        reload_data()
    else
        -- Favorites / tab prefs change without a channel retune.
        local f_fav = io.open(FAVORITES_PATH, "r")
        if f_fav then
            local content = f_fav:read("*all")
            f_fav:close()
            local data = utils.parse_json(content)
            if type(data) == "table" then cached_favorites = data end
        end
        local f_prefs = io.open(UI_PREFS_PATH, "r")
        if f_prefs then
            local content = f_prefs:read("*all")
            f_prefs:close()
            local data = utils.parse_json(content)
            if type(data) == "table" then cached_prefs = data end
        end
    end
    local pool = surf_pool()
    local n = pool and #pool or 0
    if n == 0 then return end
    local path = mp.get_property("path") or ""
    if not path:match("^dvb://") then
        return
    end
    local tune_name = path:gsub("^dvb://", "")
    local idx = channel_index_for(pool, tune_name)
    local next_i
    if not idx then
        next_i = delta > 0 and 1 or n
    else
        next_i = (idx - 1 + delta) % n
        if next_i < 0 then next_i = next_i + n end
        next_i = next_i + 1
    end
    local ch = pool[next_i]
    local target = (ch and (ch.tune_name or ch.name or ch.raw_name)) or ""
    if target == "" or target == tune_name then return end
    mp.commandv("loadfile", "dvb://" .. target, "replace")
    show_hud()
end

local returning_live = false

local apply_virt_seek

local function seek_live_edge()
    mp.commandv("set", "pause", "no")
    if is_timeshift_playback() then
        virt_update()
        local dur = atsc_duration()
        virt_pos = math.max(0, dur - LIVE_SLACK)
        pcall(apply_virt_seek)
        pending_live_flash = true
        show_live_badge()
        sync_player_state()
        return
    end
    local path = mp.get_property("path") or ""
    if path:match("^dvb://") then
        pending_live_flash = true
        mp.commandv("stop")
        mp.add_timeout(0.05, function()
            mp.commandv("loadfile", path, "replace")
        end)
        return
    end
    show_live_badge()
    sync_player_state()
end

local function request_live()
    if is_library_playback() then
        local cli = tv_cli()
        mp.command_native_async({
            name = "subprocess",
            playback_only = false,
            args = {cli, "live"}
        }, function(ok, result)
            local status = result and result.status
            if ok == false or (status and status ~= 0) then
                returning_live = false
                mp.osd_message("Could not return to live", 4)
            end
        end)
        return
    end
    seek_live_edge()
end

local function go_live()
    if returning_live then return end
    returning_live = true
    request_live()
    mp.add_timeout(2.5, function()
        if is_file_playback() then
            returning_live = false
        end
    end)
end

local function at_file_end()
    if not is_library_playback() then return false end
    virt_update()
    local dur = atsc_duration()
    if dur < 8 then return false end
    return virt_pos >= (dur - 1.0)
end

local function send_follow_seek(bytes)
    local sock = follow_sock_opt()
    if not sock then return false end
    local py = table.concat({
        "import socket, sys",
        "s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)",
        "s.settimeout(1)",
        "s.connect(sys.argv[1])",
        "s.sendall(sys.argv[2].encode())",
    }, "\n")
    local res = mp.command_native({
        name = "subprocess",
        playback_only = false,
        args = {"/usr/bin/python3", "-c", py, sock, "SEEK " .. tostring(bytes)},
    })
    return type(res) == "table" and (res.status == 0 or res.status == true)
end

apply_virt_seek = function()
    local path = timeshift_file_opt() or mp.get_property("path") or ""
    if path == "" then return end
    local size = file_bytes()
    local bytes = math.floor((virt_pos * ATSC_BPS) / 8)
    if size > 188 then
        bytes = math.max(0, math.min(bytes, size - 188))
    else
        bytes = math.max(0, bytes)
    end
    if timeshift_file_opt() then
        send_follow_seek(bytes)
        if mp.get_property_bool("pause", false) then
            virt_last = nil
        else
            virt_last = mp.get_time()
        end
        return
    end
    seek_reload = true
    saved_virt = virt_pos
    -- MPEG-TS ignores relative time seeks. start=# is a byte offset.
    mp.command_native({
        name = "loadfile",
        url = path,
        flags = "replace",
        options = { start = "#" .. tostring(bytes) }
    })
end

local function seek_rel(delta)
    local step = math.abs(tonumber(delta) or SEEK_STEP)
    local signed = ((tonumber(delta) or 0) < 0) and -step or step
    if is_library_playback() then
        virt_update()
        local dur = atsc_duration()
        if signed < 0 then
            virt_pos = math.max(0, virt_pos - step)
            apply_virt_seek()
            show_hud()
            return
        end
        if at_file_end() or (dur > 8 and (virt_pos + step) >= (dur - 0.5)) then
            go_live()
            return
        end
        virt_pos = virt_pos + step
        apply_virt_seek()
        show_hud()
        return
    end
    if is_timeshift_playback() then
        virt_update()
        local dur = atsc_duration()
        if signed < 0 then
            virt_pos = math.max(0, virt_pos - step)
            pcall(apply_virt_seek)
            show_hud()
            return
        end
        -- Already on the write head: flash LIVE, do not slam the bar to 100%.
        if dur <= 0 or (dur - virt_pos) <= LIVE_SLACK then
            show_live_badge()
            return
        end
        virt_pos = virt_pos + step
        if (dur - virt_pos) <= LIVE_SLACK then
            seek_live_edge()
            return
        end
        pcall(apply_virt_seek)
        show_hud()
        return
    end
    if signed > 0 then
        if behind_live() then
            seek_live_edge()
            return
        end
        show_live_badge()
        return
    end
    show_hud()
end

local function request_pause()
    mp.commandv("cycle", "pause")
    show_hud()
    sync_player_state()
end

local function surf_next()
    surf(1)
end

local function surf_prev()
    surf(-1)
end

local function vol_up()
    mp.commandv("add", "volume", 5)
    show_hud()
end

local function vol_down()
    mp.commandv("add", "volume", -5)
    show_hud()
end

mp.add_forced_key_binding("LEFT", "tv_seek_back", function() seek_rel(-SEEK_STEP) end)
mp.add_forced_key_binding("RIGHT", "tv_seek_fwd", function() seek_rel(SEEK_STEP) end)
mp.register_script_message("tv-seek", function(delta)
    seek_rel(tonumber(delta) or SEEK_STEP)
end)
mp.register_script_message("tv-live-edge", function()
    seek_live_edge()
end)
mp.add_forced_key_binding("SPACE", "tv_pause", request_pause)
mp.add_forced_key_binding("l", "tv_return_live", request_live)
mp.add_forced_key_binding("UP", "tv_surf_next", surf_next)
mp.add_forced_key_binding("k", "tv_surf_next_k", surf_next)
mp.add_forced_key_binding("DOWN", "tv_surf_prev", surf_prev)
mp.add_forced_key_binding("j", "tv_surf_prev_j", surf_prev)
mp.add_forced_key_binding("WHEEL_UP", "tv_vol_up", vol_up)
mp.add_forced_key_binding("WHEEL_DOWN", "tv_vol_down", vol_down)

-- Hook Events
local prev_was_file = false

mp.register_event("file-loaded", function()
    local ok, err = pcall(function()
    returning_live = false
    if is_timeshift_playback() then
        prev_was_file = true
        if seek_reload then
            seek_reload = false
            virt_pos = saved_virt
            if mp.get_property_bool("pause", false) then
                virt_last = nil
            else
                virt_last = mp.get_time()
            end
        elseif not pending_live_flash then
            reset_virt()
        end
        if pending_live_flash then
            pending_live_flash = false
            show_live_badge()
        end
    elseif is_file_playback() then
        prev_was_file = true
        if seek_reload then
            seek_reload = false
            virt_pos = saved_virt
            if mp.get_property_bool("pause", false) then
                virt_last = nil
            else
                virt_last = mp.get_time()
            end
        else
            reset_virt()
        end
        hide_live_badge()
    else
        if pending_live_flash or prev_was_file then
            show_live_badge()
        end
        pending_live_flash = false
        prev_was_file = false
    end
    show_hud()
    sync_player_state()
    end)
    if not ok then
        mp.msg.error("file-loaded: " .. tostring(err))
    end
end)

mp.register_event("end-file", function(event)
    if event.reason ~= "eof" then return end
    if is_library_playback() then
        go_live()
    end
end)

mp.observe_property("eof-reached", "bool", function(_, eof)
    if eof and is_library_playback() then
        go_live()
    end
end)

mp.add_periodic_timer(0.4, function()
    if is_library_playback() then
        virt_update()
        if at_file_end() then
            go_live()
            return
        end
    elseif is_timeshift_playback() then
        virt_update()
    end
    if hud_visible or live_flash_until > mp.get_time() then pcall(render_hud) end
end)

mp.observe_property("path", "string", function(_, path)
    show_hud()
    if is_timeshift_playback() then
        return
    end
    if type(path) == "string" and path ~= "" and not path:match("^dvb://") then
        hide_live_badge()
    end
end)

mp.register_event("shutdown", function()
    pcall(hide_live_badge)
    pcall(write_player_state, false, "", "")
    local cli = tv_cli()
    if cli and cli ~= "" then
        mp.command_native_async({
            name = "subprocess",
            playback_only = false,
            args = {cli, "sync"},
        }, function() end)
    end
end)

mp.observe_property("volume", "number", function(_, _)
    if hud_visible then render_hud() end
end)

mp.observe_property("mute", "bool", function(_, _)
    if hud_visible then render_hud() end
end)

mp.observe_property("pause", "bool", function(_, paused)
    show_hud()
    sync_player_state()
end)

-- Mouse Activity
mp.observe_property("mouse-pos", "native", function(_, pos)
    if pos and pos.hover then
        show_hud()
    end
end)

mp.add_forced_key_binding("MBTN_MID", "tv_mute_toggle", function()
    mp.command("cycle mute")
    show_hud()
end)

-- Hyprland owns the floating PiP size. MPV's own fullscreen does not
-- restore that default geometry, so toggle compositor fullscreen instead.
local HYPR_FS_TOGGLE = 'hl.dispatch(hl.dsp.window.fullscreen({ mode = "fullscreen", action = "toggle", layout_aware = false, window = "class:^(omarchy-tv)$" }))'

local function toggle_window_fullscreen()
    mp.command_native_async({
        name = "subprocess",
        playback_only = false,
        args = { "hyprctl", "eval", HYPR_FS_TOGGLE }
    }, function() end)
end

mp.add_forced_key_binding("MBTN_LEFT_DBL", "tv_fs_dbl", toggle_window_fullscreen)
mp.add_forced_key_binding("f", "tv_fs_key", toggle_window_fullscreen)
mp.add_forced_key_binding("c", "tv_sub_cycle", function()
    mp.command("cycle sub")
    show_hud()
end)
mp.add_forced_key_binding("r", "tv_record_toggle", function()
    reload_data()
    local rec = cached_recordings[1]
    if rec then
        local ident = rec.tune_name or rec.station or rec.channel_number
        local cli = tv_cli()
        mp.command_native_async({
            name = "subprocess",
            playback_only = false,
            capture_stdout = true,
            args = {cli, "record", "stop", tostring(ident)}
        }, function()
            reload_data()
            show_hud()
        end)
        return
    end
    local path = mp.get_property("path") or ""
    if is_library_playback() then return end
    local ch, _ = get_active_info()
    if not ch then return end
    local ch_ident = ch.tune_name or ch.name or ch.channel_number
    local cli = tv_cli()
    mp.command_native_async({
        name = "subprocess",
        playback_only = false,
        capture_stdout = true,
        args = {cli, "record", "start", tostring(ch_ident)}
    }, function()
        reload_data()
        show_hud()
    end)
end)

reload_data()
pcall(show_hud)

local joined_live_flash = false
mp.observe_property("video-codec", "string", function(_, codec)
    if joined_live_flash then return end
    if not codec or codec == "" then return end
    if not is_timeshift_playback() then return end
    joined_live_flash = true
    show_live_badge()
end)
