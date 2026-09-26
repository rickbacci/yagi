import QtQuick
import qs.Ui
import qs.Commons
import "Model.js" as Model

CursorSurface {
  id: chItem
  required property var tv
  required property var modelData
  required property int index

  readonly property bool isCurrent: chItem.tv.activeChannelName === modelData.channel_number || chItem.tv.activeChannelName === modelData.name || chItem.tv.activeChannelName === modelData.tune_name
  readonly property var program: chItem.tv.getProgram(modelData)
  readonly property var onNow: Model.currentProgram(program, chItem.tv.guideClockMin)
  readonly property var onNext: Model.nextProgram(program, chItem.tv.guideClockMin)
  readonly property real progress: Model.airingProgress(chItem.onNow, chItem.tv.guideClockMin)
  readonly property string stationName: Model.getDisplayTitle(modelData)
  readonly property string channelBadge: Model.getChannelBadge(modelData)
  readonly property bool isRecordingHere: chItem.tv.isChannelRecording(modelData.tune_name || modelData.channel_number)
  readonly property bool isFav: chItem.tv.isFavorite(modelData.name) || (modelData.tune_name && chItem.tv.isFavorite(modelData.tune_name))
  readonly property bool hiddenView: chItem.tv.channelFilter === "hidden" || chItem.tv.channelIsHidden(chItem.modelData)

  height: Math.max(Style.space(36), chLine.implicitHeight + Style.space(12))
  foreground: chItem.tv.bar.foreground
  accent: Color.accent
  hasCursor: chItem.tv.cursorActive && chItem.tv.cursorIndex === index
  current: isCurrent

  Rectangle {
    visible: chItem.isRecordingHere || (chItem.tv.liveOn && chItem.isCurrent)
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
      chItem.tv.cursorActive = true
      chItem.tv.cursorIndex = chItem.index
    }
    onClicked: chItem.tv.useListedChannel(chItem.tv.listedKey(chItem.modelData))
    onWheel: function(wheel) { wheel.accepted = false }
  }

  Button {
    id: hideBtn
    visible: chItem.tv.channelFilter === "all" || chItem.tv.channelFilter === "hidden"
    anchors.right: parent.right
    anchors.rightMargin: Style.space(4)
    anchors.verticalCenter: parent.verticalCenter
    text: chItem.hiddenView ? "Show" : "Hide"
    tooltipText: chItem.hiddenView ? "Put this station back" : "Set this station aside"
    fontSize: Style.font.caption
    foreground: chItem.tv.bar.foreground
    onClicked: {
      if (chItem.hiddenView) chItem.tv.showListed(chItem.modelData)
      else chItem.tv.hideListed(chItem.modelData)
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
    fontFamily: chItem.tv.bar.fontFamily
    onClicked: chItem.tv.toggleFavorite(chItem.modelData.tune_name || chItem.modelData.name)
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
        color: chItem.isCurrent ? Color.accent : chItem.tv.bar.foreground
        font.family: chItem.tv.bar.fontFamily
        font.pixelSize: Style.font.bodySmall
        font.bold: true
        width: Math.max(implicitWidth, Style.space(40))
      }

      Text {
        width: Math.max(0, chLine.width - chLine.textX)
        textFormat: Text.PlainText
        text: chItem.onNow && chItem.onNow.title ? chItem.onNow.title : chItem.stationName
        color: chItem.isCurrent ? Color.accent : chItem.tv.bar.foreground
        font.family: chItem.tv.bar.fontFamily
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
      color: Style.normalFillFor(chItem.tv.bar.foreground, Color.accent)

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
      font.family: chItem.tv.bar.fontFamily
      font.pixelSize: Style.font.caption
      elide: Text.ElideRight
    }
  }
}
