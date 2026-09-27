import QtQuick
import qs.Ui
import qs.Commons
import "Model.js" as Model

CursorSurface {
  id: recRow
  required property var tv
  property var rec: ({})
  property int recIndex: -1
  readonly property bool live: Model.recordingLive(recRow.rec)

  height: Style.space(52)
  foreground: recRow.tv.bar.foreground
  accent: Color.accent
  hasCursor: recRow.tv.libraryModalOpen && recRow.tv.cursorActive && recRow.tv.recCursorIndex === recRow.recIndex

  Rectangle {
    visible: recRow.live
    anchors.fill: parent
    radius: recRow.radius
    color: Style.selectedFillFor(recRow.tv.bar.foreground, Color.urgent)
  }

  MouseArea {
    anchors.fill: parent
    anchors.rightMargin: recRow.live ? 0 : Style.space(64)
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    onEntered: {
      recRow.tv.cursorActive = true
      recRow.tv.recCursorIndex = recRow.recIndex
    }
    onClicked: recRow.tv.playRecording(recRow.rec.path || recRow.rec.name, recRow.rec.playable)
  }

  Column {
    anchors.left: parent.left
    anchors.leftMargin: Style.space(6)
    anchors.right: recRow.live ? parent.right : recKeepBtn.left
    anchors.rightMargin: Style.space(8)
    anchors.verticalCenter: parent.verticalCenter
    spacing: Style.space(2)

    Row {
      width: parent.width
      spacing: Style.space(6)

      Text {
        id: recTitle
        textFormat: Text.PlainText
        text: recRow.rec.title || recRow.rec.name || ""
        color: recRow.rec.playable === false && !recRow.live ? Color.muted : recRow.tv.bar.foreground
        font.family: recRow.tv.bar.fontFamily
        font.pixelSize: Style.font.bodySmall
        font.bold: true
        elide: Text.ElideRight
        width: Math.min(implicitWidth, parent.width - (seriesTag.visible ? seriesTag.width + parent.spacing : 0))
      }

      Rectangle {
        id: seriesTag
        visible: !!recRow.rec.rule_id
        anchors.verticalCenter: recTitle.verticalCenter
        width: seriesText.implicitWidth + Style.space(10)
        height: seriesText.implicitHeight + Style.space(2)
        radius: Style.spacing.xs
        color: "transparent"
        border.width: 1
        border.color: Color.muted

        Text {
          id: seriesText
          anchors.centerIn: parent
          textFormat: Text.PlainText
          text: "series"
          color: Color.muted
          font.family: recRow.tv.bar.fontFamily
          font.pixelSize: Style.font.caption
        }
      }
    }

    Text {
      textFormat: Text.PlainText
      text: Model.recordingLine(recRow.rec, recRow.tv.gridNow)
      color: recRow.live ? Color.urgent : Color.muted
      font.family: recRow.tv.bar.fontFamily
      font.pixelSize: Style.font.caption
      elide: Text.ElideRight
      width: parent.width
    }
  }

  PanelActionButton {
    id: recKeepBtn
    visible: !recRow.live
    anchors.right: recDeleteBtn.left
    anchors.rightMargin: Style.space(2)
    anchors.verticalCenter: parent.verticalCenter
    iconText: recRow.rec.keep ? "\uf023" : "\uf09c"
    tooltipText: recRow.rec.keep ? "Locked. The size limit won't delete it. Click to unlock" : "Lock it so the size limit never deletes it"
    foreground: recRow.rec.keep ? Color.accent : Color.muted
    hoverColor: recRow.tv.bar.foreground
    fontFamily: recRow.tv.bar.fontFamily
    onClicked: recRow.tv.setRecordingKept(recRow.rec, !recRow.rec.keep)
  }

  PanelActionButton {
    id: recDeleteBtn
    visible: !recRow.live
    anchors.right: parent.right
    anchors.rightMargin: Style.space(2)
    anchors.verticalCenter: parent.verticalCenter
    readonly property bool armed: recRow.tv.deleteArmed === (recRow.rec.path || recRow.rec.name)
    iconText: "󰅙"
    tooltipText: armed ? "Click again to delete" : "Delete"
    foreground: armed ? Color.urgent : recRow.tv.bar.foreground
    hoverColor: armed ? Color.urgent : recRow.tv.bar.foreground
    fontFamily: recRow.tv.bar.fontFamily
    onClicked: recRow.tv.deleteWithConfirm(recRow.rec)
  }
}
