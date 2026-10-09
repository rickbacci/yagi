import QtQuick
import qs.Ui
import qs.Commons

Item {
  id: empty
  required property var tv
  property string title: ""
  property string detail: ""
  property bool titleBold: false
  property real gap: Style.space(8)
  property string actionIcon: ""
  property string actionText: ""
  signal action()

  Column {
    anchors.centerIn: parent
    spacing: empty.gap

    Text {
      anchors.horizontalCenter: parent.horizontalCenter
      text: empty.title
      color: Color.muted
      font.family: empty.tv.bar.fontFamily
      font.pixelSize: Style.font.heading
      font.bold: empty.titleBold
    }

    Text {
      anchors.horizontalCenter: parent.horizontalCenter
      text: empty.detail
      color: Color.muted
      font.family: empty.tv.bar.fontFamily
      font.pixelSize: Style.font.heading
    }

    Button {
      visible: empty.actionText !== ""
      anchors.horizontalCenter: parent.horizontalCenter
      iconText: empty.actionIcon
      text: empty.actionText
      foreground: empty.tv.bar.foreground
      onClicked: empty.action()
    }
  }
}
