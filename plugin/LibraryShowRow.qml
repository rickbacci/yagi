import QtQuick
import qs.Ui
import qs.Commons

CursorSurface {
  id: showRow
  required property var tv
  property var show: ({})
  property string line: ""
  property int recIndex: -1

  height: Math.max(Style.space(64), showInfo.implicitHeight + Style.space(16))
  foreground: showRow.tv.bar.foreground
  accent: Color.accent
  hasCursor: showRow.tv.libraryModalOpen && showRow.tv.cursorActive && showRow.tv.recCursorIndex === showRow.recIndex

  MouseArea {
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    onEntered: {
      showRow.tv.cursorActive = true
      showRow.tv.recCursorIndex = showRow.recIndex
    }
    onClicked: {
      showRow.tv.cursorActive = true
      showRow.tv.recCursorIndex = showRow.recIndex
      showRow.tv.openLibraryShow(showRow.show.key || "")
    }
  }

  Column {
    id: showInfo
    anchors.left: parent.left
    anchors.leftMargin: Style.space(8)
    anchors.right: parent.right
    anchors.rightMargin: Style.space(8)
    anchors.verticalCenter: parent.verticalCenter
    spacing: Style.space(2)

    Text {
      width: parent.width
      textFormat: Text.PlainText
      text: showRow.show.title || ""
      color: showRow.tv.bar.foreground
      font.family: showRow.tv.bar.fontFamily
      font.pixelSize: Style.font.heading
      font.bold: true
      elide: Text.ElideRight
    }

    Text {
      width: parent.width
      textFormat: Text.PlainText
      text: showRow.line
      color: Color.muted
      font.family: showRow.tv.bar.fontFamily
      font.pixelSize: Style.font.heading
      elide: Text.ElideRight
    }
  }
}
