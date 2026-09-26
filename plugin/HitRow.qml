import QtQuick
import qs.Ui
import qs.Commons

Item {
  id: hitRow
  required property var tv
  required property var modelData
  required property int index

  readonly property string recState: hitRow.tv.hitRecordState(modelData)
  readonly property bool ruled: hitRow.tv.hitRuleId(modelData) !== ""
  readonly property bool willRecord: ruled || recState !== ""

  implicitHeight: Math.max(hitText.implicitHeight, hitActions.implicitHeight) + Style.space(8)

  Rectangle {
    anchors.fill: parent
    visible: hitRow.tv.cursorActive && hitRow.tv.guideSearchActive && hitRow.tv.guideCursor === hitRow.index
    radius: Style.spacing.labelGap
    color: Style.hoverFillFor(hitRow.tv.bar.foreground, Color.accent)
  }

  Rectangle {
    visible: hitRow.willRecord || !!hitRow.modelData.on_now
    anchors.left: parent.left
    anchors.top: parent.top
    anchors.bottom: parent.bottom
    anchors.margins: Style.space(2)
    width: Style.space(3)
    color: hitRow.willRecord ? Color.urgent : Color.accent
  }

  Column {
    id: hitText
    anchors.left: parent.left
    anchors.leftMargin: Style.space(8)
    anchors.right: hitActions.left
    anchors.rightMargin: Style.space(6)
    anchors.verticalCenter: parent.verticalCenter
    spacing: Style.space(1)

    Text {
      width: parent.width
      textFormat: Text.PlainText
      text: (hitRow.modelData.title || "")
      color: hitRow.tv.bar.foreground
      font.family: hitRow.tv.bar.fontFamily
      font.pixelSize: Style.font.bodySmall
      font.bold: hitRow.willRecord || !!hitRow.modelData.on_now
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
      font.family: hitRow.tv.bar.fontFamily
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
      foreground: hitRow.tv.bar.foreground
      onClicked: hitRow.tv.selectChannel(hitRow.modelData.tune_name || hitRow.modelData.channel_number)
    }

    Button {
      visible: !hitRow.ruled || hitRow.recState !== ""
      text: hitRow.recState === "recording" ? "Recording"
            : (hitRow.recState === "scheduled" ? "Scheduled" : "Record")
      tooltipText: hitRow.recState === "recording" ? "Stop this recording"
            : (hitRow.recState === "scheduled" ? "Don't record this"
            : (hitRow.modelData.on_now ? "Record the rest of this show" : "Record this one when it airs"))
      selected: hitRow.recState !== ""
      enabled: hitRow.recState !== "" || !hitRow.modelData.on_now || hitRow.tv.freeTunerForRecording()
      fontSize: Style.font.caption
      foreground: hitRow.tv.bar.foreground
      onClicked: hitRow.tv.toggleHitRecord(hitRow.modelData)
    }

    Button {
      text: hitRow.ruled ? "Recording all" : "Record all"
      tooltipText: hitRow.ruled ? "Stop recording this show"
            : "Record every new airing on " + (hitRow.modelData.channel_number || "this channel") + ", any time of day"
      selected: hitRow.ruled
      enabled: hitRow.ruled || !!hitRow.modelData.tune_name
      fontSize: Style.font.caption
      foreground: hitRow.tv.bar.foreground
      onClicked: hitRow.tv.toggleHitRecordAll(hitRow.modelData)
    }
  }
}
