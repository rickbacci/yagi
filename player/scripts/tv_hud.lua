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

local cached_channels = {}
local cached_guide = {}
local cached_recordings = {}

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
end

local function get_active_info()
    local path = mp.get_property("path") or ""
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

    -- 4. Right Status Badges
    ass = ass .. string.format("{\\an9\\pos(1240,40)\\bord0\\shad0\\fnSans-Serif\\b1\\fs16}%s{\\1c&Ha6e3a1&}󰐊 LIVE  {\\1c&Hcdd6f4&}·  %s  ·  5.1 AC-3\n", rec_badge, v_quality)
    ass = ass .. string.format("{\\an9\\pos(1240,70)\\bord0\\shad0\\fnSans-Serif\\fs16\\1c&H89b4fa&}%s  {\\1c&Ha6adc8&}·  CC Sub (C)\n", vol_str)

    -- 5. Bottom Floating Quick Transport Bar
    -- Draw bottom pill: x=330, y=654, w=620, h=44
    ass = ass .. "{\\an7\\pos(330,654)\\bord0\\shad0\\1c&H181825&\\1a&H20&}{\\p1}m 0 10 s 0 0 10 0 l 610 0 s 620 0 620 10 l 620 34 s 620 44 610 44 l 10 44 s 0 44 0 34{\\p0}\n"
    local rec_prompt = is_recording and "{\\1c&H7B7BFA&}{\\b1}󰓛 Stop REC{\\b0} (r){\\1c&Hcdd6f4&}" or "{\\b1}󰑈 Record{\\b0} (r)"
    ass = ass .. string.format("{\\an5\\pos(640,676)\\bord0\\shad0\\fnSans-Serif\\fs16\\1c&Hcdd6f4&}{\\b1}󰒮 Prev{\\b0} (j)  ·  {\\b1}󰒭 Next{\\b0} (k)  ·  %s  ·  {\\b1}󰕾 Vol{\\b0} (Wheel)  ·  {\\b1}󰊓 Full{\\b0} (F)\n", rec_prompt)

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

-- Channel surfing commands via omarchy-tv
local function surf_next()
    show_hud()
    utils.subprocess({ args = { "omarchy-tv", "next" }, cancellable = false })
end

local function surf_prev()
    show_hud()
    utils.subprocess({ args = { "omarchy-tv", "prev" }, cancellable = false })
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
    show_hud()
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

-- Mouse Activity
mp.observe_property("mouse-pos", "native", function(_, pos)
    if pos and pos.hover then
        show_hud()
    end
end)

-- Keybindings
mp.add_forced_key_binding("TAB", "toggle_tv_hud", toggle_hud)
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
mp.add_forced_key_binding("MBTN_LEFT_DBL", "tv_fs_dbl", function()
    mp.command("cycle fullscreen")
end)
mp.add_forced_key_binding("f", "tv_fs_key", function()
    mp.command("cycle fullscreen")
end)
mp.add_forced_key_binding("c", "tv_sub_cycle", function()
    mp.command("cycle sub")
    show_hud()
end)
mp.add_forced_key_binding("r", "tv_record_toggle", function()
    local ch, _ = get_active_info()
    if not ch then return end
    local ch_ident = ch.channel_number or ch.tune_name or ch.name
    local is_rec = false
    for _, rec in ipairs(cached_recordings) do
        if rec.channel_number == ch.channel_number or rec.station == ch.station or rec.tune_name == ch.tune_name then
            is_rec = true
            break
        end
    end
    local act = is_rec and "stop" or "start"
    mp.command_native_async({
        name = "subprocess",
        playback_only = false,
        capture_stdout = true,
        args = {"omarchy-tv", "record", act, ch_ident}
    }, function()
        reload_data()
        show_hud()
    end)
end)

reload_data()
show_hud()
