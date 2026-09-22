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

function slotIsNow(slotLabel, nowMin) {
  var t = parseMinutes(slotLabel)
  if (t < 0) return false
  if (nowMin === undefined || nowMin === null) nowMin = minutesNow()
  return nowMin >= t && nowMin < t + 30
}

function guidePlayIdent(item) {
  if (!item) return ""
  return item.tune_name || item.station || item.channel_number || ""
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

function isTranslator(ch) {
  if (!ch) return false;
  if (ch.is_translator === true) return true;
  var blob = ((ch.callsign || "") + " " + (ch.display_name || "") + " " + (ch.name || "")).toUpperCase();
  return blob.indexOf("DRT") !== -1 || blob.indexOf("TRANSLATOR") !== -1;
}

function channelKind(item) {
  if (!item) return ""
  if (item.kind) return String(item.kind)
  var blob = [item.network, item.display_name, item.callsign, item.station, item.name]
    .join(" ").toLowerCase().replace(/[!&-]+/g, " ").replace(/\s+/g, " ").trim()
  var padded = " " + blob + " "
  var rules = [
    ["kids", ["pbs kids", "metv toons", "toons"]],
    ["religious", ["daystar", "tbn", "tct", "insp"]],
    ["shop", ["shop lc", "shoplc", "hsn", "qvc", "jtv"]],
    ["movies", ["movies gold", "movies", "grit", "comet", "charge", "outlaw", "western"]],
    ["classic", ["antenna", "heroes", "rewind", "metv", "cozi", "laff", "buzzr", "catchy", "start tv", "ion plus", "bounce"]],
    ["network", ["univision", "unimas", "telemundo", "nbc", "abc", "cbs", "fox", "pbs", "ion", "cw"]]
  ]
  var r, p, phrase
  for (r = 0; r < rules.length; r++) {
    for (p = 0; p < rules[r][1].length; p++) {
      phrase = rules[r][1][p]
      if (phrase.indexOf(" ") !== -1) {
        if (blob.indexOf(phrase) !== -1) return rules[r][0]
      } else if (padded.indexOf(" " + phrase + " ") !== -1) {
        return rules[r][0]
      }
    }
  }
  return ""
}

function networkShort(network) {
  if (!network) return "";
  var n = String(network).replace(/\s+/g, " ").trim();
  if (!n) return "";
  var key = n.toUpperCase();
  if (key === "UNIVISION") return "UNI";
  if (key === "TELEMUNDO") return "TEL";
  if (key === "ANTENNA TV") return "ANT";
  if (n.length <= 4) return n;
  return n.slice(0, 3).toUpperCase();
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

function guideAllSlots(nowMin) {
  if (nowMin === undefined || nowMin === null || nowMin < 0) nowMin = minutesNow()
  var start = nowMin - (nowMin % 30)
  var slots = []
  for (var i = 0; i < 10; i++) slots.push(formatSlot(start + i * 30))
  return slots
}

function visibleSlotCount(panelWidth, minSlotPx) {
  var w = Number(panelWidth) || 0
  var minSlot = Math.max(80, Number(minSlotPx) || 120)
  var usable = Math.max(minSlot * 3, w - 160)
  var n = Math.floor(usable / minSlot)
  if (n < 3) n = 3
  if (n > 10) n = 10
  return n
}

function slotWindow(offset, count, nowMin) {
  var all = guideAllSlots(nowMin)
  var start = Math.max(0, Number(offset) || 0)
  var n = Math.max(1, Number(count) || 3)
  return all.slice(start, start + n)
}

function maxSlotOffset(visibleCount, nowMin) {
  return Math.max(0, guideAllSlots(nowMin).length - Math.max(1, Number(visibleCount) || 1))
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

function programBlocks(item, slots) {
  var programs = programsFor(item)
  var nowMin = minutesNow()
  var blocks = []
  var i = 0
  while (i < slots.length) {
    var p = coveringProgram(programs, slots[i])
    var span = 1
    while (p && i + span < slots.length && coveringProgram(programs, slots[i + span]) === p)
      span++
    var now = false
    var s = 0
    for (s = 0; s < span; s++) {
      if (slotIsNow(slots[i + s], nowMin)) now = true
    }
    blocks.push({
      title: p ? (p.title || "") : "",
      start: p ? (p.start || p.start_time || "") : "",
      end: p ? (p.end || p.end_time || "") : "",
      span: p ? span : 1,
      empty: !p,
      now: now && !!p,
      synopsis: p ? (p.synopsis || "") : "",
      usual: p ? (p.usual || "") : "",
      also: p ? (p.also || "") : "",
      duration_sec: p ? (Number(p.duration_sec) || 0) : 0
    })
    i += p ? span : 1
  }
  return blocks
}

function preferredGuideBlock(item, slots) {
  var blocks = programBlocks(item, slots)
  var i
  for (i = 0; i < blocks.length; i++) {
    if (blocks[i].now && !blocks[i].empty) return blocks[i]
  }
  for (i = 0; i < blocks.length; i++) {
    if (!blocks[i].empty) return blocks[i]
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

function guideSlotMax() {
  return Math.max(0, guideAllSlots().length - 1)
}

function guideSlotLabel(slot) {
  var slots = guideAllSlots()
  return slots[Number(slot)] || slots[0] || "Tonight"
}

function guideSlotCaption(slot) {
  return "Tonight"
}

function guideProgramTitle(item, slot) {
  if (!item) return "Live Broadcast"
  if (Number(slot) === 1) return item.next_title || "Upcoming"
  return item.title || "Live Broadcast"
}

function guideProgramTime(item, slot) {
  if (!item) return ""
  if (Number(slot) === 1) {
    return item.end_time ? ("From " + item.end_time) : "Next"
  }
  if (item.start_time && item.end_time) return item.start_time + " – " + item.end_time
  return "Now"
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

function formatGuideUpdated(updatedAt) {
  var stamp = Number(updatedAt) || 0
  if (stamp <= 0) return "Listings have not been updated."
  var when = new Date(stamp * 1000)
  var now = new Date()
  var h24 = when.getHours()
  var h = h24 % 12
  if (h === 0) h = 12
  var min = when.getMinutes()
  var clock = h + ":" + (min < 10 ? "0" : "") + min + " " + (h24 >= 12 ? "PM" : "AM")
  if (when.toDateString() === now.toDateString()) return "Updated " + clock
  var months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
  return "Updated " + months[when.getMonth()] + " " + when.getDate() + ", " + clock
}
