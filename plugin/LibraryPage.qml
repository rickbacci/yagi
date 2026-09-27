import QtQuick
import qs.Ui
import qs.Commons

Column {
  id: library
  required property var tv
  property real outerSpacing: 0
  property alias flick: recFlick
  property alias rows: recRepeater
  readonly property bool onRecorded: library.tv.libraryTab === "recorded"
  readonly property int shownCount: library.onRecorded ? library.tv.librarySorted.length : library.tv.scheduledPicks.length

  visible: library.tv.libraryModalOpen
  spacing: Style.space(10)

  Item {
    id: libraryHeader
    width: parent.width
    implicitHeight: height
    height: Math.max(Style.space(36), libraryBackBtn.implicitHeight)

    BorderSurface {
      width: Style.space(36)
      height: Style.space(36)
      anchors.left: parent.left
      anchors.verticalCenter: parent.verticalCenter
      radius: Style.spacing.labelGap
      color: Style.normalFillFor(library.tv.bar.foreground, Color.accent)
      borderSpec: Border.controlSpec("normal", library.tv.bar.foreground, Color.accent)

      Text {
        anchors.centerIn: parent
        text: "󰑈"
        color: Color.accent
        font.family: library.tv.bar.fontFamily
        font.pixelSize: Style.font.subtitle
      }
    }

    Button {
      id: libraryBackBtn
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      iconText: "\udb80\udc4d"
      text: "Back"
      tooltipText: "Back to channels"
      foreground: library.tv.bar.foreground
      onClicked: library.tv.toggleLibrary()
    }

    Button {
      id: libraryCapBtn
      anchors.right: libraryBackBtn.left
      anchors.rightMargin: Style.space(6)
      anchors.verticalCenter: parent.verticalCenter
      text: library.tv.libraryCapButtonText()
      tooltipText: "Over the limit, the oldest recordings are deleted, series episodes first. Locked ones never are. Click to change"
      fontSize: Style.font.caption
      foreground: library.tv.bar.foreground
      onClicked: library.tv.cycleLibraryCap()
    }

    Column {
      anchors.left: parent.left
      anchors.right: libraryCapBtn.left
      anchors.leftMargin: Style.space(44)
      anchors.rightMargin: Style.space(8)
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(2)

      Text {
        textFormat: Text.PlainText
        text: "Recordings"
        color: library.tv.bar.foreground
        font.family: library.tv.bar.fontFamily
        font.pixelSize: Style.font.bodySmall
        font.bold: true
        elide: Text.ElideRight
        width: parent.width
      }

      Text {
        textFormat: Text.PlainText
        text: (library.tv.recordingsData.length > 0)
          ? (library.tv.recordingsData.length + (library.tv.recordingsData.length === 1 ? " recording · " : " recordings · ")
             + library.tv.libraryBytesLabel + (library.tv.libraryBudgetLabel && library.tv.libraryBudgetLabel !== "Unlimited" ? " of " + library.tv.libraryBudgetLabel : ""))
          : "Nothing recorded yet"
        color: Color.muted
        font.family: library.tv.bar.fontFamily
        font.pixelSize: Style.font.caption
        elide: Text.ElideRight
        width: parent.width
      }
    }
  }

  Row {
    spacing: Style.space(4)

    Button {
      text: "Recorded"
      selected: library.onRecorded
      fontSize: Style.font.caption
      foreground: library.tv.bar.foreground
      onClicked: library.tv.showLibraryTab("recorded")
    }

    Button {
      text: library.tv.scheduledPicks.length ? "Scheduled (" + library.tv.scheduledPicks.length + ")" : "Scheduled"
      tooltipText: "What will record, and each series"
      selected: !library.onRecorded
      fontSize: Style.font.caption
      foreground: library.tv.bar.foreground
      onClicked: library.tv.showLibraryTab("scheduled")
    }
  }

  Item {
    visible: library.shownCount === 0
    width: parent.width
    height: Style.space(80)

    Text {
      anchors.centerIn: parent
      width: parent.width
      horizontalAlignment: Text.AlignHCenter
      wrapMode: Text.Wrap
      textFormat: Text.PlainText
      text: library.onRecorded ? "Record from the Guide, then play it back here."
                               : "Nothing scheduled. In the Guide, Record takes one airing and Record series takes every one."
      color: Color.muted
      font.family: library.tv.bar.fontFamily
      font.pixelSize: Style.font.caption
    }
  }

  Item {
    visible: library.shownCount > 0
    width: parent.width
    implicitHeight: height
    height: {
      if (!visible) return 0
      var content = recCol.implicitHeight
      var room = library.tv.roomFor(libraryHeader.height + library.outerSpacing + Style.space(60))
      if (content > 0) return Math.min(content, room)
      return Math.min(Style.space(120), room)
    }
    clip: true

    Flickable {
      id: recFlick
      anchors.fill: parent
      contentWidth: width
      contentHeight: recCol.implicitHeight
      boundsBehavior: Flickable.StopAtBounds
      flickableDirection: Flickable.VerticalFlick
      clip: true

      Column {
        id: recCol
        width: parent.width
        spacing: Style.space(6)

        Repeater {
          id: recRepeater
          model: library.onRecorded ? library.tv.recordedRows : library.tv.scheduledRows
          delegate: Item {
            id: entry
            required property var modelData
            readonly property bool isHeader: library.onRecorded ? !!entry.modelData.header : entry.modelData.kind === "header"
            readonly property int pick: library.onRecorded ? entry.modelData.index : entry.modelData.pick
            width: recCol.width
            height: entry.isHeader ? headText.implicitHeight + Style.space(6)
                    : (library.onRecorded ? recItem.height : schedItem.height)

            Text {
              id: headText
              visible: entry.isHeader
              anchors.bottom: parent.bottom
              anchors.bottomMargin: Style.space(2)
              textFormat: Text.PlainText
              text: (library.onRecorded ? entry.modelData.header : entry.modelData.title) || ""
              color: Color.muted
              font.family: library.tv.bar.fontFamily
              font.pixelSize: Style.font.caption
              font.bold: true
            }

            RecordingRow {
              id: recItem
              visible: library.onRecorded && !entry.isHeader
              tv: library.tv
              width: parent.width
              rec: entry.modelData.rec || ({})
              recIndex: entry.pick
            }

            ScheduledRow {
              id: schedItem
              visible: !library.onRecorded && !entry.isHeader
              tv: library.tv
              width: parent.width
              row: entry.modelData
              pickIndex: entry.pick
            }
          }
        }
      }
    }
  }

  function revealCursor() {
    var want = library.onRecorded ? library.tv.recCursorIndex : library.tv.schedCursorIndex
    for (var i = 0; i < recRepeater.count; i++) {
      var item = recRepeater.itemAt(i)
      if (!item || item.isHeader || item.pick !== want) continue
      var top = i > 0 && recRepeater.itemAt(i - 1).isHeader ? recRepeater.itemAt(i - 1).y : item.y
      if (top < recFlick.contentY) recFlick.contentY = top
      else if (item.y + item.height > recFlick.contentY + recFlick.height)
        recFlick.contentY = item.y + item.height - recFlick.height
      return
    }
  }
}
