-- Drive player/scripts/tv_hud.lua under a fake mp and print one JSON object.
local hud = arg[1]
local bindings = {}
local events = {}
local armed = false
local current = {key = "", n = 0}

local function format_json(v)
    local kind = type(v)
    if kind == "string" then
        return '"' .. v:gsub("\\", "\\\\"):gsub('"', '\\"') .. '"'
    elseif kind == "number" then
        return tostring(v)
    elseif kind == "boolean" then
        return v and "true" or "false"
    elseif kind == "nil" then
        return "null"
    elseif kind == "table" then
        local array = true
        local count = 0
        for k in pairs(v) do
            count = count + 1
            if type(k) ~= "number" then array = false end
        end
        if array then
            local parts = {}
            for i = 1, #v do parts[i] = format_json(v[i]) end
            return "[" .. table.concat(parts, ",") .. "]"
        end
        local keys = {}
        for k in pairs(v) do keys[#keys + 1] = tostring(k) end
        table.sort(keys)
        local parts = {}
        for _, k in ipairs(keys) do
            parts[#parts + 1] = format_json(k) .. ":" .. format_json(v[k])
        end
        return "{" .. table.concat(parts, ",") .. "}"
    end
    return "null"
end

local function parse_json(s)
    local i, n = 1, #s
    local function skip()
        while i <= n and s:sub(i, i):match("%s") do i = i + 1 end
    end
    local function parse()
        skip()
        local c = s:sub(i, i)
        if c == "{" then
            i = i + 1
            local obj = {}
            skip()
            if s:sub(i, i) == "}" then i = i + 1 return obj end
            while true do
                skip()
                local key = parse()
                skip()
                if s:sub(i, i) ~= ":" then error("json colon at " .. i) end
                i = i + 1
                obj[key] = parse()
                skip()
                local sep = s:sub(i, i)
                i = i + 1
                if sep == "}" then return obj end
                if sep ~= "," then error("json object at " .. i) end
            end
        elseif c == "[" then
            i = i + 1
            local arr = {}
            skip()
            if s:sub(i, i) == "]" then i = i + 1 return arr end
            while true do
                arr[#arr + 1] = parse()
                skip()
                local sep = s:sub(i, i)
                i = i + 1
                if sep == "]" then return arr end
                if sep ~= "," then error("json array at " .. i) end
            end
        elseif c == '"' then
            i = i + 1
            local out = {}
            while i <= n do
                local ch = s:sub(i, i)
                if ch == "\\" then
                    local nxt = s:sub(i + 1, i + 1)
                    if nxt == "n" then out[#out + 1] = "\n"
                    elseif nxt == "t" then out[#out + 1] = "\t"
                    elseif nxt == "r" then out[#out + 1] = "\r"
                    else out[#out + 1] = nxt end
                    i = i + 2
                elseif ch == '"' then
                    i = i + 1
                    return table.concat(out)
                else
                    out[#out + 1] = ch
                    i = i + 1
                end
            end
            error("json string")
        elseif c == "t" then
            i = i + 4
            return true
        elseif c == "f" then
            i = i + 5
            return false
        elseif c == "n" then
            i = i + 4
            return nil
        else
            local num = s:sub(i):match("^-?%d+%.?%d*[eE]?[-+]?%d*")
            if not num or num == "" then error("json value at " .. i .. ": " .. s:sub(i, i + 20)) end
            i = i + #num
            return tonumber(num)
        end
    end
    if s == nil or s == "" then return nil end
    return parse()
end

local function note(ev)
    if not armed then return end
    ev.key = current.key
    ev.n = current.n
    events[#events + 1] = ev
end

local function args_of(tbl)
    local args = {}
    if type(tbl) == "table" and type(tbl.args) == "table" then
        for i = 1, #tbl.args do args[i] = tostring(tbl.args[i]) end
    end
    return args
end

local props = {
    ["video-params/w"] = 1280,
    ["video-params/h"] = 720,
    path = "fd://0",
    volume = 100,
    pause = false,
    mute = false,
    pid = 1,
    ["hwdec-current"] = "no",
}
local opts = {
    ["timeshift-file"] = os.getenv("YAGI_TIMESHIFT_FILE") or "",
    tune = "8.1",
    cli = "yagi",
}

local function missing(name)
    return function(...)
        io.stderr:write("missing mp." .. name .. "\n")
        os.exit(1)
    end
end

mp = {}
setmetatable(mp, {__index = function(_, name) return missing(name) end})

function mp.get_opt(name)
    return opts[name]
end
function mp.get_property(name)
    local value = props[name]
    if value == nil then return nil end
    return value
end
function mp.get_property_number(name, default)
    local value = props[name]
    if type(value) == "number" then return value end
    return default
end
function mp.get_property_bool(name, default)
    local value = props[name]
    if type(value) == "boolean" then return value end
    return default
end
function mp.get_property_native(name)
    if name == "track-list" then return {} end
    if name == "video-params/h" then return props["video-params/h"] end
    if name == "video-frame-info/interlaced" then return false end
    return nil
end
function mp.set_property() end
function mp.set_property_number() end
function mp.get_time() return 1000 end
function mp.osd_message() end
mp.msg = {
    error = function(text)
        io.stderr:write("HUDERR " .. tostring(text) .. "\n")
        note({kind = "error", text = tostring(text)})
    end,
    warn = function() end,
    info = function() end,
    fatal = function(text)
        io.stderr:write("HUDERR " .. tostring(text) .. "\n")
        os.exit(1)
    end,
}
function mp.create_osd_overlay()
    return {
        data = "", res_x = 1280, res_y = 720, z = 0,
        update = function() end,
        remove = function() end,
    }
end
function mp.command(text)
    note({kind = "command", text = tostring(text)})
end
function mp.commandv(...)
    local args = {}
    for i = 1, select("#", ...) do args[i] = tostring(select(i, ...)) end
    note({kind = "commandv", args = args})
end
function mp.command_native(tbl)
    note({kind = "native", name = type(tbl) == "table" and tostring(tbl.name or "") or ""})
end
function mp.command_native_async(tbl, cb)
    note({
        kind = "async",
        args = args_of(tbl),
        stdin = type(tbl) == "table" and tostring(tbl.stdin_data or "") or "",
        detach = type(tbl) == "table" and tbl.detach == true or false,
    })
    if cb then cb(true, {status = 0}) end
end
function mp.add_forced_key_binding(key, _, fn, ...)
    bindings[key] = fn
end
function mp.add_timeout()
    return {kill = function() end}
end
function mp.add_periodic_timer()
    return {kill = function() end, stop = function() end, resume = function() end}
end
function mp.observe_property() end
function mp.register_event() end
function mp.register_script_message() end
function mp.add_hook() end

package.preload["mp.utils"] = function()
    return {
        file_info = function(path)
            local f = io.open(path or "", "rb")
            if not f then return nil end
            local size = f:seek("end")
            f:close()
            return {size = size, mtime = 1}
        end,
        parse_json = parse_json,
        format_json = format_json,
    }
end

local ok, err = pcall(dofile, hud)
if not ok then
    io.stderr:write("LOAD " .. tostring(err) .. "\n")
    os.exit(1)
end

local function press(key)
    current.n = current.n + 1
    current.key = key
    local fn = bindings[key]
    if type(fn) ~= "function" then
        io.stderr:write("no handler for " .. key .. "\n")
        os.exit(1)
    end
    local ran, press_err = pcall(fn)
    if not ran then
        io.stderr:write("PRESS " .. key .. " " .. tostring(press_err) .. "\n")
        os.exit(1)
    end
end

armed = true
for _, key in ipairs({
    "j", "k", "LEFT", "RIGHT", "UP", "DOWN", "SPACE", "l", "f",
    "MBTN_LEFT_DBL", "ESC", "i", "m", "y", "WHEEL_UP", "WHEEL_DOWN", "r",
}) do
    press(key)
end

local cfg = os.getenv("XDG_CONFIG_HOME") or ""
local rec = io.open(cfg .. "/yagi/recordings_active.json", "w")
if not rec then
    io.stderr:write("cannot write recordings\n")
    os.exit(1)
end
rec:write('[{"tune_name":"FOX","channel_number":"8.1"}]')
rec:close()
press("r")

io.write(format_json(events))
io.write("\n")
