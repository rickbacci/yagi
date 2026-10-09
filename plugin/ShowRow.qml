import QtQuick
import qs.Ui
import qs.Commons
import "Model.js" as Model

Item {
  id: showRow
  required property var tv
  required property var modelData
  required property int index

  readonly property bool ruled: !!showRow.tv.ruleIds[modelData.id]
  readonly property var airing: Model.showAiring(modelData)
  readonly property string oneState: showRow.tv.hitRecordState(airing)
  readonly property bool onNow: !!(airing && airing.on_now)
  readonly property bool willRecord: ruled || oneState !== ""

  implicitHeight: Math.max(showText.implicitHeight, showActions.implicitHeight) + Style.space(4)

  Rectangle {
    anchors.fill: parent
    visible: showRow.tv.cursorActive && showRow.tv.guideCursor === showRow.index
    radius: Style.spacing.labelGap
    color: Style.hoverFillFor(showRow.tv.bar.foreground, Color.accent)
  }

  Rectangle {
    visible: showRow.willRecord || showRow.onNow
    anchors.left: parent.left
    anchors.top: parent.top
    anchors.bottom: parent.bottom
    width: Style.space(3)
    color: showRow.willRecord ? Color.urgent : Color.accent
  }

  Column {
    id: showText
    anchors.left: parent.left
    anchors.leftMargin: Style.space(8)
    anchors.right: showActions.left
    anchors.rightMargin: Style.space(6)
    anchors.verticalCenter: parent.verticalCenter
    spacing: Style.space(1)

    Text {
      width: parent.width
      textFormat: Text.PlainText
      text: showRow.modelData.title || ""
      color: showRow.modelData.pattern || showRow.onNow || showRow.willRecord ? showRow.tv.bar.foreground : Color.muted
      font.family: showRow.tv.bar.fontFamily
      font.pixelSize: Style.font.heading
      font.bold: showRow.onNow || showRow.willRecord
      elide: Text.ElideRight
    }

    Text {
      width: parent.width
      textFormat: Text.PlainText
      text: Model.showSubLine(showRow.modelData, showRow.tv.stationFor(showRow.modelData.channel))
      color: Color.muted
      font.family: showRow.tv.bar.fontFamily
      font.pixelSize: Style.font.heading
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
      fontSize: Style.font.heading
      foreground: showRow.tv.bar.foreground
      onClicked: showRow.tv.selectChannel(showRow.modelData.tune_name)
    }

    Button {
      visible: !!showRow.airing && (!showRow.ruled || showRow.oneState !== "")
      text: showRow.ruled && showRow.oneState === "recording" ? "Stop this one"
            : showRow.ruled ? "Skip this one"
            : showRow.oneState === "recording" ? "Recording"
            : (showRow.oneState === "scheduled" ? "Scheduled" : "Record")
      tooltipText: showRow.ruled ? "Just this airing. The series keeps recording the rest"
            : showRow.oneState === "recording" ? "Stop this recording"
            : (showRow.oneState === "scheduled" ? "Don't record this"
            : (showRow.airing && showRow.airing.on_now ? "Record the rest of this one"
            : "Record the next one, " + ((showRow.modelData.next && showRow.modelData.next.day) || "") + " " + ((showRow.airing && showRow.airing.start) || "")))
      selected: showRow.oneState !== ""
      enabled: showRow.oneState !== "" || !(showRow.airing && showRow.airing.on_now) || showRow.tv.freeTunerForRecording()
      fontSize: Style.font.heading
      foreground: showRow.tv.bar.foreground
      onClicked: showRow.tv.toggleHitRecord(showRow.airing)
    }

    Button {
      visible: showRow.ruled
      text: showRow.tv.showLimitText(showRow.modelData)
      tooltipText: "How many episodes to keep. Older ones are deleted"
      fontSize: Style.font.heading
      foreground: showRow.tv.bar.foreground
      onClicked: showRow.tv.cycleShowLimit(showRow.modelData)
    }

    Button {
      text: showRow.ruled ? "Series on" : "Record series"
      tooltipText: showRow.ruled ? "Stop recording every airing" : "Record every airing on " + (showRow.modelData.channel || "this channel") + ", any time of day"
      selected: showRow.ruled
      enabled: showRow.ruled || !!showRow.modelData.tune_name
      fontSize: Style.font.heading
      foreground: showRow.tv.bar.foreground
      onClicked: showRow.tv.toggleRecordAll(showRow.modelData)
    }
  }
}
