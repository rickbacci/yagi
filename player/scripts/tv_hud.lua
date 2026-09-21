-- Omarchy TV - Modern Broadcast Heads-Up Display (Live TV OSD)
-- Replaces retro desktop seekbars with a sleek, glassmorphic TV banner and transport HUD.

local utils = require "mp.utils"

local overlay = mp.create_osd_overlay("ass-events")
overlay.res_x = 1280
overlay.res_y = 720

local hud_visible = false
local hide_timer = nil
local HIDE_DELAY = 3.5

-- Paths
local xdg_config = os.getenv("XDG_CONFIG_HOME")
if not xdg_config or xdg_config == "" then
    xdg_config = (os.getenv("HOME") or "") .. "/.config"
end
local CHANNELS_PATH = xdg_config .. "/omarchy/tv/channels.json"
local GUIDE_PATH = xdg_config .. "/omarchy/tv/guide.json"
local RECORDINGS_PATH = xdg_config .. "/omarchy/tv/recordings_active.json"
local TIMESHIFT_PATH = xdg_config .. "/omarchy/tv/timeshift_active.json"
local PLAYER_STATE_PATH = xdg_config .. "/omarchy/tv/player_state.json"
local FAVORITES_PATH = xdg_config .. "/omarchy/tv/favorites.json"
local UI_PREFS_PATH = xdg_config .. "/omarchy/tv/ui_prefs.json"

local cached_channels = {}
local cached_guide = {}
local cached_recordings = {}
local cached_favorites = {}
local cached_prefs = {}

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
end

local function json_escape(s)
    s = tostring(s or "")
    return s:gsub("\\", "\\\\"):gsub('"', '\\"'):gsub("\n", "\\n"):gsub("\r", "\\r")
end

local function is_file_playback()
    local path = mp.get_property("path") or ""
    return path ~= "" and not path:match("^dvb://")
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
    local is_live = path:match("^dvb://") ~= nil
    local mode = (running and (is_live and "live" or "recording")) or ""
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
    if path:match("^dvb://") then
        local tune_name = path:gsub("^dvb://", "")
        if tune_name == "" then return nil, nil end

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
    local prog_time = prog and (prog.start_time .. " - " .. prog.end_time) or "Over-The-Air"
    local prog_synopsis = prog and prog.synopsis or "Digital ATSC 8VSB Terrestrial Transmission"

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
    local path = mp.get_property("path") or ""
    local is_file = not path:match("^dvb://")
    local mode_badge = is_file and "{\\1c&H89b4fa&}󰐊 PLAYBACK" or "{\\1c&Ha6e3a1&}󰐊 LIVE"

    -- 4. Right Status Badges
    ass = ass .. string.format("{\\an9\\pos(1240,40)\\bord0\\shad0\\fnSans-Serif\\b1\\fs16}%s%s  {\\1c&Hcdd6f4&}·  %s  ·  5.1 AC-3\n", rec_badge, mode_badge, v_quality)
    ass = ass .. string.format("{\\an9\\pos(1240,70)\\bord0\\shad0\\fnSans-Serif\\fs16\\1c&H89b4fa&}%s  {\\1c&Ha6adc8&}·  CC Sub (C)\n", vol_str)

    -- 5. Bottom Floating Quick Transport Bar
    -- Draw bottom pill: x=330, y=654, w=620, h=44
    ass = ass .. "{\\an7\\pos(330,654)\\bord0\\shad0\\1c&H181825&\\1a&H20&}{\\p1}m 0 10 s 0 0 10 0 l 610 0 s 620 0 620 10 l 620 34 s 620 44 610 44 l 10 44 s 0 44 0 34{\\p0}\n"
    local paused = mp.get_property_bool("pause", false)
    local rec_prompt
    if is_file then
        rec_prompt = paused and "{\\b1}󰐊 Play{\\b0} (Space)" or "{\\b1}󰏤 Pause{\\b0} (Space)"
        local pos = mp.get_property_number("time-pos", 0) or 0
        local dur = mp.get_property_number("duration", 0) or 0
        prog_time = fmt_clock(pos) .. " / " .. fmt_clock(dur)
        prog_title = paused and "Paused" or "Playing"
        prog_synopsis = path:match("timeshift") and "Timeshift buffer" or "Recorded broadcast"
    elseif is_recording then
        rec_prompt = "{\\1c&H7B7BFA&}{\\b1}󰓛 Stop REC{\\b0} (r){\\1c&Hcdd6f4&}"
    else
        rec_prompt = "{\\b1}󰑈 Record{\\b0} (r)"
    end
    local pause_prompt = paused and "{\\b1}󰐊 Play{\\b0} (Space)" or "{\\b1}󰏤 Pause{\\b0} (Space)"
    if is_file then
        ass = ass .. string.format("{\\an5\\pos(640,676)\\bord0\\shad0\\fnSans-Serif\\fs16\\1c&Hcdd6f4&}{\\b1}󰒮 −10s{\\b0} (j)  ·  %s  ·  {\\b1}󰒭 +10s{\\b0} (k)  ·  {\\b1}Live{\\b0} (l)  ·  {\\b1}󰕾 Vol{\\b0} (Wheel)  ·  {\\b1}󰊓 Full{\\b0} (F)\n", rec_prompt)
    else
        ass = ass .. string.format("{\\an5\\pos(640,676)\\bord0\\shad0\\fnSans-Serif\\fs16\\1c&Hcdd6f4&}{\\b1}󰒮 Prev{\\b0} (j)  ·  {\\b1}󰒭 Next{\\b0} (k)  ·  %s  ·  %s  ·  {\\b1}󰕾 Vol{\\b0} (Wheel)  ·  {\\b1}󰊓 Full{\\b0} (F)\n", pause_prompt, rec_prompt)
    end

    overlay.data = ass
    overlay:update()
end

local function hide_hud()
    overlay.data = ""
    overlay:update()
    hud_visible = false
    if hide_timer then
        hide_timer:kill()
        hide_timer = nil
    end
end

local function show_hud()
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
    hide_timer = mp.add_timeout(HIDE_DELAY, hide_hud)
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

local function timeshift_dump_active()
    local f = io.open(TIMESHIFT_PATH, "r")
    if not f then return false end
    local content = f:read("*all")
    f:close()
    local data = utils.parse_json(content)
    return type(data) == "table" and #data > 0
end

local function surf(delta)
    mp.commandv("set", "pause", "no")
    if timeshift_dump_active() then
        local cli = mp.get_opt("cli") or "omarchy-tv"
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

local function request_live()
    local cli = mp.get_opt("cli") or "omarchy-tv"
    mp.command_native_async({
        name = "subprocess",
        playback_only = false,
        args = {cli, "live"}
    }, function() end)
end

local function go_live()
    if returning_live then return end
    returning_live = true
    request_live()
end

local function seek_rel(delta)
    if not is_file_playback() then return end
    if delta > 0 then
        local pos = mp.get_property_number("time-pos", 0) or 0
        local dur = mp.get_property_number("duration", 0) or 0
        if dur > 0 and (pos + delta) >= (dur - 0.25) then
            go_live()
            return
        end
    end
    mp.commandv("seek", tostring(delta), "relative")
    show_hud()
end

local function request_pause()
    local cli = mp.get_opt("cli") or "omarchy-tv"
    mp.command_native_async({
        name = "subprocess",
        playback_only = false,
        args = {cli, "pause"}
    }, function()
        show_hud()
    end)
end

local function surf_next()
    if is_file_playback() then
        seek_rel(10)
        return
    end
    surf(1)
end

local function surf_prev()
    if is_file_playback() then
        seek_rel(-10)
        return
    end
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

-- Hook Events
mp.register_event("file-loaded", function()
    returning_live = false
    show_hud()
    sync_player_state()
end)

mp.register_event("end-file", function(event)
    if event.reason ~= "eof" then return end
    if not is_file_playback() then return end
    go_live()
end)

mp.observe_property("eof-reached", "bool", function(_, eof)
    if eof and is_file_playback() then
        go_live()
    end
end)

mp.register_event("shutdown", function()
    pcall(write_player_state, false, "", "")
end)

mp.observe_property("path", "string", function(_, _)
    show_hud()
end)

mp.observe_property("volume", "number", function(_, _)
    if hud_visible then render_hud() end
end)

mp.observe_property("mute", "bool", function(_, _)
    if hud_visible then render_hud() end
end)

mp.observe_property("pause", "bool", function(_, paused)
    if paused then
        show_hud()
    elseif hud_visible then
        show_hud()
    end
end)

-- Mouse Activity
mp.observe_property("mouse-pos", "native", function(_, pos)
    if pos and pos.hover then
        show_hud()
    end
end)

-- Keybindings
mp.add_forced_key_binding("LEFT", "tv_seek_back", function() seek_rel(-10) end)
mp.add_forced_key_binding("RIGHT", "tv_seek_fwd", function() seek_rel(10) end)
mp.add_forced_key_binding("SPACE", "tv_pause", request_pause)
mp.add_forced_key_binding("l", "tv_return_live", request_live)
mp.add_forced_key_binding("UP", "tv_surf_next", surf_next)
mp.add_forced_key_binding("k", "tv_surf_next_k", surf_next)
mp.add_forced_key_binding("DOWN", "tv_surf_prev", surf_prev)
mp.add_forced_key_binding("j", "tv_surf_prev_j", surf_prev)
mp.add_forced_key_binding("WHEEL_UP", "tv_vol_up", vol_up)
mp.add_forced_key_binding("WHEEL_DOWN", "tv_vol_down", vol_down)
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
    local path = mp.get_property("path") or ""
    if not path:match("^dvb://") then return end
    local ch, _ = get_active_info()
    if not ch then return end
    local ch_ident = ch.tune_name or ch.name or ch.channel_number
    local is_rec = false
    for _, rec in ipairs(cached_recordings) do
        if rec.channel_number == ch.channel_number or rec.station == ch.station or rec.tune_name == ch.tune_name then
            is_rec = true
            break
        end
    end
    local act = is_rec and "stop" or "start"
    local cli = mp.get_opt("cli") or "omarchy-tv"
    mp.command_native_async({
        name = "subprocess",
        playback_only = false,
        capture_stdout = true,
        args = {cli, "record", act, ch_ident}
    }, function()
        reload_data()
        show_hud()
    end)
end)

reload_data()
show_hud()
