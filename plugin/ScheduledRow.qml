import QtQuick
import qs.Ui
import qs.Commons

CursorSurface {
  id: schedRow
  required property var tv
  property var row: ({})
  property int pickIndex: -1
  readonly property bool armed: schedRow.tv.deleteArmed === schedRow.row.key

  height: Style.space(52)
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
    anchors.left: parent.left
    anchors.leftMargin: Style.space(6)
    anchors.right: schedButtons.left
    anchors.rightMargin: Style.space(8)
    anchors.verticalCenter: parent.verticalCenter
    spacing: Style.space(2)

    Row {
      width: parent.width
      spacing: Style.space(6)

      Text {
        id: schedTitle
        textFormat: Text.PlainText
        text: schedRow.row.title || ""
        color: schedRow.tv.bar.foreground
        font.family: schedRow.tv.bar.fontFamily
        font.pixelSize: Style.font.bodySmall
        font.bold: true
        elide: Text.ElideRight
        width: Math.min(implicitWidth, parent.width - (seriesTag.visible ? seriesTag.width + parent.spacing : 0))
      }

      Rectangle {
        id: seriesTag
        visible: !!schedRow.row.series
        anchors.verticalCenter: schedTitle.verticalCenter
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
          font.family: schedRow.tv.bar.fontFamily
          font.pixelSize: Style.font.caption
        }
      }
    }

    Text {
      textFormat: Text.PlainText
      text: schedRow.row.line || ""
      color: schedRow.row.live || schedRow.row.missed ? Color.urgent : Color.muted
      font.family: schedRow.tv.bar.fontFamily
      font.pixelSize: Style.font.caption
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
      fontSize: Style.font.caption
      foreground: schedRow.tv.bar.foreground
      onClicked: schedRow.tv.cycleShowLimit({ id: schedRow.row.item.id })
    }

    Button {
      text: schedRow.armed ? "Sure?" : (schedRow.row.kind === "waiting" ? "Remove" : "Stop")
      tooltipText: schedRow.row.kind === "active" ? "Stop this recording. What is recorded so far stays"
                   : schedRow.row.kind === "series" ? "Stop recording this series. Its recordings stay"
                   : "Don't record this"
      fontSize: Style.font.caption
      foreground: schedRow.armed ? Color.urgent : schedRow.tv.bar.foreground
      onClicked: {
        schedRow.tv.deleteArmed = schedRow.row.key
        schedRow.tv.dropScheduled(schedRow.row)
      }
    }
  }
}
