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
    if (root.popupOpen) {
      if (!root.openIntoGuide) root.guideModalOpen = false
      root.openIntoGuide = false
      root.libraryModalOpen = false
      root.cursorActive = false
      root.reloadChannelData()
      if (root.guideModalOpen)
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
  property bool showTranslators: false
  property var favoritesData: []
  property var guideData: ({})
  property var activeRecordings: []
  readonly property bool isRecording: root.activeRecordings && root.activeRecordings.length > 0
  property bool guideModalOpen: false
  property bool openIntoGuide: false
  property bool libraryModalOpen: false
  property var recordingsData: []
  property string libraryBytesLabel: ""
  property string libraryBudgetLabel: ""
  property var libraryMaxGb: "auto"
  property int recCursorIndex: 0
  readonly property bool showChannelBrowser: root.activeChannelName === ""
  property int guideSlotOffset: 0
  property int guideClockMin: -1
  readonly property var guideAllSlots: Model.guideAllSlots(root.guideClockMin)
  readonly property int guideVisibleSlots: {
    var w = popup.contentWidth || popup.availableCardWidth || Style.space(900)
    return Model.visibleSlotCount(w, Style.space(128))
  }
  readonly property int guideSlotMax: Model.maxSlotOffset(root.guideVisibleSlots, root.guideClockMin)
  readonly property var guideVisibleSlotLabels: Model.slotWindow(root.guideSlotOffset, root.guideVisibleSlots, root.guideClockMin)
  readonly property int guideStationWidth: Style.space(112)
  readonly property int guideRecWidth: Style.space(40)
  readonly property int guideSlotGap: Style.space(6)
  readonly property int guideSlotPixelWidth: {
    var n = Math.max(1, root.guideVisibleSlots)
    var usable = Math.max(n, (popup.contentWidth || Style.space(900)) - root.guideStationWidth - root.guideRecWidth - Style.space(24))
    return Math.max(Style.space(96), Math.floor(usable / n) - root.guideSlotGap)
  }
  onGuideVisibleSlotsChanged: {
    root.guideSlotOffset = Math.max(0, Math.min(root.guideSlotMax, root.guideSlotOffset))
  }
  property string channelFilter: "all" // "all" | "favorites"
  property string playerMode: "live"
  property string lastLiveChannel: ""
  readonly property bool isLibraryPlayback: root.playerMode === "recording"
  readonly property bool isLiveSession: root.playerMode === "live" || root.playerMode === "timeshift"
  readonly property bool isPlayback: root.isLibraryPlayback || root.playerMode === "timeshift"
  property bool cursorActive: false
  property int cursorIndex: 0
  property int guideCursorIndex: 0

  function shiftGuideSlot(delta) {
    root.guideSlotOffset = Math.max(0, Math.min(root.guideSlotMax, root.guideSlotOffset + delta))
  }

  function snapGuideToNow() {
    var slots = root.guideAllSlots || []
    var nowMin = (new Date()).getHours() * 60 + (new Date()).getMinutes()
    var idx = 0
    for (var i = 0; i < slots.length; i++) {
      if (Model.parseMinutes(slots[i]) <= nowMin) idx = i
    }
    root.guideSlotOffset = Math.max(0, Math.min(root.guideSlotMax, idx))
  }

  function toggleGuide() {
    if (root.guideModalOpen) {
      root.guideModalOpen = false
      root.cursorActive = false
      return
    }
    root.libraryModalOpen = false
    root.guideCursorIndex = 0
    root.cursorActive = false
    root.guideClockMin = Model.minutesNow()
    root.guideModalOpen = true
    root.snapGuideToNow()
  }

  function toggleLibrary() {
    if (root.libraryModalOpen) {
      root.libraryModalOpen = false
      root.cursorActive = false
      return
    }
    root.guideModalOpen = false
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
    if (root.guideModalOpen) return root.guideList ? root.guideList.length : 0
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
    if (root.guideModalOpen) {
      root.guideCursorIndex = Math.max(0, Math.min(n - 1, root.guideCursorIndex + delta))
    } else if (root.libraryModalOpen) {
      root.recCursorIndex = Math.max(0, Math.min(n - 1, root.recCursorIndex + delta))
    } else {
      root.cursorIndex = Math.max(0, Math.min(n - 1, root.cursorIndex + delta))
    }
  }

  function activateCursor() {
    if (!root.cursorActive) return
    if (root.guideModalOpen) {
      var g = root.guideList[root.guideCursorIndex]
      if (g) root.selectChannel(Model.guidePlayIdent(g))
      return
    }
    if (root.libraryModalOpen) {
      var rec = root.recordingsData[root.recCursorIndex]
      if (rec) root.playRecording(rec.path || rec.name, rec.playable)
      return
    }
    var ch = root.displayChannels[root.cursorIndex]
    if (ch) root.selectChannel(ch.tune_name || ch.name)
  }

  function cursorChannelIdent() {
    if (root.guideModalOpen) {
      var g = root.guideList[root.guideCursorIndex]
      return g ? Model.guidePlayIdent(g) : ""
    }
    if (root.cursorActive && root.displayChannels && root.displayChannels.length > 0) {
      var ch = root.displayChannels[root.cursorIndex]
      if (ch) return ch.tune_name || ch.name || ""
    }
    return root.activeChannelName || ""
  }

  function isChannelRecording(chIdent) {
    if (!root.activeRecordings || root.activeRecordings.length === 0) return false
    var q = (chIdent || "").toString().toLowerCase()
    for (var i = 0; i < root.activeRecordings.length; i++) {
      var r = root.activeRecordings[i]
      if ((r.channel_number || "").toLowerCase() === q ||
          (r.station || "").toLowerCase() === q ||
          (r.tune_name || "").toLowerCase() === q) {
        return true
      }
    }
    return false
  }

  function activeRecordingIdent() {
    if (!root.activeRecordings || root.activeRecordings.length === 0) return ""
    var r = root.activeRecordings[0]
    return r.tune_name || r.station || r.channel_number || ""
  }

  function toggleRecord(chIdent) {
    if (!chIdent) return
    dvrProc.running = false
    if (root.isChannelRecording(chIdent)) {
      dvrProc.command = [root.binPath, "record", "stop", chIdent]
    } else {
      dvrProc.command = [root.binPath, "record", "start", chIdent]
    }
    dvrProc.running = true
  }

  readonly property var guideList: {
    var list = []
    var chs = root.displayChannels || []
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

  readonly property int translatorCount: {
    var n = 0
    var chs = root.channelsData || []
    for (var i = 0; i < chs.length; i++) {
      if (Model.isTranslator(chs[i])) n++
    }
    return n
  }

  readonly property int listedChannelCount: {
    var n = 0
    var chs = root.channelsData || []
    for (var i = 0; i < chs.length; i++) {
      if (!root.showTranslators && Model.isTranslator(chs[i])) continue
      n++
    }
    return n
  }

  readonly property var displayChannels: {
    var list = root.channelsData || []
    if (root.channelFilter === "favorites") {
      list = list.filter(function(ch) {
        if (!root.favoritesData) return false
        return root.favoritesData.indexOf(ch.name) !== -1 || (ch.tune_name && root.favoritesData.indexOf(ch.tune_name) !== -1)
      })
    }
    if (!root.showTranslators) {
      list = list.filter(function(ch) { return !Model.isTranslator(ch) })
    }
    return list
  }

  onDisplayChannelsChanged: {
    var n = root.displayChannels ? root.displayChannels.length : 0
    if (root.cursorIndex >= n) root.cursorIndex = Math.max(0, n - 1)
  }

  readonly property string binPath: "omarchy-tv"

  function close() { root.popupOpen = false }
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

  function pausePlayer() {
    navProc.running = false
    navProc.command = [root.binPath, "pause"]
    navProc.running = true
    root.close()
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
      if (p.show_translators === true) root.showTranslators = true
      if (p.show_translators === false) root.showTranslators = false
      if (p.channel_filter === "favorites" || p.channel_filter === "all") {
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

  function setShowTranslators(on) {
    root.showTranslators = on
    prefsProc.command = [root.binPath, "pref", "translators", on ? "on" : "off"]
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
      if (!root.filterInitialized) {
        root.setChannelFilter((root.favoritesData && root.favoritesData.length > 0) ? "favorites" : "all")
      }
    } catch (e) {
      root.favoritesData = []
    }
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
    var num = (r.channel_number || "").toString()
    var st = (r.station || r.name || "").toString()
    if (num && st) return num + " " + st
    return num || st || "Recording"
  }

  readonly property string watchModeLabel: {
    if (tuneProc.running && root.playerMode !== "recording")
      return "TUNING"
    return root.playerMode === "timeshift" ? "TIMESHIFT" : (root.isPlayback ? "PLAYBACK" : "LIVE")
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
      text: root.isScanning ? "󰛳" : (root.isRecording ? "󰑈" : "󰢹")
      color: root.isRecording ? Color.urgent : (root.isScanning || root.activeChannelName !== "" ? Color.accent : root.bar.barForeground)
      font.family: root.bar.fontFamily
      font.pixelSize: Style.font.body
      anchors.verticalCenter: parent.verticalCenter
    }

    Text {
      id: label
      visible: (root.isScanning || root.isRecording || root.activeChannelName !== "") && !root.bar.vertical
      textFormat: Text.PlainText
      text: root.isScanning ? (root.scanPercent + "% Scanning") : (root.isRecording ? ("REC " + (root.activeRecordings[0] ? (root.activeRecordings[0].station || root.activeRecordings[0].channel_number) : "")) : root.activeChannelName)
      color: root.isRecording ? Color.urgent : (root.isScanning ? Color.accent : root.bar.barForeground)
      font.family: root.bar.fontFamily
      font.pixelSize: Style.font.bodySmall
      font.bold: true
      anchors.verticalCenter: parent.verticalCenter
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
      root.openIntoGuide = true
      root.guideClockMin = Model.minutesNow()
      root.popupOpen = true
      root.guideModalOpen = true
      root.snapGuideToNow()
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
    onExited: playerStateFile.reload()
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
    id: recIndexProc
    command: [root.binPath, "record", "list"]
    onExited: recordingsFile.reload()
  }

  Component.onCompleted: {
    Qt.callLater(function() {
      channelsFile.reload()
      guideFile.reload()
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
    contentWidth: {
      var avail = popup.availableCardWidth
      if (root.guideModalOpen) {
        if (!(avail > 0)) return popup.fittedContentWidth(Style.space(1600))
        return popup.fittedContentWidth(avail)
      }
      if (!(avail > 0)) return popup.fittedContentWidth(Style.space(520))
      var third = Math.round(avail * 0.34)
      return popup.fittedContentWidth(Math.max(Style.space(480), Math.min(Style.space(780), third)))
    }
    contentHeight: {
      if (root.guideModalOpen) {
        var availH = popup.availableCardHeight
        if (!(availH > 0)) return popup.fittedContentHeight(Style.space(720))
        return popup.cappedContentHeight(Math.round(availH * 0.92))
      }
      return popup.fittedContentHeight(mainCol.implicitHeight, Style.space(560))
    }
    margin: Style.gapsOut * 2

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: {
        if (root.guideModalOpen) root.guideModalOpen = false
        else if (root.libraryModalOpen) root.libraryModalOpen = false
        else root.close()
      }
      onMoveRequested: function(dx, dy) {
        if (dx !== 0 && root.guideModalOpen) {
          root.shiftGuideSlot(dx)
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
        else if (t === "x" || t === "X") {
          if (root.activeChannelName !== "") root.stopPlayer()
        }
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
        else if (t === "d" || t === "D") root.setShowTranslators(!root.showTranslators)
      }

      Column {
        id: mainCol
        anchors.left: parent.left
        anchors.right: parent.right
        spacing: Style.space(12)

      // Remote & Drawer View
      Column {
        id: remoteView
        visible: !root.guideModalOpen && !root.libraryModalOpen
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
              selected: root.guideModalOpen
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
              text: root.isScanning
                ? "Scanning Broadcast Frequencies..."
                : (root.listedChannelCount > 0
                    ? (root.listedChannelCount + " channels · " + (root.favoritesData ? root.favoritesData.length : 0) + " favorites")
                    : "No channels scanned")
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

      // Now Playing Info Card
      BorderSurface {
        id: nowPlayingCard
        visible: root.activeChannelName !== ""
        readonly property var activeProg: root.getActiveProgram()
        width: parent.width
        implicitHeight: nowPlayingCol.implicitHeight + Style.space(20)
        radius: Style.spacing.labelGap
        color: Style.selectedFillFor(root.bar.foreground, Color.accent)
        borderSpec: Border.controlSpec("normal", root.bar.foreground, Color.accent)

        Column {
          id: nowPlayingCol
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.top: parent.top
          anchors.margins: Style.space(10)
          spacing: Style.space(8)

          Item {
            width: parent.width
            height: Math.max(npLiveReturn.implicitHeight, npModeLabel.implicitHeight)

            Button {
              id: npLiveReturn
              visible: root.isPlayback
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
              text: "Live"
              tooltipText: "Return to live TV"
              foreground: root.bar.foreground
              fontSize: Style.font.caption
              onClicked: root.returnToLive()
            }

            Text {
              id: npModeLabel
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              textFormat: Text.PlainText
              text: root.watchModeLabel
              color: Color.accent
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              font.bold: true
            }
          }

          Text {
            textFormat: Text.PlainText
            text: root.getActiveDisplayName()
            color: root.bar.foreground
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.subtitle
            font.bold: true
            elide: Text.ElideRight
            width: parent.width
          }

          Text {
            visible: nowPlayingCard.activeProg !== null && nowPlayingCard.activeProg.title !== undefined
            textFormat: Text.PlainText
            text: nowPlayingCard.activeProg ? ("󰥔 " + nowPlayingCard.activeProg.title + (nowPlayingCard.activeProg.start_time ? (" (" + nowPlayingCard.activeProg.start_time + " - " + nowPlayingCard.activeProg.end_time + ")") : "")) : ""
            color: Color.accent
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.bodySmall
            font.bold: true
            elide: Text.ElideRight
            width: parent.width
          }

          Text {
            visible: nowPlayingCard.activeProg !== null && nowPlayingCard.activeProg.synopsis !== undefined
            textFormat: Text.PlainText
            text: nowPlayingCard.activeProg ? nowPlayingCard.activeProg.synopsis : ""
            color: Qt.darker(root.bar.foreground, 1.4)
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
            width: parent.width
            maximumLineCount: 2
            elide: Text.ElideRight
          }

          Item {
            width: parent.width
            height: Math.max(npLiveRow.implicitHeight, npSeekRow.implicitHeight, npCloseBtn.implicitHeight)

            Row {
              id: npLiveRow
              visible: root.isLiveSession
              anchors.horizontalCenter: parent.horizontalCenter
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(6)

              Button {
                iconText: "󰒮"
                tooltipText: "Seek back 15 seconds"
                foreground: root.bar.foreground
                horizontalPadding: Style.spacing.controlPaddingX
                verticalPadding: Style.spacing.controlPaddingY
                onClicked: root.seekPlayer(-15)
              }

              Button {
                id: npPauseBtn
                iconText: "󰏤"
                text: "Pause"
                tooltipText: "Pause live TV"
                foreground: root.bar.foreground
                onClicked: root.pausePlayer()
              }

              Button {
                iconText: "󰒭"
                tooltipText: "Seek forward 15 seconds"
                foreground: root.bar.foreground
                horizontalPadding: Style.spacing.controlPaddingX
                verticalPadding: Style.spacing.controlPaddingY
                onClicked: root.seekPlayer(15)
              }

              Button {
                visible: !root.isChannelRecording(root.activeChannelName)
                iconText: "󰑈"
                text: "Record"
                tooltipText: "Record this channel"
                foreground: root.bar.foreground
                onClicked: root.toggleRecord(root.activeChannelName)
              }
            }

            Row {
              id: npSeekRow
              visible: root.isLibraryPlayback
              anchors.horizontalCenter: parent.horizontalCenter
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(6)

              Button {
                iconText: "󰒮"
                tooltipText: "Seek back 15 seconds"
                foreground: root.bar.foreground
                horizontalPadding: Style.spacing.controlPaddingX
                verticalPadding: Style.spacing.controlPaddingY
                onClicked: root.seekPlayer(-15)
              }

              Button {
                iconText: "󰏤"
                text: "Pause"
                tooltipText: "Pause or resume"
                foreground: root.bar.foreground
                onClicked: root.pausePlayer()
              }

              Button {
                iconText: "󰒭"
                tooltipText: "Seek forward 15 seconds"
                foreground: root.bar.foreground
                horizontalPadding: Style.spacing.controlPaddingX
                verticalPadding: Style.spacing.controlPaddingY
                onClicked: root.seekPlayer(15)
              }
            }

            Button {
              id: npCloseBtn
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              iconText: "󰅖"
              tooltipText: "Close TV"
              foreground: root.bar.foreground
              horizontalPadding: Style.spacing.controlPaddingX
              verticalPadding: Style.spacing.controlPaddingY
              onClicked: root.stopPlayer()
            }
          }
        }
      }

      Repeater {
        model: root.activeRecordings

        BorderSurface {
          required property var modelData
          required property int index
          width: parent.width
          implicitHeight: recCardCol.implicitHeight + Style.space(20)
          radius: Style.spacing.labelGap
          color: Style.selectedFillFor(root.bar.foreground, Color.urgent)
          borderSpec: Border.controlSpec("normal", root.bar.foreground, Color.urgent)

          Column {
            id: recCardCol
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: Style.space(10)
            spacing: Style.space(8)

            Item {
              width: parent.width
              height: recModeLabel.implicitHeight

              Text {
                id: recModeLabel
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                textFormat: Text.PlainText
                text: "REC"
                color: Color.urgent
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.caption
                font.bold: true
              }
            }

            Text {
              textFormat: Text.PlainText
              text: root.recordingTitle(modelData)
              color: root.bar.foreground
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.subtitle
              font.bold: true
              elide: Text.ElideRight
              width: parent.width
            }

            Text {
              visible: !!(modelData && modelData.program_title)
              textFormat: Text.PlainText
              text: modelData && modelData.program_title ? ("󰑊 " + modelData.program_title) : ""
              color: Color.urgent
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.bodySmall
              font.bold: true
              elide: Text.ElideRight
              width: parent.width
            }

            Item {
              width: parent.width
              height: recStopBtn.implicitHeight

              Button {
                id: recStopBtn
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.verticalCenter: parent.verticalCenter
                iconText: "󰓛"
                text: "Stop " + ((modelData && (modelData.channel_number || modelData.station)) || "REC")
                tooltipText: "Stop this recording"
                foreground: Color.urgent
                onClicked: root.toggleRecord(root.recordingIdent(modelData))
              }
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
            text: "All (" + root.listedChannelCount + ")"
            tooltipText: "All channels"
            selected: root.channelFilter === "all"
            fontSize: Style.font.caption
            foreground: root.bar.foreground
            onClicked: root.setChannelFilter("all")
          }

          Button {
            text: "Favs (" + (root.favoritesData ? root.favoritesData.length : 0) + ")"
            tooltipText: "Favorite channels"
            selected: root.channelFilter === "favorites"
            fontSize: Style.font.caption
            foreground: root.bar.foreground
            onClicked: root.setChannelFilter("favorites")
          }

          Button {
            visible: root.translatorCount > 0
            text: "Dupes (" + root.translatorCount + ")"
            tooltipText: "Show translator duplicates"
            active: root.showTranslators
            fontSize: Style.font.caption
            foreground: root.bar.foreground
            onClicked: root.setShowTranslators(!root.showTranslators)
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

      // Channel List Scroll Area
      Item {
        id: channelScrollContainer
        visible: root.showChannelBrowser && root.displayChannels.length > 0
        width: parent.width
        height: Math.min(Math.max(Style.space(260), Math.round((popup.availableCardHeight || Style.space(520)) * 0.50)), channelListView.implicitHeight)
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
                readonly property string channelBadge: Model.getChannelBadge(modelData)
                readonly property string netColor: Model.networkColor(modelData.network, Color.accent)
                readonly property bool isFav: root.isFavorite(modelData.name) || (modelData.tune_name && root.isFavorite(modelData.tune_name))

                width: channelListView.width
                height: Style.space(48)
                foreground: root.bar.foreground
                accent: Color.accent
                hasCursor: !root.guideModalOpen && root.cursorActive && root.cursorIndex === index
                current: isCurrent

                MouseArea {
                  anchors.fill: parent
                  hoverEnabled: true
                  cursorShape: Qt.PointingHandCursor
                  onEntered: {
                    root.cursorActive = true
                    root.cursorIndex = chItem.index
                  }
                  onClicked: root.selectChannel(chItem.modelData.tune_name || chItem.modelData.name)
                  onWheel: function(wheel) { wheel.accepted = false }
                }

                Row {
                  anchors.left: parent.left
                  anchors.right: parent.right
                  anchors.verticalCenter: parent.verticalCenter
                  anchors.leftMargin: Style.space(8)
                  anchors.rightMargin: Style.space(8)
                  spacing: Style.space(8)

                  BorderSurface {
                    width: Style.space(46)
                    height: Style.space(26)
                    radius: Style.spacing.labelGap
                    color: chItem.isCurrent ? Style.selectedFillFor(root.bar.foreground, Color.accent) : Style.normalFillFor(root.bar.foreground, Color.accent)
                    anchors.verticalCenter: parent.verticalCenter

                    Text {
                      anchors.centerIn: parent
                      textFormat: Text.PlainText
                      text: chItem.channelBadge
                      color: chItem.isCurrent ? Color.accent : root.bar.foreground
                      font.family: root.bar.fontFamily
                      font.pixelSize: Style.font.caption
                      font.bold: true
                    }
                  }

                  Column {
                    width: parent.width - Style.space(46) - Style.space(16)
                    spacing: Style.space(2)
                    anchors.verticalCenter: parent.verticalCenter

                    Row {
                      width: parent.width
                      spacing: Style.space(4)

                      Text {
                        id: chTitle
                        textFormat: Text.PlainText
                        text: Model.getDisplayTitle(chItem.modelData)
                        color: root.bar.foreground
                        font.family: root.bar.fontFamily
                        font.pixelSize: Style.font.bodySmall
                        font.bold: chItem.isCurrent
                        elide: Text.ElideRight
                        width: Math.min(
                          implicitWidth,
                          Math.max(
                            Style.space(48),
                            parent.width
                              - (netBadge.visible ? netBadge.width + Style.space(4) : 0)
                              - favBtn.width
                              - Style.space(4)
                          )
                        )
                      }

                      BorderSurface {
                        id: netBadge
                        visible: chItem.modelData.network !== undefined && chItem.modelData.network !== "" && chItem.modelData.network !== "OTA"
                        height: Style.space(16)
                        width: netBadgeText.implicitWidth + Style.space(8)
                        radius: 3
                        color: "transparent"
                        borderSpec: Border.controlSpec("normal", chItem.netColor, chItem.netColor)
                        anchors.verticalCenter: parent.verticalCenter

                        Text {
                          id: netBadgeText
                          anchors.centerIn: parent
                          textFormat: Text.PlainText
                          text: Model.networkShort(chItem.modelData.network)
                          color: chItem.netColor
                          font.family: root.bar.fontFamily
                          font.pixelSize: Style.font.caption
                          font.bold: true
                        }
                      }

                      PanelActionButton {
                        id: favBtn
                        anchors.verticalCenter: parent.verticalCenter
                        size: Style.space(20)
                        fontSize: Style.font.bodySmall
                        iconText: chItem.isFav ? "★" : "☆"
                        tooltipText: chItem.isFav ? "Remove favorite" : "Add favorite"
                        foreground: chItem.isFav ? Color.accent : Qt.darker(root.bar.foreground, 1.8)
                        fontFamily: root.bar.fontFamily
                        onClicked: root.toggleFavorite(chItem.modelData.tune_name || chItem.modelData.name)
                      }
                    }

                    Text {
                      textFormat: Text.PlainText
                      text: chItem.program ? ("󰥔 " + chItem.program.title) : (Model.formatFreq(chItem.modelData.frequency) + (chItem.modelData.band ? (" · " + chItem.modelData.band) : ""))
                      color: chItem.program ? (chItem.isCurrent ? Color.accent : Qt.darker(root.bar.foreground, 1.4)) : Qt.darker(root.bar.foreground, 1.7)
                      font.family: root.bar.fontFamily
                      font.pixelSize: Style.font.caption
                      elide: Text.ElideRight
                      width: parent.width
                    }
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
        id: guideGridView
        visible: root.guideModalOpen
        width: parent.width
        spacing: Style.space(10)

        Item {
          width: parent.width
          height: Math.max(Style.space(36), guideBackBtn.implicitHeight)

          Column {
            anchors.left: parent.left
            anchors.right: guideNowBtn.left
            anchors.rightMargin: Style.space(8)
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(2)

            Text {
              textFormat: Text.PlainText
              text: "Guide"
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
                var n = root.guideList ? root.guideList.length : 0
                var slots = root.guideVisibleSlotLabels || []
                var window = slots.length ? (slots[0] + " – " + slots[slots.length - 1]) : ""
                if (!n) return window || "No stations"
                return n + (n === 1 ? " station" : " stations") + (window ? (" · " + window) : "")
              }
              color: Qt.darker(root.bar.foreground, 1.5)
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              elide: Text.ElideRight
              width: parent.width
            }
          }

          Button {
            id: guideNowBtn
            anchors.right: guideBackBtn.left
            anchors.rightMargin: Style.space(6)
            anchors.verticalCenter: parent.verticalCenter
            text: "Now"
            tooltipText: "Jump to now"
            foreground: root.bar.foreground
            onClicked: root.snapGuideToNow()
          }

          Button {
            id: guideBackBtn
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            iconText: "󰅖"
            text: "Back"
            tooltipText: "Back"
            foreground: root.bar.foreground
            onClicked: root.toggleGuide()
          }
        }

        Item {
          width: parent.width
          height: Math.max(Style.space(32), guidePrevBtn.implicitHeight)

          Button {
            id: guidePrevBtn
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            iconText: "󰅁"
            tooltipText: "Earlier"
            foreground: root.bar.foreground
            enabled: root.guideSlotOffset > 0
            horizontalPadding: Style.space(8)
            verticalPadding: Style.space(4)
            onClicked: root.shiftGuideSlot(-1)
          }

          Button {
            id: guideNextBtn
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            iconText: "󰅂"
            tooltipText: "Later"
            foreground: root.bar.foreground
            enabled: root.guideSlotOffset < root.guideSlotMax
            horizontalPadding: Style.space(8)
            verticalPadding: Style.space(4)
            onClicked: root.shiftGuideSlot(1)
          }

          Item {
            anchors.left: guidePrevBtn.right
            anchors.right: guideNextBtn.left
            anchors.leftMargin: Style.space(6)
            anchors.rightMargin: Style.space(6)
            anchors.verticalCenter: parent.verticalCenter
            height: parent.height

            Item {
              id: guideHdrStation
              width: root.guideStationWidth
              height: parent.height
              anchors.left: parent.left
            }

            Item {
              id: guideHdrRec
              width: root.guideRecWidth
              height: parent.height
              anchors.right: parent.right
            }

            Row {
              anchors.left: guideHdrStation.right
              anchors.right: guideHdrRec.left
              anchors.leftMargin: root.guideSlotGap
              anchors.rightMargin: root.guideSlotGap
              anchors.verticalCenter: parent.verticalCenter
              spacing: root.guideSlotGap

              Repeater {
                model: root.guideVisibleSlotLabels

                Item {
                  required property var modelData
                  width: root.guideSlotPixelWidth
                  height: parent.height

                  Text {
                    anchors.fill: parent
                    textFormat: Text.PlainText
                    text: parent.modelData
                    color: Model.slotIsNow(parent.modelData) ? Color.accent : Qt.darker(root.bar.foreground, 1.4)
                    font.family: root.bar.fontFamily
                    font.pixelSize: Style.font.caption
                    font.bold: Model.slotIsNow(parent.modelData)
                    elide: Text.ElideRight
                    verticalAlignment: Text.AlignVCenter
                  }
                }
              }
            }
          }
        }

        Item {
          width: parent.width
          height: Math.max(Style.space(320), Math.round((popup.availableCardHeight || Style.space(720)) * 0.72))
          clip: true

          Flickable {
            id: guideFlickable
            anchors.fill: parent
            contentWidth: width
            contentHeight: guideCol.implicitHeight
            boundsBehavior: Flickable.StopAtBounds
            flickableDirection: Flickable.VerticalFlick
            clip: true

            Column {
              id: guideCol
              width: guideFlickable.width
              spacing: Style.space(4)

              Repeater {
                model: root.guideList

                CursorSurface {
                  id: gridRow
                  required property var modelData
                  required property int index
                  readonly property string playIdent: Model.guidePlayIdent(modelData)
                  readonly property bool isCurrent: root.activeChannelName === playIdent ||
                    root.activeChannelName === modelData.tune_name ||
                    root.activeChannelName === modelData.station ||
                    root.activeChannelName === modelData.channel_number
                  readonly property var blocks: Model.programBlocks(modelData, root.guideVisibleSlotLabels)

                  width: guideCol.width
                  height: Style.space(56)
                  foreground: root.bar.foreground
                  accent: Color.accent
                  hasCursor: root.guideModalOpen && root.cursorActive && root.guideCursorIndex === index
                  current: isCurrent

                  Item {
                    anchors.fill: parent
                    anchors.margins: Style.space(4)

                    BorderSurface {
                      id: stationBadge
                      width: root.guideStationWidth
                      height: parent.height
                      anchors.left: parent.left
                      radius: Style.spacing.labelGap
                      color: gridRow.isCurrent
                        ? Style.selectedFillFor(root.bar.foreground, Color.accent)
                        : Style.normalFillFor(root.bar.foreground, Color.accent)
                      borderSpec: Border.controlSpec(gridRow.isCurrent ? "focus" : "normal", root.bar.foreground, Color.accent)

                      Column {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.leftMargin: Style.space(8)
                        anchors.rightMargin: Style.space(8)
                        spacing: Style.space(2)

                        Text {
                          width: parent.width
                          textFormat: Text.PlainText
                          text: gridRow.modelData.channel_number || "OTA"
                          color: gridRow.isCurrent ? Color.accent : root.bar.foreground
                          font.family: root.bar.fontFamily
                          font.pixelSize: Style.font.bodySmall
                          font.bold: true
                          elide: Text.ElideRight
                        }

                        Text {
                          width: parent.width
                          textFormat: Text.PlainText
                          text: gridRow.modelData.callsign || gridRow.modelData.station || Model.networkShort(gridRow.modelData.network)
                          color: Qt.darker(root.bar.foreground, 1.4)
                          font.family: root.bar.fontFamily
                          font.pixelSize: Style.font.caption
                          elide: Text.ElideRight
                          visible: text !== ""
                        }
                      }

                      MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.selectChannel(gridRow.playIdent)
                      }
                    }

                    PanelActionButton {
                      id: recBtn
                      anchors.right: parent.right
                      anchors.verticalCenter: parent.verticalCenter
                      readonly property bool isRec: root.isChannelRecording(gridRow.playIdent)
                      iconText: isRec ? "󰓛" : "󰑈"
                      tooltipText: isRec ? "Stop recording" : "Record"
                      foreground: isRec ? Color.urgent : root.bar.foreground
                      hoverColor: Color.accent
                      fontFamily: root.bar.fontFamily
                      onClicked: root.toggleRecord(gridRow.playIdent)
                    }

                    Row {
                      anchors.left: stationBadge.right
                      anchors.right: recBtn.left
                      anchors.leftMargin: root.guideSlotGap
                      anchors.rightMargin: root.guideSlotGap
                      anchors.verticalCenter: parent.verticalCenter
                      height: parent.height
                      spacing: root.guideSlotGap

                      Repeater {
                        model: gridRow.blocks

                        BorderSurface {
                          required property var modelData
                          width: root.guideSlotPixelWidth * Math.max(1, Number(modelData.span) || 1) + root.guideSlotGap * (Math.max(1, Number(modelData.span) || 1) - 1)
                          height: parent.height
                          radius: Style.spacing.labelGap
                          color: {
                            if (modelData.empty) return "transparent"
                            if (modelData.now) return Style.selectedFillFor(root.bar.foreground, Color.accent)
                            return Style.normalFillFor(root.bar.foreground, Color.accent)
                          }
                          borderSpec: modelData.empty
                            ? Border.controlSpec("normal", root.bar.foreground, root.bar.foreground)
                            : Border.controlSpec(modelData.now ? "focus" : "normal", root.bar.foreground, Color.accent)
                          opacity: modelData.empty ? 0.35 : 1

                          Column {
                            anchors.fill: parent
                            anchors.leftMargin: Style.space(8)
                            anchors.rightMargin: Style.space(8)
                            anchors.topMargin: Style.space(4)
                            anchors.bottomMargin: Style.space(4)
                            spacing: Style.space(2)
                            visible: !modelData.empty

                            Text {
                              width: parent.width
                              textFormat: Text.PlainText
                              text: modelData.title || ""
                              color: modelData.now || gridRow.isCurrent ? Color.accent : root.bar.foreground
                              font.family: root.bar.fontFamily
                              font.pixelSize: Style.font.bodySmall
                              font.bold: true
                              elide: Text.ElideRight
                            }

                            Text {
                              width: parent.width
                              textFormat: Text.PlainText
                              text: (modelData.start && modelData.end) ? (modelData.start + " – " + modelData.end) : ""
                              color: Qt.darker(root.bar.foreground, 1.5)
                              font.family: root.bar.fontFamily
                              font.pixelSize: Style.font.caption
                              elide: Text.ElideRight
                              visible: text !== ""
                            }
                          }

                          MouseArea {
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.selectChannel(gridRow.playIdent)
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

      Column {
        id: libraryView
        visible: root.libraryModalOpen
        width: parent.width
        spacing: Style.space(10)

        Item {
          width: parent.width
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
          visible: root.recordingsData.length > 0
          width: parent.width
          height: Math.min(Math.max(Style.space(280), Math.round((popup.availableCardHeight || Style.space(520)) * 0.58)), Math.max(Style.space(120), recCol.implicitHeight))
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
