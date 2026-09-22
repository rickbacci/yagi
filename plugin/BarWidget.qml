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
      root.clearGuideDetail()
      return
    }
    if (root.popupOpen) {
      if (!root.openIntoGuide) {
        root.guideModalOpen = false
        root.clearGuideDetail()
      }
      root.openIntoGuide = false
      root.libraryModalOpen = false
      root.cursorActive = false
      root.channelListOpen = !root.flyoutStatusOn
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
  readonly property int guideSlotGap: Style.space(6)
  readonly property int guideSlotPixelWidth: {
    var n = Math.max(1, root.guideVisibleSlots)
    var usable = Math.max(n, (popup.contentWidth || Style.space(900)) - root.guideStationWidth - Style.space(24))
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
  property var guideDetail: null
  readonly property bool guideDetailOpen: !!(root.guideDetail && (root.guideDetail.playIdent || root.guideDetail.title))
  property bool guideRefreshing: false
  property string guideNote: ""
  property string guideSearchText: ""
  property string guideKind: "all"
  property real guideUpdatedAt: 0
  readonly property bool guideSearchActive: root.guideSearchText.replace(/\s+/g, " ").trim().length >= 2
  readonly property var guideSearchHits: {
    var hits = Model.searchGuide(root.guideData, root.guideSearchText, root.guideClockMin) || []
    if (!root.guideKind || root.guideKind === "all") return hits
    return hits.filter(function(hit) { return Model.channelKind(hit) === root.guideKind })
  }

  function shiftGuideSlot(delta) {
    root.guideSlotOffset = Math.max(0, Math.min(root.guideSlotMax, root.guideSlotOffset + delta))
  }

  function refreshGuide() {
    if (guideRefreshProc.running) return
    if (root.isRecording) {
      root.guideNote = "Already recording. Guide left alone."
      return
    }
    root.guideRefreshing = true
    root.guideNote = "Updating the guide…"
    guideRefreshProc.running = false
    guideRefreshProc.command = [root.binPath, "guide", "refresh"]
    guideRefreshProc.running = true
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
    root.clearGuideDetail()
    guideSearchField.text = ""
    root.guideSearchText = ""
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
    root.clearGuideDetail()
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
      if (root.guideDetailOpen) {
        root.watchGuideDetail()
        return
      }
      var g = root.guideList[root.guideCursorIndex]
      if (g) root.openGuideDetailFromRow(g)
      return
    }
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
      root.toggleRecord(chName)
      return
    }
    root.selectChannel(chName)
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
    return root.recordingSessionFor(chIdent, null) !== null
  }

  function recordingSessionFor(chIdent, row) {
    if (!root.activeRecordings || root.activeRecordings.length === 0) return null
    var idents = []
    function add(s) {
      var v = (s || "").toString().toLowerCase().trim()
      if (v && idents.indexOf(v) === -1) idents.push(v)
    }
    add(chIdent)
    if (row) {
      add(row.channel_number)
      add(row.station)
      add(row.callsign)
      add(row.tune_name)
      add(Model.guidePlayIdent(row))
    }
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

  function isGuideBlockRecording(row, block) {
    if (!row || !block || block.empty) return false
    var rec = root.recordingSessionFor(Model.guidePlayIdent(row), row)
    if (!rec) return false
    var recTitle = String(rec.program_title || "").replace(/\s+/g, " ").trim().toLowerCase()
    var blockTitle = String(block.title || "").replace(/\s+/g, " ").trim().toLowerCase()
    if (recTitle && recTitle !== "live broadcast" && recTitle !== "live") {
      if (recTitle === blockTitle) return true
    }
    return !!block.now
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

  function clearGuideDetail() {
    root.guideDetail = null
  }

  function openGuideDetail(row, block) {
    if (!row || !block || block.empty) return
    root.guideClockMin = Model.minutesNow()
    var list = root.guideList || []
    var i
    for (i = 0; i < list.length; i++) {
      if (Model.guidePlayIdent(list[i]) === Model.guidePlayIdent(row)) {
        root.guideCursorIndex = i
        break
      }
    }
    root.cursorActive = true
    root.guideDetail = {
      playIdent: Model.guidePlayIdent(row),
      channel_number: row.channel_number || "",
      callsign: row.callsign || row.station || "",
      tune_name: row.tune_name || "",
      station: row.station || "",
      title: block.title || "Live",
      start: block.start || "",
      end: block.end || "",
      synopsis: block.synopsis || "",
      usual: block.usual || "",
      also: block.also || "",
      duration_sec: Number(block.duration_sec) || 0,
      now: !!block.now,
      before: block.before || null,
      after: block.after || null
    }
  }

  function openGuideDetailFromRow(row) {
    if (!row) return
    var block = Model.preferredGuideBlock(row, root.guideVisibleSlotLabels)
    if (!block) {
      root.selectChannel(Model.guidePlayIdent(row))
      return
    }
    root.openGuideDetail(row, block)
  }

  function alreadyShowingChannel(detail) {
    if (!detail || !root.activeChannelName || root.isLibraryPlayback) return false
    function norm(s) {
      return String(s || "").replace(/\s+/g, " ").trim().toLowerCase()
    }
    var active = norm(root.activeChannelName)
    if (!active) return false
    var keys = []
    function add(s) {
      var v = norm(s)
      if (v && keys.indexOf(v) === -1) keys.push(v)
    }
    add(detail.playIdent)
    add(detail.channel_number)
    add(detail.callsign)
    add(detail.tune_name)
    add(detail.station)
    var chs = root.channelsData || []
    var i
    for (i = 0; i < chs.length; i++) {
      var ch = chs[i]
      var names = [ch.name, ch.tune_name, ch.channel_number, ch.callsign, ch.station]
      var hitsActive = false
      var n
      for (n = 0; n < names.length; n++) {
        if (norm(names[n]) === active) hitsActive = true
      }
      if (!hitsActive) continue
      for (n = 0; n < names.length; n++) add(names[n])
    }
    return keys.indexOf(active) !== -1
  }

  function watchGuideDetail() {
    if (!root.guideDetail || !root.guideDetail.playIdent) return
    if (root.alreadyShowingChannel(root.guideDetail)) {
      root.close()
      return
    }
    root.selectChannel(root.guideDetail.playIdent)
  }

  function guideDetailRecording() {
    var d = root.guideDetail
    if (!d) return null
    return root.recordingSessionFor(d.playIdent, d)
  }

  function playGuideDetailFromStart() {
    var rec = root.guideDetailRecording()
    if (!rec || !rec.file_path) return
    var n = Number(rec.file_size) || 0
    if (n < 262144) return
    root.playRecording(rec.file_path, true)
    root.close()
  }

  function recordGuideDetail() {
    if (!root.guideDetail || !root.guideDetail.playIdent) return
    var ident = root.guideDetail.playIdent
    if (root.isChannelRecording(ident)) {
      root.toggleRecord(ident)
      return
    }
    if (!Model.showIsOn(root.guideDetail, root.guideClockMin)) return
    var dur = Model.recordDurationArg(root.guideDetail, root.guideClockMin)
    var title = (root.guideDetail.title || "").toString()
    dvrProc.running = false
    var cmd = [root.binPath, "record", "start", ident]
    if (dur) cmd.push(dur)
    if (title) {
      cmd.push("--title")
      cmd.push(title)
    }
    dvrProc.command = cmd
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
      if (root.guideKind && root.guideKind !== "all") {
        list = list.filter(function(item) { return Model.channelKind(item) === root.guideKind })
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
    if (root.guideKind && root.guideKind !== "all") {
      list = list.filter(function(item) { return Model.channelKind(item) === root.guideKind })
    }
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

  function close() {
    root.clearGuideDetail()
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
      root.guideUpdatedAt = Number(d.updated_at) || 0
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
      root.clearGuideDetail()
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
    id: guideClockTimer
    interval: 30000
    repeat: true
    running: root.guideModalOpen
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
        var first = String(text || "").split("\n")[0]
        if (first.indexOf("Tuner 1 is recording") !== -1)
          root.guideNote = "Already recording. Guide left alone."
        else
          root.guideNote = "Guide updated."
        root.guideRefreshing = false
        guideFile.reload()
      }
    }
    onExited: function(code) {
      root.guideRefreshing = false
      if (code !== 0)
        root.guideNote = "Guide update failed."
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
      blocked: guideSearchField.activeFocus
      onCloseRequested: {
        if (root.guideDetailOpen) root.clearGuideDetail()
        else if (root.guideModalOpen) root.guideModalOpen = false
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
        else if (t === "a" || t === "A") {
          root.setChannelFilter("all")
        }
        else if (t === "f" || t === "F") {
          root.setChannelFilter("favorites")
        }
        else if (t === "s" || t === "S") root.startScan()
        else if (t === "r" || t === "R") {
          if (root.guideDetailOpen) {
            root.recordGuideDetail()
            return
          }
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
        readonly property string showLine: (activeProg && activeProg.title) ? activeProg.title : ""
        width: parent.width
        implicitHeight: watchRow.implicitHeight + Style.space(12)
        radius: Style.spacing.labelGap
        color: Style.selectedFillFor(root.bar.foreground, Color.accent)
        borderSpec: Border.controlSpec("normal", root.bar.foreground, Color.accent)

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
              color: Color.accent
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
        height: {
          var cap = Math.max(Style.space(260), Math.round((popup.availableCardHeight || Style.space(520)) * 0.50))
          var content = channelListView.implicitHeight
          if (content > 0 && content < cap) return content
          return cap
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
                  onClicked: root.useListedChannel(chItem.modelData.tune_name || chItem.modelData.name)
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
            anchors.right: guideRefreshBtn.left
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
                if (root.guideNote) return root.guideNote
                var n = root.guideList ? root.guideList.length : 0
                var slots = root.guideVisibleSlotLabels || []
                var window = slots.length ? (slots[0] + " – " + slots[slots.length - 1]) : ""
                if (!n) return window || "No stations"
                var updated = Model.formatGuideUpdated(root.guideUpdatedAt)
                return n + (n === 1 ? " station" : " stations") + (window ? (" · " + window) : "") + (updated ? (" · " + updated) : "")
              }
              color: Qt.darker(root.bar.foreground, 1.5)
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              elide: Text.ElideRight
              width: parent.width
            }
          }

          Button {
            id: guideRefreshBtn
            anchors.right: guideNowBtn.left
            anchors.rightMargin: Style.space(6)
            anchors.verticalCenter: parent.verticalCenter
            text: root.guideRefreshing ? "Updating" : "Refresh"
            tooltipText: root.isRecording ? "Already recording" : "Update the guide"
            enabled: !root.guideRefreshing
            foreground: root.bar.foreground
            onClicked: root.refreshGuide()
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

        TextField {
          id: guideSearchField
          width: parent.width
          placeholderText: "Search shows"
          foreground: root.bar.foreground
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.body
          onTextChanged: root.guideSearchText = text
          Keys.onEscapePressed: function(event) {
            if (text !== "") {
              text = ""
            } else {
              focus = false
            }
            event.accepted = true
          }
        }

        Flickable {
          width: parent.width
          height: guideKindRow.implicitHeight
          contentWidth: guideKindRow.implicitWidth
          flickableDirection: Flickable.HorizontalFlick
          clip: true

          Row {
            id: guideKindRow
            spacing: Style.space(4)

            Repeater {
              model: [
                { id: "all", label: "All" },
                { id: "network", label: "Network" },
                { id: "movies", label: "Movies" },
                { id: "classic", label: "Classic" },
                { id: "shop", label: "Shop" },
                { id: "religious", label: "Religious" },
                { id: "kids", label: "Kids" }
              ]

              Button {
                required property var modelData
                text: modelData.label
                selected: root.guideKind === modelData.id
                fontSize: Style.font.caption
                foreground: root.bar.foreground
                onClicked: root.guideKind = modelData.id
              }
            }
          }
        }

        Item {
          width: parent.width
          visible: !root.guideSearchActive
          height: visible ? Math.max(Style.space(32), guidePrevBtn.implicitHeight) : 0

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

            Row {
              anchors.left: guideHdrStation.right
              anchors.right: parent.right
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
                    color: Model.slotIsNow(parent.modelData, root.guideClockMin) ? Color.accent : Qt.darker(root.bar.foreground, 1.4)
                    font.family: root.bar.fontFamily
                    font.pixelSize: Style.font.caption
                    font.bold: Model.slotIsNow(parent.modelData, root.guideClockMin)
                    elide: Text.ElideRight
                    verticalAlignment: Text.AlignVCenter
                  }

                  Rectangle {
                    visible: Model.slotIsNow(parent.modelData, root.guideClockMin)
                    width: 2
                    height: parent.height
                    color: Color.accent
                    x: {
                      var start = Model.parseMinutes(parent.modelData)
                      var now = root.guideClockMin
                      if (start < 0 || now < 0) return 0
                      var frac = (now - start) / 30
                      if (frac < 0) frac = 0
                      if (frac > 1) frac = 1
                      return frac * Math.max(0, parent.width - width)
                    }
                  }
                }
              }
            }
          }
        }

        BorderSurface {
          id: guideDetailCard
          visible: root.guideDetailOpen
          width: parent.width
          implicitHeight: visible ? (guideDetailCol.implicitHeight + Style.space(20)) : 0
          radius: Style.spacing.labelGap
          color: Style.selectedFillFor(root.bar.foreground, Color.accent)
          borderSpec: Border.controlSpec("focus", root.bar.foreground, Color.accent)

          Column {
            id: guideDetailCol
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: Style.space(10)
            spacing: Style.space(8)

            Text {
              width: parent.width
              textFormat: Text.PlainText
              text: {
                var d = root.guideDetail
                if (!d) return ""
                var num = d.channel_number || ""
                var call = d.callsign || ""
                if (num && call) return num + "  ·  " + call
                return num || call || ""
              }
              color: Qt.darker(root.bar.foreground, 1.4)
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              elide: Text.ElideRight
            }

            Text {
              width: parent.width
              textFormat: Text.PlainText
              text: root.guideDetail ? (root.guideDetail.title || "Live") : ""
              color: root.bar.foreground
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.subtitle
              font.bold: true
              wrapMode: Text.WordWrap
            }

            Text {
              width: parent.width
              visible: !!(root.guideDetail && (root.guideDetail.start || root.guideDetail.end))
              textFormat: Text.PlainText
              text: {
                var d = root.guideDetail
                if (!d) return ""
                if (d.start && d.end) return d.start + " – " + d.end
                return d.start || d.end || ""
              }
              color: Color.accent
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.bodySmall
              font.bold: true
            }

            Text {
              width: parent.width
              visible: !!(root.guideDetail && root.guideDetail.usual)
              textFormat: Text.PlainText
              text: root.guideDetail ? (root.guideDetail.usual || "") : ""
              color: Color.accent
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              wrapMode: Text.WordWrap
            }

            Text {
              width: parent.width
              visible: !!(root.guideDetail && root.guideDetail.before && root.guideDetail.before.title)
              textFormat: Text.PlainText
              text: {
                var d = root.guideDetail
                if (!d || !d.before) return ""
                var when = d.before.start || ""
                return "Before: " + (d.before.title || "") + (when ? (" · " + when) : "")
              }
              color: Qt.darker(root.bar.foreground, 1.4)
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              elide: Text.ElideRight
            }

            Text {
              width: parent.width
              visible: !!(root.guideDetail && root.guideDetail.after && root.guideDetail.after.title)
              textFormat: Text.PlainText
              text: {
                var d = root.guideDetail
                if (!d || !d.after) return ""
                var when = d.after.start || ""
                return "After: " + (d.after.title || "") + (when ? (" · " + when) : "")
              }
              color: Qt.darker(root.bar.foreground, 1.4)
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              elide: Text.ElideRight
            }

            Text {
              width: parent.width
              visible: !!(root.guideDetail && root.guideDetail.also)
              textFormat: Text.PlainText
              text: root.guideDetail ? (root.guideDetail.also || "") : ""
              color: Qt.darker(root.bar.foreground, 1.4)
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              wrapMode: Text.WordWrap
            }

            Text {
              width: parent.width
              textFormat: Text.PlainText
              text: {
                var d = root.guideDetail
                if (!d) return ""
                if (d.synopsis) return d.synopsis
                return "No description for this show."
              }
              color: Qt.darker(root.bar.foreground, 1.4)
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              wrapMode: Text.WordWrap
              maximumLineCount: 8
              elide: Text.ElideRight
            }

            Text {
              width: parent.width
              visible: {
                var d = root.guideDetail
                if (!d || root.isChannelRecording(d.playIdent)) return false
                return !Model.showIsOn(d, root.guideClockMin)
              }
              textFormat: Text.PlainText
              text: "This show hasn’t started yet."
              color: Qt.darker(root.bar.foreground, 1.5)
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
            }

            Text {
              width: parent.width
              visible: {
                var rec = root.guideDetailRecording()
                if (!rec || !rec.file_path) return false
                return (Number(rec.file_size) || 0) < 262144
              }
              textFormat: Text.PlainText
              text: "Still starting."
              color: Qt.darker(root.bar.foreground, 1.5)
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
            }

            Item {
              width: parent.width
              height: Math.max(guideWatchBtn.implicitHeight, guideFromStartBtn.implicitHeight, guideRecordShowBtn.implicitHeight, guideDetailCloseBtn.implicitHeight)

              Row {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                spacing: Style.space(6)

                Button {
                  id: guideWatchBtn
                  text: root.guideDetailRecording() ? "Watch live" : "Watch"
                  tooltipText: root.guideDetailRecording() ? "Tune this channel live" : "Tune this channel"
                  foreground: root.bar.foreground
                  onClicked: root.watchGuideDetail()
                }

                Button {
                  id: guideFromStartBtn
                  visible: {
                    var rec = root.guideDetailRecording()
                    if (!rec || !rec.file_path) return false
                    return (Number(rec.file_size) || 0) >= 262144
                  }
                  text: "From the start"
                  tooltipText: "Play this recording from the beginning"
                  foreground: root.bar.foreground
                  onClicked: root.playGuideDetailFromStart()
                }

                Button {
                  id: guideRecordShowBtn
                  visible: {
                    var d = root.guideDetail
                    if (!d) return false
                    if (root.isChannelRecording(d.playIdent)) return true
                    return Model.showIsOn(d, root.guideClockMin)
                  }
                  text: {
                    var d = root.guideDetail
                    if (d && root.isChannelRecording(d.playIdent)) return "Stop"
                    return "Record this show"
                  }
                  tooltipText: {
                    var d = root.guideDetail
                    if (d && root.isChannelRecording(d.playIdent)) return "Stop recording"
                    return "Record until this show ends"
                  }
                  foreground: root.bar.foreground
                  onClicked: root.recordGuideDetail()
                }
              }

              Button {
                id: guideDetailCloseBtn
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                text: "Close"
                tooltipText: "Back to the grid"
                foreground: root.bar.foreground
                onClicked: root.clearGuideDetail()
              }
            }
          }
        }

        Item {
          id: guideGridClip
          visible: !root.guideSearchActive
          width: parent.width
          height: visible ? Math.max(Style.space(200), Math.round((popup.availableCardHeight || Style.space(720)) * 0.72) - (root.guideDetailOpen ? (guideDetailCard.implicitHeight + Style.space(10)) : 0)) : 0
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
                        onClicked: root.openGuideDetailFromRow(gridRow.modelData)
                      }
                    }

                    Row {
                      anchors.left: stationBadge.right
                      anchors.right: parent.right
                      anchors.leftMargin: root.guideSlotGap
                      anchors.rightMargin: 0
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
                            var recBox = root.isGuideBlockRecording(gridRow.modelData, modelData)
                            var d = root.guideDetail
                            var picked = !!(d && d.playIdent === gridRow.playIdent && d.start === modelData.start && d.title === modelData.title)
                            if (recBox) return Style.selectedFillFor(root.bar.foreground, Color.urgent)
                            if (picked || modelData.now) return Style.selectedFillFor(root.bar.foreground, Color.accent)
                            return Style.normalFillFor(root.bar.foreground, Color.accent)
                          }
                          borderSpec: {
                            if (modelData.empty)
                              return Border.flat("transparent", 0)
                            if (root.isGuideBlockRecording(gridRow.modelData, modelData))
                              return Border.controlSpec("focus", root.bar.foreground, Color.urgent)
                            var d = root.guideDetail
                            var picked = !!(d && d.playIdent === gridRow.playIdent && d.start === modelData.start && d.title === modelData.title)
                            return Border.controlSpec((picked || modelData.now) ? "focus" : "normal", root.bar.foreground, Color.accent)
                          }
                          opacity: 1

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
                              color: root.isGuideBlockRecording(gridRow.modelData, modelData)
                                ? Color.urgent
                                : (modelData.now || gridRow.isCurrent ? Color.accent : root.bar.foreground)
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
                            cursorShape: modelData.empty ? Qt.ArrowCursor : Qt.PointingHandCursor
                            onClicked: {
                              if (modelData.empty) return
                              root.openGuideDetail(gridRow.modelData, modelData)
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

        Flickable {
          id: guideSearchFlick
          visible: root.guideSearchActive
          width: parent.width
          height: visible
            ? Math.max(Style.space(200), Math.round((popup.availableCardHeight || Style.space(720)) * 0.72) - (root.guideDetailOpen ? (guideDetailCard.implicitHeight + Style.space(10)) : 0))
            : 0
          contentWidth: width
          contentHeight: guideSearchCol.implicitHeight
          clip: true
          boundsBehavior: Flickable.StopAtBounds

          Column {
            id: guideSearchCol
            width: parent.width
            spacing: Style.space(6)

            Text {
              width: parent.width
              visible: root.guideSearchHits.length === 0
              textFormat: Text.PlainText
              text: "No shows match."
              color: Qt.darker(root.bar.foreground, 1.5)
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.bodySmall
            }

            Repeater {
              model: root.guideSearchHits

              BorderSurface {
                required property var modelData
                width: guideSearchCol.width
                height: searchHitCol.implicitHeight + Style.space(16)
                radius: Style.spacing.labelGap
                color: {
                  var d = root.guideDetail
                  var picked = !!(d && d.playIdent === Model.guidePlayIdent(modelData) && d.start === modelData.start && d.title === modelData.title)
                  if (picked || modelData.on_now) return Style.selectedFillFor(root.bar.foreground, Color.accent)
                  return Style.normalFillFor(root.bar.foreground, Color.accent)
                }
                borderSpec: {
                  var d = root.guideDetail
                  var picked = !!(d && d.playIdent === Model.guidePlayIdent(modelData) && d.start === modelData.start && d.title === modelData.title)
                  return Border.controlSpec((picked || modelData.on_now) ? "focus" : "normal", root.bar.foreground, Color.accent)
                }

                Column {
                  id: searchHitCol
                  anchors.left: parent.left
                  anchors.right: parent.right
                  anchors.top: parent.top
                  anchors.margins: Style.space(8)
                  spacing: Style.space(2)

                  Text {
                    width: parent.width
                    textFormat: Text.PlainText
                    text: (modelData.channel_number || "") + "  " + (modelData.callsign || modelData.station || "")
                    color: Color.accent
                    font.family: root.bar.fontFamily
                    font.pixelSize: Style.font.caption
                    elide: Text.ElideRight
                  }

                  Text {
                    width: parent.width
                    textFormat: Text.PlainText
                    text: modelData.title || ""
                    color: root.bar.foreground
                    font.family: root.bar.fontFamily
                    font.pixelSize: Style.font.bodySmall
                    font.bold: true
                    elide: Text.ElideRight
                  }

                  Text {
                    width: parent.width
                    textFormat: Text.PlainText
                    text: (modelData.start && modelData.end) ? (modelData.start + " – " + modelData.end) : (modelData.start || "")
                    color: Qt.darker(root.bar.foreground, 1.5)
                    font.family: root.bar.fontFamily
                    font.pixelSize: Style.font.caption
                    elide: Text.ElideRight
                    visible: text !== ""
                  }

                  Text {
                    width: parent.width
                    textFormat: Text.PlainText
                    text: modelData.usual || ""
                    color: Color.accent
                    font.family: root.bar.fontFamily
                    font.pixelSize: Style.font.caption
                    elide: Text.ElideRight
                    visible: text !== ""
                  }

                  Text {
                    width: parent.width
                    textFormat: Text.PlainText
                    text: {
                      var parts = []
                      if (modelData.before && modelData.before.title)
                        parts.push("Before: " + modelData.before.title)
                      if (modelData.after && modelData.after.title)
                        parts.push("After: " + modelData.after.title)
                      return parts.join("   ·   ")
                    }
                    color: Qt.darker(root.bar.foreground, 1.4)
                    font.family: root.bar.fontFamily
                    font.pixelSize: Style.font.caption
                    wrapMode: Text.WordWrap
                    visible: text !== ""
                  }
                }

                MouseArea {
                  anchors.fill: parent
                  hoverEnabled: true
                  cursorShape: Qt.PointingHandCursor
                  onClicked: {
                    root.openGuideDetail({
                      channel_number: modelData.channel_number,
                      callsign: modelData.callsign,
                      tune_name: modelData.tune_name,
                      station: modelData.station || modelData.callsign
                    }, modelData.block)
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
