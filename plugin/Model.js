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

// Nicknames only, for games a station lists with no description.
var TEAMS = {
  football: "bears bengals bills broncos browns buccaneers bucs cardinals chargers chiefs colts commanders cowboys dolphins eagles falcons 49ers niners giants jaguars jags jets lions packers panthers patriots pats raiders rams ravens saints seahawks steelers texans titans vikings",
  basketball: "hawks celtics nets hornets bulls cavaliers cavs mavericks mavs nuggets pistons warriors rockets pacers clippers lakers grizzlies heat bucks timberwolves wolves pelicans knicks thunder magic 76ers sixers suns blazers kings spurs raptors jazz wizards",
  baseball: "diamondbacks dbacks braves orioles sox cubs reds guardians rockies tigers astros royals angels dodgers marlins brewers twins mets yankees athletics phillies pirates padres giants mariners cardinals rays rangers jays nationals nats",
  hockey: "ducks bruins sabres flames hurricanes canes blackhawks avalanche avs jackets stars wings oilers panthers kings wild canadiens habs predators preds devils islanders rangers senators sens flyers penguins pens sharks kraken blues lightning leafs canucks knights capitals caps jets"
}
var SPORT_WORDS = { football: /football|\bnfl\b/, basketball: /basketball|\bnba\b/, baseball: /baseball|\bmlb\b/, hockey: /hockey|\bnhl\b/ }

function _teamSport(words, title) {
  for (var sport in SPORT_WORDS) {
    if (!SPORT_WORDS[sport].test(title)) continue
    var teams = " " + TEAMS[sport] + " "
    for (var w = 0; w < words.length; w++) if (teams.indexOf(" " + words[w] + " ") !== -1) return sport
  }
  return ""
}

// Games list as "NFL Football" with the teams only in the description, so a
// title miss still counts when every word is in the description. A game with
// no description is a maybe when a word is a team in its sport.
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
  if (inTitle || inAbout) return { by_title: inTitle }
  if (!about && isGameTitle(title) && _teamSport(words, folded)) return { by_title: false, maybe: true }
  return null
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

function channelLabel(rec) {
  return (String((rec && rec.channel_number) || "") + " " + String((rec && rec.station) || "")).trim()
}

// "Today", "Yesterday", a weekday inside the last week, else "Mon Oct 5".
function recentDay(unix, nowUnix) {
  var days = Math.round((_midnight(nowUnix) - _midnight(unix)) / 86400)
  if (days <= 0) return "Today"
  if (days === 1) return "Yesterday"
  if (days < 7) return DAY_NAMES[new Date(Number(unix) * 1000).getDay()]
  return formatDay(unix)
}

// Episode title inside a show: "7:28–7:59 PM". The day is the header above it.
function recordingClock(rec, nowUnix) {
  var start = recordingStart(rec)
  if (!start) return ""
  if (recordingLive(rec)) return formatClock(start)
  var end = Number(rec.end || rec.mtime) || start
  return formatSpan(start, end)
}

// "Today 7:28–7:59 PM". A recording still in progress has a start only.
function recordingWhen(rec, nowUnix) {
  var start = recordingStart(rec)
  if (!start) return ""
  var clock = recordingClock(rec, nowUnix)
  return clock ? recentDay(start, nowUnix) + " " + clock : ""
}

function recordingStamp(rec, nowUnix) {
  var start = recordingStart(rec)
  if (!start) return ""
  return recentDay(start, nowUnix) + " " + formatClock(start)
}

function recordingBlurb(rec) {
  return String(rec && rec.synopsis || "").replace(/\s+/g, " ").trim()
}

// Length and the ad breaks playback skips. The live pin also names the channel.
function recordingDetail(rec, nowUnix, kind) {
  if (!rec) return ""
  var start = recordingStart(rec)
  var live = recordingLive(rec)
  var end = live ? nowUnix : (Number(rec.end || rec.mtime) || start)
  var parts = []
  if (live) parts.push("● Recording")
  parts.push(formatLength(end - start))
  if (rec.playable === false && !live) parts.push("nothing recorded")
  if (kind === "live") {
    var ch = channelLabel(rec)
    if (ch) parts.push(ch)
  }
  var ads = Number(rec.ads) || 0
  if (ads > 0) parts.push(ads === 1 ? "skips 1 ad break" : "skips " + ads + " ad breaks")
  return parts.join(" · ")
}

// One show is a folded title on one channel, any hour. Enter opens it; Esc backs out. Episodes stay newest first.
function groupRecordings(sorted) {
  var out = []
  var at = {}
  var list = sorted || []
  for (var i = 0; i < list.length; i++) {
    var rec = list[i]
    if (!rec) continue
    var key = showKey(rec.title, rec.channel_number)
    var show = at[key]
    if (!show) {
      show = {
        key: key,
        title: rec.title || rec.name || "Recording",
        channel: String(rec.channel_number || ""),
        station: String(rec.station || ""),
        episodes: []
      }
      at[key] = show
      out.push(show)
    }
    show.episodes.push(rec)
  }
  return out
}

// A blurb every episode shares is the series, not the episode.
function episodeBlurb(show, rec) {
  var text = recordingBlurb(rec)
  var eps = (show && show.episodes) || []
  if (!text || eps.length < 2) return text
  for (var i = 0; i < eps.length; i++) {
    if (recordingBlurb(eps[i]) !== text) return text
  }
  return ""
}

function showLine(show, nowUnix) {
  if (!show) return ""
  var parts = []
  var eps = show.episodes || []
  var ch = (String(show.channel || "") + " " + String(show.station || "")).trim()
  if (ch) parts.push(ch)
  if (eps.length > 1) parts.push(String(eps.length))
  if (eps.length) {
    var stamp = recordingStamp(eps[0], nowUnix)
    if (stamp) parts.push(stamp)
  }
  return parts.join(" · ")
}

function showSubtitle(show) {
  if (!show) return ""
  var parts = []
  var ch = (String(show.channel || "") + " " + String(show.station || "")).trim()
  if (ch) parts.push(ch)
  var n = (show.episodes || []).length
  parts.push(n === 1 ? "1 episode" : (n + " episodes"))
  return parts.join(" · ")
}

function showByKey(sorted, key) {
  if (!key) return null
  var shows = groupRecordings(sorted)
  for (var i = 0; i < shows.length; i++) {
    if (shows[i].key === key) return shows[i]
  }
  return null
}

// Show list, or one show's episodes. A recording in progress is pinned above the shows.
function recordedPicks(sorted, nowUnix, openKey) {
  var shows = groupRecordings(sorted)
  var out = []
  var i
  if (openKey) {
    var show = null
    for (i = 0; i < shows.length; i++) if (shows[i].key === openKey) show = shows[i]
    if (!show) return out
    var lastDay = ""
    var pick = 0
    for (i = 0; i < show.episodes.length; i++) {
      var ep = show.episodes[i]
      var day = recentDay(recordingStart(ep), nowUnix)
      if (day !== lastDay) {
        out.push({ kind: "header", title: day, pick: -1 })
        lastDay = day
      }
      out.push({
        kind: "episode",
        rec: ep,
        title: recordingClock(ep, nowUnix),
        detail: recordingDetail(ep, nowUnix, "episode"),
        blurb: episodeBlurb(show, ep),
        pick: pick++
      })
    }
    return out
  } else {
    var list = sorted || []
    for (i = 0; i < list.length; i++) {
      if (!recordingLive(list[i])) continue
      out.push({
        kind: "live",
        rec: list[i],
        title: list[i].title || list[i].name || "",
        detail: recordingDetail(list[i], nowUnix, "live"),
        blurb: ""
      })
    }
    for (i = 0; i < shows.length; i++) {
      out.push({ kind: "show", show: shows[i], line: showLine(shows[i], nowUnix), blurb: "" })
    }
    for (i = 0; i < out.length; i++) out[i].pick = i
  }
  return out
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
        maybe: !!(hit && hit.maybe),
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
