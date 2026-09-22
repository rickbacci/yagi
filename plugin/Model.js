// Omarchy TV - Model and Helpers

function formatFreq(freqHz) {
  if (!freqHz) return "";
  var mhz = (freqHz / 1000000.0).toFixed(1);
  return mhz + " MHz";
}

function cleanChannelName(name) {
  if (!name) return "Unknown Station";
  return name.replace(/_/g, " ").trim();
}

function bandColor(band, accent, foreground) {
  if (band === "UHF") return accent;
  if (band === "VHF-High") return "#89b4fa"; // Soft Blue
  if (band === "VHF-Low") return "#f9e2af";  // Soft Amber
  return foreground;
}

function networkColor(network, fallback) {
  var n = String(network || "").toUpperCase()
  if (n === "NBC" || n === "CW") return "#A6E3A1"
  if (n === "ABC") return "#F9E2AF"
  if (n === "FOX") return "#B489FA"
  if (n === "CBS") return "#CBA6F7"
  if (n === "PBS") return "#94E2D5"
  if (n === "UNIVISION") return "#F38BA8"
  return fallback
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

function currentProgram(item, nowMin) {
  var now = (nowMin === undefined || nowMin === null || nowMin < 0) ? minutesNow() : nowMin
  return coveringProgram(programsFor(item), formatSlot(now))
}

function coveringProgram(programs, slotLabel) {
  var t = parseMinutes(slotLabel)
  if (t < 0) return null
  for (var i = 0; i < programs.length; i++) {
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

function searchGuide(guideData, query, nowMin) {
  var words = String(query || "").toLowerCase().split(/\s+/).filter(function(w) { return w })
  if (words.join(" ").length < 2 || !guideData) return []
  var now = (nowMin === undefined || nowMin === null || nowMin < 0) ? minutesNow() : nowMin
  var hits = []
  for (var num in guideData) {
    var row = guideData[num]
    if (!row) continue
    var programs = row.programs || []
    var i
    for (i = 0; i < programs.length; i++) {
      var prog = programs[i]
      var title = String((prog && prog.title) || "")
      var folded = title.toLowerCase()
      var ok = !!title
      var w
      for (w = 0; w < words.length; w++) {
        if (folded.indexOf(words[w]) === -1) ok = false
      }
      if (!ok) continue
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
    var ta = parseMinutes(a.start)
    var tb = parseMinutes(b.start)
    if (ta !== tb) return ta - tb
    return (parseFloat(a.channel_number) || 999) - (parseFloat(b.channel_number) || 999)
  })
  return hits
}

function programUnix(prog) {
  var gps = Number(prog && prog.gps_start) || 0
  if (gps <= 0) return 0
  return gps + 315964800 - 18
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
