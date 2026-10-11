// plugin/GuidePage.qml at 08ae869fd205f2324606e54807228849031b2dec
import QtQuick
import qs.Ui
import qs.Commons

Column {
  id: guide
  required property var tv
  required property Item keyTarget
  property alias grid: guideGrid
  property alias showsFlick: stripFlick
  property alias showsList: showsRepeater
  // False until the user opens search. The field is a Loader child, so it
  // does not exist while this stays false.
  property bool searchOpen: false
  readonly property bool searchFocused: guide.searchOpen && searchLoader.item !== null && searchLoader.item.activeFocus
  readonly property int searchLimit: 64

  readonly property bool onGrid: guide.tv.guideTab === "grid"

  function openSearch() {
    guide.searchOpen = true
  }

  function closeSearch() {
    guide.searchOpen = false
  }

  function clearSearch() {
    guide.tv.guideSearchText = ""
    guide.searchOpen = false
  }

  function insertSearch(chunk) {
    var next = (guide.tv.guideSearchText + (chunk || "")).slice(0, guide.searchLimit)
    guide.tv.guideSearchText = next
    if (searchLoader.item)
      searchLoader.item.text = next
  }

  function backspaceSearch() {
    var cur = guide.tv.guideSearchText
    if (!cur.length)
      return
    var next = cur.slice(0, cur.length - 1)
    guide.tv.guideSearchText = next
    if (searchLoader.item)
      searchLoader.item.text = next
  }

  function pasteSearch() {
    if (pasteProc.running)
      return
    pasteProc.command = [guide.tv.binPath, "clipboard-text"]
    pasteProc.running = true
  }

  visible: guide.tv.guideStripOpen
  spacing: Style.space(6)

  Item {
    width: parent.width
    height: Math.max(tabRow.implicitHeight, searchPlaceholder.implicitHeight)

    Row {
      id: tabRow
      spacing: Style.space(4)
      anchors.verticalCenter: parent.verticalCenter

      Button {
        text: "Grid"
        tooltipText: "What is on each channel, by time"
        selected: guide.onGrid
        fontSize: Style.font.heading
        foreground: guide.tv.bar.foreground
        onClicked: guide.tv.showGuideTab("grid")
      }

      Button {
        text: "Shows"
        tooltipText: "Shows the Guide has seen, by time of day"
        selected: !guide.onGrid
        fontSize: Style.font.heading
        foreground: guide.tv.bar.foreground
        onClicked: guide.tv.showGuideTab("shows")
      }
    }

    Item {
      id: searchBox
      anchors.left: tabRow.right
      anchors.leftMargin: Style.space(10)
      anchors.right: matchCount.visible ? matchCount.left : parent.right
      anchors.rightMargin: matchCount.visible ? Style.space(8) : 0
      anchors.verticalCenter: parent.verticalCenter
      height: searchPlaceholder.implicitHeight

      Text {
        id: searchPlaceholder
        visible: !guide.searchOpen
        width: parent.width
        textFormat: Text.PlainText
        text: guide.tv.guideSearchText.length
              ? guide.tv.guideSearchText
              : (guide.onGrid ? "Search shows and teams" : "Filter shows")
        color: guide.tv.guideSearchText.length ? guide.tv.bar.foreground : Color.muted
        font.family: guide.tv.bar.fontFamily
        font.pixelSize: Style.font.heading
        elide: Text.ElideRight

        MouseArea {
          anchors.fill: parent
          onClicked: guide.openSearch()
        }
      }

      // Inactive until search is open. Qt 6.12 connects every TextInput to
      // clipboard dataChanged and then reads the offer synchronously.
      Loader {
        id: searchLoader
        active: guide.searchOpen
        anchors.fill: parent
        sourceComponent: Component {
          TextField {
            id: guideSearch
            readOnly: true
            maximumLength: guide.searchLimit
            placeholderText: guide.onGrid ? "Search shows and teams" : "Filter shows"
            font.family: guide.tv.bar.fontFamily
            font.pixelSize: Style.font.heading
            anchors.fill: parent
            Component.onCompleted: {
              text = guide.tv.guideSearchText
              forceActiveFocus()
            }
            Keys.priority: Keys.BeforeItem
            Keys.onPressed: function(event) {
              if (event.key === Qt.Key_Escape) {
                guide.tv.guideSearchText = ""
                guide.keyTarget.forceActiveFocus()
                event.accepted = true
                Qt.callLater(guide.closeSearch)
                return
              }
              if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Down) {
                guide.tv.leaveGuideSearch()
                event.accepted = true
                return
              }
              if (event.key === Qt.Key_Backspace) {
                guide.backspaceSearch()
                event.accepted = true
                return
              }
              if ((event.key === Qt.Key_V && (event.modifiers & Qt.ControlModifier))
                  || (event.key === Qt.Key_Insert && (event.modifiers & Qt.ShiftModifier))) {
                guide.pasteSearch()
                event.accepted = true
                return
              }
              var ch = event.text || ""
              if (ch.length && !(event.modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier))) {
                guide.insertSearch(ch)
                event.accepted = true
              }
            }
          }
        }
      }
    }

    Process {
      id: pasteProc
      stdout: StdioCollector {
        id: pasteOut
        waitForEnd: true
      }
      onExited: function(code) {
        if (!guide.searchOpen || code !== 0)
          return
        guide.insertSearch(String(pasteOut.text || "").replace(/[\r\n]+/g, " "))
      }
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
      font.pixelSize: Style.font.heading
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
          : (guide.tv.channelFilter === "favorites" && guide.tv.favoriteVisibleCount === 0
             && (guide.tv.watchableChannels || []).length > 0)
            ? "No favorites yet. Open All and click ☆ on a channel to add it here."
            : (guide.tv.guideWaitReason
               || "No listings yet for these channels. Each Guide update adds what the stations send.")
    color: Color.muted
    font.family: guide.tv.bar.fontFamily
    font.pixelSize: Style.font.heading
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
        fontSize: Style.font.heading
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
    font.pixelSize: Style.font.heading
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
