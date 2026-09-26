import QtQuick
import qs.Ui
import qs.Commons

Column {
  id: library
  required property var tv
  property real outerSpacing: 0
  property alias flick: recFlick
  property alias rows: recRepeater

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

  Item {
    visible: library.tv.recordingsData.length === 0
    width: parent.width
    height: Style.space(80)

    Text {
      anchors.centerIn: parent
      text: "Record from the Guide, then play it back here."
      color: Color.muted
      font.family: library.tv.bar.fontFamily
      font.pixelSize: Style.font.caption
    }
  }

  Item {
    visible: library.tv.recordingsData.length > 0
    width: parent.width
    implicitHeight: height
    height: {
      if (!visible) return 0
      var content = recCol.implicitHeight
      var room = library.tv.roomFor(libraryHeader.height + library.outerSpacing + Style.space(24))
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
          model: library.tv.recordingsData
          delegate: RecordingRow {
            tv: library.tv
            width: recCol.width
          }
        }
      }
    }
  }
}
