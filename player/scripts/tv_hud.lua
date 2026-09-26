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
-- Weak or lost signal, shown on the picture while the HUD is hidden.
local badge = make_overlay(11)
local signal_label = ""
local signal_bgr = "&Hc8d0e0&"
local update_badge = function() end

local pointer_in = false
local hud_visible = false
local hide_timer = nil
local HIDE_DELAY = 3.5
local LIVE_SLACK = 2.5
local PAUSE_WINDOW = 3600

-- Paths
local xdg_config = os.getenv("XDG_CONFIG_HOME")
if not xdg_config or xdg_config == "" then
    xdg_config = (os.getenv("HOME") or "") .. "/.config"
end
local CHANNELS_PATH = xdg_config .. "/omarchy/tv/channels.json"
local GUIDE_PATH = xdg_config .. "/omarchy/tv/guide.json"
local RECORDINGS_PATH = xdg_config .. "/omarchy/tv/recordings_active.json"
local PLAYER_STATE_PATH = xdg_config .. "/omarchy/tv/player_state.json"
local TIMESHIFT_ACTIVE_PATH = xdg_config .. "/omarchy/tv/timeshift_active.json"
local xdg_cache = os.getenv("XDG_CACHE_HOME")
if not xdg_cache or xdg_cache == "" then
    xdg_cache = (os.getenv("HOME") or "") .. "/.cache"
end
local TIMESHIFT_DIR = xdg_cache .. "/omarchy/tv/timeshift"
local xdg_state = os.getenv("XDG_STATE_HOME")
if not xdg_state or xdg_state == "" then
    xdg_state = (os.getenv("HOME") or "") .. "/.local/state"
end
local THEME_COLORS_PATH = xdg_state .. "/omarchy/current/theme/colors.toml"

-- ASS colors are &HBBGGRR&. This is the look with no Omarchy theme found.
local THEME_DEFAULT = {
    bg = "&H12141C&", fg = "&Hcdd6f4&", title = "&HFFFFFF&", dim = "&Hc8d0e0&",
    accent = "&H89b4fa&", urgent = "&H3333F0&", warn = "&H30C0F0&", live = "&H7dcea0&", track = "&H2a2e3a&",
}
local theme = {}
for k, v in pairs(THEME_DEFAULT) do theme[k] = v end
local theme_stamp = nil

local function ass_color(hex)
    local r, g, b = tostring(hex or ""):match("^#(%x%x)(%x%x)(%x%x)$")
    if not r then return nil end
    return ("&H" .. b .. g .. r .. "&"):upper()
end

-- Same keys and fallbacks the shell reads, so the HUD matches the bar.
local function load_theme()
    local info = utils.file_info(THEME_COLORS_PATH)
    local stamp = info and tostring(info.mtime) or "none"
    if stamp == theme_stamp then return end
    theme_stamp = stamp
    local vals = {}
    local f = io.open(THEME_COLORS_PATH, "r")
    if f then
        for line in f:lines() do
            local k, v = line:match("^%s*([%w_%-]+)%s*=%s*[\"']?(#%x%x%x%x%x%x)")
            if k then vals[k] = v end
        end
        f:close()
    end
    local function pick(name, ...)
        for _, key in ipairs({...}) do
            local c = ass_color(vals[key])
            if c then
                theme[name] = c
                return
            end
        end
        theme[name] = THEME_DEFAULT[name]
    end
    pick("bg", "background", "color0")
    pick("fg", "foreground", "color7")
    pick("title", "bright_foreground", "light_foreground", "foreground", "color15")
    pick("dim", "dark_foreground", "muted", "color8")
    pick("accent", "accent", "color4")
    pick("urgent", "red", "color1")
    pick("warn", "yellow", "color3")
    pick("live", "green", "color2")
    pick("track", "lighter_background", "selection", "color8")
end
load_theme()

local cached_channels = {}
local cached_guide = {}
local cached_recordings = {}
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

local function opted_tune()
    local t = mp.get_opt("tune")
    if t and t ~= "" then return t end
    return ""
end

local function picture_ready()
    local w = mp.get_property_number("video-params/w", 0) or 0
    local h = mp.get_property_number("video-params/h", 0) or 0
    return w > 0 and h > 0
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
local BIG_STEP = 60
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
local rate_mark_byte = nil
local rate_mark_t = nil
local clock_shown = nil
local clock_tick = nil
local clock_raw = nil
local clock_jump = nil
local clock_jump_until = nil
local CLOCK_JUMP_HOLD = 2.0

local function tv_cli()
    local cli = mp.get_opt("cli")
    if cli and cli ~= "" then return cli end
    local src = debug.getinfo(1, "S").source or ""
    if src:sub(1, 1) == "@" then src = src:sub(2) end
    local root = src:match("^(.*)/player/scripts/tv_hud%.lua$")
    if root then
        local candidate = root .. "/bin/omarchy-tv"
        local f = io.open(candidate, "r")
        if f then
            f:close()
            return candidate
        end
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

local function read_sidecar(path)
    local f = io.open((path:gsub("%.[^./]+$", "")) .. ".json", "r")
    if not f then return nil end
    local content = f:read("*a")
    f:close()
    local data = utils.parse_json(content or "")
    if type(data) == "table" then return data end
    return nil
end

-- One station alone is far below the tower's 19.39 Mbps. Byte math at the tower
-- rate would end an SD episode after a few minutes.
local lib_side_path = nil
local lib_side = nil
local function library_side()
    local path = mp.get_property("path") or ""
    if path ~= lib_side_path then
        lib_side_path = path
        lib_side = read_sidecar(path)
    end
    return lib_side
end

local function library_rate()
    local side = library_side()
    if type(side) ~= "table" then return ATSC_BPS / 8 end
    local rate = tonumber(side.byte_rate)
    if rate and rate > 1000 then return rate end
    if side.full_mux then return ATSC_BPS / 8 end
    local start = tonumber(side.start) or 0
    local stop = tonumber(side["end"]) or 0
    if stop <= start then
        stop = os.time()
    end
    local size = file_bytes()
    if start > 0 and stop - start >= 10 and size > 0 then
        return size / (stop - start)
    end
    return ATSC_BPS / 8
end

-- A recording starts early, on the last show's credits. It opens just
-- before the listed start; the back key still reaches the rest.
local LEAD_IN_SEC = 10
local function listed_offset()
    local side = library_side()
    if type(side) ~= "table" then return 0 end
    local listed = tonumber(side.listed_start)
    if not listed and type(side.episodes) == "table" then
        for _, ep in ipairs(side.episodes) do
            local t = type(ep) == "table" and tonumber(ep.start_unix) or nil
            if t and (not listed or t < listed) then listed = t end
        end
    end
    local start = tonumber(side.start)
    if not listed or not start then return 0 end
    local off = listed - start - LEAD_IN_SEC
    if off < 5 or off > 600 then return 0 end
    return off
end

-- A whole-tower file carries every station on it. mpv 0.41 has no program
-- property, so this station is its own video and audio tracks by program id.
local function wanted_program()
    if is_library_playback() then
        local side = library_side()
        if type(side) == "table" and side.full_mux then return tonumber(side.service_id) end
        return nil
    end
    if is_timeshift_playback() and cached_timeshift.full_mux then
        return tonumber(cached_timeshift.service_id)
    end
    return nil
end

-- True once this station's picture track is chosen, or there is nothing to choose.
-- Stations on one tower keep their own clocks, up to ~25 s apart. A switch while
-- playing keeps the old clock and holds the new picture that long, so settle
-- drops the buffers and playback restarts on the new station's clock.
local function select_program(settle)
    local sid = wanted_program()
    if not sid or sid <= 0 then return true end
    local vid, aid
    for _, t in ipairs(mp.get_property_native("track-list") or {}) do
        if t["program-id"] == sid then
            if t.type == "video" and not vid then vid = t.id end
            if t.type == "audio" and not aid then aid = t.id end
        end
    end
    local changed = false
    if vid and mp.get_property_number("vid", -1) ~= vid then
        mp.set_property_number("vid", vid)
        changed = true
    end
    if aid and mp.get_property_number("aid", -1) ~= aid then
        mp.set_property_number("aid", aid)
        changed = true
    end
    if changed and settle then mp.command("drop-buffers") end
    return vid ~= nil
end
local program_pending = false

local function atsc_duration()
    local size = file_bytes()
    if size < 1024 then return 0 end
    return size / library_rate()
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

local function read_follow_cursor()
    local sock = follow_sock_opt()
    if not sock or sock == "" then return nil end
    local pos_path = sock:gsub("%.sock$", ".pos")
    local f = io.open(pos_path, "r")
    if not f then return nil end
    local n = tonumber(f:read("*l"))
    f:close()
    return n
end

local function measured_rate()
    local saved = tonumber(cached_timeshift.mux_bps) or 0
    if saved >= 1000 then return saved end
    local size = file_bytes()
    local now = mp.get_time()
    if not rate_mark_t then
        rate_mark_byte = size
        rate_mark_t = now
    else
        local elapsed = now - rate_mark_t
        if elapsed >= 5 and size > (rate_mark_byte or 0) then
            local rate = (size - rate_mark_byte) / elapsed
            if rate >= 1000 then
                mux_bps = rate
                rate_mark_byte = size
                rate_mark_t = now
            end
        end
    end
    if mux_bps >= 1000 then return mux_bps end
    return ATSC_BPS / 8
end

local function smooth_clock(raw)
    raw = math.max(0, math.floor((tonumber(raw) or 0) + 0.5))
    local now = mp.get_time()
    local paused = cached_timeshift.paused == true or mp.get_property_bool("pause", false)
    if clock_shown == nil or clock_tick == nil then
        clock_shown = raw
        clock_raw = raw
        clock_tick = now
        return clock_shown
    end
    -- A skip moves the file by seconds all at once. The pause count does not.
    -- Keyframes and the file's start can land it off the guess; then the file wins.
    if clock_jump ~= nil then
        if math.abs(raw - clock_jump) <= 1 or now >= (clock_jump_until or 0) then
            clock_jump = nil
            clock_raw = raw
            clock_shown = raw
            clock_tick = now
            return clock_shown
        end
        return clock_shown
    end
    if math.abs(raw - (clock_raw or raw)) >= 8 then
        clock_raw = raw
        clock_shown = raw
        clock_tick = now
        return clock_shown
    end
    clock_raw = raw
    if now < clock_tick + 0.98 then
        return clock_shown
    end
    clock_tick = now
    if paused then
        clock_shown = clock_shown + 1
    elseif raw < clock_shown then
        clock_shown = clock_shown - 1
    end
    return clock_shown
end

local function timeshift_delay()
    if not is_timeshift_playback() then
        behind_clock = 0
        playhead_byte = nil
        clock_shown = nil
        clock_tick = nil
        clock_raw = nil
        clock_jump = nil
        return 0
    end
    local f_ts = io.open(TIMESHIFT_ACTIVE_PATH, "r")
    if f_ts then
        local content = f_ts:read("*all")
        f_ts:close()
        local data = utils.parse_json(content)
        if type(data) == "table" then cached_timeshift = data end
    end
    -- Live and playing is live, whatever gap the tune left. Same as delay_sec.
    local view = tostring(cached_timeshift.view or "live")
    if view == "live" and not cached_timeshift.paused and not mp.get_property_bool("pause", false) then
        behind_clock = 0
        clock_shown = nil
        clock_tick = nil
        clock_raw = nil
        clock_jump = nil
        return 0
    end
    local size = file_bytes()
    local pos = read_follow_cursor()
    if pos == nil then
        pos = tonumber(cached_timeshift.playhead_byte) or 0
    end
    local rate = measured_rate()
    if size > 188 then
        pos = math.max(0, math.min(pos, size - 188))
    else
        pos = math.max(0, pos)
    end
    local lag = tonumber(cached_timeshift.live_lag) or 0
    behind_clock = smooth_clock(math.max(0, (size - pos - lag) / rate))
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
    rate_mark_byte = nil
    rate_mark_t = nil
    clock_shown = nil
    clock_tick = nil
    clock_raw = nil
    clock_jump = nil
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

-- GPS epoch to Unix, less the 18 leap seconds. Same as Model.js programUnix.
local GPS_UNIX_OFFSET = 315964800 - 18

local function program_on_now(row)
    if type(row) ~= "table" or type(row.programs) ~= "table" then return nil end
    -- A broadcast start time wins, like the flyout. Clock labels are the fallback.
    local now_unix = os.time()
    local dated = false
    for _, prog in ipairs(row.programs) do
        local gps = type(prog) == "table" and tonumber(prog.gps_start) or nil
        if gps and gps > 0 then
            dated = true
            local start = gps + GPS_UNIX_OFFSET
            local dur = tonumber(prog.duration_sec) or 0
            if dur <= 0 then dur = 30 * 60 end
            if start <= now_unix and now_unix < start + dur then
                return prog
            end
        end
    end
    if dated then return nil end
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
    local path = mp.get_property("path") or ""
    local tune_name = nil
    if is_timeshift_playback() then
        tune_name = tostring(cached_timeshift.tune_name or cached_timeshift.channel or "")
        if tune_name == "" then
            tune_name = opted_tune()
        end
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
            if ch.channel_number == tune_name or ch.name == tune_name or ch.tune_name == tune_name or ch.raw_name == tune_name then
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
    local ch = select(1, get_active_info())
    if ch then
        write_player_state(true, ch.tune_name or ch.name or "", ch.display_name or "")
    end
end

local blanking = false
local blank_saw_load = false
local blank_at = 0

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
    load_theme()
    local net_col = theme.accent

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
        status = "PLAYBACK"
    elseif is_ts and (paused or ts_delay > LIVE_SLACK) then
        status = fmt_clock(ts_delay) .. " BEHIND"
    elseif delayed then
        status = "BEHIND LIVE"
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
    if blanking then
        ass = ass .. box(0, 0, 1280, 720, "&H000000&", "00")
    end
    ass = ass .. box(0, 0, 1280, 96, theme.bg, "18")
    ass = ass .. box(0, 0, 8, 96, net_col, "00")
    ass = ass .. string.format(
        "{\\an7\\pos(28,22)\\bord0\\shad0\\fnSans-Serif\\b1\\fs34\\1c%s}%s\n",
        net_col, clip(ch_num, 8)
    )
    ass = ass .. string.format(
        "{\\an7\\pos(28,58)\\bord0\\shad0\\fnSans-Serif\\b1\\fs16\\1c%s}%s\n",
        theme.dim, clip(net, 12)
    )
    ass = ass .. string.format(
        "{\\an7\\pos(148,20)\\bord0\\shad0\\fnSans-Serif\\b1\\fs28\\1c%s}%s\n",
        theme.title, clip(display_title, 42)
    )
    ass = ass .. string.format(
        "{\\an7\\pos(148,58)\\bord0\\shad0\\fnSans-Serif\\fs20\\1c%s}%s\n",
        theme.fg, show_line
    )
    local status_col = (status == "LIVE") and theme.live or theme.accent
    ass = ass .. string.format(
        "{\\an9\\pos(1252,28)\\bord0\\shad0\\fnSans-Serif\\b1\\fs18\\1c%s}%s\n",
        status_col, ass_escape(status)
    )
    local side_y = 52
    if signal_label ~= "" and not is_library then
        ass = ass .. string.format(
            "{\\an9\\pos(1252,52)\\bord0\\shad0\\fnSans-Serif\\b1\\fs18\\1c%s}%s\n",
            signal_bgr, ass_escape(signal_label)
        )
        side_y = 74
    end
    if is_recording or any_rec then
        local rec_label = "REC"
        if any_rec and not is_recording then
            local r0 = cached_recordings[1] or {}
            rec_label = "REC " .. tostring(r0.channel_number or r0.station or "")
        end
        ass = ass .. string.format(
            "{\\an9\\pos(1252,%d)\\bord0\\shad0\\fnSans-Serif\\b1\\fs16\\1c%s}%s\n",
            side_y, theme.urgent, clip(rec_label, 16)
        )
    end
    if paused or delayed then
        local frac = 0
        if is_library then
            frac = (file_progress() or 0) / 100
        elseif is_ts then
            -- Right edge is live. An hour behind is the left edge.
            frac = 1 - (ts_delay / PAUSE_WINDOW)
        else
            local delay = cache_ahead()
            frac = LIVE_SLACK / math.max(LIVE_SLACK, delay)
        end
        local fill = math.floor(1280 * math.max(0, math.min(1, frac)))
        ass = ass .. box(0, 92, 1280, 4, theme.track, "00")
        if fill > 0 then
            ass = ass .. box(0, 92, fill, 4, theme.accent, "00")
        end
    end

    local vol = math.floor(mp.get_property_number("volume", 100) or 100)
    local vol_label = is_muted and ("{\\1c" .. theme.urgent .. "\\b1}Muted{\\1c" .. theme.fg .. "\\b0}") or ("Vol " .. tostring(vol))
    local action = paused and "Space Play" or "Space Pause"
    local record = is_recording and "r Stop recording" or "r Record"
    local hints
    if is_library then
        hints = string.format("← → 10s    ↑ ↓ 1 min    PgUp skip ads    %s    l Live TV    m Mute    %s", action, vol_label)
    elseif is_ts or delayed then
        hints = string.format("j k Channel    ← → 10s    ↑ ↓ 1 min    %s    y Save    %s    l Live    m Mute    %s", action, record, vol_label)
    else
        hints = string.format("j k Channel    %s    %s    m Mute    %s", action, record, vol_label)
    end
    ass = ass .. box(0, 676, 1280, 44, theme.bg, "18")
    ass = ass .. string.format(
        "{\\an5\\pos(640,698)\\bord0\\shad0\\fnSans-Serif\\fs18\\1c%s}%s\n",
        theme.fg, hints
    )

    overlay.data = ass
    overlay:update()
end

local function hide_hud()
    if not picture_ready() then
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
    update_badge()
end

local function show_hud()
    local ok, err = pcall(function()
        reload_data()
        render_hud()
        hud_visible = true
        update_badge()

        if hide_timer then
            hide_timer:kill()
            hide_timer = nil
        end
        if blanking or not picture_ready() then
            return
        end
        if mp.get_property_bool("pause", false) then
            return
        end
        if is_timeshift_playback() and timeshift_behind() then
            return
        end
        hide_timer = mp.add_timeout(HIDE_DELAY, hide_hud)
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

-- MPEG-TS ignores relative time seeks. mpv's start=#N is chapter N, not byte N;
-- a percent start on a TS file is a byte seek at that share of its size.
local function byte_start(bytes, size)
    if size <= 188 then return "0%" end
    bytes = math.max(0, math.min(bytes, size - 188))
    return string.format("%.6f%%", 100 * bytes / size)
end

apply_virt_seek = function()
    local path = mp.get_property("path") or ""
    if path == "" then return end
    seek_reload = true
    saved_virt = virt_pos
    mp.command_native({
        name = "loadfile",
        url = path,
        flags = "replace",
        options = { start = byte_start(math.floor(virt_pos * library_rate()), file_bytes()) }
    })
end

-- Same test as Model.isGameTitle. A wrong mark in a game skips a play, so games only jump on PgUp.
local GAME_SPORTS = { "football", "baseball", "basketball", "hockey", "soccer" }
local GAME_LEAGUES = { nfl = true, nba = true, mlb = true, nhl = true, mls = true, ncaa = true }
local NOT_A_GAME = { "pregame", "postgame", "kickoff", "today", "tonight", "countdown", "review", "highlights", "preview" }
local function is_game_title(title)
    local t = string.lower(tostring(title or ""))
    for _, word in ipairs(NOT_A_GAME) do
        if t:find(word, 1, true) then return false end
    end
    for _, word in ipairs(GAME_SPORTS) do
        if t:find("%f[%w]" .. word .. "%f[%W]") then return true end
    end
    return GAME_LEAGUES[t:match("^%s*(%w+)") or ""] == true
end

-- Each marked break is jumped once. Backing up into it plays it, so a wrong mark costs one key.
local skipped_path = nil
local skipped = {}
local function marked_breaks()
    local path = mp.get_property("path") or ""
    if path ~= skipped_path then
        skipped_path = path
        skipped = {}
    end
    local side = library_side()
    local ads = type(side) == "table" and side.ads or nil
    if type(ads) ~= "table" then return {}, side end
    return ads, side
end

local function skip_ads()
    local ads, side = marked_breaks()
    if #ads == 0 or is_game_title(type(side) == "table" and side.title or "") then return false end
    for i, span in ipairs(ads) do
        local a = type(span) == "table" and tonumber(span[1]) or nil
        local b = type(span) == "table" and tonumber(span[2]) or nil
        if a and b and not skipped[i] and virt_pos >= a and virt_pos < b - 2 then
            skipped[i] = true
            virt_pos = b
            apply_virt_seek()
            mp.osd_message("Skipped " .. fmt_clock(b - a) .. " of ads · ← to watch", 3)
            return true
        end
    end
    return false
end

-- mpv's chapter keys: PgUp is the next break's end, PgDn the last break's start.
local function jump_break(direction)
    if not is_library_playback() then
        mp.osd_message("Ad breaks are marked after a recording finishes · ↑ ↓ jump 1 minute", 3)
        return
    end
    virt_update()
    local ads = marked_breaks()
    local target, index = nil, nil
    for i, span in ipairs(ads) do
        local a = type(span) == "table" and tonumber(span[1]) or nil
        local b = type(span) == "table" and tonumber(span[2]) or nil
        if a and b then
            if direction > 0 and b > virt_pos + 1 and (not target or b < target) then
                target, index = b, i
            elseif direction < 0 and a < virt_pos - 3 and (not target or a > target) then
                target, index = a, i
            end
        end
    end
    if not target then
        mp.osd_message(#ads == 0 and "No ad breaks marked in this recording" or "No more ad breaks that way", 2)
        return
    end
    skipped[index] = true
    virt_pos = target
    apply_virt_seek()
    show_hud()
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
        clock_shown = math.max(0, (clock_shown or 0) - signed)
        clock_jump = clock_shown
        clock_jump_until = mp.get_time() + CLOCK_JUMP_HOLD
        clock_raw = clock_shown
        clock_tick = mp.get_time()
        cli_async({"seek", tostring(signed)})
        show_hud()
        return
    end
    if signed > 0 then
        show_hud()
        return
    end
    show_hud()
end

local function request_pause()
    -- Nothing plays under the black cover yet. A pause there has no picture to hold.
    if blanking or not picture_ready() then return end
    if is_library_playback() then
        mp.commandv("no-osd", "cycle", "pause")
        show_hud()
        sync_player_state()
        return
    end
    cli_async({"pause"})
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
mp.add_forced_key_binding("UP", "tv_seek_fwd_big", function() seek_rel(BIG_STEP) end)
mp.add_forced_key_binding("DOWN", "tv_seek_back_big", function() seek_rel(-BIG_STEP) end)
mp.add_forced_key_binding("PGUP", "tv_next_break", function() jump_break(1) end)
mp.add_forced_key_binding("PGDWN", "tv_prev_break", function() jump_break(-1) end)
mp.register_script_message("tv-seek", function(delta)
    seek_rel(tonumber(delta) or SEEK_STEP)
end)
mp.register_script_message("tv-live-edge", function()
    cli_async({"live"})
end)
local function cover_picture()
    blanking = true
    blank_saw_load = false
    blank_at = mp.get_time()
end

local function uncover_picture()
    blanking = false
    blank_saw_load = false
    blank_at = 0
    show_hud()
end

mp.register_script_message("tv-blank", function()
    cover_picture()
    show_hud()
end)
mp.register_script_message("tv-unblank", function()
    uncover_picture()
end)
mp.register_script_message("tv-retuned", function()
    cover_picture()
    reload_data()
    reset_virt()
    pcall(function()
        mp.commandv("set", "aid", "auto")
        mp.commandv("set", "pause", "no")
    end)
    show_hud()
end)
-- A station on the tower already playing. No reopen: switch tracks, and the
-- old picture holds until the new one's first keyframe.
mp.register_script_message("tv-program", function()
    reload_data()
    program_pending = not select_program(true)
    show_hud()
end)
-- Before decoders start, so a new file begins on this station's clock.
mp.add_hook("on_preloaded", 50, function()
    reload_data()
    program_pending = not select_program(false)
end)
mp.add_forced_key_binding("SPACE", "tv_pause", request_pause)
mp.add_forced_key_binding("l", "tv_return_live", function()
    cli_async({"live"})
end)
mp.add_forced_key_binding("WHEEL_UP", "tv_vol_up", vol_up)
mp.add_forced_key_binding("WHEEL_DOWN", "tv_vol_down", vol_down)

-- Hook Events
local prev_was_file = false

mp.register_event("file-loaded", function()
    local ok, err = pcall(function()
    returning_live = false
    lib_side_path = nil
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
            local off = listed_offset()
            if off > 0 then
                virt_pos = off
                apply_virt_seek()
            end
        end
    elseif is_timeshift_playback() then
        prev_was_file = true
    else
        prev_was_file = false
    end
    if blanking then
        blank_saw_load = true
        if not wanted_program() then
            pcall(function() mp.set_property("vid", "auto") end)
        end
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
end

mp.register_event("playback-restart", function()
    if blanking and blank_saw_load then
        uncover_picture()
    end
end)

mp.register_event("end-file", function(event)
    if event.reason ~= "eof" then return end
    on_dump_eof()
end)

mp.observe_property("eof-reached", "bool", function(_, eof)
    if not eof then return end
    on_dump_eof()
end)

local banner_tune = ""

mp.add_periodic_timer(0.4, function()
    if is_library_playback() then
        virt_update()
        if skip_ads() then return end
        if at_file_end() then
            go_live()
            return
        end
    elseif is_timeshift_playback() then
        virt_update()
    end
    if blanking and blank_at > 0 and (mp.get_time() - blank_at) > 12 then
        uncover_picture()
        return
    end
    if program_pending then
        program_pending = not select_program(true)
    end
    if is_timeshift_playback() then
        reload_data()
        local live_name = tostring(cached_timeshift.tune_name or cached_timeshift.channel or "")
        if live_name ~= "" and live_name ~= banner_tune then
            banner_tune = live_name
            show_hud()
            sync_player_state()
            return
        end
    end
    if hud_visible then pcall(render_hud) end
end)

mp.observe_property("path", "string", function(_, path)
    show_hud()
end)

local signal_busy = false
-- A good picture says nothing. Weak below 25 dB; good again at 26 so it
-- does not flicker. Two bad readings in a row before anything shows.
local WEAK_DB = 25
local GOOD_AGAIN_DB = 26
local signal_state = "good"
local bad_streak = 0
local last_poll = 0

local function signal_color(db)
    if db and db < 18 then return theme.urgent end
    return theme.warn
end

local function clear_signal()
    signal_state = "good"
    bad_streak = 0
    signal_label = ""
end

update_badge = function()
    local show = signal_label ~= "" and not hud_visible and not blanking
        and picture_ready() and not is_library_playback()
    if show then
        badge.data = string.format(
            "{\\an9\\pos(1252,28)\\bord2\\3c&H000000&\\shad0\\fnSans-Serif\\b1\\fs26\\1c%s}%s",
            signal_bgr, signal_label
        )
    else
        badge.data = ""
    end
    badge:update()
end

local function note_reading(db)
    local state = "good"
    if db == nil then
        state = "lost"
    elseif db < WEAK_DB or (signal_state ~= "good" and db < GOOD_AGAIN_DB) then
        state = "weak"
    end
    if state == "good" then
        clear_signal()
    else
        bad_streak = bad_streak + 1
        if bad_streak >= 2 then
            signal_state = state
            if state == "lost" then
                signal_label = "No signal"
                signal_bgr = theme.urgent
            else
                signal_label = "Weak signal"
                signal_bgr = signal_color(db)
            end
        end
    end
    if hud_visible then pcall(render_hud) end
    update_badge()
end

local function poll_signal()
    if is_library_playback() or blanking or not picture_ready() then
        -- A tune in progress has no lock yet. That is not a weak signal.
        if signal_label ~= "" or bad_streak > 0 then
            clear_signal()
            update_badge()
        end
        return
    end
    local every = (signal_state ~= "good" or bad_streak > 0 or hud_visible) and 2 or 5
    local now = mp.get_time()
    if now - last_poll < every - 0.05 then return end
    if signal_busy then return end
    last_poll = now
    signal_busy = true
    mp.command_native_async({
        name = "subprocess",
        playback_only = false,
        args = {tv_cli(), "signal", "--plain"},
        capture_stdout = true,
    }, function(success, result)
        signal_busy = false
        if success == false or not result then
            return
        end
        if result.status and result.status ~= 0 then
            return
        end
        local line = (result.stdout or ""):gsub("^%s+", ""):gsub("%s+$", "")
        note_reading(tonumber(line))
    end)
end

mp.add_periodic_timer(1, poll_signal)
poll_signal()

mp.register_event("shutdown", function()
    pcall(write_player_state, false, "", "")
    local cli = tv_cli()
    if cli and cli ~= "" then
        local pid = tostring(mp.get_property_number("pid", 0) or 0)
        mp.command_native_async({
            name = "subprocess",
            playback_only = false,
            detach = true,
            args = {cli, "sync", "--reap", pid},
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
local function recording_for_channel(ch)
    if not ch then return nil end
    local ch_num = ch.channel_number
    local tune = ch.tune_name or ch.name
    for _, rec in ipairs(cached_recordings) do
        if (tune and rec.tune_name == tune) or (ch_num and rec.channel_number == ch_num) then
            return rec
        end
    end
    return nil
end

local function change_channel(direction)
    if is_library_playback() then return end
    local cli = tv_cli()
    mp.command_native_async({
        name = "subprocess",
        playback_only = false,
        args = {cli, direction}
    }, function()
        reload_data()
        show_hud()
    end)
end

mp.add_forced_key_binding("y", "tv_keep_pause", function()
    if is_library_playback() then return end
    local cli = tv_cli()
    mp.command_native_async({
        name = "subprocess",
        playback_only = false,
        args = {cli, "keep"},
        capture_stdout = true,
    }, function(ok, res)
        if ok and type(res) == "table" and res.status == 0 then
            mp.osd_message("Saved to Recordings", 3)
        else
            mp.osd_message("Nothing paused to save yet", 3)
        end
        show_hud()
    end)
end)

mp.add_forced_key_binding("j", "tv_surf_prev_j", function() change_channel("prev") end)
mp.add_forced_key_binding("k", "tv_surf_next_k", function() change_channel("next") end)

mp.add_forced_key_binding("r", "tv_record_toggle", function()
    reload_data()
    if is_library_playback() then return end
    local ch, _ = get_active_info()
    if not ch then return end
    local ch_ident = ch.tune_name or ch.name or ch.channel_number
    local rec = recording_for_channel(ch)
    local cli = tv_cli()
    local args
    if rec then
        local ident = rec.tune_name or rec.channel_number or ch_ident
        args = {cli, "record", "stop", tostring(ident)}
    else
        args = {cli, "record", "start", tostring(ch_ident)}
    end
    mp.command_native_async({
        name = "subprocess",
        playback_only = false,
        capture_stdout = true,
        args = args
    }, function()
        reload_data()
        show_hud()
    end)
end)

mp.observe_property("video-params/w", "number", function(_, w)
    if w and w > 0 then
        show_hud()
    end
end)

reload_data()
banner_tune = tostring(cached_timeshift.tune_name or cached_timeshift.channel or "")
pcall(show_hud)
