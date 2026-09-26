import QtQuick
import qs.Ui
import qs.Commons

BorderSurface {
  id: card
  required property var tv
  required property var modelData

  implicitHeight: recRow.implicitHeight + Style.space(12)
  radius: Style.spacing.labelGap
  color: Style.selectedFillFor(card.tv.bar.foreground, Color.urgent)
  borderSpec: Border.controlSpec("normal", card.tv.bar.foreground, Color.urgent)

  Item {
    id: recRow
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.top: parent.top
    anchors.margins: Style.space(6)
    implicitHeight: Math.max(recLine.implicitHeight, recStopBtn.implicitHeight)
    height: implicitHeight

    Button {
      id: recStopBtn
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      text: "Stop"
      tooltipText: "Stop this recording"
      foreground: Color.urgent
      fontSize: Style.font.caption
      onClicked: card.tv.toggleRecord(card.tv.recordingIdent(card.modelData))
    }

    Row {
      id: recLine
      anchors.left: parent.left
      anchors.right: recStopBtn.left
      anchors.rightMargin: Style.space(8)
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(4)

      Text {
        id: recChannel
        textFormat: Text.PlainText
        text: card.tv.recordingTitle(card.modelData)
        color: card.tv.bar.foreground
        font.family: card.tv.bar.fontFamily
        font.pixelSize: Style.font.bodySmall
        font.bold: true
        anchors.verticalCenter: parent.verticalCenter
      }

      Text {
        id: recDot
        visible: !!(card.modelData && card.modelData.program_title)
        textFormat: Text.PlainText
        text: "·"
        color: Color.accent
        font.family: card.tv.bar.fontFamily
        font.pixelSize: Style.font.bodySmall
        anchors.verticalCenter: parent.verticalCenter
      }

      Text {
        visible: !!(card.modelData && card.modelData.program_title)
        width: Math.max(0, recLine.width - recChannel.width - recDot.width - recLine.spacing * 2)
        textFormat: Text.PlainText
        text: card.modelData && card.modelData.program_title ? card.modelData.program_title : ""
        color: Color.urgent
        font.family: card.tv.bar.fontFamily
        font.pixelSize: Style.font.bodySmall
        elide: Text.ElideRight
        anchors.verticalCenter: parent.verticalCenter
      }
    }
  }
}
