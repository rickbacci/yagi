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
      if (root.favoritesData && root.favoritesData.length > 0) {
        root.channelFilter = "favorites"
      } else {
        root.channelFilter = "all"
      }
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
  property string channelFilter: "all" // "all" | "favorites"

  readonly property var displayChannels: {
    if (root.channelFilter === "favorites") {
      return (root.channelsData || []).filter(function(ch) {
        if (!root.favoritesData) return false
        return root.favoritesData.indexOf(ch.name) !== -1 || (ch.tune_name && root.favoritesData.indexOf(ch.tune_name) !== -1)
      })
    }
    return root.channelsData || []
  }

  readonly property string binPath: "omarchy-tv"

  function close() { root.popupOpen = false }
  function toggle() { root.popupOpen = !root.popupOpen }

  function playChannel(chName) {
    root.activeChannelName = chName
    tuneProc.command = [root.binPath, "play", chName]
    tuneProc.running = true
  }

  function channelUp() {
    navProc.command = [root.binPath, "next"]
    navProc.running = true
  }

  function channelDown() {
    navProc.command = [root.binPath, "prev"]
    navProc.running = true
  }

  function stopPlayer() {
    root.activeChannelName = ""
    stopProc.command = [root.binPath, "stop"]
    stopProc.running = true
  }

  function startScan() {
    root.isScanning = true
    root.scanPercent = 1
    root.scanTotalFound = 0
    root.scanSignal = null
    scanProc.running = false
    scanProc.command = [root.binPath, "scan"]
    scanProc.running = true
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
      root.isScanning = (status.is_scanning === true) && (isHeartbeatValid || scanProc.running)
      root.scanPercent = status.percent || 0
      root.scanChannel = status.channel || 0
      root.scanBand = status.band || ""
      root.scanFreq = status.frequency || 0
      root.scanSignal = (status.signal_dbm !== undefined) ? status.signal_dbm : null
      root.scanTotalFound = status.total_found || 0
      if (status.channels && status.channels.length > 0) {
        root.channelsData = status.channels
      }
    } catch (e) {
      // ignore transient partial write
    }
  }

  property bool filterInitialized: false

  function applyFavorites(jsonText) {
    try {
      root.favoritesData = JSON.parse(jsonText || "[]")
      if (!root.filterInitialized) {
        root.channelFilter = (root.favoritesData && root.favoritesData.length > 0) ? "favorites" : "all"
        root.filterInitialized = true
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

  function getProgram(ch) {
    if (!root.guideData || !ch) return null
    if (ch.channel_number && root.guideData[ch.channel_number]) {
      return root.guideData[ch.channel_number]
    }
    for (var k in root.guideData) {
      var p = root.guideData[k]
      if (p.station && (p.station === ch.name || p.station === ch.raw_name || p.station === ch.tune_name)) return p
      if (p.network && ch.network && p.network.toLowerCase() === ch.network.toLowerCase()) return p
    }
    return null
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
      text: root.isScanning ? "󰛳" : "󰢹"
      color: root.isScanning ? "#89b4fa" : (root.activeChannelName !== "" ? Color.accent : root.bar.barForeground)
      font.family: root.bar.fontFamily
      font.pixelSize: Style.font.body
      anchors.verticalCenter: parent.verticalCenter
    }

    Text {
      id: label
      visible: (root.isScanning || root.activeChannelName !== "") && !root.bar.vertical
      textFormat: Text.PlainText
      text: root.isScanning ? (root.scanPercent + "% Scanning") : root.activeChannelName
      color: root.isScanning ? "#89b4fa" : root.bar.barForeground
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
    }

    function reloadChannels(): void {
      channelsFile.reload()
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

    function scan(): void {
      root.startScan()
    }

    function toggle(): void {
      root.toggle()
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

  // Watch guide.json EPG file
  FileView {
    id: guideFile
    path: (Quickshell.env("HOME") || "") + "/.config/omarchy/tv/guide.json"
    watchChanges: true
    printErrors: false
    onLoaded: root.applyGuide(text())
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

  Timer {
    id: scanPollTimer
    interval: 500
    running: true
    repeat: true
    onTriggered: scanStatusFile.reload()
  }

  // Processes for tuning & scan
  Process {
    id: tuneProc
    command: []
  }

  Process {
    id: navProc
    command: []
  }

  Process {
    id: favProc
    command: []
    onExited: function(code) {
      favoritesFile.reload()
    }
  }

  Process {
    id: stopProc
    command: [root.binPath, "stop"]
  }

  Process {
    id: scanProc
    command: [root.binPath, "scan"]
    onExited: function(code) {
      root.isScanning = false
      scanStatusFile.reload()
      channelsFile.reload()
    }
  }

  Component.onCompleted: {
    Qt.callLater(function() {
      channelsFile.reload()
      scanStatusFile.reload()
    })
  }

  // Flyout Panel
  PopupCard {
    id: popup
    anchorItem: root
    bar: root.bar
    owner: root
    open: root.popupOpen
    contentWidth: popup.fittedContentWidth(Style.space(380))
    contentHeight: popup.fittedContentHeight(Math.min(Style.space(560), mainCol.implicitHeight + Style.space(24)))

    Column {
      id: mainCol
      anchors.left: parent.left
      anchors.right: parent.right
      spacing: Style.space(12)

      // Header
      Row {
        width: parent.width
        spacing: Style.space(10)

        BorderSurface {
          width: Style.space(42)
          height: Style.space(42)
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

        Column {
          width: parent.width - Style.space(52)
          spacing: Style.space(2)
          anchors.verticalCenter: parent.verticalCenter

          Text {
            textFormat: Text.PlainText
            text: "Omarchy TV"
            color: root.bar.foreground
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.subtitle
            font.bold: true
          }

          Text {
            textFormat: Text.PlainText
            text: root.isScanning ? "Scanning Broadcast Frequencies..." : (root.channelsData.length > 0 ? (root.channelsData.length + " Channels Available") : "No Channels Scanned")
            color: root.isScanning ? Color.accent : Qt.darker(root.bar.foreground, 1.4)
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
          }
        }
      }

      // Action Bar: Scan / Stop
      Row {
        width: parent.width
        spacing: Style.space(8)

        Button {
          iconText: root.isScanning ? "󰑐" : "󰍉"
          text: root.isScanning ? "Scanning in progress..." : "Scan OTA Channels"
          foreground: root.bar.foreground
          enabled: !root.isScanning
          onClicked: root.startScan()
        }

        Button {
          iconText: "󰓛"
          text: "Stop Player"
          foreground: root.bar.foreground
          visible: root.activeChannelName !== ""
          onClicked: root.stopPlayer()
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
                color: root.scanSignal !== null && root.scanSignal > -55 ? "#a6e3a1" : (root.scanSignal !== null ? "#89b4fa" : Qt.darker(root.bar.foreground, 1.6))
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
        radius: Style.spacing.labelGap
        color: Style.selectedFillFor(root.bar.foreground, Color.accent)
        borderSpec: Border.controlSpec("normal", root.bar.foreground, Color.accent)

        Column {
          anchors.fill: parent
          anchors.margins: Style.space(10)
          spacing: Style.space(4)

          Row {
            width: parent.width
            spacing: Style.space(6)

            Text {
              textFormat: Text.PlainText
              text: "󰐊 LIVE STREAM"
              color: Color.accent
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              font.bold: true
            }

            Item {
              width: Math.max(8, parent.width - Style.space(210))
              height: 1
            }

            Text {
              textFormat: Text.PlainText
              text: "720p HD · AC-3 5.1 Digital"
              color: Qt.darker(root.bar.foreground, 1.4)
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
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
        }
      }

      PanelSeparator {
        width: parent.width
        foreground: root.bar.foreground
      }

      // Channel Guide Header with Filter Tabs
      Row {
        width: parent.width
        spacing: Style.space(6)

        Item {
          width: parent.width - filterTabRow.width - Style.space(6)
          height: filterTabRow.height

          Text {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            textFormat: Text.PlainText
            text: "CHANNEL GUIDE"
            color: Qt.darker(root.bar.foreground, 1.6)
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
            font.bold: true
          }
        }

        Row {
          id: filterTabRow
          spacing: Style.space(4)
          anchors.verticalCenter: parent.verticalCenter

          // "All" Tab
          BorderSurface {
            height: Style.space(22)
            width: allTabText.implicitWidth + Style.space(14)
            radius: 4
            color: root.channelFilter === "all" ? Style.selectedFillFor(root.bar.foreground, Color.accent) : "transparent"
            borderSpec: root.channelFilter === "all" ? Border.controlSpec("normal", root.bar.foreground, Color.accent) : Border.controlSpec("normal", root.bar.foreground, "transparent")

            Text {
              id: allTabText
              anchors.centerIn: parent
              textFormat: Text.PlainText
              text: "All (" + root.channelsData.length + ")"
              color: root.channelFilter === "all" ? Color.accent : Qt.darker(root.bar.foreground, 1.6)
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              font.bold: root.channelFilter === "all"
            }

            MouseArea {
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: root.channelFilter = "all"
            }
          }

          // "Favorites" Tab
          BorderSurface {
            height: Style.space(22)
            width: favTabText.implicitWidth + Style.space(14)
            radius: 4
            color: root.channelFilter === "favorites" ? Style.selectedFillFor(root.bar.foreground, Color.accent) : "transparent"
            borderSpec: root.channelFilter === "favorites" ? Border.controlSpec("normal", root.bar.foreground, Color.accent) : Border.controlSpec("normal", root.bar.foreground, "transparent")

            Text {
              id: favTabText
              anchors.centerIn: parent
              textFormat: Text.PlainText
              text: "★ Favs (" + root.favoritesData.length + ")"
              color: root.channelFilter === "favorites" ? "#f9e2af" : (root.favoritesData.length > 0 ? root.bar.foreground : Qt.darker(root.bar.foreground, 1.8))
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              font.bold: root.channelFilter === "favorites"
            }

            MouseArea {
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: root.channelFilter = "favorites"
            }
          }
        }
      }

      // Empty State (No Channels Scanned)
      Item {
        visible: root.channelsData.length === 0 && !root.isScanning
        width: parent.width
        height: Style.space(80)

        Column {
          anchors.centerIn: parent
          spacing: Style.space(6)
          Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "No channels found yet"
            color: Qt.darker(root.bar.foreground, 1.5)
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.bodySmall
          }
          Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "Click 'Scan OTA Channels' to discover local stations."
            color: Qt.darker(root.bar.foreground, 1.8)
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
          }
        }
      }

      // Empty State (No Favorites Selected)
      Item {
        visible: root.channelsData.length > 0 && root.channelFilter === "favorites" && root.displayChannels.length === 0
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
        visible: root.displayChannels.length > 0
        width: parent.width
        height: Math.min(Style.space(260), channelListView.implicitHeight)
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

              BorderSurface {
                id: chItem
                required property var modelData
                readonly property bool isCurrent: root.activeChannelName === modelData.name || root.activeChannelName === modelData.tune_name
                readonly property var program: root.getProgram(modelData)
                readonly property string channelBadge: Model.getChannelBadge(modelData)
                readonly property string netColor: Model.networkColor(modelData.network, Color.accent)

                width: channelListView.width
                height: Style.space(48)
                radius: Style.spacing.labelGap
                color: isCurrent ? Style.selectedFillFor(root.bar.foreground, Color.accent) : "transparent"
                borderSpec: isCurrent ? Border.controlSpec("normal", root.bar.foreground, Color.accent) : Border.none()

                Row {
                  anchors.left: parent.left
                  anchors.right: parent.right
                  anchors.verticalCenter: parent.verticalCenter
                  anchors.leftMargin: Style.space(8)
                  anchors.rightMargin: Style.space(8)
                  spacing: Style.space(8)

                  // Channel Number Badge
                  BorderSurface {
                    width: Style.space(46)
                    height: Style.space(26)
                    radius: Style.spacing.labelGap
                    color: chItem.isCurrent ? Color.accent : Style.normalFillFor(root.bar.foreground, Color.accent)
                    anchors.verticalCenter: parent.verticalCenter

                    Text {
                      anchors.centerIn: parent
                      textFormat: Text.PlainText
                      text: chItem.channelBadge
                      color: chItem.isCurrent ? "#11111b" : root.bar.foreground
                      font.family: root.bar.fontFamily
                      font.pixelSize: Style.font.caption
                      font.bold: true
                    }
                  }

                  // Channel Info (Title + Network + EPG Current Program)
                  Column {
                    width: parent.width - Style.space(90)
                    spacing: Style.space(2)
                    anchors.verticalCenter: parent.verticalCenter

                    Row {
                      width: parent.width
                      spacing: Style.space(6)

                      Text {
                        textFormat: Text.PlainText
                        text: Model.getDisplayTitle(chItem.modelData)
                        color: root.bar.foreground
                        font.family: root.bar.fontFamily
                        font.pixelSize: Style.font.bodySmall
                        font.bold: chItem.isCurrent
                        elide: Text.ElideRight
                        width: Math.max(Style.space(80), parent.width - (netBadge.visible ? netBadge.width + Style.space(6) : 0))
                      }

                      BorderSurface {
                        id: netBadge
                        visible: chItem.modelData.network !== undefined && chItem.modelData.network !== "" && chItem.modelData.network !== "OTA"
                        height: Style.space(16)
                        width: netBadgeText.implicitWidth + Style.space(8)
                        radius: 3
                        color: "transparent"
                        borderSpec: Border.controlSpec("normal", chItem.netColor, chItem.netColor)

                        Text {
                          id: netBadgeText
                          anchors.centerIn: parent
                          textFormat: Text.PlainText
                          text: chItem.modelData.network || ""
                          color: chItem.netColor
                          font.family: root.bar.fontFamily
                          font.pixelSize: Style.font.tiny
                          font.bold: true
                        }
                      }
                    }

                    // Program Guide Show Title or Frequency
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

                  // Favorite Star Button
                  Item {
                    width: Style.space(26)
                    height: Style.space(26)
                    anchors.verticalCenter: parent.verticalCenter

                    Text {
                      anchors.centerIn: parent
                      text: root.isFavorite(chItem.modelData.name) || (chItem.modelData.tune_name && root.isFavorite(chItem.modelData.tune_name)) ? "★" : "☆"
                      color: (root.isFavorite(chItem.modelData.name) || (chItem.modelData.tune_name && root.isFavorite(chItem.modelData.tune_name))) ? "#f9e2af" : (starMouse.containsMouse ? Color.accent : Qt.darker(root.bar.foreground, 2.2))
                      font.pixelSize: Style.font.body
                    }

                    MouseArea {
                      id: starMouse
                      anchors.fill: parent
                      hoverEnabled: true
                      cursorShape: Qt.PointingHandCursor
                      onClicked: function(mouse) {
                        mouse.accepted = true
                        root.toggleFavorite(chItem.modelData.tune_name || chItem.modelData.name)
                      }
                      onWheel: function(wheel) { wheel.accepted = false }
                    }
                  }
                }

                MouseArea {
                  anchors.fill: parent
                  anchors.rightMargin: Style.space(34)
                  hoverEnabled: true
                  cursorShape: Qt.PointingHandCursor
                  onClicked: root.playChannel(chItem.modelData.tune_name || chItem.modelData.name)
                  onWheel: function(wheel) { wheel.accepted = false }
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

      // Quick Nav footer
      Row {
        visible: root.channelsData.length > 0
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: Style.space(8)

        Button {
          iconText: "󰒮"
          text: "Prev Ch"
          foreground: root.bar.foreground
          onClicked: root.channelDown()
        }

        Button {
          iconText: "󰒭"
          text: "Next Ch"
          foreground: root.bar.foreground
          onClicked: root.channelUp()
        }
      }
    }
  }
}
