import QtQuick
import qs.Ui
import qs.Commons

Column {
  id: guide
  required property var tv
  required property Item keyTarget
  property alias searchField: guideSearch
  property alias grid: guideGrid
  property alias showsFlick: stripFlick
  property alias showsList: showsRepeater

  readonly property bool onGrid: guide.tv.guideTab === "grid"

  visible: guide.tv.guideStripOpen
  spacing: Style.space(6)

  Item {
    width: parent.width
    height: Math.max(tabRow.implicitHeight, guideSearch.implicitHeight)

    Row {
      id: tabRow
      spacing: Style.space(4)
      anchors.verticalCenter: parent.verticalCenter

      Button {
        text: "Grid"
        tooltipText: "What is on each channel, by time"
        selected: guide.onGrid
        fontSize: Style.font.caption
        foreground: guide.tv.bar.foreground
        onClicked: guide.tv.showGuideTab("grid")
      }

      Button {
        text: "Shows"
        tooltipText: "Shows the Guide has seen, by time of day"
        selected: !guide.onGrid
        fontSize: Style.font.caption
        foreground: guide.tv.bar.foreground
        onClicked: guide.tv.showGuideTab("shows")
      }
    }

    TextField {
      id: guideSearch
      anchors.left: tabRow.right
      anchors.leftMargin: Style.space(10)
      anchors.right: matchCount.visible ? matchCount.left : parent.right
      anchors.rightMargin: matchCount.visible ? Style.space(8) : 0
      anchors.verticalCenter: parent.verticalCenter
      placeholderText: guide.onGrid ? "Search shows and teams" : "Filter shows"
      Keys.onEscapePressed: {
        text = ""
        guide.keyTarget.forceActiveFocus()
      }
      Keys.onReturnPressed: guide.tv.leaveGuideSearch()
      Keys.onDownPressed: guide.tv.leaveGuideSearch()
      font.family: guide.tv.bar.fontFamily
      onTextChanged: guide.tv.guideSearchText = text
    }

    Text {
      id: matchCount
      visible: guide.onGrid && guide.tv.guideSearchActive
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      textFormat: Text.PlainText
      text: guide.tv.gridMatchCount === 1 ? "1 match" : guide.tv.gridMatchCount + " matches"
      color: Color.accent
      font.family: guide.tv.bar.fontFamily
      font.pixelSize: Style.font.caption
      font.bold: true
    }
  }

  ChannelTabs {
    tv: guide.tv
    visible: guide.onGrid
  }

  GuideGrid {
    id: guideGrid
    tv: guide.tv
    visible: guide.onGrid && guide.tv.gridRows.length > 0
    width: parent.width
    height: guide.tv.guideListRoom()
  }

  Text {
    visible: guide.onGrid && guide.tv.gridRows.length === 0
    width: parent.width
    textFormat: Text.PlainText
    text: guide.tv.guideSearchActive
          ? "Nothing listed matches. Stations list about the next five hours, so search again closer to air time."
          : "No listings yet for these channels. Each Guide update adds what the stations send."
    color: Color.muted
    font.family: guide.tv.bar.fontFamily
    font.pixelSize: Style.font.caption
    wrapMode: Text.Wrap
  }

  Row {
    visible: !guide.onGrid
    spacing: Style.space(4)

    Repeater {
      model: [
        { key: "day", label: "Day 6 AM–8 PM" },
        { key: "prime", label: "Prime 8–11 PM" },
        { key: "late", label: "Late 11 PM–2 AM" },
        { key: "overnight", label: "Overnight 2–6 AM" }
      ]
      delegate: Button {
        id: bucketBtn
        required property var modelData
        text: bucketBtn.modelData.label
        selected: guide.tv.showBucket === bucketBtn.modelData.key
        fontSize: Style.font.caption
        foreground: guide.tv.bar.foreground
        onClicked: guide.tv.showBucket = bucketBtn.modelData.key
      }
    }
  }

  Text {
    visible: !guide.onGrid && guide.tv.guideShowRows.length === 0
    width: parent.width
    textFormat: Text.PlainText
    text: guide.tv.showsLoading ? "Reading the Guide…"
          : (guide.tv.guideSearchActive ? "No show here matches." : "Nothing listed for this time yet. Each Guide update adds what the stations send.")
    color: Color.muted
    font.family: guide.tv.bar.fontFamily
    font.pixelSize: Style.font.caption
    wrapMode: Text.Wrap
  }

  Flickable {
    id: stripFlick
    width: parent.width
    height: Math.min(stripShowsCol.implicitHeight, guide.tv.guideListRoom())
    contentWidth: width
    contentHeight: stripShowsCol.implicitHeight
    clip: true
    visible: !guide.onGrid && guide.tv.guideShowRows.length > 0
    flickableDirection: Flickable.VerticalFlick
    boundsBehavior: Flickable.StopAtBounds

    Column {
      id: stripShowsCol
      width: stripFlick.width
      spacing: Style.space(6)

      Repeater {
        id: showsRepeater
        model: guide.tv.guideShowRows
        delegate: ShowRow {
          tv: guide.tv
          width: stripShowsCol.width
        }
      }
    }
  }
}
