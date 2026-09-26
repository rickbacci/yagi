import QtQuick
import qs.Ui
import qs.Commons

Item {
  id: header
  required property var tv

  height: Math.max(Style.space(42), headerGuideBtn.implicitHeight)

  BorderSurface {
    id: headerIcon
    width: Style.space(42)
    height: Style.space(42)
    anchors.left: parent.left
    anchors.verticalCenter: parent.verticalCenter
    radius: Style.spacing.labelGap
    color: Style.normalFillFor(header.tv.bar.foreground, Color.accent)
    borderSpec: Border.controlSpec("normal", header.tv.bar.foreground, Color.accent)

    Text {
      anchors.centerIn: parent
      text: header.tv.isScanning ? "󰛳" : "󰢹"
      color: Color.accent
      font.family: header.tv.bar.fontFamily
      font.pixelSize: Style.font.display
    }
  }

  Row {
    id: headerNavRow
    anchors.right: parent.right
    anchors.verticalCenter: parent.verticalCenter
    spacing: Style.space(4)

    Button {
      iconText: "󰑈"
      text: "Recordings"
      tooltipText: "Recorded videos"
      foreground: header.tv.bar.foreground
      onClicked: header.tv.toggleLibrary()
    }

    Button {
      id: headerGuideBtn
      iconText: "󰥔"
      text: "Guide"
      tooltipText: "Program guide"
      selected: header.tv.guideStripOpen
      foreground: header.tv.bar.foreground
      onClicked: header.tv.toggleGuide()
    }
  }

  Column {
    anchors.left: headerIcon.right
    anchors.right: headerNavRow.left
    anchors.leftMargin: Style.space(10)
    anchors.rightMargin: Style.space(8)
    anchors.verticalCenter: parent.verticalCenter
    spacing: Style.space(2)

    Text {
      textFormat: Text.PlainText
      text: "Omarchy TV"
      color: header.tv.bar.foreground
      font.family: header.tv.bar.fontFamily
      font.pixelSize: Style.font.subtitle
      font.bold: true
      elide: Text.ElideRight
      width: parent.width
    }

    Text {
      textFormat: Text.PlainText
      text: {
        if (header.tv.isScanning) return "Scanning for channels…"
        return header.tv.listedChannelCount > 0
          ? ((header.tv.watchableChannels || []).length + " channels · " + header.tv.favoriteVisibleCount + " favorites")
          : "No channels yet"
      }
      color: header.tv.isScanning ? Color.accent : Color.muted
      font.family: header.tv.bar.fontFamily
      font.pixelSize: Style.font.caption
      elide: Text.ElideRight
      width: parent.width
    }
  }
}
