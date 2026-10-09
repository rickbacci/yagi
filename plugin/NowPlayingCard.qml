import QtQuick
import qs.Ui
import qs.Commons
import "Model.js" as Model

BorderSurface {
  id: card
  required property var tv

  readonly property var activeProg: card.tv.getActiveProgram()
  readonly property var onNow: activeProg ? Model.currentProgram(activeProg, card.tv.guideClockMin) : null
  readonly property string showLine: {
    if (card.tv.tuning) return card.tv.tuneSnr
    var same = card.tv.tuneDisplay === card.tv.getActiveDisplayName() || card.tv.tuneName === card.tv.activeChannelName
    if (card.tv.tunePhase === "failed" && card.tv.tuneMessage && same) return card.tv.tuneMessage
    return (onNow && onNow.title) ? onNow.title : ""
  }
  property bool tuneHot: false

  visible: card.tv.activeChannelName !== ""
  implicitHeight: watchRow.implicitHeight + Style.space(12)
  radius: Style.spacing.labelGap
  color: tuneHot
    ? Style.hoverFillFor(card.tv.bar.foreground, Color.accent)
    : Style.selectedFillFor(card.tv.bar.foreground, Color.accent)
  borderSpec: Border.controlSpec("normal", card.tv.bar.foreground, Color.accent)

  MouseArea {
    id: tuneAgainArea
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    onEntered: card.tuneHot = true
    onExited: card.tuneHot = false
    onClicked: card.tv.playChannel(card.tv.activeChannelName)
    PanelToolTip {
      visible: tuneAgainArea.containsMouse
      text: "Click to retune this channel"
      fontFamily: card.tv.bar.fontFamily
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
        visible: card.tv.isLiveSession && !card.tv.pauseKept
        text: "Save"
        tooltipText: "Save what you paused to Recordings"
        foreground: card.tv.bar.foreground
        fontSize: Style.font.heading
        onClicked: card.tv.keepPause()
      }

      Button {
        id: npCloseBtn
        text: "Close"
        tooltipText: "Close TV and drop the pause"
        foreground: card.tv.bar.foreground
        fontSize: Style.font.heading
        onClicked: card.tv.stopPlayer()
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
        text: card.tv.getActiveDisplayName()
        color: card.tv.bar.foreground
        font.family: card.tv.bar.fontFamily
        font.pixelSize: Style.font.heading
        font.bold: true
        anchors.verticalCenter: parent.verticalCenter
      }

      Text {
        id: watchDot
        visible: card.showLine !== ""
        textFormat: Text.PlainText
        text: "·"
        color: Color.accent
        font.family: card.tv.bar.fontFamily
        font.pixelSize: Style.font.heading
        anchors.verticalCenter: parent.verticalCenter
      }

      Text {
        visible: card.showLine !== ""
        width: Math.max(0, watchLine.width - watchChannel.width - watchDot.width - watchLine.spacing * 2)
        textFormat: Text.PlainText
        text: card.showLine
        color: (!card.tv.tuning && card.tv.tunePhase === "failed" && card.showLine === card.tv.tuneMessage) ? Color.urgent : Color.accent
        font.family: card.tv.bar.fontFamily
        font.pixelSize: Style.font.heading
        elide: Text.ElideRight
        anchors.verticalCenter: parent.verticalCenter
      }
    }
  }
}
