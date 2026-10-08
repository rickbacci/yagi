import QtQuick
import qs.Ui
import qs.Commons
import "Model.js" as Model

CursorSurface {
  id: recRow
  required property var tv
  property var rec: ({})
  property int recIndex: -1
  property string titleText: ""
  property string detailText: ""
  property string blurb: ""
  readonly property bool live: Model.recordingLive(recRow.rec)
  readonly property bool actions: !recRow.live

  height: Math.max(Style.space(64), recInfo.implicitHeight + Style.space(16))
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
    anchors.left: parent.left
    anchors.top: parent.top
    anchors.bottom: parent.bottom
    anchors.right: recRow.actions ? recKeepBtn.left : parent.right
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    onEntered: {
      recRow.tv.cursorActive = true
      recRow.tv.recCursorIndex = recRow.recIndex
    }
    onClicked: recRow.tv.playRecording(recRow.rec.path || recRow.rec.name, recRow.rec.playable)
  }

  Column {
    id: recInfo
    anchors.left: parent.left
    anchors.leftMargin: Style.space(8)
    anchors.right: recRow.actions ? recKeepBtn.left : parent.right
    anchors.rightMargin: Style.space(8)
    anchors.verticalCenter: parent.verticalCenter
    spacing: Style.space(2)

    Text {
      width: parent.width
      textFormat: Text.PlainText
      text: recRow.titleText
      color: recRow.rec.playable === false && !recRow.live ? Color.muted : recRow.tv.bar.foreground
      font.family: recRow.tv.bar.fontFamily
      font.pixelSize: Style.font.heading
      font.bold: true
      elide: Text.ElideRight
    }

    Text {
      width: parent.width
      textFormat: Text.PlainText
      text: recRow.detailText
      color: recRow.live ? Color.urgent : Color.muted
      font.family: recRow.tv.bar.fontFamily
      font.pixelSize: Style.font.title
      elide: Text.ElideRight
    }

    Text {
      visible: recRow.blurb !== ""
      width: parent.width
      textFormat: Text.PlainText
      text: recRow.blurb
      color: Color.muted
      font.family: recRow.tv.bar.fontFamily
      font.pixelSize: Style.font.title
      wrapMode: Text.Wrap
      maximumLineCount: 3
      elide: Text.ElideRight
    }
  }

  PanelActionButton {
    id: recKeepBtn
    visible: recRow.actions
    anchors.right: recDeleteBtn.left
    anchors.rightMargin: Style.space(2)
    anchors.verticalCenter: parent.verticalCenter
    fontSize: Style.font.heading
    iconText: recRow.rec.keep ? "\uf023" : "\uf09c"
    tooltipText: recRow.rec.keep ? "Locked. The size limit won't delete it. Click to unlock" : "Lock it so the size limit never deletes it"
    foreground: recRow.rec.keep ? Color.accent : Color.muted
    hoverColor: recRow.tv.bar.foreground
    fontFamily: recRow.tv.bar.fontFamily
    onClicked: recRow.tv.setRecordingKept(recRow.rec, !recRow.rec.keep)
  }

  PanelActionButton {
    id: recDeleteBtn
    visible: recRow.actions
    anchors.right: parent.right
    anchors.rightMargin: Style.space(2)
    anchors.verticalCenter: parent.verticalCenter
    readonly property bool armed: recRow.tv.deleteArmed === (recRow.rec.path || recRow.rec.name)
    fontSize: Style.font.heading
    iconText: "󰅙"
    tooltipText: armed ? "Click again to delete" : "Delete"
    foreground: armed ? Color.urgent : recRow.tv.bar.foreground
    hoverColor: armed ? Color.urgent : recRow.tv.bar.foreground
    fontFamily: recRow.tv.bar.fontFamily
    onClicked: recRow.tv.deleteWithConfirm(recRow.rec)
  }
}
