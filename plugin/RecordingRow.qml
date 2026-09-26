import QtQuick
import qs.Ui
import qs.Commons

CursorSurface {
  id: recRow
  required property var tv
  required property var modelData
  required property int index

  height: Style.space(52)
  foreground: recRow.tv.bar.foreground
  accent: Color.accent
  hasCursor: recRow.tv.libraryModalOpen && recRow.tv.cursorActive && recRow.tv.recCursorIndex === index

  MouseArea {
    anchors.fill: parent
    anchors.rightMargin: Style.space(32)
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    onEntered: {
      recRow.tv.cursorActive = true
      recRow.tv.recCursorIndex = recRow.index
    }
    onClicked: recRow.tv.playRecording(recRow.modelData.path || recRow.modelData.name, recRow.modelData.playable)
  }

  Column {
    anchors.left: parent.left
    anchors.leftMargin: Style.space(6)
    anchors.right: recKeepBtn.left
    anchors.rightMargin: Style.space(8)
    anchors.verticalCenter: parent.verticalCenter
    spacing: Style.space(2)

    Text {
      textFormat: Text.PlainText
      text: recRow.modelData.title || recRow.modelData.name
      color: recRow.modelData.playable === false ? Color.muted : recRow.tv.bar.foreground
      font.family: recRow.tv.bar.fontFamily
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
        + (recRow.modelData.ads > 0 ? " · skips " + recRow.modelData.ads + (recRow.modelData.ads === 1 ? " ad break" : " ad breaks") : "")
        + (recRow.modelData.playable === false ? " · nothing recorded" : "")
      color: Color.muted
      font.family: recRow.tv.bar.fontFamily
      font.pixelSize: Style.font.caption
      elide: Text.ElideRight
      width: parent.width
    }
  }

  PanelActionButton {
    id: recKeepBtn
    anchors.right: recDeleteBtn.left
    anchors.rightMargin: Style.space(2)
    anchors.verticalCenter: parent.verticalCenter
    iconText: recRow.modelData.keep ? "\uf023" : "\uf09c"
    tooltipText: recRow.modelData.keep ? "Locked. The size limit won't delete it. Click to unlock" : "Lock it so the size limit never deletes it"
    foreground: recRow.modelData.keep ? Color.accent : Color.muted
    hoverColor: recRow.tv.bar.foreground
    fontFamily: recRow.tv.bar.fontFamily
    onClicked: recRow.tv.setRecordingKept(recRow.modelData, !recRow.modelData.keep)
  }

  PanelActionButton {
    id: recDeleteBtn
    anchors.right: parent.right
    anchors.rightMargin: Style.space(2)
    anchors.verticalCenter: parent.verticalCenter
    readonly property bool armed: recRow.tv.deleteArmed === (recRow.modelData.path || recRow.modelData.name)
    iconText: "󰅙"
    tooltipText: armed ? "Click again to delete" : "Delete"
    foreground: armed ? Color.urgent : recRow.tv.bar.foreground
    hoverColor: armed ? Color.urgent : recRow.tv.bar.foreground
    fontFamily: recRow.tv.bar.fontFamily
    onClicked: recRow.tv.deleteWithConfirm(recRow.modelData)
  }
}
