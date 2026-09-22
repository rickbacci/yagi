import QtQuick
import Quickshell
import Quickshell.Io
import qs.Ui
import qs.Commons
import "Model.js" as Model

BarWidget {
  id: root
  moduleName: "richardb.omarchy-tv"

  property bool popupOpen: false
  onPopupOpenChanged: {
    if (!root.popupOpen) {
      root.guideStripOpen = false
      return
    }
    if (root.popupOpen) {
      root.libraryModalOpen = false
      root.cursorActive = false
      root.channelListOpen = !root.flyoutStatusOn
      root.reloadChannelData()
      root.guideClockMin = Model.minutesNow()
      if (!tuneProc.running)
        root.syncPlayerState()
    }
  }
  property var channelsData: []
  property var activeChannel: null
  property string activeChannelName: ""

  // Scan HUD state
  property bool isScanning: false
  property int scanPercent: 0
  property int scanChannel: 0
  property string scanBand: ""
  property double scanFreq: 0
  property var scanSignal: null
  property int scanTotalFound: 0
  property var favoritesData: []
  property var guideData: ({})
  property var activeRecordings: []
  readonly property bool isRecording: root.activeRecordings && root.activeRecordings.length > 0
  property bool guideStripOpen: false
  property bool libraryModalOpen: false
  property var recordingsData: []
  property string libraryBytesLabel: ""
  property string libraryBudgetLabel: ""
  property var libraryMaxGb: "auto"
  property int recCursorIndex: 0
  readonly property bool tuner0Busy: root.activeChannelName !== "" && root.isLiveSession
  readonly property bool tuner1Busy: root.isRecording || root.isScanning || root.guideRefreshing
  readonly property bool bothTunersBusy: root.tuner0Busy && root.tuner1Busy
  readonly property bool flyoutStatusOn: root.activeChannelName !== "" || root.isRecording || root.isScanning || root.guideRefreshing
  property bool channelListOpen: true
  readonly property string channelListLabel: {
    if (!root.flyoutStatusOn) return "Channels"
    var watch = !root.tuner0Busy
    var record = !root.tuner1Busy
    if (watch && record) return "Watch or record"
    if (watch) return "Watch"
    if (record) return "Record"
    return "Channels"
  }
  onFlyoutStatusOnChanged: root.channelListOpen = !root.flyoutStatusOn
  onBothTunersBusyChanged: if (root.bothTunersBusy) root.channelListOpen = false
  readonly property bool showChannelBrowser: root.channelListOpen && !root.bothTunersBusy
  property int guideClockMin: -1
  property string channelFilter: "favorites" // favorites | watchable | all | hidden
  property var hiddenData: []
  property string playerMode: "live"
  property string lastLiveChannel: ""
  readonly property bool isLibraryPlayback: root.playerMode === "recording"
  readonly property bool isLiveSession: root.playerMode === "live" || root.playerMode === "timeshift"
  readonly property bool isPlayback: root.isLibraryPlayback || root.playerMode === "timeshift"
  property bool cursorActive: false
  property int cursorIndex: 0
  property bool guideRefreshing: false
  readonly property var guideBlocks: {
    var _tick = root.guideClockMin
    return Model.guideHourBlocks(root.guideList, Math.floor(Date.now() / 1000))
  }
  property int guideBlockIndex: 0
  readonly property int guideNameCol: Style.space(168)
  readonly property int guideHourCol: {
    var w = guideStripCol.width
    if (!(w > 0)) w = Style.space(840)
    var later = laterBtn.width > 0 ? laterBtn.width : Style.space(72)
    var gaps = Style.space(6) * 4
    return Math.max(Style.space(120), Math.floor((w - root.guideNameCol - later - gaps) / 3))
  }
  readonly property var guideHourLabels: {
    var blocks = root.guideBlocks || []
    var start = Number(blocks[root.guideBlockIndex] || 0)
    if (start <= 0) return ["", "", ""]
    return [
      root.clockLabel(start),
      root.clockLabel(start + 3600),
      root.clockLabel(start + 7200)
    ]
  }
  readonly property var guideStripRows: {
    var blocks = root.guideBlocks || []
    var start = Number(blocks[root.guideBlockIndex] || 0)
    if (start <= 0) return []
    var nowSec = Math.floor(Date.now() / 1000)
    var list = root.guideList || []
    var out = []
    var i, j, h, programs, prog, unix, dur, hourStart, cells, cover
    for (i = 0; i < list.length; i++) {
      programs = list[i].programs || []
      cells = []
      for (h = 0; h < 3; h++) {
        hourStart = start + h * 3600
        cover = null
        for (j = 0; j < programs.length; j++) {
          prog = programs[j]
          unix = Model.programUnix(prog)
          dur = Number(prog.duration_sec) || 0
          if (unix <= 0 || dur <= 0) continue
          if (unix < hourStart + 3600 && (unix + dur) > hourStart) {
            if (!cover || unix >= cover.unix) cover = { prog: prog, unix: unix, dur: dur }
          }
        }
        if (!cover) {
          cells.push({ title: "" })
        } else {
          cells.push({
            tune_name: list[i].tune_name || "",
            display_name: list[i].display_name || list[i].tune_name || "",
            title: cover.prog.title || "",
            start: cover.prog.start || "",
            end: cover.prog.end || "",
            gps_start: Number(cover.prog.gps_start) || 0,
            duration_sec: cover.dur,
            unix: cover.unix,
            on_now: cover.unix <= nowSec && (cover.unix + cover.dur) > nowSec
          })
        }
      }
      out.push({
        tune_name: list[i].tune_name || "",
        display_name: list[i].display_name || list[i].tune_name || "",
        network: list[i].network || "",
        cells: cells
      })
    }
    return out
  }
  property var scheduleItems: []
  readonly property string scheduleLine: {
    var items = root.scheduleItems || []
    if (!items.length) return ""
    if (items.length === 1) {
      var one = items[0]
      var who = one.display_name || one.tune_name || ""
      var when = one.clock || ""
      return who + (one.title ? " · " + one.title : "") + (when ? " · " + when : "")
    }
    return items.length + " scheduled"
  }
  property string guideSearchText: ""
  readonly property bool guideSearchActive: root.guideSearchText.replace(/\s+/g, " ").trim().length >= 2
  readonly property var guideSearchHits: Model.searchGuide(root.guideData, root.guideSearchText, root.guideClockMin) || []

  function roomFor(chromeHeight) {
    var avail = popup.availableCardHeight
    if (!(avail > 0)) avail = Style.space(720)
    var inset = popup.verticalContentInset || 0
    return Math.max(Style.space(96), Math.round(avail - inset - Math.max(0, chromeHeight)))
  }

  function flyoutContentWidth() {
    var avail = popup.availableCardWidth
    if (root.guideStripOpen) {
      if (!(avail > 0)) return popup.fittedContentWidth(Style.space(840))
      var wide = Math.round(avail * 0.55)
      return popup.fittedContentWidth(Math.max(Style.space(720), Math.min(Style.space(960), wide)))
    }
    if (!(avail > 0)) return popup.fittedContentWidth(Style.space(440))
    var share = Math.round(avail * 0.30)
    return popup.fittedContentWidth(Math.max(Style.space(340), Math.min(Style.space(460), share)))
  }

  function refreshGuide() {
    if (guideRefreshProc.running) return
    if (root.isRecording) return
    root.guideRefreshing = true
    guideRefreshProc.running = false
    guideRefreshProc.command = [root.binPath, "guide", "refresh"]
    guideRefreshProc.running = true
  }

  function clockLabel(unixSec) {
    var when = new Date(Number(unixSec) * 1000)
    var h24 = when.getHours()
    var h = h24 % 12
    if (h === 0) h = 12
    var min = when.getMinutes()
    return h + ":" + (min < 10 ? "0" : "") + min + " " + (h24 >= 12 ? "PM" : "AM")
  }

  function shiftGuideBlock(delta) {
    var n = (root.guideBlocks || []).length
    if (n <= 0) return
    root.guideBlockIndex = Math.max(0, Math.min(n - 1, root.guideBlockIndex + delta))
  }

  function snapGuideBlock() {
    var blocks = root.guideBlocks || []
    var now = Math.floor(Date.now() / 1000)
    var idx = 0
    var i
    for (i = 0; i < blocks.length; i++) {
      if (Number(blocks[i]) <= now) idx = i
    }
    root.guideBlockIndex = idx
  }

  function applySchedule(raw) {
    try {
      var data = JSON.parse(raw || "{}")
      var items = data.items || data
      root.scheduleItems = (items && items.length) ? items : []
    } catch (e) {
      root.scheduleItems = []
    }
  }

  function scheduleLater(show) {
    if (!show || !show.tune_name || !show.gps_start) return
    var dur = Math.max(60, Number(show.duration_sec) || 1800)
    schedProc.running = false
    schedProc.command = [
      root.binPath, "record", "later", show.tune_name, String(dur),
      "--title", show.title || "Scheduled",
      "--gps", String(show.gps_start),
      "--clock", show.start || "",
      "--end-clock", show.end || "",
      "--display-name", show.display_name || show.tune_name
    ]
    schedProc.running = true
  }

  function removeScheduled(itemId) {
    if (!itemId) return
    schedProc.running = false
    schedProc.command = [root.binPath, "record", "unlater", itemId]
    schedProc.running = true
  }

  function useStripShow(show) {
    if (!show || !show.tune_name) return
    var start = Model.programUnix(show)
    var dur = Number(show.duration_sec) || 0
    var now = Math.floor(Date.now() / 1000)
    if (start > 0 && dur > 0 && (start + dur) <= now) return
    var onNow = (start > 0 && dur > 0) ? (start <= now) : !!show.on_now
    if (onNow) {
      if (root.tuner1Busy) return
      var left = Model.recordDurationArg(show, root.guideClockMin)
      dvrProc.running = false
      var cmd = [root.binPath, "record", "start", show.tune_name]
      if (left) cmd.push(left)
      if (show.title) {
        cmd.push("--title")
        cmd.push(show.title)
      }
      dvrProc.command = cmd
      dvrProc.running = true
      return
    }
    root.scheduleLater(show)
  }

  function toggleGuide() {
    if (root.guideStripOpen) {
      root.guideStripOpen = false
      root.cursorActive = false
      return
    }
    root.libraryModalOpen = false
    root.guideSearchText = ""
    guideStripSearch.text = ""
    root.guideClockMin = Model.minutesNow()
    root.snapGuideBlock()
    root.guideStripOpen = true
  }

  function toggleLibrary() {
    if (root.libraryModalOpen) {
      root.libraryModalOpen = false
      root.cursorActive = false
      return
    }
    root.guideStripOpen = false
    root.recCursorIndex = 0
    root.cursorActive = false
    root.libraryModalOpen = true
    recIndexProc.running = false
    recIndexProc.command = [root.binPath, "record", "list"]
    recIndexProc.running = true
  }

  function selectChannel(chName) {
    root.playChannel(chName)
    root.close()
  }

  function playRecording(filePath, playable) {
    if (playable === false) return
    recPlayProc.running = false
    recPlayProc.command = [root.binPath, "record", "play", filePath]
    recPlayProc.running = true
  }

  function deleteRecording(filePath) {
    dvrProc.running = false
    dvrProc.command = [root.binPath, "record", "delete", filePath]
    dvrProc.running = true
  }

  function listLen() {
    if (root.libraryModalOpen) return root.recordingsData ? root.recordingsData.length : 0
    return root.displayChannels ? root.displayChannels.length : 0
  }

  function moveCursor(delta) {
    var n = root.listLen()
    if (n <= 0) return
    if (!root.cursorActive) {
      root.cursorActive = true
      return
    }
    if (root.libraryModalOpen) {
      root.recCursorIndex = Math.max(0, Math.min(n - 1, root.recCursorIndex + delta))
    } else {
      root.cursorIndex = Math.max(0, Math.min(n - 1, root.cursorIndex + delta))
    }
  }

  function activateCursor() {
    if (!root.cursorActive) return
    if (root.libraryModalOpen) {
      var rec = root.recordingsData[root.recCursorIndex]
      if (rec) root.playRecording(rec.path || rec.name, rec.playable)
      return
    }
    var ch = root.displayChannels[root.cursorIndex]
    if (ch) root.useListedChannel(ch.tune_name || ch.name)
  }

  function useListedChannel(chName) {
    if (!chName) return
    if (root.tuner0Busy && !root.tuner1Busy) {
      root.recordListedShow(chName)
      return
    }
    root.selectChannel(chName)
  }

  function recordListedShow(chName) {
    if (!chName) return
    if (root.isChannelRecording(chName)) {
      root.toggleRecord(chName)
      return
    }
    var ch = null
    var list = root.channelsData || []
    var i
    for (i = 0; i < list.length; i++) {
      var item = list[i]
      if (!item) continue
      if (item.tune_name === chName || item.name === chName) {
        ch = item
        break
      }
    }
    var row = ch ? root.getProgram(ch) : null
    var now = Model.minutesNow()
    var prog = row ? Model.currentProgram(row, now) : null
    if (prog && Model.showIsOn(prog, now)) {
      var dur = Model.recordDurationArg(prog, now)
      var title = (prog.title || "").toString()
      dvrProc.running = false
      var cmd = [root.binPath, "record", "start", chName]
      if (dur) cmd.push(dur)
      if (title) {
        cmd.push("--title")
        cmd.push(title)
      }
      dvrProc.command = cmd
      dvrProc.running = true
      return
    }
    root.toggleRecord(chName)
  }

  function cursorChannelIdent() {
    if (root.cursorActive && root.displayChannels && root.displayChannels.length > 0) {
      var ch = root.displayChannels[root.cursorIndex]
      if (ch) return ch.tune_name || ch.name || ""
    }
    return root.activeChannelName || ""
  }

  function isChannelRecording(chIdent) {
    return root.recordingSessionFor(chIdent) !== null
  }

  function recordingSessionFor(chIdent) {
    if (!root.activeRecordings || root.activeRecordings.length === 0) return null
    var idents = []
    function add(s) {
      var v = (s || "").toString().toLowerCase().trim()
      if (v && idents.indexOf(v) === -1) idents.push(v)
    }
    add(chIdent)
    if (idents.length === 0) return null
    for (var i = 0; i < root.activeRecordings.length; i++) {
      var r = root.activeRecordings[i]
      var keys = [r.channel_number, r.station, r.tune_name]
      for (var k = 0; k < keys.length; k++) {
        var key = (keys[k] || "").toString().toLowerCase().trim()
        if (key && idents.indexOf(key) !== -1) return r
      }
    }
    return null
  }

  readonly property var guideList: {
    var list = []
    var chs = root.guideSourceChannels || []
    if (chs.length > 0) {
      for (var i = 0; i < chs.length; i++) {
        var ch = chs[i]
        var g = Model.matchGuideProgram(ch, root.guideData) || {}
        var item = Object.assign({}, g)
        item.channel_number = ch.channel_number || item.channel_number || ""
        item.network = ch.network || item.network || ""
        item.station = ch.callsign || item.station || ""
        item.tune_name = ch.tune_name || ch.name || item.tune_name || ""
        item.callsign = ch.callsign || item.callsign || ""
        item.display_name = ch.display_name || ch.name || item.display_name || ""
        if (!item.programs || !item.programs.length)
          item.programs = Model.programsFor(item)
        list.push(item)
      }
      return list
    }
    if (!root.guideData) return list
    for (var k in root.guideData) {
      var fallback = Object.assign({}, root.guideData[k])
      fallback.channel_number = k
      list.push(fallback)
    }
    list.sort(function(a, b) {
      return (parseFloat(a.channel_number) || 999) - (parseFloat(b.channel_number) || 999)
    })
    return list
  }

  function channelIsHidden(ch) {
    if (!ch) return false
    var num = String(ch.channel_number || "")
    var items = root.hiddenData || []
    var i
    for (i = 0; i < items.length; i++) {
      if (String(items[i]) === num) return true
    }
    return false
  }

  function channelIsFavorite(ch) {
    if (!ch || !root.favoritesData) return false
    return root.favoritesData.indexOf(ch.name) !== -1 || (ch.tune_name && root.favoritesData.indexOf(ch.tune_name) !== -1)
  }

  readonly property int listedChannelCount: (root.channelsData || []).length

  readonly property int favoriteVisibleCount: {
    return (root.watchableChannels || []).filter(function(ch) { return root.channelIsFavorite(ch) }).length
  }

  readonly property var watchableChannels: {
    return (root.channelsData || []).filter(function(ch) { return !root.channelIsHidden(ch) })
  }

  readonly property var displayChannels: {
    var list = root.channelsData || []
    if (root.channelFilter === "hidden") {
      return list.filter(function(ch) { return root.channelIsHidden(ch) })
    }
    list = list.filter(function(ch) { return !root.channelIsHidden(ch) })
    if (root.channelFilter === "favorites") {
      list = list.filter(function(ch) { return root.channelIsFavorite(ch) })
    }
    return list
  }

  readonly property var guideSourceChannels: {
    if (root.channelFilter === "favorites") {
      return (root.watchableChannels || []).filter(function(ch) { return root.channelIsFavorite(ch) })
    }
    return root.watchableChannels || []
  }

  onDisplayChannelsChanged: {
    var n = root.displayChannels ? root.displayChannels.length : 0
    if (root.cursorIndex >= n) root.cursorIndex = Math.max(0, n - 1)
  }

  readonly property string binPath: "omarchy-tv"

  function close() {
    root.popupOpen = false
  }
  function toggle() { root.popupOpen = !root.popupOpen }

  function playChannel(chName) {
    if (tuneProc.running && root.activeChannelName === chName)
      return
    root.activeChannelName = chName
    tuneProc.running = false
    tuneProc.command = [root.binPath, "play", chName]
    tuneProc.running = true
  }

  function cycleListed(delta) {
    var list = root.displayChannels || []
    if (list.length === 0) return
    var q = (root.activeChannelName || "").toLowerCase()
    var idx = -1
    for (var i = 0; i < list.length; i++) {
      var ch = list[i]
      if ((ch.name || "").toLowerCase() === q || (ch.tune_name || "").toLowerCase() === q) {
        idx = i
        break
      }
    }
    var next = idx < 0 ? (delta > 0 ? 0 : list.length - 1) : ((idx + delta + list.length) % list.length)
    var target = list[next]
    root.playChannel(target.tune_name || target.name)
  }

  function channelUp() {
    root.cycleListed(1)
  }

  function channelDown() {
    root.cycleListed(-1)
  }

  function stopPlayer() {
    root.activeChannelName = ""
    root.playerMode = "live"
    stopProc.command = [root.binPath, "stop"]
    stopProc.running = true
  }

  function syncPlayerState() {
    syncProc.running = false
    syncProc.command = [root.binPath, "sync"]
    syncProc.running = true
  }

  function returnToLive() {
    tuneProc.running = false
    tuneProc.command = [root.binPath, "live"]
    tuneProc.running = true
  }

  function seekPlayer(seconds) {
    navProc.running = false
    navProc.command = [root.binPath, "seek", String(seconds)]
    navProc.running = true
  }

  function startScan() {
    root.isScanning = true
    root.scanPercent = 1
    root.scanTotalFound = 0
    root.scanSignal = null
    scanProc.running = false
    scanProc.command = [root.binPath, "scan"]
    Qt.callLater(function() {
      scanProc.running = true
    })
  }

  function reloadChannelData() {
    channelsFile.reload()
    guideFile.reload()
    favoritesFile.reload()
    hiddenFile.reload()
    uiPrefsFile.reload()
    recordingsFile.reload()
    recIndexProc.running = false
    recIndexProc.command = [root.binPath, "record", "list"]
    recIndexProc.running = true
  }

  function applyUiPrefs(jsonText) {
    try {
      var raw = (jsonText || "").trim()
      if (!raw) return
      var p = JSON.parse(raw)
      if (p.channel_filter === "favorites" || p.channel_filter === "all" || p.channel_filter === "watchable" || p.channel_filter === "hidden") {
        root.channelFilter = p.channel_filter
        root.filterInitialized = true
      }
      if (p.library_max_gb !== undefined) root.libraryMaxGb = p.library_max_gb
    } catch (e) {
    }
  }

  function setChannelFilter(filter) {
    root.channelFilter = filter
    root.filterInitialized = true
    prefsProc.running = false
    prefsProc.command = [root.binPath, "pref", "filter", filter]
    prefsProc.running = true
  }

  function cycleLibraryCap() {
    var cur = root.libraryMaxGb
    var next = "auto"
    if (cur === "auto" || cur === undefined || cur === null || cur === "") next = "20"
    else if (cur === 20 || cur === "20") next = "50"
    else if (cur === 50 || cur === "50") next = "off"
    else next = "auto"
    prefsProc.running = false
    prefsProc.command = [root.binPath, "pref", "library-max", next]
    prefsProc.running = true
  }

  function libraryCapButtonText() {
    var cur = root.libraryMaxGb
    if (cur === 0 || cur === "0" || cur === "off") return "Cap off"
    if (cur === 20 || cur === "20") return "20 GB"
    if (cur === 50 || cur === "50") return "50 GB"
    return "Auto cap"
  }

  function applyChannels(jsonText) {
    try {
      var data = JSON.parse(jsonText || "{}")
      root.channelsData = data.channels || []
    } catch (e) {
      root.channelsData = []
    }
  }

  function applyScanStatus(jsonText) {
    try {
      var status = JSON.parse(jsonText || "{}")
      var now = Date.now() / 1000
      var isHeartbeatValid = status.updated_at ? (now - status.updated_at < 15) : false
      var liveScan = (status.is_scanning === true) && isHeartbeatValid
      root.isScanning = liveScan || scanProc.running
      root.scanPercent = status.percent || 0
      root.scanChannel = status.channel || 0
      root.scanBand = status.band || ""
      root.scanFreq = status.frequency || 0
      root.scanSignal = (status.signal_dbm !== undefined) ? status.signal_dbm : null
      root.scanTotalFound = status.total_found || 0
      // Never copy scan_status channels into the guide list. That file is raw
      // tuner names and would clobber enriched channels.json in memory.
    } catch (e) {
      // ignore transient partial write
    }
  }

  property bool filterInitialized: false

  function applyFavorites(jsonText) {
    try {
      root.favoritesData = JSON.parse(jsonText || "[]")
    } catch (e) {
      root.favoritesData = []
    }
  }

  function applyHidden(jsonText) {
    try {
      var data = JSON.parse(jsonText || "[]")
      root.hiddenData = (data && data.length !== undefined) ? data : []
    } catch (e) {
      root.hiddenData = []
    }
    if (root.channelFilter === "hidden" && !(root.hiddenData && root.hiddenData.length))
      root.channelFilter = "watchable"
  }

  function hideListed(ch) {
    var num = ch ? String(ch.channel_number || "") : ""
    if (!num) return
    hiddenProc.running = false
    hiddenProc.command = [root.binPath, "hidden", "hide", num]
    hiddenProc.running = true
  }

  function showListed(ch) {
    var num = ch ? String(ch.channel_number || "") : ""
    if (!num) return
    hiddenProc.running = false
    hiddenProc.command = [root.binPath, "hidden", "show", num]
    hiddenProc.running = true
  }

  function isFavorite(chName) {
    return root.favoritesData && root.favoritesData.indexOf(chName) !== -1
  }

  function applyGuide(jsonText) {
    try {
      var d = JSON.parse(jsonText || "{}")
      root.guideData = d.channels || {}
    } catch (e) {
      root.guideData = {}
    }
  }

  function applyRecordings(jsonText) {
    try {
      var d = JSON.parse(jsonText || "{}")
      root.recordingsData = d.recordings || []
      root.libraryBytesLabel = d.library_bytes_formatted || ""
      root.libraryBudgetLabel = d.library_budget_formatted || ""
      if (d.library_max_gb !== undefined) root.libraryMaxGb = d.library_max_gb
    } catch (e) {
      root.recordingsData = []
    }
  }

  function getProgram(ch) {
    return Model.matchGuideProgram(ch, root.guideData)
  }

  function getActiveDisplayName() {
    if (!root.activeChannelName) return ""
    for (var i = 0; i < (root.channelsData || []).length; i++) {
      var ch = root.channelsData[i]
      if (ch.name === root.activeChannelName || ch.tune_name === root.activeChannelName) {
        return Model.getDisplayTitle(ch)
      }
    }
    return root.activeChannelName
  }

  function getActiveProgram() {
    if (!root.activeChannelName) return null
    for (var i = 0; i < (root.channelsData || []).length; i++) {
      var ch = root.channelsData[i]
      if (ch.name === root.activeChannelName || ch.tune_name === root.activeChannelName) {
        return root.getProgram(ch)
      }
    }
    return root.getProgram({ name: root.activeChannelName })
  }

  function recordingIdent(r) {
    if (!r) return ""
    return r.tune_name || r.station || r.channel_number || ""
  }

  function recordingTitle(r) {
    if (!r) return "Recording"
    var list = root.channelsData || []
    var keys = [r.tune_name, r.station, r.name, r.channel_number]
    var i
    var k
    for (i = 0; i < list.length; i++) {
      var ch = list[i]
      if (!ch) continue
      for (k = 0; k < keys.length; k++) {
        var key = keys[k]
        if (!key) continue
        if (ch.tune_name === key || ch.name === key || ch.channel_number === key) {
          var title = Model.getDisplayTitle(ch)
          if (title) return title
        }
      }
    }
    var num = (r.channel_number || "").toString()
    var st = (r.station || r.name || "").toString()
    if (num && st) return num + " " + st
    return num || st || "Recording"
  }

  function barWatchLabel() {
    if (!root.activeChannelName || root.isLibraryPlayback) return ""
    var list = root.channelsData || []
    var i
    for (i = 0; i < list.length; i++) {
      var ch = list[i]
      if (!ch) continue
      if (ch.name === root.activeChannelName || ch.tune_name === root.activeChannelName) {
        if (ch.channel_number) return String(ch.channel_number)
        return Model.getChannelBadge(ch)
      }
    }
    return ""
  }

  function barRecLabel() {
    if (!root.isRecording) return ""
    var r = root.activeRecordings && root.activeRecordings.length ? root.activeRecordings[0] : null
    if (!r) return "REC"
    var num = (r.channel_number || "").toString()
    if (num) return "REC " + num
    var st = (r.station || "").toString()
    return st ? ("REC " + st) : "REC"
  }

  function barStatusText() {
    if (root.isScanning) return "Scan " + root.scanPercent + "%"
    var parts = []
    var watch = root.barWatchLabel()
    var rec = root.barRecLabel()
    if (watch) parts.push(watch)
    if (rec) parts.push(rec)
    return parts.join(" · ")
  }

  function toggleFavorite(chName) {
    favProc.command = [root.binPath, "favorite", "toggle", chName]
    favProc.running = true
  }

  implicitWidth: row.implicitWidth + Style.space(12)
  implicitHeight: barSize

  Row {
    id: row
    anchors.centerIn: parent
    spacing: Style.space(6)

    Text {
      id: iconText
      textFormat: Text.PlainText
      text: "󰢹"
      color: root.bar.barForeground
      font.family: root.bar.fontFamily
      font.pixelSize: Style.font.body
      anchors.verticalCenter: parent.verticalCenter
    }

    Row {
      id: label
      visible: root.barStatusText() !== "" && !root.bar.vertical
      spacing: Style.space(4)
      anchors.verticalCenter: parent.verticalCenter

      Text {
        visible: !root.isScanning && root.barWatchLabel() !== ""
        textFormat: Text.PlainText
        text: root.barWatchLabel()
        color: root.bar.barForeground
        font.family: root.bar.fontFamily
        font.pixelSize: Style.font.bodySmall
        font.bold: true
        anchors.verticalCenter: parent.verticalCenter
      }

      Text {
        visible: !root.isScanning && root.barWatchLabel() !== "" && root.barRecLabel() !== ""
        textFormat: Text.PlainText
        text: "·"
        color: Color.accent
        font.family: root.bar.fontFamily
        font.pixelSize: Style.font.bodySmall
        font.bold: true
        anchors.verticalCenter: parent.verticalCenter
      }

      Text {
        visible: !root.isScanning && root.barRecLabel() !== ""
        textFormat: Text.PlainText
        text: root.barRecLabel()
        color: Color.urgent
        font.family: root.bar.fontFamily
        font.pixelSize: Style.font.bodySmall
        font.bold: true
        anchors.verticalCenter: parent.verticalCenter
      }

      Text {
        visible: root.isScanning
        textFormat: Text.PlainText
        text: root.barStatusText()
        color: Color.accent
        font.family: root.bar.fontFamily
        font.pixelSize: Style.font.bodySmall
        font.bold: true
        anchors.verticalCenter: parent.verticalCenter
      }
    }
  }

  MouseArea {
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    acceptedButtons: Qt.LeftButton | Qt.RightButton
    onClicked: function(mouse) {
      if (mouse.button === Qt.LeftButton) {
        root.toggle()
      }
    }
    onEntered: if (root.bar) root.bar.showTooltip(root, "Omarchy TV — Over-The-Air Television")
    onExited: if (root.bar) root.bar.hideTooltip(root)
  }

  IpcHandler {
    target: "richardb.omarchy-tv"

    function reloadStatus(): void {
      scanStatusFile.reload()
      playerStateFile.reload()
    }

    function reloadChannels(): void {
      root.reloadChannelData()
    }

    function play(channelName: string): void {
      root.playChannel(channelName)
    }

    function stop(): void {
      root.stopPlayer()
    }

    function next(): void {
      root.channelUp()
    }

    function prev(): void {
      root.channelDown()
    }

    function live(): void {
      root.returnToLive()
    }

    function scan(): void {
      root.startScan()
    }

    function toggle(): void {
      root.toggle()
    }

    function open(): void {
      root.popupOpen = true
    }

    function close(): void {
      root.close()
    }

    function guide(): void {
      root.libraryModalOpen = false
      root.guideClockMin = Model.minutesNow()
      root.snapGuideBlock()
      root.guideStripOpen = true
      root.popupOpen = true
    }
  }

  // Watch channels.json file
  FileView {
    id: channelsFile
    path: (Quickshell.env("HOME") || "") + "/.config/omarchy/tv/channels.json"
    watchChanges: true
    printErrors: false
    onLoaded: root.applyChannels(text())
    onFileChanged: reload()
  }

  // Watch favorites.json file
  FileView {
    id: favoritesFile
    path: (Quickshell.env("HOME") || "") + "/.config/omarchy/tv/favorites.json"
    watchChanges: true
    printErrors: false
    onLoaded: root.applyFavorites(text())
    onFileChanged: reload()
  }

  FileView {
    id: hiddenFile
    path: (Quickshell.env("HOME") || "") + "/.config/omarchy/tv/hidden.json"
    watchChanges: true
    printErrors: false
    onLoaded: root.applyHidden(text())
    onFileChanged: reload()
  }

  FileView {
    id: uiPrefsFile
    path: (Quickshell.env("HOME") || "") + "/.config/omarchy/tv/ui_prefs.json"
    watchChanges: true
    printErrors: false
    onLoaded: root.applyUiPrefs(text())
    onFileChanged: reload()
  }

  // Watch guide.json EPG file
  FileView {
    id: guideFile
    path: (Quickshell.env("HOME") || "") + "/.config/omarchy/tv/guide.json"
    watchChanges: true
    printErrors: false
    onLoaded: root.applyGuide(text())
    onFileChanged: reload()
  }

  FileView {
    id: recordingsFile
    path: (Quickshell.env("HOME") || "") + "/.config/omarchy/tv/recordings.json"
    watchChanges: true
    printErrors: false
    onLoaded: root.applyRecordings(text())
    onFileChanged: reload()
  }

  // Watch live scan status file
  FileView {
    id: scanStatusFile
    path: (Quickshell.env("HOME") || "") + "/.config/omarchy/tv/scan_status.json"
    watchChanges: true
    printErrors: false
    onLoaded: root.applyScanStatus(text())
    onFileChanged: reload()
  }

  // Watch active DVR recordings
  FileView {
    id: recordingsActiveFile
    path: (Quickshell.env("HOME") || "") + "/.config/omarchy/tv/recordings_active.json"
    watchChanges: true
    printErrors: false
    onLoaded: root.applyRecordingsActive(text())
    onFileChanged: reload()
  }

  function applyRecordingsActive(raw) {
    try {
      root.activeRecordings = JSON.parse(raw) || []
    } catch(e) {
      root.activeRecordings = []
    }
  }

  property string tunePhase: ""
  property string tuneMessage: ""
  property string tuneSnr: ""
  property string tuneName: ""
  property string tuneDisplay: ""

  function applyTuneStatus(raw) {
    try {
      var text = (raw || "").trim()
      if (!text) return
      var s = JSON.parse(text)
      root.tunePhase = s.phase || ""
      root.tuneMessage = s.message || ""
      root.tuneName = s.tune_name || ""
      root.tuneDisplay = s.display_name || ""
      if (s.snr_db === null || s.snr_db === undefined || s.snr_db === "")
        root.tuneSnr = ""
      else
        root.tuneSnr = Number(s.snr_db).toFixed(1) + " dB"
    } catch (e) {
    }
  }

  function applyPlayerState(jsonText) {
    try {
      var raw = (jsonText || "").trim()
      if (!raw) return
      var s = JSON.parse(raw)
      if (s.running === true) {
        if (s.channel) root.activeChannelName = s.channel
        root.playerMode = s.mode || ((s.station === "Recording") ? "recording" : "live")
        if (s.last_live) root.lastLiveChannel = s.last_live
      } else if (s.running === false) {
        root.activeChannelName = ""
        root.playerMode = "live"
        if (s.last_live) root.lastLiveChannel = s.last_live
      }
    } catch (e) {
      // ignore transient partial write
    }
  }

  // Watch live playback state
  FileView {
    id: playerStateFile
    path: (Quickshell.env("HOME") || "") + "/.config/omarchy/tv/player_state.json"
    watchChanges: true
    printErrors: false
    onLoaded: root.applyPlayerState(text())
    onFileChanged: reload()
  }

  FileView {
    id: scheduleFile
    path: (Quickshell.env("HOME") || "") + "/.config/omarchy/tv/schedule.json"
    watchChanges: true
    printErrors: false
    onLoaded: root.applySchedule(text())
    onFileChanged: reload()
  }

  Timer {
    interval: 30000
    running: true
    repeat: true
    onTriggered: dueProc.running = true
  }

  Process {
    id: dueProc
    command: [root.binPath, "record", "due"]
    onExited: function(code) {
      scheduleFile.reload()
      recordingsActiveFile.reload()
    }
  }

  Process {
    id: schedProc
    command: []
    onExited: function(code) {
      scheduleFile.reload()
    }
  }

  FileView {
    id: tuneStatusFile
    path: (Quickshell.env("HOME") || "") + "/.config/omarchy/tv/tune_status.json"
    watchChanges: true
    printErrors: false
    onLoaded: root.applyTuneStatus(text())
    onFileChanged: reload()
  }

  Timer {
    id: tuneStatusTimer
    interval: 400
    running: tuneProc.running
    repeat: true
    onTriggered: tuneStatusFile.reload()
  }

  Timer {
    id: scanPollTimer
    interval: 500
    running: root.isScanning
    repeat: true
    onTriggered: scanStatusFile.reload()
  }

  // Processes for tuning & scan
  Process {
    id: tuneProc
    command: []
    onExited: {
      playerStateFile.reload()
      tuneStatusFile.reload()
    }
  }

  Process {
    id: recPlayProc
    command: []
    onExited: function(code) {
      playerStateFile.reload()
      if (code === 0) {
        root.close()
      }
    }
  }

  Process {
    id: navProc
    command: []
    onExited: playerStateFile.reload()
  }

  Process {
    id: favProc
    command: []
    onExited: function(code) {
      favoritesFile.reload()
    }
  }

  Process {
    id: hiddenProc
    command: []
    onExited: function(code) {
      hiddenFile.reload()
    }
  }

  Process {
    id: hiddenSeedProc
    command: [root.binPath, "hidden", "list"]
    onExited: function(code) {
      hiddenFile.reload()
    }
  }

  Process {
    id: prefsProc
    command: []
    onExited: function(code) {
      uiPrefsFile.reload()
      recordingsFile.reload()
      recIndexProc.running = false
      recIndexProc.command = [root.binPath, "record", "list"]
      recIndexProc.running = true
    }
  }

  Process {
    id: stopProc
    command: [root.binPath, "stop"]
    onExited: playerStateFile.reload()
  }

  Process {
    id: syncProc
    command: [root.binPath, "sync"]
    onExited: playerStateFile.reload()
  }

  Timer {
    id: guideClockTimer
    interval: 30000
    repeat: true
    running: root.popupOpen
    onTriggered: root.guideClockMin = Model.minutesNow()
  }

  Timer {
    id: playerAliveTimer
    interval: 1500
    repeat: true
    running: root.activeChannelName !== ""
    onTriggered: {
      if (tuneProc.running)
        return
      root.syncPlayerState()
    }
  }

  Process {
    id: scanProc
    command: [root.binPath, "scan"]
    onExited: function(code) {
      root.isScanning = false
      root.reloadChannelData()
    }
  }

  Process {
    id: dvrProc
    command: []
    onExited: function(code) {
      recordingsActiveFile.reload()
      recordingsFile.reload()
    }
  }

  Process {
    id: guideRefreshProc
    command: []
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        root.guideRefreshing = false
        guideFile.reload()
      }
    }
    onExited: function(code) {
      root.guideRefreshing = false
      guideFile.reload()
    }
  }

  Process {
    id: recIndexProc
    command: [root.binPath, "record", "list"]
    onExited: recordingsFile.reload()
  }

  Component.onCompleted: {
    Qt.callLater(function() {
      channelsFile.reload()
      guideFile.reload()
      hiddenSeedProc.running = true
      uiPrefsFile.reload()
      scanStatusFile.reload()
      recordingsActiveFile.reload()
      playerStateFile.reload()
    })
  }

  // Flyout Panel
  KeyboardPanel {
    id: popup
    anchorItem: root
    bar: root.bar
    owner: root
    open: root.popupOpen
    focusTarget: keyCatcher
    contentWidth: root.flyoutContentWidth()
    contentHeight: popup.fittedContentHeight(mainCol.implicitHeight)
    margin: Style.gapsOut * 2

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: guideStripSearch.activeFocus
      onCloseRequested: {
        if (root.guideStripOpen) root.guideStripOpen = false
        else if (root.libraryModalOpen) root.libraryModalOpen = false
        else root.close()
      }
      onMoveRequested: function(dx, dy) {
        if (dx !== 0 && root.guideStripOpen) {
          root.shiftGuideBlock(dx)
          return
        }
        if (dy !== 0) root.moveCursor(dy)
      }
      onActivateRequested: root.activateCursor()
      onTabRequested: function(direction) {
        if (root.bar && typeof root.bar.switchPanelFrom === "function")
          root.bar.switchPanelFrom(root, direction)
      }
      onTextKey: function(t) {
        if (t === "g" || t === "G") root.toggleGuide()
        else if (t === "v" || t === "V") root.toggleLibrary()
        else if (t === "a" || t === "A") {
          root.setChannelFilter("all")
        }
        else if (t === "f" || t === "F") {
          root.setChannelFilter("favorites")
        }
        else if (t === "s" || t === "S") root.startScan()
        else if (t === "r" || t === "R") {
          var ident = root.activeChannelName || root.cursorChannelIdent()
          if (ident) root.toggleRecord(ident)
        }
      }

      Column {
        id: mainCol
        anchors.left: parent.left
        anchors.right: parent.right
        spacing: Style.space(12)

      // Remote & Drawer View
      Column {
        id: remoteView
        visible: !root.libraryModalOpen
        width: parent.width
        spacing: Style.space(12)

        Column {
          id: remoteChrome
          width: parent.width
          spacing: Style.space(12)

        Item {
          width: parent.width
          height: Math.max(Style.space(42), headerGuideBtn.implicitHeight)

          BorderSurface {
            id: headerIcon
            width: Style.space(42)
            height: Style.space(42)
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            radius: Style.spacing.labelGap
            color: Style.normalFillFor(root.bar.foreground, Color.accent)
            borderSpec: Border.controlSpec("normal", root.bar.foreground, Color.accent)

            Text {
              anchors.centerIn: parent
              text: root.isScanning ? "󰛳" : "󰢹"
              color: Color.accent
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.display
            }
          }

          Row {
            id: headerNavRow
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(4)

            Button {
              iconText: "󰑈"
              text: "Recordings"
              tooltipText: "Recorded videos"
              foreground: root.bar.foreground
              onClicked: root.toggleLibrary()
            }

            Button {
              id: headerGuideBtn
              iconText: "󰥔"
              text: "Guide"
              tooltipText: "Program guide"
              selected: root.guideStripOpen
              foreground: root.bar.foreground
              onClicked: root.toggleGuide()
            }
          }

          Column {
            anchors.left: headerIcon.right
            anchors.right: headerNavRow.left
            anchors.leftMargin: Style.space(10)
            anchors.rightMargin: Style.space(8)
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(2)

            Text {
              textFormat: Text.PlainText
              text: "Omarchy TV"
              color: root.bar.foreground
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.subtitle
              font.bold: true
              elide: Text.ElideRight
              width: parent.width
            }

            Text {
              textFormat: Text.PlainText
              text: {
                if (root.isScanning) return "Scanning Broadcast Frequencies..."
                return root.listedChannelCount > 0
                  ? (root.listedChannelCount + " channels · " + (root.favoritesData ? root.favoritesData.length : 0) + " favorites")
                  : "No channels scanned"
              }
              color: root.isScanning ? Color.accent : Qt.darker(root.bar.foreground, 1.4)
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              elide: Text.ElideRight
              width: parent.width
            }
          }
        }

      // ==========================================
      // LIVE RF HUD & ANIMATED GRADIENT PROGRESS BAR
      // ==========================================
      BorderSurface {
        visible: root.isScanning
        width: parent.width
        height: Style.space(110)
        radius: Style.spacing.labelGap
        color: Style.selectedFillFor(root.bar.foreground, Color.accent)
        borderSpec: Border.controlSpec("focus", root.bar.foreground, Color.accent)

        Column {
          anchors.fill: parent
          anchors.margins: Style.space(10)
          spacing: Style.space(8)

          // Top Row: Status badge & Discovered count
          Item {
            width: parent.width
            height: Style.space(18)

            Text {
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
              textFormat: Text.PlainText
              text: "󰛳  RF TUNER LOCK"
              color: Color.accent
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              font.bold: true
            }

            Text {
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              textFormat: Text.PlainText
              text: "✨ " + root.scanTotalFound + " Discovered"
              color: Color.accent
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              font.bold: true
            }
          }

          // Middle Row: Channel, Band, Signal Quality
          Item {
            width: parent.width
            height: Style.space(26)

            Row {
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(8)

              BorderSurface {
                width: Style.space(56)
                height: Style.space(22)
                radius: 4
                color: Style.normalFillFor(root.bar.foreground, Color.accent)

                Text {
                  anchors.centerIn: parent
                  textFormat: Text.PlainText
                  text: "Ch " + (root.scanChannel > 0 ? root.scanChannel : "--")
                  color: root.bar.foreground
                  font.family: root.bar.fontFamily
                  font.pixelSize: Style.font.bodySmall
                  font.bold: true
                }
              }

              Column {
                anchors.verticalCenter: parent.verticalCenter
                spacing: 1

                Text {
                  textFormat: Text.PlainText
                  text: (root.scanBand !== "" ? root.scanBand : "ATSC") + " Band"
                  color: root.bar.foreground
                  font.family: root.bar.fontFamily
                  font.pixelSize: Style.font.caption
                  font.bold: true
                }

                Text {
                  textFormat: Text.PlainText
                  text: Model.formatFreq(root.scanFreq)
                  color: Qt.darker(root.bar.foreground, 1.5)
                  font.family: root.bar.fontFamily
                  font.pixelSize: Style.font.caption
                }
              }
            }

            Column {
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              spacing: 1

              Text {
                anchors.right: parent.right
                textFormat: Text.PlainText
                text: root.scanSignal !== null ? (root.scanSignal.toFixed(1) + " dBm") : "Searching..."
                color: root.scanSignal !== null && root.scanSignal > -55 ? Color.accent : (root.scanSignal !== null ? root.bar.foreground : Qt.darker(root.bar.foreground, 1.6))
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.caption
                font.bold: true
              }

              Text {
                anchors.right: parent.right
                textFormat: Text.PlainText
                text: root.scanSignal !== null && root.scanSignal > -55 ? "Strong Signal" : (root.scanSignal !== null ? "Carrier Locked" : "Scanning")
                color: Qt.darker(root.bar.foreground, 1.5)
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.caption
              }
            }
          }

          // Progress Bar
          Column {
            width: parent.width
            spacing: Style.space(4)

            Item {
              width: parent.width
              height: Style.space(16)

              Text {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                textFormat: Text.PlainText
                text: "Progress"
                color: Qt.darker(root.bar.foreground, 1.4)
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.caption
              }

              Text {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                textFormat: Text.PlainText
                text: root.scanPercent + "%"
                color: Color.accent
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.caption
                font.bold: true
              }
            }

            // Track & Fill
            BorderSurface {
              width: parent.width
              height: Style.space(8)
              radius: 4
              color: Qt.darker(root.bar.foreground, 2.5)

              Rectangle {
                height: parent.height
                width: parent.width * (Math.max(1, root.scanPercent) / 100.0)
                radius: 4
                color: Color.accent

                Behavior on width {
                  NumberAnimation { duration: 250; easing.type: Easing.OutQuad }
                }
              }
            }
          }
        }
      }

      BorderSurface {
        id: nowPlayingCard
        visible: root.activeChannelName !== ""
        readonly property var activeProg: root.getActiveProgram()
        readonly property var onNow: activeProg ? Model.currentProgram(activeProg, root.guideClockMin) : null
        readonly property string showLine: {
          if (tuneProc.running) return root.tuneSnr
          var same = root.tuneDisplay === root.getActiveDisplayName() || root.tuneName === root.activeChannelName
          if (root.tunePhase === "failed" && root.tuneMessage && same) return root.tuneMessage
          return (onNow && onNow.title) ? onNow.title : ""
        }
        property bool tuneHot: false
        width: parent.width
        implicitHeight: watchRow.implicitHeight + Style.space(12)
        radius: Style.spacing.labelGap
        color: tuneHot
          ? Style.hoverFillFor(root.bar.foreground, Color.accent)
          : Style.selectedFillFor(root.bar.foreground, Color.accent)
        borderSpec: Border.controlSpec("normal", root.bar.foreground, Color.accent)

        MouseArea {
          id: tuneAgainArea
          anchors.fill: parent
          hoverEnabled: true
          cursorShape: Qt.PointingHandCursor
          onEntered: nowPlayingCard.tuneHot = true
          onExited: nowPlayingCard.tuneHot = false
          onClicked: root.playChannel(root.activeChannelName)
          PanelToolTip {
            visible: tuneAgainArea.containsMouse
            text: "Tune again"
            fontFamily: root.bar.fontFamily
          }
        }

        Item {
          id: watchRow
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.top: parent.top
          anchors.margins: Style.space(6)
          implicitHeight: Math.max(watchLine.implicitHeight, npCloseBtn.implicitHeight)
          height: implicitHeight

          Button {
            id: npCloseBtn
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            text: "Close"
            tooltipText: "Close TV"
            foreground: root.bar.foreground
            fontSize: Style.font.caption
            onClicked: root.stopPlayer()
          }

          Row {
            id: watchLine
            anchors.left: parent.left
            anchors.right: npCloseBtn.left
            anchors.rightMargin: Style.space(8)
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(4)

            Text {
              id: watchChannel
              textFormat: Text.PlainText
              text: root.getActiveDisplayName()
              color: root.bar.foreground
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.bodySmall
              font.bold: true
              anchors.verticalCenter: parent.verticalCenter
            }

            Text {
              id: watchDot
              visible: nowPlayingCard.showLine !== ""
              textFormat: Text.PlainText
              text: "·"
              color: Color.accent
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.bodySmall
              anchors.verticalCenter: parent.verticalCenter
            }

            Text {
              visible: nowPlayingCard.showLine !== ""
              width: Math.max(0, watchLine.width - watchChannel.width - watchDot.width - watchLine.spacing * 2)
              textFormat: Text.PlainText
              text: nowPlayingCard.showLine
              color: (!tuneProc.running && root.tunePhase === "failed" && nowPlayingCard.showLine === root.tuneMessage) ? Color.urgent : Color.accent
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.bodySmall
              elide: Text.ElideRight
              anchors.verticalCenter: parent.verticalCenter
            }
          }
        }
      }

      Repeater {
        model: root.activeRecordings

        BorderSurface {
          required property var modelData
          width: parent.width
          implicitHeight: recRow.implicitHeight + Style.space(12)
          radius: Style.spacing.labelGap
          color: Style.selectedFillFor(root.bar.foreground, Color.urgent)
          borderSpec: Border.controlSpec("normal", root.bar.foreground, Color.urgent)

          Item {
            id: recRow
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: Style.space(6)
            implicitHeight: Math.max(recLine.implicitHeight, recStopBtn.implicitHeight)
            height: implicitHeight

            Button {
              id: recStopBtn
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              text: "Stop"
              tooltipText: "Stop this recording"
              foreground: Color.urgent
              fontSize: Style.font.caption
              onClicked: root.toggleRecord(root.recordingIdent(modelData))
            }

            Row {
              id: recLine
              anchors.left: parent.left
              anchors.right: recStopBtn.left
              anchors.rightMargin: Style.space(8)
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(4)

              Text {
                id: recChannel
                textFormat: Text.PlainText
                text: root.recordingTitle(modelData)
                color: root.bar.foreground
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.bodySmall
                font.bold: true
                anchors.verticalCenter: parent.verticalCenter
              }

              Text {
                id: recDot
                visible: !!(modelData && modelData.program_title)
                textFormat: Text.PlainText
                text: "·"
                color: Color.accent
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.bodySmall
                anchors.verticalCenter: parent.verticalCenter
              }

              Text {
                visible: !!(modelData && modelData.program_title)
                width: Math.max(0, recLine.width - recChannel.width - recDot.width - recLine.spacing * 2)
                textFormat: Text.PlainText
                text: modelData && modelData.program_title ? modelData.program_title : ""
                color: Color.urgent
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.bodySmall
                elide: Text.ElideRight
                anchors.verticalCenter: parent.verticalCenter
              }
            }
          }
        }
      }

      BorderSurface {
        id: guideUpdateCard
        visible: root.guideRefreshing
        width: parent.width
        implicitHeight: guideUpdateRow.implicitHeight + Style.space(12)
        radius: Style.spacing.labelGap
        color: Style.selectedFillFor(root.bar.foreground, Color.accent)
        borderSpec: Border.controlSpec("normal", root.bar.foreground, Color.accent)

        Item {
          id: guideUpdateRow
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.top: parent.top
          anchors.margins: Style.space(6)
          implicitHeight: guideUpdateLine.implicitHeight
          height: implicitHeight

          Text {
            id: guideUpdateLine
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            textFormat: Text.PlainText
            text: "Updating the Guide"
            color: Color.accent
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.bodySmall
            font.bold: true
            elide: Text.ElideRight
          }
        }
      }

      BorderSurface {
        id: scheduleCard
        visible: root.scheduleLine !== ""
        width: parent.width
        implicitHeight: scheduleRow.implicitHeight + Style.space(12)
        radius: Style.spacing.labelGap
        color: Style.selectedFillFor(root.bar.foreground, Color.accent)
        borderSpec: Border.controlSpec("normal", root.bar.foreground, Color.accent)

        Item {
          id: scheduleRow
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.top: parent.top
          anchors.margins: Style.space(6)
          implicitHeight: scheduleLineText.implicitHeight
          height: implicitHeight

          MouseArea {
            anchors.fill: parent
            onClicked: {
              root.guideStripOpen = true
              root.snapGuideBlock()
            }
          }

          Text {
            id: scheduleLineText
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            textFormat: Text.PlainText
            text: root.scheduleLine
            color: Color.accent
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.bodySmall
            font.bold: true
            elide: Text.ElideRight
          }
        }
      }

      Column {
        id: guideStripCol
        visible: root.guideStripOpen
        width: parent.width
        spacing: Style.space(6)

        TextField {
          id: guideStripSearch
          width: parent.width
          placeholderText: "Search titles"
          font.family: root.bar.fontFamily
          onTextChanged: root.guideSearchText = text
        }

        Item {
          id: guideBlockNav
          visible: !root.guideSearchActive && root.guideStripRows.length > 0
          width: parent.width
          height: Math.max(earlierBtn.implicitHeight, laterBtn.implicitHeight)

          Button {
            id: earlierBtn
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            text: "Earlier"
            enabled: root.guideBlockIndex > 0
            fontSize: Style.font.caption
            foreground: root.bar.foreground
            onClicked: root.shiftGuideBlock(-1)
          }

          Item {
            id: hourHead
            anchors.left: parent.left
            anchors.leftMargin: root.guideNameCol + Style.space(6)
            anchors.right: laterBtn.left
            anchors.rightMargin: Style.space(6)
            anchors.verticalCenter: parent.verticalCenter
            height: parent.height

            Repeater {
              model: root.guideHourLabels
              delegate: Text {
                required property string modelData
                required property int index
                x: index * (root.guideHourCol + Style.space(6))
                y: Math.max(0, (hourHead.height - implicitHeight) / 2)
                width: root.guideHourCol
                textFormat: Text.PlainText
                text: modelData
                color: root.bar.foreground
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.caption
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
              }
            }
          }

          Button {
            id: laterBtn
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            text: "Later"
            enabled: root.guideBlockIndex < (root.guideBlocks.length - 1)
            fontSize: Style.font.caption
            foreground: root.bar.foreground
            onClicked: root.shiftGuideBlock(1)
          }
        }

        Text {
          visible: root.guideStripOpen && !root.guideSearchActive && root.guideStripRows.length === 0
          width: parent.width
          textFormat: Text.PlainText
          text: "Nothing listed in these hours."
          color: Qt.darker(root.bar.foreground, 1.4)
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.Wrap
        }

        Flickable {
          id: stripFlick
          width: parent.width
          height: Math.min(stripShowsCol.implicitHeight, Style.space(280))
          contentWidth: width
          contentHeight: stripShowsCol.implicitHeight
          clip: true
          visible: !root.guideSearchActive && root.guideStripRows.length > 0
          flickableDirection: Flickable.VerticalFlick
          boundsBehavior: Flickable.StopAtBounds

          Column {
            id: stripShowsCol
            width: stripFlick.width
            spacing: Style.space(4)

            Repeater {
              model: root.guideStripRows
              delegate: Item {
                id: stripRow
                required property var modelData
                required property int index
                width: stripShowsCol.width
                implicitHeight: Math.max(stripName.implicitHeight + Style.space(10), Style.space(32))
                height: implicitHeight

                Rectangle {
                  anchors.left: parent.left
                  anchors.top: parent.top
                  anchors.bottom: parent.bottom
                  width: Style.space(3)
                  color: Model.networkColor(modelData.network, Color.accent)
                }

                Text {
                  id: stripName
                  anchors.left: parent.left
                  anchors.leftMargin: Style.space(8)
                  anchors.verticalCenter: parent.verticalCenter
                  width: root.guideNameCol - Style.space(8)
                  textFormat: Text.PlainText
                  text: modelData.display_name || modelData.tune_name || ""
                  color: root.bar.foreground
                  font.family: root.bar.fontFamily
                  font.pixelSize: Style.font.bodySmall
                  font.bold: true
                  elide: Text.ElideRight
                }

                Repeater {
                  model: modelData.cells
                  delegate: Item {
                    required property var modelData
                    required property int index
                    x: root.guideNameCol + Style.space(6) + index * (root.guideHourCol + Style.space(6))
                    width: root.guideHourCol
                    height: stripRow.height

                    MouseArea {
                      anchors.fill: parent
                      enabled: (modelData.title || "") !== ""
                      hoverEnabled: enabled
                      cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                      onClicked: root.useStripShow(modelData)
                    }

                    Text {
                      anchors.left: parent.left
                      anchors.right: parent.right
                      anchors.verticalCenter: parent.verticalCenter
                      textFormat: Text.PlainText
                      text: modelData.title || ""
                      color: root.bar.foreground
                      font.family: root.bar.fontFamily
                      font.pixelSize: Style.font.caption
                      elide: Text.ElideRight
                    }
                  }
                }
              }
            }
          }
        }

        Flickable {
          id: stripSearchFlick
          width: parent.width
          height: Math.min(stripSearchCol.implicitHeight, Style.space(220))
          contentWidth: width
          contentHeight: stripSearchCol.implicitHeight
          clip: true
          visible: root.guideSearchActive && root.guideSearchHits.length > 0
          flickableDirection: Flickable.VerticalFlick
          boundsBehavior: Flickable.StopAtBounds

          Column {
            id: stripSearchCol
            width: stripSearchFlick.width

            Repeater {
              model: root.guideSearchHits
              delegate: Item {
                required property var modelData
                required property int index
                width: stripSearchCol.width
                implicitHeight: stripSearchLine.implicitHeight + Style.space(8)

                MouseArea {
                  anchors.fill: parent
                  hoverEnabled: true
                  cursorShape: Qt.PointingHandCursor
                  onClicked: root.useStripShow(modelData)
                }

                Text {
                  id: stripSearchLine
                  width: parent.width
                  textFormat: Text.PlainText
                  text: (modelData.display_name || modelData.tune_name || modelData.channel_number || "")
                        + "  " + (modelData.title || "")
                        + (modelData.start ? "  " + modelData.start : "")
                  color: root.bar.foreground
                  font.family: root.bar.fontFamily
                  font.pixelSize: Style.font.bodySmall
                  elide: Text.ElideRight
                }
              }
            }
          }
        }

        Text {
          visible: root.scheduleItems.length > 0
          textFormat: Text.PlainText
          text: "Waiting to record"
          color: root.bar.foreground
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: true
        }

        Repeater {
          model: root.scheduleItems
          delegate: Row {
            required property var modelData
            width: guideStripCol.width
            spacing: Style.space(6)

            Text {
              width: Math.max(0, parent.width - stripRemove.width - parent.spacing)
              textFormat: Text.PlainText
              text: (modelData.display_name || modelData.tune_name || "")
                    + " · " + (modelData.title || "")
                    + (modelData.clock ? " · " + modelData.clock : "")
              color: Color.accent
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              elide: Text.ElideRight
              anchors.verticalCenter: parent.verticalCenter
            }

            Button {
              id: stripRemove
              text: "Remove"
              fontSize: Style.font.caption
              foreground: root.bar.foreground
              onClicked: root.removeScheduled(modelData.id)
            }
          }
        }
      }

      Item {
        visible: !root.bothTunersBusy
        width: parent.width
        height: Math.max(Style.space(32), channelListToggle.implicitHeight)

        Text {
          anchors.left: parent.left
          anchors.verticalCenter: parent.verticalCenter
          textFormat: Text.PlainText
          text: root.channelListLabel
          color: root.bar.foreground
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.bodySmall
          font.bold: true
        }

        Button {
          id: channelListToggle
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          text: root.channelListOpen ? "Hide" : "Show"
          tooltipText: root.channelListOpen ? "Hide the channel list" : "Show the channel list"
          foreground: root.bar.foreground
          fontSize: Style.font.caption
          onClicked: root.channelListOpen = !root.channelListOpen
        }
      }

      Row {
        visible: root.showChannelBrowser
        width: parent.width
        spacing: Style.space(6)

        Row {
          id: filterTabRow
          spacing: Style.space(4)

          Button {
            text: "Favs (" + root.favoriteVisibleCount + ")"
            tooltipText: "Favorite channels"
            selected: root.channelFilter === "favorites"
            fontSize: Style.font.caption
            foreground: root.bar.foreground
            onClicked: root.setChannelFilter("favorites")
          }

          Button {
            text: "Watchable (" + (root.watchableChannels ? root.watchableChannels.length : 0) + ")"
            tooltipText: "Stations worth watching"
            selected: root.channelFilter === "watchable"
            fontSize: Style.font.caption
            foreground: root.bar.foreground
            onClicked: root.setChannelFilter("watchable")
          }

          Button {
            text: "All (" + (root.watchableChannels ? root.watchableChannels.length : 0) + ")"
            tooltipText: "Same stations, with Hide"
            selected: root.channelFilter === "all"
            fontSize: Style.font.caption
            foreground: root.bar.foreground
            onClicked: root.setChannelFilter("all")
          }

          Button {
            visible: root.hiddenData && root.hiddenData.length > 0
            text: "Hidden (" + root.hiddenData.length + ")"
            tooltipText: "Stations set aside"
            selected: root.channelFilter === "hidden"
            fontSize: Style.font.caption
            foreground: root.bar.foreground
            onClicked: root.setChannelFilter("hidden")
          }
        }
      }

      // Empty State (No Channels Scanned)
      Item {
        visible: root.showChannelBrowser && root.channelsData.length === 0 && !root.isScanning
        width: parent.width
        height: Style.space(110)

        Column {
          anchors.centerIn: parent
          spacing: Style.space(8)
          Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "No channels found yet"
            color: Qt.darker(root.bar.foreground, 1.5)
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.bodySmall
          }
          Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "Scan for local Over-The-Air stations."
            color: Qt.darker(root.bar.foreground, 1.8)
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
          }
          Button {
            anchors.horizontalCenter: parent.horizontalCenter
            iconText: "󰍉"
            text: "Scan"
            foreground: root.bar.foreground
            onClicked: root.startScan()
          }
        }
      }

      // Empty State (No Favorites Selected)
      Item {
        visible: root.showChannelBrowser && root.channelsData.length > 0 && root.channelFilter === "favorites" && root.displayChannels.length === 0
        width: parent.width
        height: Style.space(70)

        Column {
          anchors.centerIn: parent
          spacing: Style.space(4)
          Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "⭐ No favorite channels yet"
            color: Qt.darker(root.bar.foreground, 1.3)
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.bodySmall
            font.bold: true
          }
          Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "Click the ☆ star on any station below to pin it here."
            color: Qt.darker(root.bar.foreground, 1.8)
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
          }
        }
      }
      }

      // Channel List Scroll Area
      Item {
        id: channelScrollContainer
        visible: root.showChannelBrowser && root.displayChannels.length > 0
        width: parent.width
        implicitHeight: height
        height: {
          if (!visible) return 0
          var extra = (guideStripCol.visible ? guideStripCol.implicitHeight : 0)
          var room = root.roomFor(remoteChrome.implicitHeight + mainCol.spacing + extra)
          var content = channelListView.implicitHeight
          if (content > 0) return Math.min(content, room)
          return Math.min(Style.space(160), room)
        }
        clip: true

        Flickable {
          id: channelFlickable
          anchors.fill: parent
          contentWidth: width
          contentHeight: channelListView.implicitHeight
          boundsBehavior: Flickable.StopAtBounds
          flickableDirection: Flickable.VerticalFlick
          clip: true

          Column {
            id: channelListView
            width: channelFlickable.width
            spacing: Style.space(4)

              Repeater {
              model: root.displayChannels

              CursorSurface {
                id: chItem
                required property var modelData
                required property int index
                readonly property bool isCurrent: root.activeChannelName === modelData.name || root.activeChannelName === modelData.tune_name
                readonly property var program: root.getProgram(modelData)
                readonly property var onNow: Model.currentProgram(program, root.guideClockMin)
                readonly property string channelBadge: Model.getChannelBadge(modelData)
                readonly property string netColor: Model.networkColor(modelData.network, Color.accent)
                readonly property bool isFav: root.isFavorite(modelData.name) || (modelData.tune_name && root.isFavorite(modelData.tune_name))

                width: channelListView.width
                height: Math.max(Style.space(36), chLine.implicitHeight + Style.space(12))
                foreground: root.bar.foreground
                accent: Color.accent
                hasCursor: root.cursorActive && root.cursorIndex === index
                current: isCurrent

                Rectangle {
                  anchors.left: parent.left
                  anchors.top: parent.top
                  anchors.bottom: parent.bottom
                  width: Style.space(3)
                  color: chItem.netColor
                }

                MouseArea {
                  anchors.fill: parent
                  hoverEnabled: true
                  cursorShape: Qt.PointingHandCursor
                  onEntered: {
                    root.cursorActive = true
                    root.cursorIndex = chItem.index
                  }
                  onClicked: root.useListedChannel(chItem.modelData.tune_name || chItem.modelData.name)
                  onWheel: function(wheel) { wheel.accepted = false }
                }

                Button {
                  id: hideBtn
                  visible: root.channelFilter === "all" || root.channelFilter === "hidden"
                  anchors.right: parent.right
                  anchors.rightMargin: Style.space(4)
                  anchors.verticalCenter: parent.verticalCenter
                  text: root.channelFilter === "hidden" ? "Show" : "Hide"
                  tooltipText: root.channelFilter === "hidden" ? "Put this station back" : "Set this station aside"
                  fontSize: Style.font.caption
                  foreground: root.bar.foreground
                  onClicked: {
                    if (root.channelFilter === "hidden") root.showListed(chItem.modelData)
                    else root.hideListed(chItem.modelData)
                  }
                }

                PanelActionButton {
                  id: favBtn
                  anchors.right: hideBtn.visible ? hideBtn.left : parent.right
                  anchors.rightMargin: hideBtn.visible ? Style.space(4) : Style.space(6)
                  anchors.verticalCenter: parent.verticalCenter
                  size: Style.space(20)
                  fontSize: Style.font.bodySmall
                  iconText: chItem.isFav ? "★" : "☆"
                  tooltipText: chItem.isFav ? "Remove favorite" : "Add favorite"
                  foreground: chItem.isFav ? Color.accent : Qt.darker(root.bar.foreground, 1.8)
                  fontFamily: root.bar.fontFamily
                  onClicked: root.toggleFavorite(chItem.modelData.tune_name || chItem.modelData.name)
                }

                Row {
                  id: chLine
                  anchors.left: parent.left
                  anchors.right: favBtn.left
                  anchors.leftMargin: Style.space(10)
                  anchors.rightMargin: Style.space(8)
                  anchors.verticalCenter: parent.verticalCenter
                  spacing: Style.space(4)

                  Text {
                    id: chNum
                    textFormat: Text.PlainText
                    text: chItem.channelBadge
                    color: chItem.isCurrent ? Color.accent : root.bar.foreground
                    font.family: root.bar.fontFamily
                    font.pixelSize: Style.font.bodySmall
                    font.bold: true
                    width: Math.max(implicitWidth, Style.space(40))
                    anchors.verticalCenter: parent.verticalCenter
                  }

                  Text {
                    id: chName
                    textFormat: Text.PlainText
                    text: Model.getDisplayTitle(chItem.modelData)
                    color: root.bar.foreground
                    font.family: root.bar.fontFamily
                    font.pixelSize: Style.font.bodySmall
                    font.bold: chItem.isCurrent
                    anchors.verticalCenter: parent.verticalCenter
                  }

                  Text {
                    id: chDot
                    visible: !!chItem.onNow
                    textFormat: Text.PlainText
                    text: "·"
                    color: Color.accent
                    font.family: root.bar.fontFamily
                    font.pixelSize: Style.font.bodySmall
                    anchors.verticalCenter: parent.verticalCenter
                  }

                  Text {
                    visible: !!chItem.onNow
                    width: {
                      var used = chNum.width + chName.width + chLine.spacing * 2
                      if (chDot.visible) used += chDot.width + chLine.spacing
                      return Math.max(0, chLine.width - used)
                    }
                    textFormat: Text.PlainText
                    text: chItem.onNow ? chItem.onNow.title : ""
                    color: chItem.isCurrent ? Color.accent : Qt.darker(root.bar.foreground, 1.4)
                    font.family: root.bar.fontFamily
                    font.pixelSize: Style.font.bodySmall
                    elide: Text.ElideRight
                    anchors.verticalCenter: parent.verticalCenter
                  }
                }
              }
            }
          }
        }
        // Scroll indicator track and thumb
        BorderSurface {
          anchors.right: parent.right
          anchors.top: parent.top
          anchors.bottom: parent.bottom
          anchors.margins: 2
          width: 4
          radius: 2
          color: Qt.darker(root.bar.foreground, 2.8)
          visible: channelFlickable.contentHeight > channelFlickable.height

          Rectangle {
            id: scrollThumb
            width: parent.width
            radius: 2
            color: Color.accent
            height: Math.max(16, channelFlickable.height * (channelFlickable.height / Math.max(1, channelFlickable.contentHeight)))
            y: (channelFlickable.contentHeight > channelFlickable.height) ? ((channelFlickable.contentY / (channelFlickable.contentHeight - channelFlickable.height)) * (parent.height - height)) : 0
          }
        }
      }
      }

      Column {
        id: libraryView
        visible: root.libraryModalOpen
        width: parent.width
        spacing: Style.space(10)

        Item {
          id: libraryHeader
          width: parent.width
          implicitHeight: height
          height: Math.max(Style.space(36), libraryBackBtn.implicitHeight)

          BorderSurface {
            width: Style.space(36)
            height: Style.space(36)
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            radius: Style.spacing.labelGap
            color: Style.normalFillFor(root.bar.foreground, Color.accent)
            borderSpec: Border.controlSpec("normal", root.bar.foreground, Color.accent)

            Text {
              anchors.centerIn: parent
              text: "󰑈"
              color: Color.accent
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.subtitle
            }
          }

          Button {
            id: libraryBackBtn
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            iconText: "󰅖"
            text: "Back"
            tooltipText: "Back"
            foreground: root.bar.foreground
            onClicked: root.toggleLibrary()
          }

          Button {
            id: libraryCapBtn
            anchors.right: libraryBackBtn.left
            anchors.rightMargin: Style.space(6)
            anchors.verticalCenter: parent.verticalCenter
            text: root.libraryCapButtonText()
            tooltipText: "Library size cap"
            fontSize: Style.font.caption
            foreground: root.bar.foreground
            onClicked: root.cycleLibraryCap()
          }

          Column {
            anchors.left: parent.left
            anchors.right: libraryCapBtn.left
            anchors.leftMargin: Style.space(44)
            anchors.rightMargin: Style.space(8)
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(2)

            Text {
              textFormat: Text.PlainText
              text: "Recordings"
              color: root.bar.foreground
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.bodySmall
              font.bold: true
              elide: Text.ElideRight
              width: parent.width
            }

            Text {
              textFormat: Text.PlainText
              text: (root.recordingsData.length > 0)
                ? (root.libraryBytesLabel + " of " + root.libraryBudgetLabel + " · " + root.recordingsData.length + " in Videos/TV")
                : "Nothing recorded yet"
              color: Qt.darker(root.bar.foreground, 1.5)
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              elide: Text.ElideRight
              width: parent.width
            }
          }
        }

        Item {
          visible: root.recordingsData.length === 0
          width: parent.width
          height: Style.space(80)

          Text {
            anchors.centerIn: parent
            text: "Record from the Guide, then play it back here."
            color: Qt.darker(root.bar.foreground, 1.5)
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
          }
        }

        Item {
          id: libraryList
          visible: root.recordingsData.length > 0
          width: parent.width
          implicitHeight: height
          height: {
            if (!visible) return 0
            var content = recCol.implicitHeight
            var room = root.roomFor(libraryHeader.height + mainCol.spacing + Style.space(24))
            if (content > 0) return Math.min(content, room)
            return Math.min(Style.space(120), room)
          }
          clip: true

          Flickable {
            anchors.fill: parent
            contentWidth: width
            contentHeight: recCol.implicitHeight
            boundsBehavior: Flickable.StopAtBounds
            flickableDirection: Flickable.VerticalFlick
            clip: true

            Column {
              id: recCol
              width: parent.width
              spacing: Style.space(6)

              Repeater {
                model: root.recordingsData

                CursorSurface {
                  id: recRow
                  required property var modelData
                  required property int index
                  width: recCol.width
                  height: Style.space(52)
                  foreground: root.bar.foreground
                  accent: Color.accent
                  hasCursor: root.libraryModalOpen && root.cursorActive && root.recCursorIndex === index

                  MouseArea {
                    anchors.fill: parent
                    anchors.rightMargin: Style.space(32)
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onEntered: {
                      root.cursorActive = true
                      root.recCursorIndex = recRow.index
                    }
                    onClicked: root.playRecording(recRow.modelData.path || recRow.modelData.name, recRow.modelData.playable)
                  }

                  Column {
                    anchors.left: parent.left
                    anchors.leftMargin: Style.space(6)
                    anchors.right: recDeleteBtn.left
                    anchors.rightMargin: Style.space(8)
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: Style.space(2)

                    Text {
                      textFormat: Text.PlainText
                      text: recRow.modelData.title || recRow.modelData.name
                      color: recRow.modelData.playable === false ? Qt.darker(root.bar.foreground, 1.5) : root.bar.foreground
                      font.family: root.bar.fontFamily
                      font.pixelSize: Style.font.bodySmall
                      font.bold: true
                      elide: Text.ElideRight
                      width: parent.width
                    }

                    Text {
                      textFormat: Text.PlainText
                      text: ((recRow.modelData.channel_number || recRow.modelData.station)
                        ? ((recRow.modelData.channel_number || "") + " " + (recRow.modelData.station || "") + " · ")
                        : "") + (recRow.modelData.date_formatted || "") + " · " + (recRow.modelData.size_formatted || "")
                        + (recRow.modelData.playable === false ? " · empty dump" : "")
                      color: Qt.darker(root.bar.foreground, 1.5)
                      font.family: root.bar.fontFamily
                      font.pixelSize: Style.font.caption
                      elide: Text.ElideRight
                      width: parent.width
                    }
                  }

                  PanelActionButton {
                    id: recDeleteBtn
                    anchors.right: parent.right
                    anchors.rightMargin: Style.space(2)
                    anchors.verticalCenter: parent.verticalCenter
                    iconText: "󰅙"
                    tooltipText: "Delete"
                    foreground: root.bar.foreground
                    hoverColor: root.bar.foreground
                    fontFamily: root.bar.fontFamily
                    onClicked: root.deleteRecording(recRow.modelData.path || recRow.modelData.name)
                  }
                }
              }
            }
          }
        }
      }
    }
    }
  }
}
