import QtQuick
import qs.Ui
import qs.Commons

CursorSurface {
  id: schedRow
  required property var tv
  property var row: ({})
  property int pickIndex: -1
  readonly property bool armed: schedRow.tv.deleteArmed === schedRow.row.key

  height: Math.max(Style.space(64), schedInfo.implicitHeight + Style.space(16))
  foreground: schedRow.tv.bar.foreground
  accent: Color.accent
  hasCursor: schedRow.tv.libraryModalOpen && schedRow.tv.cursorActive && schedRow.tv.schedCursorIndex === schedRow.pickIndex

  MouseArea {
    anchors.fill: parent
    hoverEnabled: true
    onEntered: {
      schedRow.tv.cursorActive = true
      schedRow.tv.schedCursorIndex = schedRow.pickIndex
    }
  }

  Column {
    id: schedInfo
    anchors.left: parent.left
    anchors.leftMargin: Style.space(8)
    anchors.right: schedButtons.left
    anchors.rightMargin: Style.space(8)
    anchors.verticalCenter: parent.verticalCenter
    spacing: Style.space(2)

    Item {
      width: parent.width
      implicitHeight: Math.max(schedTitle.implicitHeight, seriesTag.implicitHeight)
      height: implicitHeight

      Text {
        id: schedTitle
        anchors.left: parent.left
        anchors.right: seriesTag.visible ? seriesTag.left : parent.right
        anchors.rightMargin: seriesTag.visible ? Style.space(6) : 0
        textFormat: Text.PlainText
        text: schedRow.row.title || ""
        color: schedRow.tv.bar.foreground
        font.family: schedRow.tv.bar.fontFamily
        font.pixelSize: Style.font.heading
        font.bold: true
        elide: Text.ElideRight
      }

      Rectangle {
        id: seriesTag
        visible: !!schedRow.row.series
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        width: seriesText.implicitWidth + Style.space(10)
        height: seriesText.implicitHeight + Style.space(4)
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
          font.family: schedRow.tv.bar.fontFamily
          font.pixelSize: Style.font.heading
        }
      }
    }

    Text {
      textFormat: Text.PlainText
      text: schedRow.row.line || ""
      color: schedRow.row.live || schedRow.row.missed ? Color.urgent : Color.muted
      font.family: schedRow.tv.bar.fontFamily
      font.pixelSize: Style.font.heading
      elide: Text.ElideRight
      width: parent.width
    }
  }

  Row {
    id: schedButtons
    anchors.right: parent.right
    anchors.rightMargin: Style.space(4)
    anchors.verticalCenter: parent.verticalCenter
    spacing: Style.space(6)

    Button {
      visible: schedRow.row.kind === "series"
      text: schedRow.tv.showLimitText({ id: schedRow.row.item ? schedRow.row.item.id : "" })
      tooltipText: "How many episodes to keep. Older ones are deleted as new ones record. Click to change"
      fontSize: Style.font.heading
      foreground: schedRow.tv.bar.foreground
      onClicked: schedRow.tv.cycleShowLimit({ id: schedRow.row.item.id })
    }

    Button {
      text: schedRow.armed ? "Sure?" : (schedRow.row.kind === "waiting" ? "Remove" : "Stop")
      tooltipText: schedRow.row.kind === "active" ? "Stop this recording. What is recorded so far stays"
                   : schedRow.row.kind === "series" ? "Stop recording this series. Its recordings stay"
                   : "Don't record this"
      fontSize: Style.font.heading
      foreground: schedRow.armed ? Color.urgent : schedRow.tv.bar.foreground
      onClicked: {
        schedRow.tv.deleteArmed = schedRow.row.key
        schedRow.tv.dropScheduled(schedRow.row)
      }
    }
  }
}
