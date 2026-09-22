-- Omarchy TV - Modern Broadcast Heads-Up Display (Live TV OSD)
-- Replaces retro desktop seekbars with a sleek, glassmorphic TV banner and transport HUD.

local utils = require "mp.utils"

local function dummy_overlay(z)
    local o = { data = "", res_x = 1280, res_y = 720, z = z or 10 }
    function o:update() end
    function o:remove() end
    return o
end

local function make_overlay(z)
    local ok, ov = pcall(function()
        local o = mp.create_osd_overlay("ass-events")
        o.res_x = 1280
        o.res_y = 720
        o.z = z
        return o
    end)
    if ok and ov then
        return ov
    end
    mp.msg.error("tv_hud osd-overlay failed: " .. tostring(ov))
    return dummy_overlay(z)
end

local overlay = make_overlay(10)

local pointer_in = false
local hud_visible = false
local hide_timer = nil
local HIDE_DELAY = 3.5
local SURF_COMMIT_DELAY = 0.9
local surf_idx = nil
local surf_timer = nil
local surf_busy = false
local surf_preview = nil
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
    if path:match("^http://127%.0%.0%.1:") and path:find("/live.ts", 1, true) then
        return true
    end
    if follow_sock_opt() and (path == "-" or path:match("^fd://") or path:match("^fdclose://") or path:find("omarchy-tv-follow.fifo", 1, true)) then
        return true
    end
    if path == "" or path:match("^dvb://") then return false end
    return path:sub(1, #TIMESHIFT_DIR) == TIMESHIFT_DIR
        or path:find("/omarchy/tv/timeshift/", 1, true) ~= nil
end

local function is_follow_pipe()
    local path = mp.get_property("path") or ""
    return path == "-" or path:match("^fd://") or path:match("^fdclose://")
        or path:find("omarchy-tv-follow.fifo", 1, true) ~= nil
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
local SEEK_STEP = 10
local SEEK_NEAR = 5
local virt_pos = 0
local virt_last = nil
local seek_reload = false
local saved_virt = 0
local pause_origin = nil
local pause_base_delay = 0
local behind_clock = 0
local playhead_byte = nil
local mux_bps = 0
local dump_start_byte = 0
local dump_start_t = nil

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

local function cli_async(argv)
    local cli = tv_cli()
    local args = {cli}
    for i = 1, #argv do
        args[#args + 1] = tostring(argv[i])
    end
    mp.command_native_async({
        name = "subprocess",
        playback_only = false,
        args = args,
    }, function()
        reload_data()
    end)
end

local function dump_path()
    local p = timeshift_file_opt()
    if p and p ~= "" then return p end
    return TIMESHIFT_DIR .. "/live.ts"
end

local function stat_bytes(path)
    if not path or path == "" then return 0 end
    local f = io.open(path, "rb")
    if not f then return 0 end
    local size = f:seek("end")
    f:close()
    return tonumber(size) or 0
end

local function file_bytes()
    if is_timeshift_playback() then
        local n = stat_bytes(dump_path())
        if n > 0 then return n end
    end
    local path = timeshift_file_opt() or mp.get_property("path") or ""
    if path == "-" or path:match("^fd://") or path:match("^fdclose://") then
        path = dump_path()
    end
    local n = stat_bytes(path)
    if n > 0 then return n end
    local st = path ~= "" and utils.file_info(path)
    if st and tonumber(st.size) and tonumber(st.size) > 0 then
        return tonumber(st.size)
    end
    return mp.get_property_number("file-size") or 0
end

local function atsc_duration()
    local size = file_bytes()
    if size < 1024 then return 0 end
    return (size * 8) / ATSC_BPS
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

local function align_ts(n)
    n = math.max(0, math.floor(tonumber(n) or 0))
    return n - (n % 188)
end

local function mux_rate()
    if mux_bps >= 1000 then return mux_bps end
    return ATSC_BPS / 8
end

local function dump_playhead()
    local pos = dump_start_byte or 0
    if pos <= 0 then pos = playhead_byte or 0 end
    if dump_start_t and not mp.get_property_bool("pause", false) then
        pos = pos + (mp.get_time() - dump_start_t) * mux_rate()
    end
    local size = file_bytes()
    if size > 188 then
        pos = math.max(0, math.min(pos, size - 188))
    else
        pos = math.max(0, pos)
    end
    return pos
end

local function timeshift_delay()
    if not is_timeshift_playback() then
        pause_origin = nil
        behind_clock = 0
        playhead_byte = nil
        return 0
    end
    local view = tostring(cached_timeshift.view or "live")
    local paused = cached_timeshift.paused == true
    if view == "live" and not paused then
        behind_clock = 0
        return 0
    end
    if paused then
        local t0 = tonumber(cached_timeshift.playhead_t) or 0
        if t0 > 0 then
            behind_clock = math.max(0, os.time() - t0)
            return behind_clock
        end
    end
    local size = file_bytes()
    local pos = tonumber(cached_timeshift.playhead_byte) or 0
    local rate = mux_rate()
    if view == "delayed" and not paused then
        local t0 = tonumber(cached_timeshift.playhead_t) or 0
        if t0 > 0 then
            pos = pos + math.max(0, os.time() - t0) * rate
        end
    end
    if size > 188 then
        pos = math.max(0, math.min(pos, size - 188))
    end
    behind_clock = math.max(0, (size - pos) / rate)
    return behind_clock
end

local function timeshift_behind(slack)
    slack = slack or LIVE_SLACK
    return timeshift_delay() > slack
end

local function reset_virt()
    virt_pos = 0
    pause_origin = nil
    pause_base_delay = 0
    behind_clock = 0
    playhead_byte = nil
    mux_bps = 0
    dump_start_byte = 0
    dump_start_t = nil
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

local function parse_clock_minutes(label)
    local h, m, ap = tostring(label or ""):match("^(%d+):(%d+)%s*([AaPp][Mm])")
    if not h then return -1 end
    h = tonumber(h)
    m = tonumber(m)
    if h == 12 then h = 0 end
    if ap:upper() == "PM" then h = h + 12 end
    return h * 60 + m
end

local function program_on_now(row)
    if type(row) ~= "table" or type(row.programs) ~= "table" then return nil end
    local now = os.date("*t")
    local clock = now.hour * 60 + now.min
    for _, prog in ipairs(row.programs) do
        if type(prog) == "table" then
            local start_m = parse_clock_minutes(prog.start or prog.start_time)
            local end_m = parse_clock_minutes(prog["end"] or prog.end_time)
            if start_m >= 0 then
                local when = clock
                if end_m < 0 then end_m = start_m + 30 end
                if end_m <= start_m then
                    end_m = end_m + 24 * 60
                    if when < start_m then when = when + 24 * 60 end
                end
                if start_m <= when and when < end_m then
                    return prog
                end
            end
        end
    end
    return nil
end

local function guide_for_channel(matched_ch)
    if not matched_ch then return nil end
    if matched_ch.channel_number and cached_guide[matched_ch.channel_number] then
        return cached_guide[matched_ch.channel_number]
    end
    local function same(a, b)
        if not a or not b then return false end
        a = tostring(a)
        b = tostring(b)
        return a ~= "" and string.lower(a) == string.lower(b)
    end
    for _, p in pairs(cached_guide) do
        if type(p) == "table" then
            if same(p.tune_name, matched_ch.tune_name) or same(p.tune_name, matched_ch.name) then
                return p
            end
            if same(p.callsign, matched_ch.callsign) or same(p.station, matched_ch.callsign) then
                return p
            end
            if same(p.station, matched_ch.tune_name) or same(p.station, matched_ch.name) then
                return p
            end
        end
    end
    return nil
end

local function get_active_info()
    if surf_preview then
        return surf_preview, guide_for_channel(surf_preview)
    end
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

        return matched_ch, guide_for_channel(matched_ch)
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
    if surf_preview then return end
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

    local block = program_on_now(prog)
    local prog_title = (block and block.title) or "Live broadcast"
    local prog_start = (block and (block.start or block.start_time)) or ""
    local prog_end = (block and (block["end"] or block.end_time)) or ""
    local prog_time = "Over-The-Air"
    if prog_start ~= "" and prog_end ~= "" then
        prog_time = prog_start .. " - " .. prog_end
    elseif prog_start ~= "" then
        prog_time = prog_start
    end
    local prog_synopsis = (block and block.synopsis) or ""

    local is_recording = false
    for _, rec in ipairs(cached_recordings) do
        if rec.channel_number == ch_num or (rec.station and string.lower(rec.station) == string.lower(display_title)) or (rec.tune_name and ch and rec.tune_name == ch.tune_name) then
            is_recording = true
            break
        end
    end
    local any_rec = type(cached_recordings) == "table" and #cached_recordings > 0
    local path = mp.get_property("path") or ""
    local is_file = not path:match("^dvb://")
    local is_ts = is_timeshift_playback()
    local is_library = is_library_playback()
    local paused = mp.get_property_bool("pause", false)
    local is_muted = mp.get_property_bool("mute", false)
    local ts_delay = is_ts and timeshift_delay() or 0
    local delayed = is_ts and (paused or ts_delay > LIVE_SLACK) or ((not is_file) and (paused or behind_live()))
    local status = "LIVE"
    if is_library then
        status = "PLAY"
    elseif is_ts and (paused or ts_delay > LIVE_SLACK) then
        status = fmt_clock(ts_delay) .. " behind"
    elseif delayed then
        status = "BEHIND"
    end

    local function ass_escape(s)
        return tostring(s or ""):gsub("[{}\\\n\r]", " ")
    end
    local function clip(s, n)
        s = ass_escape(s)
        if #s > n then return s:sub(1, n - 1) .. "…" end
        return s
    end
    local function box(x, y, w, h, bgr, alpha)
        return string.format(
            "{\\an7\\pos(%d,%d)\\bord0\\shad0\\1c%s\\1a&H%s&\\p1}m 0 0 l %d 0 l %d %d l 0 %d{\\p0}\n",
            x, y, bgr, alpha, w, w, h, h
        )
    end

    local when = ""
    if prog_start ~= "" and prog_end ~= "" then
        when = prog_start .. " – " .. prog_end
    elseif prog_start ~= "" then
        when = prog_start
    end
    local show_line = clip(prog_title, 46)
    if when ~= "" then
        show_line = show_line .. "   ·   " .. when
    end

    local ass = ""
    ass = ass .. box(0, 0, 1280, 96, "&H12141C&", "18")
    ass = ass .. box(0, 0, 8, 96, net_col, "00")
    ass = ass .. string.format(
        "{\\an7\\pos(28,22)\\bord0\\shad0\\fnSans-Serif\\b1\\fs34\\1c%s}%s\n",
        net_col, clip(ch_num, 8)
    )
    ass = ass .. string.format(
        "{\\an7\\pos(28,58)\\bord0\\shad0\\fnSans-Serif\\b1\\fs16\\1c&Hcdd6f4&}%s\n",
        clip(net, 12)
    )
    ass = ass .. string.format(
        "{\\an7\\pos(148,20)\\bord0\\shad0\\fnSans-Serif\\b1\\fs28\\1c&HFFFFFF&}%s\n",
        clip(display_title, 42)
    )
    ass = ass .. string.format(
        "{\\an7\\pos(148,58)\\bord0\\shad0\\fnSans-Serif\\fs20\\1c&Hc8d0e0&}%s\n",
        show_line
    )
    local status_col = (status == "LIVE") and "&H7dcea0&" or "&H89b4fa&"
    ass = ass .. string.format(
        "{\\an9\\pos(1252,28)\\bord0\\shad0\\fnSans-Serif\\b1\\fs18\\1c%s}%s\n",
        status_col, ass_escape(status)
    )
    if is_recording or any_rec then
        local rec_label = "REC"
        if any_rec and not is_recording then
            local r0 = cached_recordings[1] or {}
            rec_label = "REC " .. tostring(r0.channel_number or r0.station or "")
        end
        ass = ass .. string.format(
            "{\\an9\\pos(1252,52)\\bord0\\shad0\\fnSans-Serif\\b1\\fs16\\1c&H6a6af0&}%s\n",
            clip(rec_label, 16)
        )
    elseif is_muted then
        ass = ass .. "{\\an9\\pos(1252,52)\\bord0\\shad0\\fnSans-Serif\\b1\\fs16\\1c&Hc8d0e0&}Muted\n"
    end
    if paused or delayed then
        local frac = 0
        if is_library then
            frac = (file_progress() or 0) / 100
        elseif is_ts then
            local t1 = atsc_duration()
            local pos = math.max(0, t1 - ts_delay)
            if t1 > 0 then frac = math.max(0, math.min(1, pos / t1)) end
        else
            local delay = cache_ahead()
            frac = LIVE_SLACK / math.max(LIVE_SLACK, delay)
        end
        local fill = math.floor(1280 * math.max(0, math.min(1, frac)))
        ass = ass .. box(0, 92, 1280, 4, "&H2a2e3a&", "00")
        if fill > 0 then
            ass = ass .. box(0, 92, fill, 4, "&H5858F8&", "00")
        end
    end

    local vol = math.floor(mp.get_property_number("volume", 100) or 100)
    local vol_label = "Vol " .. tostring(vol)
    local action = paused and "Play (Space)" or "Pause (Space)"
    local record = (is_recording or any_rec) and "Stop (r)" or "Record (r)"
    local hints
    if is_library or is_ts or delayed then
        hints = string.format("Prev (j)    Next (k)    Back 10s (←)    %s    Ahead 10s (→)    Live (l)    Mute (m)    %s", action, vol_label)
    else
        hints = string.format("Prev (j)    Next (k)    %s    %s    Live (l)    Mute (m)    %s", action, record, vol_label)
    end
    ass = ass .. box(0, 676, 1280, 44, "&H12141C&", "18")
    ass = ass .. string.format(
        "{\\an5\\pos(640,698)\\bord0\\shad0\\fnSans-Serif\\fs18\\1c&Hcdd6f4&}%s\n",
        hints
    )

    overlay.data = ass
    overlay:update()
end

local function hide_hud()
    if surf_preview then
        return
    end
    if is_timeshift_playback() and timeshift_behind() then
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
        if is_timeshift_playback() and timeshift_behind() then
            return
        end
        local delay = HIDE_DELAY
        if surf_preview then
            delay = math.max(delay, SURF_COMMIT_DELAY + 2)
        end
        hide_timer = mp.add_timeout(delay, hide_hud)
    end)
    if not ok then
        mp.msg.error("show_hud: " .. tostring(err))
    end
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
    local filter = tostring((cached_prefs and cached_prefs.channel_filter) or "favorites")
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

local function live_tune_name()
    reload_data()
    local ts = cached_timeshift or {}
    local name = tostring(ts.tune_name or ts.channel or "")
    if name ~= "" then return name end
    local saved = surf_preview
    surf_preview = nil
    local ch = select(1, get_active_info())
    surf_preview = saved
    if ch then return tostring(ch.tune_name or ch.name or "") end
    return ""
end

local function format_ch_banner(ch)
    if not ch then return "" end
    local num = tostring(ch.channel_number or "")
    local name = ch.display_name or ch.callsign or ch.name or ch.tune_name or ""
    if num ~= "" and num ~= "OTA" and num ~= "REC" then
        return num .. "  " .. name
    end
    return name
end

local function commit_surf()
    surf_timer = nil
    local pool = surf_pool()
    local n = pool and #pool or 0
    if n == 0 or not surf_idx or not pool[surf_idx] then
        return
    end
    if surf_busy then
        surf_timer = mp.add_timeout(0.3, commit_surf)
        return
    end
    local ch = pool[surf_idx]
    local target = ch.tune_name or ch.name or ch.raw_name or ""
    if target == "" then return end
    if target == live_tune_name() then
        surf_preview = nil
        show_hud()
        return
    end
    surf_busy = true
    surf_preview = ch
    show_hud()
    local cli = tv_cli()
    mp.command_native_async({
        name = "subprocess",
        playback_only = false,
        args = {cli, "play", target}
    }, function()
        surf_busy = false
        reload_data()
        local live = live_tune_name()
        if surf_preview then
            local want = surf_preview.tune_name or surf_preview.name
            if want == live then
                surf_preview = nil
            end
        end
        show_hud()
        -- Extra j/k during the tune already reset surf_timer. Do not
        -- start a second play from this callback — that paused the
        -- follow pipe and froze the picture.
    end)
end

local function surf(delta)
    if not cached_channels or #cached_channels == 0 then
        reload_data()
    else
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
        local f_ts = io.open(TIMESHIFT_ACTIVE_PATH, "r")
        if f_ts then
            local content = f_ts:read("*all")
            f_ts:close()
            local data = utils.parse_json(content)
            if type(data) == "table" then cached_timeshift = data end
        end
    end
    local pool = surf_pool()
    local n = pool and #pool or 0
    if n == 0 then return end
    if not surf_idx then
        surf_idx = channel_index_for(pool, live_tune_name()) or 1
    end
    surf_idx = ((surf_idx - 1 + delta) % n) + 1
    if surf_idx < 1 then surf_idx = surf_idx + n end
    surf_preview = pool[surf_idx]
    show_hud()
    if surf_timer then
        surf_timer:kill()
        surf_timer = nil
    end
    surf_timer = mp.add_timeout(SURF_COMMIT_DELAY, commit_surf)
end

local returning_live = false

local apply_virt_seek

local function request_live()
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

apply_virt_seek = function()
    local path = mp.get_property("path") or ""
    if path == "" then return end
    local size = file_bytes()
    local bytes = math.floor((virt_pos * ATSC_BPS) / 8)
    if size > 188 then
        bytes = math.max(0, math.min(bytes, size - 188))
    else
        bytes = math.max(0, bytes)
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
        cli_async({"seek", tostring(signed)})
        return
    end
    if signed > 0 then
        show_hud()
        return
    end
    show_hud()
end

local function request_pause()
    if is_library_playback() then
        mp.commandv("no-osd", "cycle", "pause")
        show_hud()
        sync_player_state()
        return
    end
    cli_async({"pause"})
end

local function surf_next()
    surf(1)
end

local function surf_prev()
    surf(-1)
end

local function vol_up()
    mp.commandv("no-osd", "add", "volume", 5)
    show_hud()
end

local function vol_down()
    mp.commandv("no-osd", "add", "volume", -5)
    show_hud()
end

mp.add_forced_key_binding("LEFT", "tv_seek_back", function() seek_rel(-SEEK_STEP) end)
mp.add_forced_key_binding("RIGHT", "tv_seek_fwd", function() seek_rel(SEEK_STEP) end)
mp.register_script_message("tv-seek", function(delta)
    seek_rel(tonumber(delta) or SEEK_STEP)
end)
mp.register_script_message("tv-live-edge", function()
    cli_async({"live"})
end)
mp.register_script_message("tv-retuned", function()
    reload_data()
    reset_virt()
    pcall(function()
        mp.commandv("set", "aid", "auto")
        mp.commandv("set", "pause", "no")
    end)
    local live = live_tune_name()
    if surf_preview then
        local want = surf_preview.tune_name or surf_preview.name
        if want == live then
            surf_preview = nil
        end
    end
    show_hud()
end)
mp.add_forced_key_binding("SPACE", "tv_pause", request_pause)
mp.add_forced_key_binding("l", "tv_return_live", function()
    cli_async({"live"})
end)
mp.add_forced_key_binding("UP", "tv_surf_next", surf_next, {repeatable = false})
mp.add_forced_key_binding("k", "tv_surf_next_k", surf_next, {repeatable = false})
mp.add_forced_key_binding("DOWN", "tv_surf_prev", surf_prev, {repeatable = false})
mp.add_forced_key_binding("j", "tv_surf_prev_j", surf_prev, {repeatable = false})
mp.add_forced_key_binding("WHEEL_UP", "tv_vol_up", vol_up)
mp.add_forced_key_binding("WHEEL_DOWN", "tv_vol_down", vol_down)

-- Hook Events
local prev_was_file = false

mp.register_event("file-loaded", function()
    local ok, err = pcall(function()
    returning_live = false
    if is_library_playback() then
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
    elseif is_timeshift_playback() then
        prev_was_file = true
    else
        prev_was_file = false
    end
    show_hud()
    sync_player_state()
    end)
    if not ok then
        mp.msg.error("file-loaded: " .. tostring(err))
    end
end)

local function on_dump_eof()
    if is_library_playback() then
        cli_async({"live"})
        return
    end
    if is_timeshift_playback() and not is_follow_pipe() then
        if mp.get_property_bool("pause", false) then
            return
        end
        cli_async({"seek", "0"})
    end
end

mp.register_event("end-file", function(event)
    if event.reason ~= "eof" then return end
    on_dump_eof()
end)

mp.observe_property("eof-reached", "bool", function(_, eof)
    if not eof then return end
    on_dump_eof()
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
    if hud_visible then pcall(render_hud) end
end)

mp.observe_property("path", "string", function(_, path)
    show_hud()
end)

mp.register_event("shutdown", function()
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
    if hud_visible then pcall(render_hud) end
end)

mp.observe_property("mute", "bool", function(_, _)
    if hud_visible then pcall(render_hud) end
end)

mp.observe_property("pause", "bool", function(_, paused)
    show_hud()
    sync_player_state()
end)

-- Pointer-enter shows the bottom HUD pill. Do not osd_message the
-- chord list — that is stock mpv text on top of the overlay.
mp.observe_property("mouse-pos", "native", function(_, pos)
    local hover = pos and pos.hover
    if hover and not pointer_in then
        show_hud()
    end
    pointer_in = not not hover
end)

mp.add_forced_key_binding("m", "tv_mute_toggle", function()
    mp.commandv("no-osd", "cycle", "mute")
    show_hud()
end)
mp.add_forced_key_binding("MBTN_MID", "tv_mute_mid", function()
    mp.commandv("no-osd", "cycle", "mute")
    show_hud()
end)

-- Fullscreen is Omarchy Super+F only (see omarchy-tv fullscreen). Do not
-- bind `f` or double-click — stock mpv fullscreen is also off.
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
