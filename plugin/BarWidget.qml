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

  function close() { root.popupOpen = false }
  function toggle() { root.popupOpen = !root.popupOpen }

  function playChannel(chName) {
    root.activeChannelName = chName
    tuneProc.command = [
      (Quickshell.env("HOME") || "") + "/Projects/personal/omarchy-tv/bin/omarchy-tv",
      "play",
      chName
    ]
    tuneProc.running = true
  }

  function channelUp() {
    navProc.command = [
      (Quickshell.env("HOME") || "") + "/Projects/personal/omarchy-tv/bin/omarchy-tv",
      "next"
    ]
    navProc.running = true
  }

  function channelDown() {
    navProc.command = [
      (Quickshell.env("HOME") || "") + "/Projects/personal/omarchy-tv/bin/omarchy-tv",
      "prev"
    ]
    navProc.running = true
  }

  function stopPlayer() {
    root.activeChannelName = ""
    stopProc.running = true
  }

  function startScan() {
    root.isScanning = true
    root.scanPercent = 1
    root.scanTotalFound = 0
    root.scanSignal = null
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
      root.isScanning = status.is_scanning === true
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
    id: stopProc
    command: [
      (Quickshell.env("HOME") || "") + "/Projects/personal/omarchy-tv/bin/omarchy-tv",
      "stop"
    ]
  }

  Process {
    id: scanProc
    command: [
      (Quickshell.env("HOME") || "") + "/Projects/personal/omarchy-tv/bin/omarchy-tv",
      "scan"
    ]
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
    contentHeight: popup.fittedContentHeight(Math.min(Style.space(540), mainCol.implicitHeight + Style.space(24)))

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

      PanelSeparator {
        width: parent.width
        foreground: root.bar.foreground
      }

      // Channels List Title
      Text {
        textFormat: Text.PlainText
        text: "CHANNEL GUIDE"
        color: Qt.darker(root.bar.foreground, 1.6)
        font.family: root.bar.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
      }

      // Empty State
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

      // Channel List Items
      Column {
        id: channelListView
        visible: root.channelsData.length > 0
        width: parent.width
        spacing: Style.space(4)

        Repeater {
          model: root.channelsData

          BorderSurface {
            id: chItem
            required property var modelData
            readonly property bool isCurrent: root.activeChannelName === modelData.name

            width: channelListView.width
            height: Style.space(42)
            radius: Style.spacing.labelGap
            color: isCurrent ? Style.selectedFillFor(root.bar.foreground, Color.accent) : "transparent"
            borderSpec: isCurrent ? Border.controlSpec("normal", root.bar.foreground, Color.accent) : Border.none()

            Row {
              anchors.left: parent.left
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              anchors.leftMargin: Style.space(10)
              anchors.rightMargin: Style.space(10)
              spacing: Style.space(10)

              Text {
                textFormat: Text.PlainText
                text: chItem.isCurrent ? "󰐊" : "󰢹"
                color: chItem.isCurrent ? Color.accent : Qt.darker(root.bar.foreground, 1.5)
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.body
                anchors.verticalCenter: parent.verticalCenter
              }

              Column {
                width: parent.width - Style.space(90)
                spacing: Style.space(1)
                anchors.verticalCenter: parent.verticalCenter

                Text {
                  textFormat: Text.PlainText
                  text: Model.cleanChannelName(chItem.modelData.name)
                  color: root.bar.foreground
                  font.family: root.bar.fontFamily
                  font.pixelSize: Style.font.bodySmall
                  font.bold: chItem.isCurrent
                  elide: Text.ElideRight
                  width: parent.width
                }

                Text {
                  textFormat: Text.PlainText
                  text: Model.formatFreq(chItem.modelData.frequency) + (chItem.modelData.band ? (" · " + chItem.modelData.band) : "")
                  color: Qt.darker(root.bar.foreground, 1.6)
                  font.family: root.bar.fontFamily
                  font.pixelSize: Style.font.caption
                }
              }

              BorderSurface {
                width: Style.space(48)
                height: Style.space(22)
                radius: Style.spacing.labelGap
                color: Style.normalFillFor(root.bar.foreground, Color.accent)
                anchors.verticalCenter: parent.verticalCenter

                Text {
                  anchors.centerIn: parent
                  textFormat: Text.PlainText
                  text: chItem.modelData.service_id ? ("#" + chItem.modelData.service_id) : "OTA"
                  color: Qt.darker(root.bar.foreground, 1.3)
                  font.family: root.bar.fontFamily
                  font.pixelSize: Style.font.caption
                }
              }
            }

            MouseArea {
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: root.playChannel(chItem.modelData.name)
            }
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
