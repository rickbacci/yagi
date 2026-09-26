import QtQuick
import qs.Ui
import qs.Commons

BorderSurface {
  id: card
  required property var tv

  visible: card.tv.pendingWatch !== ""
  implicitHeight: bothBusyCol.implicitHeight + Style.space(12)
  radius: Style.spacing.labelGap
  color: Style.selectedFillFor(card.tv.bar.foreground, Color.urgent)
  borderSpec: Border.controlSpec("normal", card.tv.bar.foreground, Color.urgent)

  Column {
    id: bothBusyCol
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.top: parent.top
    anchors.margins: Style.space(6)
    spacing: Style.space(6)

    Text {
      width: parent.width
      textFormat: Text.PlainText
      text: "Both tuners are recording. Stop one to watch " + card.tv.getActiveDisplayNameFor(card.tv.pendingWatch) + "?"
      color: card.tv.bar.foreground
      font.family: card.tv.bar.fontFamily
      font.pixelSize: Style.font.bodySmall
      font.bold: true
      wrapMode: Text.Wrap
    }

    Flow {
      width: parent.width
      spacing: Style.space(6)

      Repeater {
        model: card.tv.activeRecordings
        delegate: Button {
          id: stopBtn
          required property var modelData
          text: "Stop " + (stopBtn.modelData.program_title || card.tv.recordingTitle(stopBtn.modelData))
          tooltipText: "Stop this recording and watch. What it recorded so far is kept"
          fontSize: Style.font.caption
          foreground: Color.urgent
          onClicked: card.tv.stopToWatch(stopBtn.modelData)
        }
      }

      Button {
        text: "Keep recording"
        tooltipText: "Don't watch right now"
        fontSize: Style.font.caption
        foreground: card.tv.bar.foreground
        onClicked: card.tv.pendingWatch = ""
      }
    }
  }
}
