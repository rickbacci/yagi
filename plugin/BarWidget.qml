import QtQuick
import Quickshell
import Quickshell.Io
import qs.Ui
import qs.Commons
import "Model.js" as Model

BarWidget {
  id: root
  moduleName: "richardb.yagi"

  readonly property string tvConfigDir: Model.tvConfigDir(
    Quickshell.env("XDG_CONFIG_HOME"),
    Quickshell.env("HOME")
  )
  property string binPath: "yagi"

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
  // A recording that copies the live dump rides live TV's tuner until it is kept.
  property int tunerCount: 2
  readonly property int tunersFree: Math.max(0, root.tunerCount - (root.liveOn ? 1 : 0)
                                             - (root.activeRecordings || []).filter(function(r) {
                                                 return !(root.liveOn && r.source && r.source.dump_pid && !r.source.kept)
                                               }).length
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
  property var ruleList: []

  // Recordings page: two tabs, each with its own cursor. Recorded drills into one show.
  property string libraryTab: "recorded"
  property string libraryShow: ""
  property int libraryShowCursor: 0
  property int schedCursorIndex: 0
  readonly property var librarySorted: Model.sortRecordings(root.recordingsData)
  readonly property var recordedPicks: Model.recordedPicks(root.librarySorted, root.gridNow, root.libraryShow)
  readonly property var libraryOpenShow: Model.showByKey(root.librarySorted, root.libraryShow)
  readonly property string libraryShowTitle: root.libraryOpenShow ? (root.libraryOpenShow.title || "") : ""
  readonly property string libraryShowSubtitle: Model.showSubtitle(root.libraryOpenShow)
  readonly property var scheduledRows: Model.scheduledRows(root.activeRecordings, root.scheduleItems, root.ruleList,
                                                           root.gridNow, root.stationFor)
  readonly property var scheduledPicks: root.scheduledRows.filter(function(r) { return r.kind !== "header" })
  property string deleteArmed: ""
  property int guideCursor: 0
  property bool focusAfterTune: false
  onGuideSearchActiveChanged: {
    root.guideCursor = 0
    root.gridCardOpen = false
    root.gridRow = 0
    root.gridCol = 0
  }
  onShowBucketChanged: root.guideCursor = 0

  // Guide grid: its cursor is a row and a block; gridTime keeps the column on up and down.
  property string guideTab: "grid"
  property int gridRow: 0
  property int gridCol: 0
  property real gridTime: 0
  property bool gridCardOpen: false
  readonly property real gridNow: {
    root.guideClockMin
    return Date.now() / 1000
  }
  readonly property real gridStart: Model.gridStart(root.gridNow)
  readonly property var gridRows: root.guideStripOpen
    ? Model.gridRows(root.guideSearchActive ? root.watchableChannels : root.displayChannels, root.guideData,
                     root.gridStart, root.gridNow, root.guideSearchActive ? root.guideSearchText : "", root.displayChannels)
    : []
  readonly property real gridEnd: Model.gridEnd(root.gridRows, root.gridStart)
  readonly property int gridMatchCount: Model.gridMatchCount(root.gridRows)

  Timer {
    id: deleteDisarm
    interval: 3000
    onTriggered: root.deleteArmed = ""
  }
  property string showBucket: Model.bucketNow()
  readonly property var guideShowRows: Model.filterShowsByQuery(Model.filterShows(root.showItems, root.showBucket), root.guideSearchText)
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

  // Header, search, and tabs take the rest.
  function guideListRoom() {
    return root.roomFor(Style.space(190))
  }

  function flyoutContentWidth() {
    var avail = popup.availableCardWidth
    var share = root.guideStripOpen ? 0.58 : 0.40
    if (!(avail > 0)) return popup.fittedContentWidth(Style.space(root.guideStripOpen ? 1200 : 900))
    return popup.fittedContentWidth(Math.max(Style.space(720), Math.round(avail * share)))
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
    var list = []
    try {
      var rules = (JSON.parse(raw || "{}").rules) || []
      list = rules
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
    root.ruleList = list
  }

  // Personal fields go on stdin. Argv stays the fixed verb so procfs does not show the title.
  function flushStdin(proc) {
    if (!proc.stdinPayload) return
    var cmd = proc.command || []
    var wants = false
    for (var i = 0; i < cmd.length; i++) if (cmd[i] === "--stdin") wants = true
    if (!wants) return
    var payload = proc.stdinPayload
    proc.stdinPayload = ""
    proc.write(payload)
    proc.stdinEnabled = false
  }

  function runPrivate(proc, argv, details) {
    proc.stdinPayload = JSON.stringify(details || {})
    proc.stdinEnabled = true
    proc.running = false
    proc.command = argv.concat(["--stdin"])
    proc.running = true
  }

  function toggleRecordAll(show) {
    if (!show) return
    if (show.id && root.ruleIds[show.id]) {
      root.runPrivate(ruleProc, [root.binPath, "series", "remove"], { target: show.id })
    } else {
      if (!show.tune_name) return
      root.runPrivate(ruleProc, [root.binPath, "series", "add"], {
        target: show.tune_name,
        title: show.title || "",
        channel: show.channel || ""
      })
    }
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
    var details = {
      target: show.tune_name,
      duration: String(dur),
      title: show.title || "Scheduled",
      gps: Number(show.gps_start) || 0,
      clock: show.start || "",
      end_clock: show.end || "",
      display_name: show.display_name || show.tune_name
    }
    if (show.channel_number) details.channel = String(show.channel_number)
    if (Model.isGameTitle(show.title)) details.extra = Model.gameExtraMin() + "m"
    root.runPrivate(schedProc, [root.binPath, "record", "later"], details)
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
    root.runPrivate(schedProc, [root.binPath, "record", "unlater"], { target: itemId })
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
      root.startRecord(show.channel_number || show.tune_name, left, show.title || "")
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
    guidePage.searchField.text = ""
    root.guideClockMin = Model.minutesNow()
    root.gridCardOpen = false
    root.cursorActive = false
    root.guideStripOpen = true
  }

  function showGuideTab(tab) {
    root.guideTab = tab
    root.gridCardOpen = false
    root.cursorActive = false
    root.guideCursor = 0
  }

  // Return or Down in the search box: into the grid at the first match, or the top of the shows.
  function leaveGuideSearch() {
    keyCatcher.forceActiveFocus()
    root.cursorActive = true
    root.guideCursor = 0
    if (root.guideTab === "grid") root.gridHome()
    Qt.callLater(root.revealCursor)
  }

  function gridBlocksAt(r) {
    var row = (root.gridRows || [])[r]
    return row ? row.blocks : []
  }

  function gridCurrent() {
    return root.gridBlocksAt(root.gridRow)[root.gridCol] || null
  }

  function gridHome() {
    root.gridCardOpen = false
    if (root.guideSearchActive) {
      root.gridRow = 0
      root.gridCol = 0
      root.gridStepMatch(1)
      return
    }
    root.gridRow = 0
    root.gridTime = root.gridNow
    root.gridCol = Math.max(0, Model.blockAt(root.gridBlocksAt(0), root.gridNow))
  }

  // Up and down step through search matches in reading order.
  function gridStepMatch(dir) {
    var rows = root.gridRows || []
    var list = []
    var at = -1
    for (var r = 0; r < rows.length; r++) {
      for (var c = 0; c < rows[r].blocks.length; c++) {
        if (!rows[r].blocks[c].match) continue
        if (r === root.gridRow && c === root.gridCol) at = list.length
        list.push([r, c])
      }
    }
    if (!list.length) return
    var next = at === -1 ? (dir > 0 ? 0 : list.length - 1) : Math.max(0, Math.min(list.length - 1, at + dir))
    root.gridRow = list[next][0]
    root.gridCol = list[next][1]
    var b = root.gridCurrent()
    if (b) root.gridTime = b.x0
  }

  function gridMove(dx, dy) {
    var rows = root.gridRows || []
    if (!rows.length) return
    if (!root.cursorActive) {
      root.cursorActive = true
      root.gridHome()
      Qt.callLater(root.revealCursor)
      return
    }
    root.gridCardOpen = false
    if (dy !== 0 && root.guideSearchActive) {
      root.gridStepMatch(dy)
    } else if (dy !== 0) {
      root.gridRow = Math.max(0, Math.min(rows.length - 1, root.gridRow + dy))
      root.gridCol = Math.max(0, Model.blockAt(root.gridBlocksAt(root.gridRow), root.gridTime))
    } else if (dx !== 0) {
      var n = root.gridBlocksAt(root.gridRow).length
      root.gridCol = Math.max(0, Math.min(n - 1, root.gridCol + dx))
      var b = root.gridCurrent()
      if (b) root.gridTime = b.x0
    }
    Qt.callLater(root.revealCursor)
  }

  // Enter opens the card; with it open, Enter watches what is on or records what is coming.
  function gridActivate() {
    var b = root.gridCurrent()
    if (!b) return
    if (!root.gridCardOpen) {
      root.gridCardOpen = true
      return
    }
    if (b.on_now) root.selectChannel(b.tune_name || b.channel_number)
    else root.toggleHitRecord(Model.blockAiring(b))
  }

  function toggleLibrary() {
    if (root.libraryModalOpen) {
      root.libraryModalOpen = false
      root.cursorActive = false
      return
    }
    root.guideStripOpen = false
    root.libraryShow = ""
    root.recCursorIndex = 0
    root.schedCursorIndex = 0
    root.libraryTab = "recorded"
    root.cursorActive = false
    root.libraryModalOpen = true
    recIndexProc.running = false
    recIndexProc.command = [root.binPath, "record", "list"]
    recIndexProc.running = true
  }

  function showLibraryTab(tab) {
    root.libraryTab = tab
    root.cursorActive = false
    root.deleteArmed = ""
  }

  function recordedCount() {
    var rows = root.recordedPicks || []
    var n = 0
    for (var i = 0; i < rows.length; i++) if (rows[i] && rows[i].pick >= 0) n++
    return n
  }

  function recordedPick() {
    var rows = root.recordedPicks || []
    for (var i = 0; i < rows.length; i++) {
      if (rows[i] && rows[i].pick === root.recCursorIndex) return rows[i]
    }
    return null
  }

  function openLibraryShow(key) {
    if (!key) return
    root.libraryShowCursor = root.recCursorIndex
    root.libraryShow = key
    root.recCursorIndex = 0
    root.cursorActive = true
    root.deleteArmed = ""
    Qt.callLater(root.revealCursor)
  }

  function closeLibraryShow() {
    if (!root.libraryShow) return false
    var back = root.libraryShowCursor
    root.libraryShow = ""
    root.recCursorIndex = back
    root.deleteArmed = ""
    root.cursorActive = true
    Qt.callLater(function() {
      root.clampRecCursor()
      root.revealCursor()
    })
    return true
  }

  function libraryBack() {
    if (root.libraryTab === "recorded" && root.closeLibraryShow()) return
    root.toggleLibrary()
  }

  function syncLibraryShow() {
    if (root.libraryShow && !Model.showByKey(root.librarySorted, root.libraryShow))
      root.libraryShow = ""
    Qt.callLater(root.clampRecCursor)
  }

  function clampRecCursor() {
    var n = root.recordedCount()
    if (root.recCursorIndex >= n) root.recCursorIndex = Math.max(0, n - 1)
  }

  function openScheduled() {
    if (!root.libraryModalOpen) root.toggleLibrary()
    root.showLibraryTab("scheduled")
  }

  // Stop what records, drop what waits, end a series. Two presses, like delete.
  function dropScheduled(row) {
    if (!row) return
    if (root.deleteArmed !== row.key) {
      root.deleteArmed = row.key
      deleteDisarm.restart()
      return
    }
    root.deleteArmed = ""
    if (row.kind === "active") root.stopRecord(root.recordingIdent(row.item))
    else if (row.kind === "waiting") root.removeScheduled(row.item.id)
    else if (row.kind === "series") root.toggleRecordAll({ id: row.item.id })
  }

  function selectChannel(chName) {
    root.focusAfterTune = true
    root.playChannel(chName)
    if (!root.pendingWatch) root.close()
  }

  function focusTv() {
    focusProc.running = false
    focusProc.command = [root.binPath, "focus"]
    focusProc.running = true
  }

  function stopToWatch(rec) {
    root.watchAfterStop = root.pendingWatch
    root.pendingWatch = ""
    root.stopRecord(root.recordingIdent(rec))
  }

  function playRecording(filePath, playable) {
    if (playable === false) return
    root.runPrivate(recPlayProc, [root.binPath, "record", "play"], { target: filePath })
  }

  function deleteRecording(filePath) {
    root.runPrivate(dvrProc, [root.binPath, "record", "delete"], { target: filePath })
  }

  function listLen() {
    if (root.libraryModalOpen) return root.libraryTab === "recorded" ? root.recordedCount() : root.scheduledPicks.length
    if (root.guideStripOpen) return root.guideItems().length
    return root.displayChannels ? root.displayChannels.length : 0
  }

  function moveCursor(delta) {
    var n = root.listLen()
    if (n <= 0) return
    if (!root.cursorActive) {
      root.cursorActive = true
    } else if (root.libraryModalOpen && root.libraryTab === "scheduled") {
      root.schedCursorIndex = Math.max(0, Math.min(n - 1, root.schedCursorIndex + delta))
    } else if (root.libraryModalOpen) {
      root.recCursorIndex = Math.max(0, Math.min(n - 1, root.recCursorIndex + delta))
    } else if (root.guideStripOpen) {
      root.guideCursor = Math.max(0, Math.min(n - 1, root.guideCursor + delta))
    } else {
      root.cursorIndex = Math.max(0, Math.min(n - 1, root.cursorIndex + delta))
    }
    Qt.callLater(root.revealCursor)
  }

  function revealIn(flick, repeater, index) {
    var item = repeater ? repeater.itemAt(index) : null
    if (!flick || !item) return
    if (item.y < flick.contentY) flick.contentY = item.y
    else if (item.y + item.height > flick.contentY + flick.height)
      flick.contentY = item.y + item.height - flick.height
  }

  function revealCursor() {
    if (root.libraryModalOpen) libraryPage.revealCursor()
    else if (root.guideStripOpen && root.guideTab === "grid") guidePage.grid.reveal(root.gridRow, root.gridCurrent())
    else if (root.guideStripOpen) root.revealIn(guidePage.showsFlick, guidePage.showsList, root.guideCursor)
    else root.revealIn(channelList.flick, channelList.rows, root.cursorIndex)
  }

  function activateCursor() {
    if (!root.cursorActive) return
    if (root.libraryModalOpen) {
      if (root.libraryTab !== "recorded") return
      var pick = root.recordedPick()
      if (!pick) return
      if (pick.kind === "show") root.openLibraryShow(pick.show && pick.show.key)
      else if (pick.rec) root.playRecording(pick.rec.path || pick.rec.name, pick.rec.playable)
      return
    }
    if (root.guideStripOpen) {
      root.guideActivate()
      return
    }
    var ch = root.displayChannels[root.cursorIndex]
    if (ch) root.useListedChannel(root.listedKey(ch))
  }

  function guideItems() {
    return root.guideShowRows || []
  }

  function guideCurrent() {
    return root.guideItems()[root.guideCursor] || null
  }

  function guideCurrentAiring() {
    if (root.guideTab === "grid") return Model.blockAiring(root.gridCurrent())
    var item = root.guideCurrent()
    return item ? Model.showAiring(item) : null
  }

  function guideActivate() {
    if (root.guideTab === "grid") {
      root.gridActivate()
      return
    }
    var item = root.guideCurrent()
    if (!item) return
    var airing = Model.showAiring(item)
    if (airing && airing.on_now) root.selectChannel(airing.tune_name || airing.channel_number)
    else if (airing) root.toggleHitRecord(airing)
    else root.toggleRecordAll(item)
  }

  function guideRecordAll() {
    if (root.guideTab === "grid") {
      var airing = root.guideCurrentAiring()
      if (airing) root.toggleHitRecordAll(airing)
      return
    }
    var item = root.guideCurrent()
    if (item) root.toggleRecordAll(item)
  }

  function shiftBucket(dx) {
    var order = ["day", "prime", "late", "overnight"]
    var i = Math.max(0, order.indexOf(root.showBucket))
    root.showBucket = order[Math.max(0, Math.min(order.length - 1, i + dx))]
    root.guideCursor = 0
  }

  function deleteWithConfirm(rec) {
    if (!rec || Model.recordingLive(rec)) return
    var target = rec.path || rec.name
    if (root.deleteArmed !== target) {
      root.deleteArmed = target
      deleteDisarm.restart()
      return
    }
    root.deleteArmed = ""
    root.deleteRecording(target)
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
    var details = { target: chName }
    if (duration) details.duration = String(duration)
    if (title) details.title = title
    root.runPrivate(dvrProc, [root.binPath, "record", "start"], details)
  }

  function stopRecord(chName) {
    if (!chName) return
    root.runPrivate(dvrProc, [root.binPath, "record", "stop"], { target: chName })
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
      if (item.channel_number === chName || item.tune_name === chName || item.name === chName) {
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
      if (ch) return root.listedKey(ch)
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

  // Favorites are channel numbers; a name is left from before and matches by name.
  function channelIsFavorite(ch) {
    if (!ch || !root.favoritesData) return false
    var num = String(ch.channel_number || "")
    for (var i = 0; i < root.favoritesData.length; i++) {
      var f = String(root.favoritesData[i])
      if (/^\d+(\.\d+)?$/.test(f) ? f === num : (f === ch.name || f === ch.tune_name)) return true
    }
    return false
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
    root.runPrivate(tuneProc, [root.binPath, "play"], { channel: chName })
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
    root.runPrivate(dvrProc, [root.binPath, "record", keep ? "keep" : "unkeep"], {
      target: rec.path || rec.name
    })
  }

  function cycleShowLimit(show) {
    if (!show || !root.ruleIds[show.id]) return
    var cur = root.ruleKeep[show.id] || 0
    var next = cur === 0 ? 10 : (cur === 10 ? 30 : 0)
    root.runPrivate(ruleProc, [root.binPath, "series", "keep"], {
      target: show.id,
      count: String(next)
    })
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
    root.runPrivate(hiddenProc, [root.binPath, "hidden", "hide"], { channel: num })
  }

  function showListed(ch) {
    var num = ch ? String(ch.channel_number || "") : ""
    if (!num) return
    root.runPrivate(hiddenProc, [root.binPath, "hidden", "show"], { channel: num })
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
    Qt.callLater(root.syncLibraryShow)
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
    root.runPrivate(favProc, [root.binPath, "favorite", "toggle"], { channel: chName })
  }

  implicitWidth: row.implicitWidth + Style.space(12)
  implicitHeight: barSize

  Row {
    id: row
    anchors.centerIn: parent
    spacing: Style.space(6)

    YagiIcon {
      id: barIcon
      size: Math.round(Style.font.body * 1.35)
      color: root.isRecording ? Color.urgent
           : (root.activeChannelName !== "" || root.isScanning) ? Color.accent
           : root.bar.barForeground
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
        font.pixelSize: Style.font.heading
        font.bold: true
        anchors.verticalCenter: parent.verticalCenter
      }

      Text {
        visible: !root.isScanning && root.barWatchLabel() !== "" && root.barRecLabel() !== ""
        textFormat: Text.PlainText
        text: "·"
        color: Color.accent
        font.family: root.bar.fontFamily
        font.pixelSize: Style.font.heading
        font.bold: true
        anchors.verticalCenter: parent.verticalCenter
      }

      Text {
        visible: !root.isScanning && root.barRecLabel() !== ""
        textFormat: Text.PlainText
        text: root.barRecLabel()
        color: Color.urgent
        font.family: root.bar.fontFamily
        font.pixelSize: Style.font.heading
        font.bold: true
        anchors.verticalCenter: parent.verticalCenter
      }

      Text {
        visible: root.isScanning
        textFormat: Text.PlainText
        text: root.barStatusText()
        color: Color.accent
        font.family: root.bar.fontFamily
        font.pixelSize: Style.font.heading
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
    onEntered: if (root.bar) root.bar.showTooltip(root, "Yagi — Over-The-Air Television")
    onExited: if (root.bar) root.bar.hideTooltip(root)
  }

  IpcHandler {
    target: "richardb.yagi"

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

  readonly property string cliBesidePluginPath: Model.fileUrlToPath(Qt.resolvedUrl("../bin/yagi"))
  readonly property string cliBesideRootPath: Model.fileUrlToPath(Qt.resolvedUrl("bin/yagi"))

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
      if (code === 0 && root.binPath === "yagi")
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

  readonly property bool tuning: tuneProc.running
  readonly property bool showsLoading: showsProc.running
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
    property string stdinPayload: ""
    command: []
    onStarted: root.flushStdin(ruleProc)
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
    property string stdinPayload: ""
    command: []
    onStarted: root.flushStdin(schedProc)
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
    property string stdinPayload: ""
    command: []
    onStarted: root.flushStdin(tuneProc)
    onExited: function(code) {
      playerStateFile.reload()
      tuneStatusFile.reload()
      if (root.focusAfterTune && code === 0) root.focusTv()
      root.focusAfterTune = false
    }
  }

  Process {
    id: focusProc
    command: []
  }

  Process {
    id: recPlayProc
    property string stdinPayload: ""
    command: []
    onStarted: root.flushStdin(recPlayProc)
    onExited: function(code) {
      playerStateFile.reload()
      if (code === 0) {
        root.close()
        root.focusTv()
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
    property string stdinPayload: ""
    command: []
    onStarted: root.flushStdin(favProc)
    onExited: function(code) {
      favoritesFile.reload()
    }
  }

  Process {
    id: hiddenProc
    property string stdinPayload: ""
    command: []
    onStarted: root.flushStdin(hiddenProc)
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
    property string stdinPayload: ""
    command: []
    onStarted: root.flushStdin(dvrProc)
    onExited: function(code) {
      recordingsActiveFile.reload()
      recordingsFile.reload()
      if (root.watchAfterStop) {
        var watch = root.watchAfterStop
        root.watchAfterStop = ""
        root.focusAfterTune = true
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

  onBinPathChanged: tunerCountProc.running = true

  Process {
    id: tunerCountProc
    command: [root.binPath, "status", "--count"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var n = parseInt(text, 10)
        if (!isNaN(n)) root.tunerCount = n
      }
    }
  }

  Component.onCompleted: {
    tunerCountProc.running = true
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
      blocked: guidePage.searchField.activeFocus
      onCloseRequested: {
        if (root.gridCardOpen) root.gridCardOpen = false
        else if (root.guideStripOpen) root.guideStripOpen = false
        else if (root.libraryModalOpen && root.libraryTab === "recorded" && root.libraryShow) root.closeLibraryShow()
        else if (root.libraryModalOpen) root.libraryModalOpen = false
        else root.close()
      }
      onMoveRequested: function(dx, dy) {
        if (root.libraryModalOpen && dx !== 0) root.showLibraryTab(dx > 0 ? "scheduled" : "recorded")
        else if (root.guideStripOpen && !root.libraryModalOpen && root.guideTab === "grid") root.gridMove(dx, dy)
        else if (dy !== 0) root.moveCursor(dy)
        else if (dx !== 0 && root.guideStripOpen && !root.libraryModalOpen) root.shiftBucket(dx)
      }
      onActivateRequested: root.activateCursor()
      onDeleteRequested: {
        if (!root.libraryModalOpen || !root.cursorActive) return
        if (root.libraryTab === "scheduled") root.dropScheduled(root.scheduledPicks[root.schedCursorIndex])
        else {
          var pick = root.recordedPick()
          if (pick && pick.kind === "episode") root.deleteWithConfirm(pick.rec)
        }
      }
      onTabRequested: function(direction) {
        if (root.bar && typeof root.bar.switchPanelFrom === "function")
          root.bar.switchPanelFrom(root, direction)
      }
      onTextKey: function(t) {
        if (root.guideStripOpen && !root.libraryModalOpen && (t === "/" || t === "r" || t === "a" || t === "s")) {
          if (t === "/") {
            guidePage.searchField.forceActiveFocus()
          } else if (t === "s") {
            root.showGuideTab(root.guideTab === "grid" ? "shows" : "grid")
          } else if (t === "r") {
            var airing = root.guideCurrentAiring()
            if (airing) root.toggleHitRecord(airing)
          } else {
            root.guideRecordAll()
          }
          return
        }
        if (root.libraryModalOpen && t === "K") {
          var kept = root.recordedPick()
          if (root.cursorActive && kept && kept.kind === "episode") root.setRecordingKept(kept.rec, !kept.rec.keep)
          return
        }
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

        Column {
          id: remoteView
          visible: !root.libraryModalOpen
          width: parent.width
          spacing: Style.space(12)

          Column {
            id: remoteChrome
            width: parent.width
            spacing: Style.space(12)

            PanelHeader { tv: root; width: parent.width }
            ScanCard { tv: root; width: parent.width }
            NowPlayingCard { tv: root; width: parent.width }

            Repeater {
              model: root.activeRecordings
              delegate: RecordingCard { tv: root; width: remoteChrome.width }
            }

            BothBusyCard { tv: root; width: parent.width }

            StatusCard {
              tv: root
              width: parent.width
              message: !root.guideRefreshing ? ""
                : root.guideStatusTowers > 0
                  ? "Updating the Guide · tower " + root.guideStatusTower + " of " + root.guideStatusTowers
                  : "Updating the Guide"
            }

            StatusCard {
              tv: root
              width: parent.width
              message: root.scheduleLine
              clickable: true
              onClicked: root.openScheduled()
            }

            GuidePage {
              id: guidePage
              tv: root
              keyTarget: keyCatcher
              width: parent.width
            }

            ChannelFilterBar { tv: root; width: parent.width }

            EmptyState {
              tv: root
              visible: root.showChannelBrowser && root.channelsData.length === 0 && !root.isScanning
              width: parent.width
              height: Style.space(110)
              title: "No channels yet"
              detail: "Scan to find the channels your antenna picks up."
              actionIcon: "󰍉"
              actionText: "Scan"
              onAction: root.startScan()
            }

            EmptyState {
              tv: root
              visible: root.showChannelBrowser && root.channelsData.length > 0 && root.channelFilter === "favorites" && root.displayChannels.length === 0
              width: parent.width
              height: Style.space(70)
              gap: Style.space(4)
              title: "No favorites yet"
              titleBold: true
              detail: "Open All and click ☆ on a channel to add it here."
            }
          }

          ChannelList {
            id: channelList
            tv: root
            width: parent.width
            room: root.roomFor(remoteChrome.implicitHeight + mainCol.spacing)
          }
        }

        LibraryPage {
          id: libraryPage
          tv: root
          width: parent.width
          outerSpacing: mainCol.spacing
        }
      }
    }
  }
}
