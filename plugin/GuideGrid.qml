import QtQuick
import qs.Ui
import qs.Commons
import "Model.js" as Model

// Channels down, half hours across from the half hour now is in. The channel
// column and the time header follow the body's scroll.
Item {
  id: grid
  required property var tv

  readonly property real chanWidth: Style.space(150)
  readonly property real headHeight: Style.space(26)
  readonly property real rowHeight: Style.space(44)
  readonly property int visibleSlots: 6
  readonly property real slotWidth: Math.max(Style.space(90), (width - chanWidth) / visibleSlots)
  readonly property real t0: grid.tv.gridStart
  readonly property real t1: grid.tv.gridEnd
  readonly property var rows: grid.tv.gridRows
  readonly property int slots: Math.max(1, Math.ceil((t1 - t0) / 1800))
  readonly property color fg: grid.tv.bar.foreground

  function xOf(unix) {
    return (unix - grid.t0) / 1800 * grid.slotWidth
  }

  function reveal(r, block) {
    if (!block) return
    var x = grid.xOf(block.x0)
    var w = Math.min(grid.xOf(block.x1) - x, body.width)
    var y = r * grid.rowHeight
    if (x < body.contentX) body.contentX = Math.max(0, x)
    else if (x + w > body.contentX + body.width) body.contentX = Math.min(Math.max(0, body.contentWidth - body.width), x + w - body.width)
    if (y < body.contentY) body.contentY = y
    else if (y + grid.rowHeight > body.contentY + body.height) body.contentY = y + grid.rowHeight - body.height
  }

  Rectangle {
    x: grid.chanWidth
    width: grid.width - grid.chanWidth
    height: grid.headHeight
    radius: Style.spacing.labelGap
    color: Style.normalFillFor(grid.fg, Color.accent)
  }

  Flickable {
    id: header
    x: grid.chanWidth
    width: grid.width - grid.chanWidth
    height: grid.headHeight
    contentWidth: body.contentWidth
    contentHeight: height
    contentX: body.contentX
    interactive: false
    clip: true

    Repeater {
      model: grid.slots
      delegate: Text {
        required property int index
        x: index * grid.slotWidth + Style.space(8)
        y: (grid.headHeight - implicitHeight) / 2
        textFormat: Text.PlainText
        text: Model.formatClock(grid.t0 + index * 1800)
        color: Color.muted
        font.family: grid.tv.bar.fontFamily
        font.pixelSize: Style.font.caption
      }
    }

    Rectangle {
      readonly property real at: grid.xOf(grid.tv.gridNow)
      visible: at >= 0
      x: at - width / 2
      y: (grid.headHeight - height) / 2
      width: nowText.implicitWidth + Style.space(10)
      height: nowText.implicitHeight + Style.space(2)
      radius: Style.space(4)
      color: Color.accent

      Text {
        id: nowText
        anchors.centerIn: parent
        textFormat: Text.PlainText
        text: "now"
        color: Color.popups.background
        font.family: grid.tv.bar.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
      }
    }
  }

  Flickable {
    id: chans
    y: grid.headHeight
    width: grid.chanWidth
    height: grid.height - grid.headHeight
    contentHeight: body.contentHeight
    contentY: body.contentY
    interactive: false
    clip: true

    Repeater {
      model: grid.rows
      delegate: Item {
        id: chanRow
        required property var modelData
        required property int index
        y: index * grid.rowHeight
        width: grid.chanWidth
        height: grid.rowHeight

        Row {
          x: Style.space(6)
          y: Style.space(6)
          spacing: Style.space(6)

          Text {
            textFormat: Text.PlainText
            text: chanRow.modelData.channel.channel_number || ""
            color: grid.fg
            font.family: grid.tv.bar.fontFamily
            font.pixelSize: Style.font.bodySmall
            font.bold: true
          }

          Text {
            visible: chanRow.modelData.outside
            textFormat: Text.PlainText
            text: grid.tv.channelFilter === "favorites" ? "not a favorite" : "not in this list"
            color: Color.accent
            font.family: grid.tv.bar.fontFamily
            font.pixelSize: Style.font.caption
            anchors.verticalCenter: parent.verticalCenter
          }
        }

        Text {
          x: Style.space(6)
          y: Style.space(24)
          width: grid.chanWidth - Style.space(12)
          textFormat: Text.PlainText
          text: Model.getDisplayTitle(chanRow.modelData.channel)
          color: Color.muted
          font.family: grid.tv.bar.fontFamily
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }
      }
    }
  }

  Flickable {
    id: body
    x: grid.chanWidth
    y: grid.headHeight
    width: grid.width - grid.chanWidth
    height: grid.height - grid.headHeight
    contentWidth: grid.xOf(grid.t1)
    contentHeight: grid.rows.length * grid.rowHeight
    boundsBehavior: Flickable.StopAtBounds
    clip: true

    Repeater {
      model: grid.slots
      delegate: Rectangle {
        required property int index
        x: index * grid.slotWidth
        width: 1
        height: body.contentHeight
        color: Style.normalFillFor(grid.fg, Color.accent)
      }
    }

    Repeater {
      model: grid.rows
      delegate: Item {
        id: rowItem
        required property var modelData
        required property int index
        y: index * grid.rowHeight
        width: body.contentWidth
        height: grid.rowHeight

        Repeater {
          model: rowItem.modelData.blocks
          delegate: GridBlock {
            row: rowItem.index
          }
        }
      }
    }

    Rectangle {
      readonly property real at: grid.xOf(grid.tv.gridNow)
      visible: at >= 0
      x: at - 1
      width: 2
      height: body.contentHeight
      color: Color.accent
    }
  }

  component GridBlock: Rectangle {
    id: cell
    required property var modelData
    required property int index
    property int row: 0
    readonly property var airing: Model.blockAiring(modelData)
    readonly property bool willRecord: grid.tv.hitRecordState(airing) !== "" || grid.tv.hitRuleId(airing) !== ""
    readonly property bool isCursor: grid.tv.cursorActive && grid.tv.gridRow === row && grid.tv.gridCol === index
    readonly property bool searching: grid.tv.guideSearchActive

    x: grid.xOf(modelData.x0) + 2
    y: 3
    width: Math.max(4, grid.xOf(modelData.x1) - grid.xOf(modelData.x0) - 4)
    height: grid.rowHeight - 6
    radius: Style.spacing.labelGap
    color: isCursor ? Style.selectedFillFor(grid.fg, Color.accent) : Style.normalFillFor(grid.fg, Color.accent)
    border.width: isCursor || (searching && modelData.match) ? 1 : 0
    border.color: Color.accent
    opacity: searching && !modelData.match ? 0.3 : 1

    Rectangle {
      visible: cell.willRecord || cell.modelData.on_now
      width: 3
      height: parent.height
      radius: 1.5
      color: cell.willRecord ? Color.urgent : Color.accent
    }

    Text {
      x: Style.space(8)
      y: Style.space(4)
      width: parent.width - Style.space(12)
      textFormat: Text.PlainText
      text: (cell.modelData.began_before ? "‹ " : "") + cell.modelData.title
      color: cell.modelData.on_now || cell.isCursor ? grid.fg : Color.muted
      font.family: grid.tv.bar.fontFamily
      font.pixelSize: Style.font.bodySmall
      font.bold: cell.modelData.on_now || cell.isCursor
      elide: Text.ElideRight
    }

    Text {
      visible: parent.width > Style.space(70)
      x: Style.space(8)
      y: Style.space(21)
      width: parent.width - Style.space(12)
      textFormat: Text.PlainText
      text: cell.modelData.on_now ? "until " + Model.formatClock(cell.modelData.end) : Model.formatClock(cell.modelData.start)
      color: Color.muted
      font.family: grid.tv.bar.fontFamily
      font.pixelSize: Style.font.caption
      elide: Text.ElideRight
    }

    MouseArea {
      anchors.fill: parent
      cursorShape: Qt.PointingHandCursor
      onClicked: {
        grid.tv.cursorActive = true
        grid.tv.gridRow = cell.row
        grid.tv.gridCol = cell.index
        grid.tv.gridTime = cell.modelData.x0
        grid.tv.gridCardOpen = true
      }
    }
  }

  BorderSurface {
    id: card
    readonly property var block: grid.tv.gridCardOpen ? grid.tv.gridCurrent() : null
    readonly property var airing: Model.blockAiring(block)
    readonly property string recState: grid.tv.hitRecordState(airing)
    readonly property bool series: grid.tv.hitRuleId(airing) !== ""

    visible: block !== null
    z: 10
    width: Math.min(Style.space(360), grid.width - Style.space(12))
    height: cardCol.implicitHeight + Style.space(20)
    x: Math.max(0, Math.min(grid.width - width, grid.chanWidth + (block ? grid.xOf(block.x0) : 0) - body.contentX))
    y: {
      var below = grid.headHeight + (grid.tv.gridRow + 1) * grid.rowHeight - body.contentY
      return below + height > grid.height ? Math.max(0, below - grid.rowHeight - height) : below
    }
    radius: Style.spacing.labelGap
    color: Color.popups.background
    borderSpec: Border.controlSpec("focus", grid.fg, Color.accent)

    Column {
      id: cardCol
      x: Style.space(10)
      y: Style.space(10)
      width: card.width - Style.space(20)
      spacing: Style.space(4)

      Text {
        width: parent.width
        textFormat: Text.PlainText
        text: card.block ? card.block.title : ""
        color: grid.fg
        font.family: grid.tv.bar.fontFamily
        font.pixelSize: Style.font.subtitle
        font.bold: true
        elide: Text.ElideRight
      }

      Text {
        width: parent.width
        textFormat: Text.PlainText
        text: card.block ? (Model.formatClock(card.block.start) + " – " + Model.formatClock(card.block.end)
                            + " · " + card.block.channel_number + " " + card.block.display_name) : ""
        color: Color.muted
        font.family: grid.tv.bar.fontFamily
        font.pixelSize: Style.font.caption
        elide: Text.ElideRight
      }

      Text {
        visible: !!(card.block && card.block.synopsis)
        width: parent.width
        textFormat: Text.PlainText
        text: card.block ? card.block.synopsis : ""
        color: Color.muted
        font.family: grid.tv.bar.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.Wrap
        maximumLineCount: 2
        elide: Text.ElideRight
      }

      Row {
        spacing: Style.space(6)
        topPadding: Style.space(4)

        Button {
          visible: !!(card.block && card.block.on_now)
          text: "Watch"
          tooltipText: "Watch this channel now"
          fontSize: Style.font.caption
          foreground: grid.fg
          onClicked: grid.tv.selectChannel(card.block.tune_name || card.block.channel_number)
        }

        Button {
          text: card.recState === "recording" ? "Recording" : (card.recState === "scheduled" ? "Scheduled" : "Record")
          tooltipText: card.recState === "recording" ? "Stop this recording"
                : (card.recState === "scheduled" ? "Don't record this"
                : (card.block && card.block.on_now ? "Record the rest of this one" : "Record this one when it airs"))
          selected: card.recState !== ""
          enabled: card.recState !== "" || !(card.block && card.block.on_now) || grid.tv.freeTunerForRecording()
          fontSize: Style.font.caption
          foreground: grid.fg
          onClicked: grid.tv.toggleHitRecord(card.airing)
        }

        Button {
          text: card.series ? "Series on" : "Record series"
          tooltipText: card.series ? "Stop recording every airing" : "Record every airing on " + (card.block ? card.block.channel_number : "this channel") + ", any time of day"
          selected: card.series
          enabled: card.series || !!(card.block && card.block.tune_name)
          fontSize: Style.font.caption
          foreground: grid.fg
          onClicked: grid.tv.toggleHitRecordAll(card.airing)
        }
      }
    }
  }
}
