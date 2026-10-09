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
  readonly property bool inShow: library.onRecorded && library.tv.libraryShow !== ""
  readonly property int shownCount: library.onRecorded ? library.tv.recordedPicks.length : library.tv.scheduledPicks.length

  visible: library.tv.libraryModalOpen
  spacing: Style.space(10)

  Item {
    id: libraryHeader
    width: parent.width
    implicitHeight: height
    height: Math.max(Style.space(44), libraryBackBtn.implicitHeight, libraryTitles.implicitHeight)

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
        font.pixelSize: Style.font.heading
      }
    }

    Button {
      id: libraryBackBtn
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      iconText: "\udb80\udc4d"
      text: "Back"
      tooltipText: library.inShow ? "Back to recordings" : "Back to channels"
      fontSize: Style.font.heading
      foreground: library.tv.bar.foreground
      onClicked: library.tv.libraryBack()
    }

    Button {
      id: libraryCapBtn
      anchors.right: libraryBackBtn.left
      anchors.rightMargin: Style.space(6)
      anchors.verticalCenter: parent.verticalCenter
      visible: !library.inShow
      text: library.tv.libraryCapButtonText()
      tooltipText: "Over the limit, the oldest recordings are deleted, series episodes first. Locked ones never are. Click to change"
      fontSize: Style.font.heading
      foreground: library.tv.bar.foreground
      onClicked: library.tv.cycleLibraryCap()
    }

    Column {
      id: libraryTitles
      anchors.left: parent.left
      anchors.right: library.inShow ? libraryBackBtn.left : libraryCapBtn.left
      anchors.leftMargin: Style.space(44)
      anchors.rightMargin: Style.space(8)
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(2)

      Text {
        textFormat: Text.PlainText
        text: library.inShow ? (library.tv.libraryShowTitle || "Recordings") : "Recordings"
        color: library.tv.bar.foreground
        font.family: library.tv.bar.fontFamily
        font.pixelSize: Style.font.heading
        font.bold: true
        elide: Text.ElideRight
        width: parent.width
      }

      Text {
        textFormat: Text.PlainText
        text: library.inShow
          ? library.tv.libraryShowSubtitle
          : ((library.tv.recordingsData.length > 0)
            ? (library.tv.recordingsData.length + (library.tv.recordingsData.length === 1 ? " recording · " : " recordings · ")
               + library.tv.libraryBytesLabel + (library.tv.libraryBudgetLabel && library.tv.libraryBudgetLabel !== "Unlimited" ? " of " + library.tv.libraryBudgetLabel : ""))
            : "Nothing recorded yet")
        color: Color.muted
        font.family: library.tv.bar.fontFamily
        font.pixelSize: Style.font.heading
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
      fontSize: Style.font.heading
      foreground: library.tv.bar.foreground
      onClicked: library.tv.showLibraryTab("recorded")
    }

    Button {
      text: library.tv.scheduledPicks.length ? "Scheduled (" + library.tv.scheduledPicks.length + ")" : "Scheduled"
      tooltipText: "What will record, and each series"
      selected: !library.onRecorded
      fontSize: Style.font.heading
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
      font.pixelSize: Style.font.heading
    }
  }

  Item {
    visible: library.shownCount > 0
    width: parent.width
    implicitHeight: height
    height: {
      if (!visible) return 0
      var content = recCol.implicitHeight
      var room = library.tv.roomFor(libraryHeader.height + library.outerSpacing + Style.space(80))
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
        spacing: Style.space(8)

        Repeater {
          id: recRepeater
          model: library.onRecorded ? library.tv.recordedPicks : library.tv.scheduledRows
          delegate: Item {
            id: entry
            required property var modelData
            readonly property bool isHeader: entry.modelData.kind === "header"
            readonly property bool isShow: library.onRecorded && entry.modelData.kind === "show"
            readonly property int pick: entry.modelData.pick
            width: recCol.width
            height: entry.isHeader ? headText.implicitHeight + Style.space(8)
                    : (entry.isShow ? showItem.height : (library.onRecorded ? recItem.height : schedItem.height))

            Text {
              id: headText
              visible: entry.isHeader
              anchors.bottom: parent.bottom
              anchors.bottomMargin: Style.space(2)
              textFormat: Text.PlainText
              text: entry.modelData.title || ""
              color: Color.muted
              font.family: library.tv.bar.fontFamily
              font.pixelSize: library.onRecorded ? Style.font.title : Style.font.heading
              font.bold: true
            }

            LibraryShowRow {
              id: showItem
              visible: entry.isShow
              tv: library.tv
              width: parent.width
              show: entry.modelData.show || ({})
              line: entry.modelData.line || ""
              recIndex: entry.pick
            }

            RecordingRow {
              id: recItem
              visible: library.onRecorded && !entry.isHeader && !entry.isShow
              tv: library.tv
              width: parent.width
              rec: entry.modelData.rec || ({})
              recIndex: entry.pick
              titleText: entry.modelData.title || ""
              detailText: entry.modelData.detail || ""
              blurb: entry.modelData.blurb || ""
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
