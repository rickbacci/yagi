import QtQuick
import qs.Ui
import qs.Commons

// One accent line: the Guide updating, or shows waiting to record.
BorderSurface {
  id: card
  required property var tv
  property string message: ""
  property bool clickable: false
  signal clicked()

  visible: card.message !== ""
  implicitHeight: statusRow.implicitHeight + Style.space(12)
  radius: Style.spacing.labelGap
  color: Style.selectedFillFor(card.tv.bar.foreground, Color.accent)
  borderSpec: Border.controlSpec("normal", card.tv.bar.foreground, Color.accent)

  Item {
    id: statusRow
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.top: parent.top
    anchors.margins: Style.space(6)
    implicitHeight: statusLine.implicitHeight
    height: implicitHeight

    MouseArea {
      anchors.fill: parent
      enabled: card.clickable
      onClicked: card.clicked()
    }

    Text {
      id: statusLine
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      textFormat: Text.PlainText
      text: card.message
      color: Color.accent
      font.family: card.tv.bar.fontFamily
      font.pixelSize: Style.font.bodySmall
      font.bold: true
      elide: Text.ElideRight
    }
  }
}
