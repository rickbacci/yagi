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
  if (!network) return fallback;
  var net = network.toUpperCase();
  if (net === "NBC") return "#a6e3a1";       // Mint green
  if (net === "ABC") return "#f9e2af";       // Soft amber
  if (net === "FOX") return "#89b4fa";       // Sapphire blue
  if (net === "CBS") return "#cba6f7";       // Mauve purple
  if (net === "PBS") return "#94e2d5";       // Teal
  if (net === "CW") return "#a6e3a1";        // Vibrant green
  if (net === "UNIVISION") return "#f38ba8"; // Coral
  if (net === "ION") return "#89dceb";       // Sky blue
  return fallback;
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

function guideAllSlots() {
  var start = parseMinutes("6:00 PM")
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

function slotWindow(offset, count) {
  var all = guideAllSlots()
  var start = Math.max(0, Number(offset) || 0)
  var n = Math.max(1, Number(count) || 3)
  return all.slice(start, start + n)
}

function maxSlotOffset(visibleCount) {
  return Math.max(0, guideAllSlots().length - Math.max(1, Number(visibleCount) || 1))
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

function coveringProgram(programs, slotLabel) {
  var t = parseMinutes(slotLabel)
  if (t < 0) return null
  for (var i = 0; i < programs.length; i++) {
    var p = programs[i]
    var a = parseMinutes(p.start || p.start_time)
    var b = parseMinutes(p.end || p.end_time)
    if (a < 0) continue
    if (b <= a) b = a + 30
    if (t >= a && t < b) return p
  }
  return null
}

function programBlocks(item, slots) {
  var programs = programsFor(item)
  var blocks = []
  var i = 0
  while (i < slots.length) {
    var p = coveringProgram(programs, slots[i])
    var span = 1
    while (p && i + span < slots.length && coveringProgram(programs, slots[i + span]) === p)
      span++
    blocks.push({ title: p ? (p.title || "") : "", span: p ? span : 1, empty: !p })
    i += p ? span : 1
  }
  return blocks
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
