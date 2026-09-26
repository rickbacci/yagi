import QtQuick
import qs.Ui
import qs.Commons

Column {
  id: guide
  required property var tv
  required property Item keyTarget
  property alias searchField: guideStripSearch
  property alias showsFlick: stripFlick
  property alias showsList: showsRepeater
  property alias hitsFlick: stripSearchFlick
  property alias hitsList: hitsRepeater

  visible: guide.tv.guideStripOpen
  spacing: Style.space(6)

  TextField {
    id: guideStripSearch
    width: parent.width
    placeholderText: "Search shows and teams"
    Keys.onEscapePressed: {
      text = ""
      guide.keyTarget.forceActiveFocus()
    }
    Keys.onReturnPressed: {
      guide.keyTarget.forceActiveFocus()
      guide.tv.cursorActive = true
      guide.tv.guideCursor = 0
    }
    Keys.onDownPressed: {
      guide.keyTarget.forceActiveFocus()
      guide.tv.cursorActive = true
      guide.tv.guideCursor = 0
    }
    font.family: guide.tv.bar.fontFamily
    onTextChanged: guide.tv.guideSearchText = text
  }

  Row {
    visible: !guide.tv.guideSearchActive
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
    visible: !guide.tv.guideSearchActive && guide.tv.guideShowRows.length === 0
    width: parent.width
    textFormat: Text.PlainText
    text: guide.tv.showsLoading ? "Reading the Guide…"
          : "Nothing listed for this time yet. Each Guide update adds what the stations send."
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
    visible: !guide.tv.guideSearchActive && guide.tv.guideShowRows.length > 0
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

  Flickable {
    id: stripSearchFlick
    width: parent.width
    height: Math.min(stripSearchCol.implicitHeight, guide.tv.guideListRoom())
    contentWidth: width
    contentHeight: stripSearchCol.implicitHeight
    clip: true
    visible: guide.tv.guideSearchActive && guide.tv.guideSearchHits.length > 0
    flickableDirection: Flickable.VerticalFlick
    boundsBehavior: Flickable.StopAtBounds

    Column {
      id: stripSearchCol
      width: stripSearchFlick.width

      Repeater {
        id: hitsRepeater
        model: guide.tv.guideSearchHits
        delegate: HitRow {
          tv: guide.tv
          width: stripSearchCol.width
        }
      }
    }
  }

  Text {
    visible: guide.tv.guideSearchActive && guide.tv.guideSearchHits.length === 0
    width: parent.width
    textFormat: Text.PlainText
    text: "Nothing listed matches. Stations only list the next few hours, so search again closer to air time."
    color: Color.muted
    font.family: guide.tv.bar.fontFamily
    font.pixelSize: Style.font.caption
    wrapMode: Text.Wrap
  }

  Text {
    visible: guide.tv.scheduleItems.length > 0
    textFormat: Text.PlainText
    text: "Waiting to record"
    color: guide.tv.bar.foreground
    font.family: guide.tv.bar.fontFamily
    font.pixelSize: Style.font.caption
    font.bold: true
  }

  Repeater {
    model: guide.tv.scheduleItems
    delegate: Row {
      id: waitRow
      required property var modelData
      width: guide.width
      spacing: Style.space(6)

      Text {
        width: Math.max(0, parent.width - stripRemove.width - parent.spacing)
        textFormat: Text.PlainText
        text: (waitRow.modelData.status === "missed" ? "Missed · " : "")
              + (waitRow.modelData.display_name || waitRow.modelData.tune_name || "")
              + " · " + (waitRow.modelData.title || "")
              + (waitRow.modelData.clock ? " · " + waitRow.modelData.clock : "")
        color: Color.accent
        font.family: guide.tv.bar.fontFamily
        font.pixelSize: Style.font.caption
        elide: Text.ElideRight
        anchors.verticalCenter: parent.verticalCenter
      }

      Button {
        id: stripRemove
        text: "Remove"
        fontSize: Style.font.caption
        foreground: guide.tv.bar.foreground
        onClicked: guide.tv.removeScheduled(waitRow.modelData.id)
      }
    }
  }
}
