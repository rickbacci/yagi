import QtQuick
import Quickshell
import Quickshell.Io
import qs.Ui
import qs.Commons
import "Model.js" as Model

BarWidget {
  id: root
  moduleName: "richardb.omarchy-tv"

  readonly property string tvConfigDir: Model.tvConfigDir(
    Quickshell.env("XDG_CONFIG_HOME"),
    Quickshell.env("HOME")
  )
  property string binPath: "omarchy-tv"

  property bool popupOpen: false
  readonly property bool opened: root.popupOpen
  property bool popoutSwitchClosing: false
  onPopupOpenChanged: {
    if (!root.popupOpen) {
      root.guideStripOpen = false
      return
    }
    if (root.popupOpen) {
      root.libraryModalOpen = false
      root.cursorActive = false
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
  // Two tuners, one pool. A Guide update gives its tuner up, so it never counts.
  readonly property bool liveOn: root.activeChannelName !== "" && root.isLiveSession
  readonly property int tunersFree: Math.max(0, 2 - (root.liveOn ? 1 : 0)
                                             - (root.activeRecordings ? root.activeRecordings.length : 0)
                                             - (root.isScanning ? 1 : 0))
  property string pendingWatch: ""
  property string watchAfterStop: ""
  readonly property bool flyoutStatusOn: root.activeChannelName !== "" || root.isRecording || root.isScanning || root.guideRefreshing
  readonly property bool showChannelBrowser: !root.guideStripOpen
  property int guideClockMin: -1
  property string channelFilter: "favorites" // favorites | all | hidden
  property var hiddenData: []
  property string playerMode: "live"
  property string lastLiveChannel: ""
  property bool pauseKept: false
  readonly property bool isLibraryPlayback: root.playerMode === "recording"
  readonly property bool isLiveSession: root.playerMode === "live" || root.playerMode === "timeshift"
  readonly property bool isPlayback: root.isLibraryPlayback || root.playerMode === "timeshift"
  property bool cursorActive: false
  property int cursorIndex: 0
  property bool guideRefreshStarted: false
  property bool guideStatusRunning: false
  property int guideStatusTower: 0
  property int guideStatusTowers: 0
  readonly property bool guideRefreshing: root.guideRefreshStarted || root.guideStatusRunning
  property var showItems: []
  property var ruleIds: ({})
  property var ruleKeep: ({})
  property var ruleByShow: ({})
  property string deleteArmed: ""

  Timer {
    id: deleteDisarm
    interval: 3000
    onTriggered: root.deleteArmed = ""
  }
  property string showBucket: Model.bucketNow()
  readonly property var guideShowRows: Model.filterShows(root.showItems, root.showBucket)
  property var scheduleItems: []
  readonly property string scheduleLine: {
    var items = root.scheduleItems || []
    if (!items.length) return ""
    if (items.length === 1) {
      var one = items[0]
      var who = one.display_name || one.tune_name || ""
      var when = one.clock || ""
      var missed = one.status === "missed" ? "Missed · " : ""
      return missed + who + (one.title ? " · " + one.title : "") + (when ? " · " + when : "")
    }
    return items.length + " waiting to record"
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

  function stationFor(channelNumber) {
    var list = root.channelsData || []
    for (var i = 0; i < list.length; i++) {
      if (list[i] && String(list[i].channel_number) === String(channelNumber))
        return Model.getDisplayTitle(list[i])
    }
    return ""
  }

  // Header, search, tabs, and the waiting list take the rest.
  function guideListRoom() {
    var waiting = (root.scheduleItems || []).length
    return root.roomFor(Style.space(230) + (waiting ? Style.space(24) + waiting * Style.space(30) : 0))
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
    if (guideRefreshProc.running || root.guideStatusRunning) return
    if (root.tunersFree === 0) return
    root.guideRefreshStarted = true
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

  onGuideStripOpenChanged: {
    if (!root.guideStripOpen) return
    root.showBucket = Model.bucketNow()
    root.loadShows()
  }

  function loadShows() {
    showsProc.running = false
    showsProc.command = [root.binPath, "guide", "shows"]
    showsProc.running = true
  }

  function applyShows(raw) {
    try {
      var data = JSON.parse(raw || "{}")
      root.showItems = data.shows || []
    } catch (e) {
      root.showItems = []
    }
  }

  function applyRules(raw) {
    var ids = {}
    var keep = {}
    var byShow = {}
    try {
      var rules = (JSON.parse(raw || "{}").rules) || []
      for (var i = 0; i < rules.length; i++) {
        if (rules[i] && rules[i].id) {
          ids[rules[i].id] = true
          keep[rules[i].id] = Number(rules[i].keep_last) || 0
          byShow[Model.showKey(rules[i].title, rules[i].channel)] = rules[i].id
        }
      }
    } catch (e) {
    }
    root.ruleIds = ids
    root.ruleKeep = keep
    root.ruleByShow = byShow
  }

  function toggleRecordAll(show) {
    if (!show) return
    ruleProc.running = false
    if (show.id && root.ruleIds[show.id]) {
      ruleProc.command = [root.binPath, "record", "unall", show.id]
    } else {
      if (!show.tune_name) return
      ruleProc.command = [
        root.binPath, "record", "all", show.tune_name,
        "--title", show.title || "",
        "--channel", show.channel || ""
      ]
    }
    ruleProc.running = true
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
    var cmd = [
      root.binPath, "record", "later", show.tune_name, String(dur),
      "--title", show.title || "Scheduled",
      "--gps", String(show.gps_start),
      "--clock", show.start || "",
      "--end-clock", show.end || "",
      "--display-name", show.display_name || show.tune_name
    ]
    if (Model.isGameTitle(show.title)) cmd.push("--extra", Model.gameExtraMin() + "m")
    schedProc.command = cmd
    schedProc.running = true
  }

  function scheduledId(show) {
    if (!show || !show.tune_name || !show.gps_start) return ""
    var ident = show.tune_name + "-" + show.gps_start
    var items = root.scheduleItems || []
    for (var i = 0; i < items.length; i++) {
      if (items[i] && items[i].id === ident) return ident
    }
    return ""
  }

  function hitRecordState(show) {
    if (!show) return ""
    if (show.on_now && root.isChannelRecording(show.tune_name)) return "recording"
    if (root.scheduledId(show)) return "scheduled"
    return ""
  }

  function freeTunerForRecording() {
    return root.tunersFree > 0
  }

  function hitRuleId(hit) {
    return hit ? (root.ruleByShow[Model.showKey(hit.title, hit.channel_number)] || "") : ""
  }

  function toggleHitRecordAll(hit) {
    if (!hit) return
    var ruled = root.hitRuleId(hit)
    root.toggleRecordAll({ id: ruled, tune_name: hit.tune_name, title: hit.title, channel: hit.channel_number })
  }

  function toggleHitRecord(show) {
    var state = root.hitRecordState(show)
    if (state === "recording") root.stopRecord(show.tune_name)
    else if (state === "scheduled") root.removeScheduled(root.scheduledId(show))
    else root.useStripShow(show)
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
      if (!root.freeTunerForRecording()) return
      var left = Model.recordDurationArg(show, root.guideClockMin)
      if (left && Model.isGameTitle(show.title)) left = (parseInt(left, 10) + Model.gameExtraMin()) + "m"
      root.startRecord(show.tune_name, left, show.title || "")
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
    if (!root.pendingWatch) root.close()
  }

  function stopToWatch(rec) {
    root.watchAfterStop = root.pendingWatch
    root.pendingWatch = ""
    root.stopRecord(root.recordingIdent(rec))
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
    if (!root.showChannelBrowser) return 0
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
    if (ch) root.useListedChannel(root.listedKey(ch))
  }

  function listedKey(ch) {
    if (!ch) return ""
    return ch.channel_number || ch.tune_name || ch.name || ""
  }

  function useListedChannel(chName) {
    if (!chName) return
    root.selectChannel(chName)
  }

  function startRecord(chName, duration, title) {
    if (!chName) return
    dvrProc.running = false
    var cmd = [root.binPath, "record", "start", chName]
    if (duration) cmd.push(duration)
    if (title) {
      cmd.push("--title")
      cmd.push(title)
    }
    dvrProc.command = cmd
    dvrProc.running = true
  }

  function stopRecord(chName) {
    if (!chName) return
    dvrProc.running = false
    dvrProc.command = [root.binPath, "record", "stop", chName]
    dvrProc.running = true
  }

  function toggleRecord(chName) {
    if (!chName) return
    if (root.isChannelRecording(chName)) {
      root.stopRecord(chName)
      return
    }
    root.startRecord(chName)
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
      root.startRecord(chName, dur, title)
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

  function open() {
    root.popupOpen = true
  }

  function close() {
    root.popupOpen = false
  }

  function closeForPopoutSwitch() {
    root.popoutSwitchClosing = true
    root.close()
    Qt.callLater(function() { root.popoutSwitchClosing = false })
  }

  function toggle() { root.opened ? root.close() : root.open() }

  function playChannel(chName) {
    if (tuneProc.running && root.activeChannelName === chName)
      return
    if (!root.liveOn && root.tunersFree === 0 && (root.activeRecordings || []).length > 0) {
      root.pendingWatch = chName
      root.open()
      return
    }
    root.pendingWatch = ""
    root.tuneNow(chName)
  }

  function tuneNow(chName) {
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
      if ((ch.channel_number || "").toLowerCase() === q || (ch.name || "").toLowerCase() === q || (ch.tune_name || "").toLowerCase() === q) {
        idx = i
        break
      }
    }
    var next = idx < 0 ? (delta > 0 ? 0 : list.length - 1) : ((idx + delta + list.length) % list.length)
    var target = list[next]
    root.playChannel(root.listedKey(target))
  }

  function channelUp() {
    root.cycleListed(1)
  }

  function channelDown() {
    root.cycleListed(-1)
  }

  function keepPause() {
    if (root.pauseKept || keepProc.running) return
    keepProc.command = [root.binPath, "keep"]
    keepProc.running = true
  }

  function stopPlayer() {
    root.pauseKept = false
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
    if (cur === "auto" || cur === undefined || cur === null || cur === "") next = "50"
    else if (cur === 0 || cur === "0" || cur === "off") next = "auto"
    else if (Number(cur) < 50) next = "50"
    else if (Number(cur) < 100) next = "100"
    else if (Number(cur) < 250) next = "250"
    else next = "off"
    prefsProc.running = false
    prefsProc.command = [root.binPath, "pref", "library-max", next]
    prefsProc.running = true
  }

  function libraryCapButtonText() {
    var cur = root.libraryMaxGb
    if (cur === 0 || cur === "0" || cur === "off") return "No limit"
    if (cur === "auto" || cur === undefined || cur === null || cur === "") return "Limit: auto"
    return "Limit: " + cur + " GB"
  }

  function setRecordingKept(rec, keep) {
    if (!rec) return
    dvrProc.running = false
    dvrProc.command = [root.binPath, "record", keep ? "keep" : "unkeep", rec.path || rec.name]
    dvrProc.running = true
  }

  function cycleShowLimit(show) {
    if (!show || !root.ruleIds[show.id]) return
    var cur = root.ruleKeep[show.id] || 0
    var next = cur === 0 ? 10 : (cur === 10 ? 30 : 0)
    ruleProc.running = false
    ruleProc.command = [root.binPath, "record", "limit", show.id, String(next)]
    ruleProc.running = true
  }

  function showLimitText(show) {
    var n = (show && root.ruleKeep[show.id]) || 0
    return n ? "Keep " + n : "Keep all"
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
      root.channelFilter = "all"
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

  function getActiveDisplayNameFor(ident) {
    var list = root.channelsData || []
    for (var i = 0; i < list.length; i++) {
      var ch = list[i]
      if (ch && (ch.name === ident || ch.tune_name === ident || String(ch.channel_number) === String(ident)))
        return Model.getDisplayTitle(ch)
    }
    return ident || "that channel"
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
      root.open()
    }

    function close(): void {
      root.close()
    }

    function show(): void {
      root.open()
    }

    function hide(): void {
      root.close()
    }

    function guide(): void {
      root.libraryModalOpen = false
      root.guideClockMin = Model.minutesNow()
      root.guideStripOpen = true
      root.open()
    }
  }

  readonly property string cliBesidePluginPath: Model.fileUrlToPath(Qt.resolvedUrl("../bin/omarchy-tv"))
  readonly property string cliBesideRootPath: Model.fileUrlToPath(Qt.resolvedUrl("bin/omarchy-tv"))

  Process {
    id: cliCheckPlugin
    command: ["test", "-x", root.cliBesidePluginPath]
    running: true
    onExited: function(code) {
      if (code === 0)
        root.binPath = root.cliBesidePluginPath
      else
        cliCheckRoot.running = true
    }
  }

  Process {
    id: cliCheckRoot
    command: ["test", "-x", root.cliBesideRootPath]
    onExited: function(code) {
      if (code === 0 && root.binPath === "omarchy-tv")
        root.binPath = root.cliBesideRootPath
    }
  }

  // Watch channels.json file
  FileView {
    id: channelsFile
    path: root.tvConfigDir + "/channels.json"
    watchChanges: true
    printErrors: false
    onLoaded: root.applyChannels(text())
    onFileChanged: reload()
  }

  // Watch favorites.json file
  FileView {
    id: favoritesFile
    path: root.tvConfigDir + "/favorites.json"
    watchChanges: true
    printErrors: false
    onLoaded: root.applyFavorites(text())
    onFileChanged: reload()
  }

  FileView {
    id: hiddenFile
    path: root.tvConfigDir + "/hidden.json"
    watchChanges: true
    printErrors: false
    onLoaded: root.applyHidden(text())
    onFileChanged: reload()
  }

  FileView {
    id: uiPrefsFile
    path: root.tvConfigDir + "/ui_prefs.json"
    watchChanges: true
    printErrors: false
    onLoaded: root.applyUiPrefs(text())
    onFileChanged: reload()
  }

  // Watch guide.json EPG file
  FileView {
    id: guideFile
    path: root.tvConfigDir + "/guide.json"
    watchChanges: true
    printErrors: false
    onLoaded: {
      root.applyGuide(text())
      if (root.guideStripOpen) root.loadShows()
    }
    onFileChanged: reload()
  }

  FileView {
    id: recordingsFile
    path: root.tvConfigDir + "/recordings.json"
    watchChanges: true
    printErrors: false
    onLoaded: root.applyRecordings(text())
    onFileChanged: reload()
  }

  // Watch live scan status file
  FileView {
    id: scanStatusFile
    path: root.tvConfigDir + "/scan_status.json"
    watchChanges: true
    printErrors: false
    onLoaded: root.applyScanStatus(text())
    onFileChanged: reload()
  }

  FileView {
    id: guideStatusFile
    path: root.tvConfigDir + "/guide_status.json"
    watchChanges: true
    printErrors: false
    onLoaded: root.applyGuideStatus(text())
    onFileChanged: reload()
  }

  function applyGuideStatus(raw) {
    try {
      var s = JSON.parse(raw) || {}
      root.guideStatusRunning = !!s.running
      root.guideStatusTower = Number(s.tower) || 0
      root.guideStatusTowers = Number(s.towers) || 0
    } catch (e) {
      root.guideStatusRunning = false
    }
  }

  // Watch active DVR recordings
  FileView {
    id: recordingsActiveFile
    path: root.tvConfigDir + "/recordings_active.json"
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
        var nextMode = s.mode || ((s.station === "Recording") ? "recording" : "live")
        if (s.channel && s.channel !== root.activeChannelName) root.pauseKept = false
        if (nextMode === "timeshift" && root.playerMode !== "timeshift") root.pauseKept = false
        if (s.channel) root.activeChannelName = s.channel
        root.playerMode = nextMode
        if (s.last_live) root.lastLiveChannel = s.last_live
      } else if (s.running === false) {
        root.pauseKept = false
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
    path: root.tvConfigDir + "/player_state.json"
    watchChanges: true
    printErrors: false
    onLoaded: root.applyPlayerState(text())
    onFileChanged: reload()
  }

  FileView {
    id: rulesFile
    path: root.tvConfigDir + "/record_rules.json"
    watchChanges: true
    printErrors: false
    onLoaded: root.applyRules(text())
    onFileChanged: reload()
  }

  Process {
    id: showsProc
    command: []
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.applyShows(text)
    }
  }

  Process {
    id: ruleProc
    command: []
    onExited: function(code) {
      rulesFile.reload()
    }
  }

  FileView {
    id: scheduleFile
    path: root.tvConfigDir + "/schedule.json"
    watchChanges: true
    printErrors: false
    onLoaded: root.applySchedule(text())
    onFileChanged: reload()
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
    path: root.tvConfigDir + "/tune_status.json"
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
    id: keepProc
    command: []
    onExited: function(code) {
      if (code === 0) root.pauseKept = true
      recordingsFile.reload()
    }
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
      if (root.watchAfterStop) {
        var watch = root.watchAfterStop
        root.watchAfterStop = ""
        root.tuneNow(watch)
        root.close()
      }
    }
  }

  Process {
    id: guideRefreshProc
    command: []
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        root.guideRefreshStarted = false
        guideFile.reload()
      }
    }
    onExited: function(code) {
      root.guideRefreshStarted = false
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
      hiddenFile.reload()
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
        else if (t === "S") root.startScan()
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
                if (root.isScanning) return "Scanning for channels…"
                return root.listedChannelCount > 0
                  ? ((root.watchableChannels || []).length + " channels · " + root.favoriteVisibleCount + " favorites")
                  : "No channels yet"
              }
              color: root.isScanning ? Color.accent : Color.muted
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
              text: "Scanning for channels"
              color: Color.accent
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              font.bold: true
            }

            Text {
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              textFormat: Text.PlainText
              text: root.scanTotalFound + " found"
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
                  text: root.scanBand !== "" ? root.scanBand : "Broadcast"
                  color: root.bar.foreground
                  font.family: root.bar.fontFamily
                  font.pixelSize: Style.font.caption
                  font.bold: true
                }

                Text {
                  textFormat: Text.PlainText
                  text: Model.formatFreq(root.scanFreq)
                  color: Color.muted
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
                text: root.scanSignal === null ? "Listening…" : (root.scanSignal > -55 ? "Strong signal" : "Signal found")
                color: root.scanSignal !== null && root.scanSignal > -55 ? Color.accent : (root.scanSignal !== null ? root.bar.foreground : Color.muted)
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.caption
                font.bold: true
              }

              Text {
                anchors.right: parent.right
                textFormat: Text.PlainText
                text: root.scanSignal !== null ? (root.scanSignal.toFixed(1) + " dBm") : ""
                color: Color.muted
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
                color: Color.muted
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
              color: Style.normalFillFor(root.bar.foreground, Color.accent)

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
            text: "Click to retune this channel"
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

          Row {
            id: watchActions
            z: 2
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(6)

            Button {
              id: npKeepBtn
              visible: root.isLiveSession && !root.pauseKept
              text: "Save"
              tooltipText: "Save what you paused to Recordings"
              foreground: root.bar.foreground
              fontSize: Style.font.caption
              onClicked: root.keepPause()
            }

            Button {
              id: npCloseBtn
              text: "Close"
              tooltipText: "Close TV and drop the pause"
              foreground: root.bar.foreground
              fontSize: Style.font.caption
              onClicked: root.stopPlayer()
            }
          }

          Row {
            id: watchLine
            anchors.left: parent.left
            anchors.right: watchActions.left
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
        id: bothBusyCard
        visible: root.pendingWatch !== ""
        width: parent.width
        implicitHeight: bothBusyCol.implicitHeight + Style.space(12)
        radius: Style.spacing.labelGap
        color: Style.selectedFillFor(root.bar.foreground, Color.urgent)
        borderSpec: Border.controlSpec("normal", root.bar.foreground, Color.urgent)

        Column {
          id: bothBusyCol
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.top: parent.top
          anchors.margins: Style.space(6)
          spacing: Style.space(6)

          Text {
            width: parent.width
            textFormat: Text.PlainText
            text: "Both tuners are recording. Stop one to watch " + root.getActiveDisplayNameFor(root.pendingWatch) + "?"
            color: root.bar.foreground
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.bodySmall
            font.bold: true
            wrapMode: Text.Wrap
          }

          Flow {
            width: parent.width
            spacing: Style.space(6)

            Repeater {
              model: root.activeRecordings
              delegate: Button {
                required property var modelData
                text: "Stop " + (modelData.program_title || root.recordingTitle(modelData))
                tooltipText: "Stop this recording and watch. What it recorded so far is kept"
                fontSize: Style.font.caption
                foreground: Color.urgent
                onClicked: root.stopToWatch(modelData)
              }
            }

            Button {
              text: "Keep recording"
              tooltipText: "Don't watch right now"
              fontSize: Style.font.caption
              foreground: root.bar.foreground
              onClicked: root.pendingWatch = ""
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
            text: root.guideStatusTowers > 0
              ? "Updating the Guide · tower " + root.guideStatusTower + " of " + root.guideStatusTowers
              : "Updating the Guide"
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
            onClicked: root.guideStripOpen = true
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
          placeholderText: "Search shows and teams"
          font.family: root.bar.fontFamily
          onTextChanged: root.guideSearchText = text
        }

        Row {
          visible: !root.guideSearchActive
          spacing: Style.space(4)

          Repeater {
            model: [
              { key: "day", label: "Day 6 AM–8 PM" },
              { key: "prime", label: "Prime 8–11 PM" },
              { key: "late", label: "Late 11 PM–2 AM" },
              { key: "overnight", label: "Overnight 2–6 AM" }
            ]
            delegate: Button {
              required property var modelData
              text: modelData.label
              selected: root.showBucket === modelData.key
              fontSize: Style.font.caption
              foreground: root.bar.foreground
              onClicked: root.showBucket = modelData.key
            }
          }
        }

        Text {
          visible: !root.guideSearchActive && root.guideShowRows.length === 0
          width: parent.width
          textFormat: Text.PlainText
          text: showsProc.running ? "Reading the Guide…"
                : "Nothing listed for this time yet. Each Guide update adds what the stations send."
          color: Color.muted
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.Wrap
        }

        Flickable {
          id: stripFlick
          width: parent.width
          height: Math.min(stripShowsCol.implicitHeight, root.guideListRoom())
          contentWidth: width
          contentHeight: stripShowsCol.implicitHeight
          clip: true
          visible: !root.guideSearchActive && root.guideShowRows.length > 0
          flickableDirection: Flickable.VerticalFlick
          boundsBehavior: Flickable.StopAtBounds

          Column {
            id: stripShowsCol
            width: stripFlick.width
            spacing: Style.space(6)

            Repeater {
              model: root.guideShowRows
              delegate: Item {
                id: showRow
                required property var modelData
                readonly property bool ruled: !!root.ruleIds[modelData.id]
                readonly property var airing: Model.showAiring(modelData)
                readonly property string oneState: root.hitRecordState(airing)
                width: stripShowsCol.width
                implicitHeight: Math.max(showText.implicitHeight, showActions.implicitHeight)

                Column {
                  id: showText
                  anchors.left: parent.left
                  anchors.right: showActions.left
                  anchors.rightMargin: Style.space(6)
                  anchors.verticalCenter: parent.verticalCenter
                  spacing: Style.space(1)

                  Text {
                    width: parent.width
                    textFormat: Text.PlainText
                    text: showRow.modelData.title || ""
                    color: showRow.ruled ? Color.accent
                           : (showRow.modelData.pattern ? root.bar.foreground : Color.muted)
                    font.family: root.bar.fontFamily
                    font.pixelSize: Style.font.bodySmall
                    font.bold: showRow.ruled
                    elide: Text.ElideRight
                  }

                  Text {
                    width: parent.width
                    textFormat: Text.PlainText
                    text: Model.showSubLine(showRow.modelData, root.stationFor(showRow.modelData.channel))
                    color: Color.muted
                    font.family: root.bar.fontFamily
                    font.pixelSize: Style.font.caption
                    elide: Text.ElideRight
                  }
                }

                Row {
                  id: showActions
                  anchors.right: parent.right
                  anchors.verticalCenter: parent.verticalCenter
                  spacing: Style.space(4)

                  Button {
                    visible: !!(showRow.airing && showRow.airing.on_now)
                    text: "Watch"
                    tooltipText: "Watch this channel now"
                    fontSize: Style.font.caption
                    foreground: root.bar.foreground
                    onClicked: root.selectChannel(showRow.modelData.tune_name)
                  }

                  Button {
                    visible: !!showRow.airing && !showRow.ruled
                    text: showRow.oneState === "recording" ? "Recording"
                          : (showRow.oneState === "scheduled" ? "Scheduled" : "Record")
                    tooltipText: showRow.oneState === "recording" ? "Stop this recording"
                          : (showRow.oneState === "scheduled" ? "Don't record this"
                          : (showRow.airing && showRow.airing.on_now ? "Record the rest of this one"
                          : "Record the next one, " + ((showRow.modelData.next && showRow.modelData.next.day) || "") + " " + ((showRow.airing && showRow.airing.start) || "")))
                    selected: showRow.oneState !== ""
                    enabled: showRow.oneState !== "" || !(showRow.airing && showRow.airing.on_now) || root.freeTunerForRecording()
                    fontSize: Style.font.caption
                    foreground: root.bar.foreground
                    onClicked: root.toggleHitRecord(showRow.airing)
                  }

                  Button {
                    visible: showRow.ruled
                    text: root.showLimitText(showRow.modelData)
                    tooltipText: "How many episodes to keep. Older ones are deleted"
                    fontSize: Style.font.caption
                    foreground: root.bar.foreground
                    onClicked: root.cycleShowLimit(showRow.modelData)
                  }

                  Button {
                    text: showRow.ruled ? "Recording all" : "Record all"
                    tooltipText: showRow.ruled ? "Stop recording this show" : "Record every new airing on " + (showRow.modelData.channel || "this channel") + ", any time of day"
                    selected: showRow.ruled
                    enabled: showRow.ruled || !!showRow.modelData.tune_name
                    fontSize: Style.font.caption
                    foreground: root.bar.foreground
                    onClicked: root.toggleRecordAll(showRow.modelData)
                  }
                }
              }
            }
          }
        }

        Flickable {
          id: stripSearchFlick
          width: parent.width
          height: Math.min(stripSearchCol.implicitHeight, root.guideListRoom())
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
                id: hitRow
                required property var modelData
                required property int index
                readonly property string recState: root.hitRecordState(modelData)
                readonly property bool ruled: root.hitRuleId(modelData) !== ""
                width: stripSearchCol.width
                implicitHeight: Math.max(hitText.implicitHeight, hitActions.implicitHeight) + Style.space(8)

                Column {
                  id: hitText
                  anchors.left: parent.left
                  anchors.right: hitActions.left
                  anchors.rightMargin: Style.space(6)
                  anchors.verticalCenter: parent.verticalCenter
                  spacing: Style.space(1)

                  Text {
                    width: parent.width
                    textFormat: Text.PlainText
                    text: (hitRow.modelData.title || "")
                    color: hitRow.recState !== "" ? Color.accent : root.bar.foreground
                    font.family: root.bar.fontFamily
                    font.pixelSize: Style.font.bodySmall
                    font.bold: hitRow.recState !== ""
                    elide: Text.ElideRight
                  }

                  Text {
                    width: parent.width
                    textFormat: Text.PlainText
                    text: [
                      hitRow.modelData.channel_number || "",
                      hitRow.modelData.display_name || hitRow.modelData.station || "",
                      hitRow.modelData.on_now ? "on now" : (hitRow.modelData.start || ""),
                      hitRow.modelData.by_title ? "" : (hitRow.modelData.synopsis || "")
                    ].filter(function(p) { return p }).join(" · ")
                    color: Color.muted
                    font.family: root.bar.fontFamily
                    font.pixelSize: Style.font.caption
                    elide: Text.ElideRight
                  }
                }

                Row {
                  id: hitActions
                  anchors.right: parent.right
                  anchors.verticalCenter: parent.verticalCenter
                  spacing: Style.space(4)

                  Button {
                    visible: !!hitRow.modelData.on_now
                    text: "Watch"
                    tooltipText: "Watch this channel now"
                    fontSize: Style.font.caption
                    foreground: root.bar.foreground
                    onClicked: root.selectChannel(hitRow.modelData.tune_name || hitRow.modelData.channel_number)
                  }

                  Button {
                    visible: !hitRow.ruled || hitRow.recState !== ""
                    text: hitRow.recState === "recording" ? "Recording"
                          : (hitRow.recState === "scheduled" ? "Scheduled" : "Record")
                    tooltipText: hitRow.recState === "recording" ? "Stop this recording"
                          : (hitRow.recState === "scheduled" ? "Don't record this"
                          : (hitRow.modelData.on_now ? "Record the rest of this show" : "Record this one when it airs"))
                    selected: hitRow.recState !== ""
                    enabled: hitRow.recState !== "" || !hitRow.modelData.on_now || root.freeTunerForRecording()
                    fontSize: Style.font.caption
                    foreground: root.bar.foreground
                    onClicked: root.toggleHitRecord(hitRow.modelData)
                  }

                  Button {
                    text: hitRow.ruled ? "Recording all" : "Record all"
                    tooltipText: hitRow.ruled ? "Stop recording this show"
                          : "Record every new airing on " + (hitRow.modelData.channel_number || "this channel") + ", any time of day"
                    selected: hitRow.ruled
                    enabled: hitRow.ruled || !!hitRow.modelData.tune_name
                    fontSize: Style.font.caption
                    foreground: root.bar.foreground
                    onClicked: root.toggleHitRecordAll(hitRow.modelData)
                  }
                }
              }
            }
          }
        }

        Text {
          visible: root.guideSearchActive && root.guideSearchHits.length === 0
          width: parent.width
          textFormat: Text.PlainText
          text: "Nothing listed matches. Stations only list the next few hours, so search again closer to air time."
          color: Color.muted
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.Wrap
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
              text: (modelData.status === "missed" ? "Missed · " : "")
                    + (modelData.display_name || modelData.tune_name || "")
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

      Row {
        visible: root.showChannelBrowser
        width: parent.width
        spacing: Style.space(6)

        Row {
          id: filterTabRow
          spacing: Style.space(4)

          Button {
            text: "Favorites (" + root.favoriteVisibleCount + ")"
            tooltipText: "Channels you starred"
            selected: root.channelFilter === "favorites"
            fontSize: Style.font.caption
            foreground: root.bar.foreground
            onClicked: root.setChannelFilter("favorites")
          }

          Button {
            text: "All (" + (root.watchableChannels ? root.watchableChannels.length : 0) + ")"
            tooltipText: "Every channel you haven't hidden"
            selected: root.channelFilter === "all"
            fontSize: Style.font.caption
            foreground: root.bar.foreground
            onClicked: root.setChannelFilter("all")
          }

          Button {
            visible: root.hiddenData && root.hiddenData.length > 0
            text: "Hidden (" + root.hiddenData.length + ")"
            tooltipText: "Channels you hid"
            selected: root.channelFilter === "hidden"
            fontSize: Style.font.caption
            foreground: root.bar.foreground
            onClicked: root.setChannelFilter("hidden")
          }
        }

        Item {
          width: Math.max(0, parent.width - filterTabRow.width - rescanBtn.width - parent.spacing * 2)
          height: 1
        }

        Button {
          id: rescanBtn
          visible: root.channelsData.length > 0 && !root.isScanning
          text: "Rescan"
          tooltipText: "Look for channels again. Takes a free tuner for a few minutes"
          enabled: root.tunersFree > 0
          fontSize: Style.font.caption
          foreground: root.bar.foreground
          onClicked: root.startScan()
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
            text: "No channels yet"
            color: Color.muted
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.bodySmall
          }
          Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "Scan to find the channels your antenna picks up."
            color: Color.muted
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
            text: "No favorites yet"
            color: Color.muted
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.bodySmall
            font.bold: true
          }
          Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "Open All and click ☆ on a channel to add it here."
            color: Color.muted
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
                readonly property bool isCurrent: root.activeChannelName === modelData.channel_number || root.activeChannelName === modelData.name || root.activeChannelName === modelData.tune_name
                readonly property var program: root.getProgram(modelData)
                readonly property var onNow: Model.currentProgram(program, root.guideClockMin)
                readonly property var onNext: Model.nextProgram(program, root.guideClockMin)
                readonly property real progress: Model.airingProgress(chItem.onNow, root.guideClockMin)
                readonly property string stationName: Model.getDisplayTitle(modelData)
                readonly property string channelBadge: Model.getChannelBadge(modelData)
                readonly property bool isRecordingHere: root.isChannelRecording(modelData.tune_name || modelData.channel_number)
                readonly property bool isFav: root.isFavorite(modelData.name) || (modelData.tune_name && root.isFavorite(modelData.tune_name))

                width: channelListView.width
                height: Math.max(Style.space(36), chLine.implicitHeight + Style.space(12))
                foreground: root.bar.foreground
                accent: Color.accent
                hasCursor: root.cursorActive && root.cursorIndex === index
                current: isCurrent

                Rectangle {
                  visible: chItem.isRecordingHere || (root.liveOn && chItem.isCurrent)
                  anchors.left: parent.left
                  anchors.top: parent.top
                  anchors.bottom: parent.bottom
                  width: Style.space(3)
                  color: chItem.isRecordingHere ? Color.urgent : Color.accent
                }

                MouseArea {
                  anchors.fill: parent
                  hoverEnabled: true
                  cursorShape: Qt.PointingHandCursor
                  onEntered: {
                    root.cursorActive = true
                    root.cursorIndex = chItem.index
                  }
                  onClicked: root.useListedChannel(root.listedKey(chItem.modelData))
                  onWheel: function(wheel) { wheel.accepted = false }
                }

                Button {
                  id: hideBtn
                  visible: root.channelFilter === "all" || root.channelFilter === "hidden"
                  anchors.right: parent.right
                  anchors.rightMargin: Style.space(4)
                  anchors.verticalCenter: parent.verticalCenter
                  text: (root.channelFilter === "hidden" || root.channelIsHidden(chItem.modelData)) ? "Show" : "Hide"
                  tooltipText: (root.channelFilter === "hidden" || root.channelIsHidden(chItem.modelData)) ? "Put this station back" : "Set this station aside"
                  fontSize: Style.font.caption
                  foreground: root.bar.foreground
                  onClicked: {
                    if (root.channelFilter === "hidden" || root.channelIsHidden(chItem.modelData)) root.showListed(chItem.modelData)
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
                  foreground: chItem.isFav ? Color.accent : Color.muted
                  fontFamily: root.bar.fontFamily
                  onClicked: root.toggleFavorite(chItem.modelData.tune_name || chItem.modelData.name)
                }

                Column {
                  id: chLine
                  anchors.left: parent.left
                  anchors.right: favBtn.left
                  anchors.leftMargin: Style.space(10)
                  anchors.rightMargin: Style.space(8)
                  anchors.verticalCenter: parent.verticalCenter
                  spacing: Style.space(3)
                  readonly property real textX: chNum.width + Style.space(6)

                  Row {
                    width: parent.width
                    spacing: Style.space(6)

                    Text {
                      id: chNum
                      textFormat: Text.PlainText
                      text: chItem.channelBadge
                      color: chItem.isCurrent ? Color.accent : root.bar.foreground
                      font.family: root.bar.fontFamily
                      font.pixelSize: Style.font.bodySmall
                      font.bold: true
                      width: Math.max(implicitWidth, Style.space(40))
                    }

                    Text {
                      width: Math.max(0, chLine.width - chLine.textX)
                      textFormat: Text.PlainText
                      text: chItem.onNow && chItem.onNow.title ? chItem.onNow.title : chItem.stationName
                      color: chItem.isCurrent ? Color.accent : root.bar.foreground
                      font.family: root.bar.fontFamily
                      font.pixelSize: Style.font.bodySmall
                      font.bold: chItem.isCurrent
                      elide: Text.ElideRight
                    }
                  }

                  Rectangle {
                    visible: chItem.progress >= 0
                    x: chLine.textX
                    width: Math.max(0, chLine.width - chLine.textX)
                    height: Style.space(2)
                    radius: height / 2
                    color: Style.normalFillFor(root.bar.foreground, Color.accent)

                    Rectangle {
                      width: parent.width * Math.max(0, chItem.progress)
                      height: parent.height
                      radius: parent.radius
                      color: Color.accent
                    }
                  }

                  Text {
                    visible: !!chItem.onNow
                    x: chLine.textX
                    width: Math.max(0, chLine.width - chLine.textX)
                    textFormat: Text.PlainText
                    text: Model.channelSubLine(chItem.stationName, chItem.onNext)
                    color: Color.muted
                    font.family: root.bar.fontFamily
                    font.pixelSize: Style.font.caption
                    elide: Text.ElideRight
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
          color: Style.normalFillFor(root.bar.foreground, Color.accent)
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
            iconText: "\udb80\udc4d"
            text: "Back"
            tooltipText: "Back to channels"
            foreground: root.bar.foreground
            onClicked: root.toggleLibrary()
          }

          Button {
            id: libraryCapBtn
            anchors.right: libraryBackBtn.left
            anchors.rightMargin: Style.space(6)
            anchors.verticalCenter: parent.verticalCenter
            text: root.libraryCapButtonText()
            tooltipText: "Over the limit, the oldest recordings are deleted, series episodes first. Locked ones never are. Click to change"
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
                ? (root.recordingsData.length + (root.recordingsData.length === 1 ? " recording · " : " recordings · ")
                   + root.libraryBytesLabel + (root.libraryBudgetLabel && root.libraryBudgetLabel !== "Unlimited" ? " of " + root.libraryBudgetLabel : ""))
                : "Nothing recorded yet"
              color: Color.muted
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
            color: Color.muted
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
                    anchors.right: recKeepBtn.left
                    anchors.rightMargin: Style.space(8)
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: Style.space(2)

                    Text {
                      textFormat: Text.PlainText
                      text: recRow.modelData.title || recRow.modelData.name
                      color: recRow.modelData.playable === false ? Color.muted : root.bar.foreground
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
                        + (recRow.modelData.ads > 0 ? " · skips " + recRow.modelData.ads + (recRow.modelData.ads === 1 ? " ad break" : " ad breaks") : "")
                        + (recRow.modelData.playable === false ? " · nothing recorded" : "")
                      color: Color.muted
                      font.family: root.bar.fontFamily
                      font.pixelSize: Style.font.caption
                      elide: Text.ElideRight
                      width: parent.width
                    }
                  }

                  PanelActionButton {
                    id: recKeepBtn
                    anchors.right: recDeleteBtn.left
                    anchors.rightMargin: Style.space(2)
                    anchors.verticalCenter: parent.verticalCenter
                    iconText: recRow.modelData.keep ? "\uf023" : "\uf09c"
                    tooltipText: recRow.modelData.keep ? "Locked. The size limit won't delete it. Click to unlock" : "Lock it so the size limit never deletes it"
                    foreground: recRow.modelData.keep ? Color.accent : Color.muted
                    hoverColor: root.bar.foreground
                    fontFamily: root.bar.fontFamily
                    onClicked: root.setRecordingKept(recRow.modelData, !recRow.modelData.keep)
                  }

                  PanelActionButton {
                    id: recDeleteBtn
                    anchors.right: parent.right
                    anchors.rightMargin: Style.space(2)
                    anchors.verticalCenter: parent.verticalCenter
                    readonly property bool armed: root.deleteArmed === (recRow.modelData.path || recRow.modelData.name)
                    iconText: "󰅙"
                    tooltipText: armed ? "Click again to delete" : "Delete"
                    foreground: armed ? Color.urgent : root.bar.foreground
                    hoverColor: armed ? Color.urgent : root.bar.foreground
                    fontFamily: root.bar.fontFamily
                    onClicked: {
                      var target = recRow.modelData.path || recRow.modelData.name
                      if (!armed) {
                        root.deleteArmed = target
                        deleteDisarm.restart()
                        return
                      }
                      root.deleteArmed = ""
                      root.deleteRecording(target)
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
}
