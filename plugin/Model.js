// Yagi - Model and Helpers

function formatFreq(freqHz) {
  if (!freqHz) return "";
  var mhz = (freqHz / 1000000.0).toFixed(1);
  return mhz + " MHz";
}

function cleanChannelName(name) {
  if (!name) return "Unknown Station";
  return name.replace(/_/g, " ").trim();
}

function minutesNow() {
  var d = new Date()
  return d.getHours() * 60 + d.getMinutes()
}

function getChannelBadge(channel) {
  if (!channel) return "OTA";
  if (channel.channel_number) return channel.channel_number;
  if (channel.service_id) return "#" + channel.service_id;
  return "OTA";
}

function getDisplayTitle(channel) {
  if (!channel) return "Unknown Station";
  if (channel.display_name) return channel.display_name;
  return cleanChannelName(channel.name);
}

function _normIdent(s) {
  return String(s || "").replace(/\s+/g, " ").trim().toLowerCase();
}

function matchGuideProgram(ch, guideData) {
  if (!guideData || !ch) return null;
  if (ch.channel_number && guideData[ch.channel_number]) {
    return guideData[ch.channel_number];
  }
  var names = [];
  var keys = ["name", "raw_name", "tune_name", "callsign"];
  for (var i = 0; i < keys.length; i++) {
    var ident = _normIdent(ch[keys[i]]);
    if (ident) names.push(ident);
  }
  for (var k in guideData) {
    var p = guideData[k];
    var station = _normIdent(p && p.station);
    if (station && names.indexOf(station) !== -1) return p;
  }
  return null;
}

function parseMinutes(label) {
  var s = String(label || "").trim()
  var m = s.match(/^(\d{1,2}):(\d{2})\s*(AM|PM)$/i)
  if (!m) return -1
  var h = parseInt(m[1], 10)
  var min = parseInt(m[2], 10)
  var ap = m[3].toUpperCase()
  if (h === 12) h = 0
  if (ap === "PM") h += 12
  return h * 60 + min
}

function formatSlot(minutes) {
  var h24 = ((Math.floor(minutes / 60) % 24) + 24) % 24
  var min = minutes % 60
  var ap = h24 >= 12 ? "PM" : "AM"
  var h = h24 % 12
  if (h === 0) h = 12
  return h + ":" + (min < 10 ? "0" : "") + min + " " + ap
}

function programsFor(item) {
  if (item && item.programs && item.programs.length) return item.programs
  var out = []
  if (item && item.title && item.start_time)
    out.push({ start: item.start_time, end: item.end_time || "", title: item.title })
  if (item && item.next_title)
    out.push({ start: item.end_time || "", end: "", title: item.next_title })
  return out
}

function airingCoversNow(prog, nowUnix) {
  var start = programUnix(prog)
  if (start <= 0) return null
  var dur = Number(prog && prog.duration_sec) || 0
  if (dur <= 0) dur = 30 * 60
  var now = Number(nowUnix) || (Date.now() / 1000)
  return now >= start && now < start + dur
}

// 0..1 through the show, or -1 without a broadcast start time. nowMin only
// makes a binding re-run on the flyout clock.
function airingProgress(prog, nowMin) {
  var start = programUnix(prog)
  var dur = Number(prog && prog.duration_sec) || 0
  if (start <= 0 || dur <= 0) return -1
  var f = (Date.now() / 1000 - start) / dur
  return Math.max(0, Math.min(1, f))
}

function channelSubLine(stationName, next) {
  var name = String(stationName || "")
  if (!next || !next.title) return name
  var when = String(next.start || next.start_time || "")
  var tail = "Next " + (when ? when + " " : "") + next.title
  return name ? name + " · " + tail : tail
}

function currentProgram(item, nowMin) {
  var now = (nowMin === undefined || nowMin === null || nowMin < 0) ? minutesNow() : nowMin
  return coveringProgram(programsFor(item), formatSlot(now))
}

function nextProgram(item, nowMin) {
  var programs = programsFor(item)
  var now = currentProgram(item, nowMin)
  if (!now) return null
  var i
  for (i = 0; i < programs.length; i++) {
    if (programs[i] === now) return programs[i + 1] || null
  }
  return null
}

function coveringProgram(programs, slotLabel) {
  var dated = false
  var i
  for (i = 0; i < programs.length; i++) {
    if (programUnix(programs[i]) > 0) {
      dated = true
      if (airingCoversNow(programs[i])) return programs[i]
    }
  }
  if (dated) return null
  var t = parseMinutes(slotLabel)
  if (t < 0) return null
  for (i = 0; i < programs.length; i++) {
    var p = programs[i]
    var a = parseMinutes(p.start || p.start_time)
    var b = parseMinutes(p.end || p.end_time)
    if (a < 0) continue
    if (b < 0) b = a + 30
    var clock = t
    if (b <= a) {
      b += 24 * 60
      if (clock < a) clock += 24 * 60
    }
    if (clock >= a && clock < b) return p
  }
  return null
}

function showIsOn(block, nowMin) {
  if (!block || block.empty) return false
  if (programUnix(block) > 0) return !!airingCoversNow(block)
  if (block.now) return true
  var now = (nowMin === undefined || nowMin === null) ? minutesNow() : nowMin
  var a = parseMinutes(block.start || block.start_time)
  var b = parseMinutes(block.end || block.end_time)
  if (a < 0) return true
  if (b < 0) b = a + 30
  var clock = now
  if (b <= a) {
    b += 24 * 60
    if (clock < a) clock += 24 * 60
  }
  return clock >= a && clock < b
}

function recordDurationArg(block, nowMin) {
  if (!block) return ""
  if (programUnix(block) > 0) {
    var start = programUnix(block)
    var dur = Number(block.duration_sec) || 0
    if (dur <= 0) dur = 30 * 60
    var stamp = Date.now() / 1000
    if (stamp >= start + dur) return ""
    var remainSec = (stamp < start) ? dur : (start + dur - stamp)
    return Math.max(1, Math.round(remainSec / 60)) + "m"
  }
  var now = (nowMin === undefined || nowMin === null) ? minutesNow() : nowMin
  var a = parseMinutes(block.start || block.start_time)
  var b = parseMinutes(block.end || block.end_time)
  if (a >= 0) {
    if (b < 0) b = a + 30
    var clock = now
    if (b <= a) {
      b += 24 * 60
      if (clock < a) clock += 24 * 60
    }
    var remain = b - Math.max(clock, a)
    if (remain > 0) return remain + "m"
  }
  var sec = Number(block.duration_sec) || 0
  if (sec > 0) return Math.max(1, Math.round(sec / 60)) + "m"
  return ""
}

function _neighborShow(prog) {
  if (!prog || !prog.title) return null
  return {
    title: prog.title || "",
    start: prog.start || prog.start_time || "",
    end: prog.end || prog.end_time || ""
  }
}

function _hasWord(text, word) {
  var at = text.indexOf(word)
  while (at !== -1) {
    if (at === 0 || !/[a-z0-9]/.test(text.charAt(at - 1))) return true
    at = text.indexOf(word, at + 1)
  }
  return false
}

function queryWords(query) {
  var words = String(query || "").toLowerCase().split(/\s+/).filter(function(w) { return w })
  return words.join(" ").length < 2 ? [] : words
}

// Games list as "NFL Football" with the teams only in the description, so a
// title miss still counts when every word is in the description.
function progMatch(prog, words) {
  var title = String((prog && prog.title) || "")
  if (!words.length || !title || isFillerTitle(title)) return null
  var folded = title.toLowerCase()
  var about = String((prog && prog.synopsis) || "").toLowerCase()
  var inTitle = true
  var inAbout = !!about
  for (var w = 0; w < words.length; w++) {
    if (!_hasWord(folded, words[w])) inTitle = false
    if (!_hasWord(folded, words[w]) && !_hasWord(about, words[w])) inAbout = false
  }
  return (inTitle || inAbout) ? { by_title: inTitle } : null
}

function searchGuide(guideData, query, nowMin) {
  var words = queryWords(query)
  if (!words.length || !guideData) return []
  var now = (nowMin === undefined || nowMin === null || nowMin < 0) ? minutesNow() : nowMin
  var nowUnix = Date.now() / 1000
  var hits = []
  for (var num in guideData) {
    var row = guideData[num]
    if (!row) continue
    var programs = row.programs || []
    var i
    for (i = 0; i < programs.length; i++) {
      var prog = programs[i]
      var title = String((prog && prog.title) || "")
      var began = programUnix(prog)
      if (began > 0 && began + (Number(prog.duration_sec) || 1800) <= nowUnix) continue
      var found = progMatch(prog, words)
      if (!found) continue
      var inTitle = found.by_title
      var block = {
        title: title,
        start: prog.start || "",
        end: prog.end || "",
        synopsis: prog.synopsis || "",
        usual: prog.usual || "",
        also: prog.also || "",
        duration_sec: Number(prog.duration_sec) || 0,
        now: showIsOn(prog, now),
        empty: false,
        before: _neighborShow(i > 0 ? programs[i - 1] : null),
        after: _neighborShow(i + 1 < programs.length ? programs[i + 1] : null)
      }
        hits.push({
        channel_number: String(num),
        callsign: row.callsign || row.station || "",
        tune_name: row.tune_name || "",
        station: row.station || row.callsign || "",
        network: row.network || "",
        display_name: row.display_name || "",
        title: title,
        synopsis: block.synopsis,
        by_title: inTitle,
        start: block.start,
        end: block.end,
        gps_start: Number(prog.gps_start) || 0,
        duration_sec: block.duration_sec,
        on_now: block.now,
        usual: block.usual,
        also: block.also,
        before: block.before,
        after: block.after,
        block: block
      })
    }
  }
  hits.sort(function(a, b) {
    var ua = programUnix(a)
    var ub = programUnix(b)
    if (ua && ub && ua !== ub) return ua - ub
    if (!ua || !ub) {
      var ta = parseMinutes(a.start)
      var tb = parseMinutes(b.start)
      if (ta !== tb) return ta - tb
    }
    return (parseFloat(a.channel_number) || 999) - (parseFloat(b.channel_number) || 999)
  })
  return hits
}

// Same cut as engine/shows.py bucket_for.
function bucketNow() {
  var h = new Date().getHours()
  if (h >= 20 && h < 23) return "prime"
  if (h >= 23 || h < 2) return "late"
  if (h >= 2 && h < 6) return "overnight"
  return "day"
}

// The Shows tab filter: every word in the title.
function filterShowsByQuery(shows, query) {
  var words = queryWords(query)
  if (!words.length) return shows || []
  return (shows || []).filter(function(s) { return !!progMatch({ title: s && s.title }, words) })
}

// Shows with a pattern first, then one-offs. Each keeps its start-time order.
function filterShows(shows, bucket) {
  var regular = []
  var once = []
  for (var i = 0; i < (shows || []).length; i++) {
    var s = shows[i]
    if (!s || (s.buckets || []).indexOf(bucket) === -1) continue
    if (s.pattern) regular.push(s)
    else once.push(s)
  }
  return regular.concat(once)
}

// Same as engine/guide.py _fold_title, so MASH and M*A*S*H are one show.
function foldTitle(title) {
  var out = ""
  var s = String(title || "").toLowerCase()
  for (var i = 0; i < s.length; i++) {
    var ch = s.charAt(i)
    if (/[0-9]/.test(ch) || ch.toLowerCase() !== ch.toUpperCase()) out += ch
    else if (/\s/.test(ch)) out += " "
  }
  return out.split(/\s+/).filter(function(w) { return w }).join(" ")
}

function showKey(title, channel) {
  return foldTitle(title) + "|" + String(channel || "")
}

// The show's next airing in the shape a search hit has, so Watch and Record treat them alike.
function showAiring(show) {
  var n = show && show.next
  if (!n || !show.tune_name || !(Number(n.start_unix) > 0)) return null
  return {
    tune_name: show.tune_name,
    channel_number: show.channel || "",
    title: show.title || "",
    gps_start: Number(n.start_unix) - 315964800 + 18,
    duration_sec: Number(n.duration_sec) || 1800,
    start: n.clock || "",
    end: "",
    on_now: !!n.on_now,
    display_name: show.tune_name
  }
}

function showSubLine(show, stationName) {
  if (!show) return ""
  var parts = [(show.channel || "") + (stationName ? " " + stationName : "")]
  parts.push(show.pattern ? (show.label || show.when || "") : "One airing " + (show.when || ""))
  var n = show.next
  if (n) parts.push((n.on_now ? "on now" : "next " + (n.day || "") + " " + (n.clock || "")).trim())
  return parts.filter(function(p) { return p }).join(" · ")
}

// Live games run past their slot. The pregame and postgame shows do not.
function gameExtraMin() {
  return 45
}

function isGameTitle(title) {
  var t = String(title || "").toLowerCase()
  if (/pregame|postgame|kickoff|today|tonight|countdown|review|highlights|preview/.test(t)) return false
  return /\b(football|baseball|basketball|hockey|soccer)\b|^(nfl|nba|mlb|nhl|mls|ncaa)\b/.test(t)
}

var FILLER_TITLES = ["paid programming", "paid program", "programa pagado", "to be announced"]

function isFillerTitle(title) {
  return FILLER_TITLES.indexOf(String(title || "").trim().toLowerCase()) !== -1
}

function programUnix(prog) {
  var gps = Number(prog && prog.gps_start) || 0
  if (gps <= 0) return 0
  return gps + 315964800 - 18
}

function formatClock(unix) {
  var d = new Date(Number(unix) * 1000)
  var h24 = d.getHours()
  var h = h24 % 12
  if (h === 0) h = 12
  var m = d.getMinutes()
  return h + ":" + (m < 10 ? "0" : "") + m + " " + (h24 >= 12 ? "PM" : "AM")
}

var DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
var MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

function _midnight(unix) {
  var d = new Date(Number(unix) * 1000)
  d.setHours(0, 0, 0, 0)
  return d.getTime() / 1000
}

function formatDay(unix) {
  var d = new Date(Number(unix) * 1000)
  return DAY_NAMES[d.getDay()] + " " + MONTH_NAMES[d.getMonth()] + " " + d.getDate()
}

// "Today", "Yesterday · Fri Sep 25", then "Thu Sep 24".
function dayLabel(unix, nowUnix) {
  var days = Math.round((_midnight(nowUnix) - _midnight(unix)) / 86400)
  if (days <= 0) return "Today"
  if (days === 1) return "Yesterday · " + formatDay(unix)
  return formatDay(unix)
}

// "Today", "Tomorrow", "Mon", then "Mon Oct 5", for things still to come.
function dayWord(unix, nowUnix) {
  var days = Math.round((_midnight(unix) - _midnight(nowUnix)) / 86400)
  if (days <= 0) return "Today"
  if (days === 1) return "Tomorrow"
  if (days < 7) return DAY_NAMES[new Date(unix * 1000).getDay()]
  return formatDay(unix)
}

// "8:03–8:11 PM"; the first AM/PM goes when both match.
function formatSpan(start, end) {
  var a = formatClock(start)
  var b = formatClock(end)
  if (a.slice(-2) === b.slice(-2)) a = a.slice(0, -3)
  return a + "–" + b
}

function formatLength(sec) {
  var min = Math.max(0, Math.round(Number(sec) / 60))
  if (min < 60) return min + " min"
  var h = Math.floor(min / 60)
  var m = min % 60
  return h + " h" + (m ? " " + m + " min" : "")
}

function recordingStart(rec) {
  return Number(rec && (rec.start || rec.mtime)) || 0
}

function recordingLive(rec) {
  return !!rec && rec.status === "recording" && !rec.end
}

// Newest first, by when it aired.
function sortRecordings(recs) {
  return (recs || []).slice().sort(function(a, b) { return recordingStart(b) - recordingStart(a) })
}

// Day headers between recordings; index points into the sorted list.
function recordedRows(sorted, nowUnix) {
  var out = []
  var last = ""
  for (var i = 0; i < (sorted || []).length; i++) {
    var label = dayLabel(recordingStart(sorted[i]), nowUnix)
    if (label !== last) {
      out.push({ header: label, index: -1 })
      last = label
    }
    out.push({ header: "", index: i, rec: sorted[i] })
  }
  return out
}

// How much is recorded, its size, and the ad breaks playback skips.
function recordingLine(rec, nowUnix) {
  if (!rec) return ""
  var start = recordingStart(rec)
  var live = recordingLive(rec)
  var parts = []
  if (live) parts.push("● Recording")
  parts.push(formatLength((live ? nowUnix : (Number(rec.end || rec.mtime) || start)) - start))
  if (rec.playable === false && !live) parts.push("nothing recorded")
  else if (rec.size_formatted) parts.push(rec.size_formatted)
  if (rec.ads > 0) parts.push(rec.ads === 1 ? "skips 1 ad break" : "skips " + rec.ads + " ad breaks")
  return parts.join(" · ")
}

// Scheduled tab: what is recording, what waits, then each series.
function scheduledRows(active, waiting, rules, nowUnix, stationOf) {
  var out = []
  var upcoming = []
  var i
  for (i = 0; i < (active || []).length; i++) {
    var a = active[i]
    if (!a) continue
    var aStart = Number(a.start_time) || nowUnix
    upcoming.push({ kind: "active", key: "active:" + (a.session_id || i), item: a,
                    title: a.program_title || a.station || "Recording",
                    line: "Recording until " + formatClock(aStart + (Number(a.duration_seconds) || 0))
                          + " · " + ((a.channel_number || "") + " " + (a.station || "")).trim(),
                    live: true, series: false })
  }
  for (i = 0; i < (waiting || []).length; i++) {
    var w = waiting[i]
    if (!w) continue
    var ws = Number(w.start_unix) || 0
    var wLine = ws ? dayWord(ws, nowUnix) + " " + formatSpan(ws, ws + (Number(w.duration_sec) || 0)) : (w.clock || "")
    upcoming.push({ kind: "waiting", key: "waiting:" + w.id, item: w, title: w.title || "Scheduled",
                    line: (w.status === "missed" ? "Missed · " : "") + wLine + " · " + (w.display_name || w.tune_name || ""),
                    missed: w.status === "missed", series: !!w.rule_id })
  }
  if (upcoming.length) out.push({ kind: "header", key: "h:upcoming", title: "Upcoming" })
  out = out.concat(upcoming)
  var series = []
  for (i = 0; i < (rules || []).length; i++) {
    var r = rules[i]
    if (!r || !r.id) continue
    var next = 0
    for (var j = 0; j < (waiting || []).length; j++) {
      var s = waiting[j]
      if (s && s.rule_id === r.id && s.status !== "missed" && (!next || s.start_unix < next)) next = Number(s.start_unix) || 0
    }
    var station = (stationOf && stationOf(r.channel)) || r.tune_name || ""
    series.push({ kind: "series", key: "series:" + r.id, item: r, title: r.title || "Series",
                  line: ((r.channel || "") + " " + station).trim() + " · "
                        + (next ? "next " + dayWord(next, nowUnix) + " " + formatClock(next) : "next not listed yet"),
                  keep: Number(r.keep_last) || 0 })
  }
  if (series.length) out.push({ kind: "header", key: "h:series", title: "Series" })
  out = out.concat(series)
  var pick = 0
  for (i = 0; i < out.length; i++) out[i].pick = out[i].kind === "header" ? -1 : pick++
  return out
}

function scheduledCount(rows) {
  return (rows || []).filter(function(r) { return r.kind !== "header" }).length
}

// The grid opens on the half hour now is in and runs to the last listing,
// three hours at least and eight at most. Listings reach about five hours.
var GRID_STEP = 1800
var GRID_MIN_SEC = 3 * 3600
var GRID_MAX_SEC = 8 * 3600

function gridStart(nowUnix) {
  var n = Math.floor(Number(nowUnix) || Date.now() / 1000)
  return n - (n % GRID_STEP)
}

// One row per channel. Searching keeps only channels with a match, whatever
// the channel tab; outside marks a channel the tab would not have shown.
function gridRows(channels, guideData, t0, nowUnix, query, shown) {
  var words = queryWords(query)
  var cap = t0 + GRID_MAX_SEC
  var now = Number(nowUnix) || Date.now() / 1000
  var out = []
  var list = channels || []
  for (var i = 0; i < list.length; i++) {
    var ch = list[i]
    var row = matchGuideProgram(ch, guideData) || {}
    var programs = row.programs || []
    var blocks = []
    var matches = 0
    for (var j = 0; j < programs.length; j++) {
      var prog = programs[j]
      var start = programUnix(prog)
      if (start <= 0) continue
      var dur = Number(prog.duration_sec) || 1800
      var end = start + dur
      if (end <= t0 || start >= cap) continue
      var hit = words.length ? progMatch(prog, words) : null
      if (hit) matches++
      blocks.push({
        title: String(prog.title || ""),
        synopsis: String(prog.synopsis || ""),
        start: start,
        end: end,
        x0: Math.max(start, t0),
        x1: Math.min(end, cap),
        began_before: start < t0,
        on_now: start <= now && now < end,
        match: !!hit,
        channel_number: String(ch.channel_number || ""),
        tune_name: ch.tune_name || ch.name || row.tune_name || "",
        display_name: getDisplayTitle(ch),
        gps_start: Number(prog.gps_start) || 0,
        duration_sec: dur
      })
    }
    blocks.sort(function(a, b) { return a.start - b.start })
    if (words.length && !matches) continue
    out.push({ channel: ch, blocks: blocks, matches: matches, outside: !!(words.length && shown && shown.indexOf(ch) === -1) })
  }
  return out
}

function gridEnd(rows, t0) {
  var end = t0 + GRID_MIN_SEC
  for (var i = 0; i < (rows || []).length; i++) {
    var blocks = rows[i].blocks || []
    for (var j = 0; j < blocks.length; j++) end = Math.max(end, blocks[j].x1)
  }
  return Math.min(end, t0 + GRID_MAX_SEC)
}

function gridMatchCount(rows) {
  var n = 0
  for (var i = 0; i < (rows || []).length; i++) n += rows[i].matches || 0
  return n
}

// The block airing at time t, or the nearest one after it, or the last.
function blockAt(blocks, t) {
  var list = blocks || []
  for (var i = 0; i < list.length; i++) {
    if (list[i].x0 <= t && t < list[i].x1) return i
    if (list[i].x0 > t) return i
  }
  return list.length - 1
}

// The shape toggleHitRecord and scheduledId read.
function blockAiring(b) {
  if (!b) return null
  return {
    tune_name: b.tune_name,
    channel_number: b.channel_number,
    title: b.title,
    synopsis: b.synopsis,
    gps_start: b.gps_start,
    duration_sec: b.duration_sec,
    start: formatClock(b.start),
    end: formatClock(b.end),
    on_now: b.on_now,
    display_name: b.display_name
  }
}

function guideHourBlocks(channels, nowUnix) {
  var now = Number(nowUnix) || (Date.now() / 1000)
  var last = now
  var list = channels || []
  var i, j, programs, unix
  for (i = 0; i < list.length; i++) {
    programs = (list[i] && list[i].programs) || []
    for (j = 0; j < programs.length; j++) {
      unix = programUnix(programs[j])
      if (unix > last) last = unix
    }
  }
  var step = 3 * 3600
  var start = now - (now % step)
  var blocks = []
  var end = Math.max(last, start + step)
  var t
  for (t = start; t < end; t += step) blocks.push(t)
  if (!blocks.length) blocks.push(start)
  return blocks
}

function fileUrlToPath(url) {
  var s = String(url || "")
  if (s.indexOf("file://") === 0)
    s = decodeURIComponent(s.slice(7))
  return s
}

function tvConfigDir(xdgConfigHome, home) {
  var xdg = String(xdgConfigHome || "")
  if (xdg.length)
    return xdg + "/yagi"
  return String(home || "") + "/.config/yagi"
}
