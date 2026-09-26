import QtQuick
import qs.Ui
import qs.Commons
import "Model.js" as Model

BorderSurface {
  id: card
  required property var tv

  visible: card.tv.isScanning
  height: Style.space(110)
  radius: Style.spacing.labelGap
  color: Style.selectedFillFor(card.tv.bar.foreground, Color.accent)
  borderSpec: Border.controlSpec("focus", card.tv.bar.foreground, Color.accent)

  Column {
    anchors.fill: parent
    anchors.margins: Style.space(10)
    spacing: Style.space(8)

    Item {
      width: parent.width
      height: Style.space(18)

      Text {
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        textFormat: Text.PlainText
        text: "Scanning for channels"
        color: Color.accent
        font.family: card.tv.bar.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
      }

      Text {
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        textFormat: Text.PlainText
        text: card.tv.scanTotalFound + " found"
        color: Color.accent
        font.family: card.tv.bar.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
      }
    }

    Item {
      width: parent.width
      height: Style.space(26)

      Row {
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.space(8)

        BorderSurface {
          width: Style.space(56)
          height: Style.space(22)
          radius: 4
          color: Style.normalFillFor(card.tv.bar.foreground, Color.accent)

          Text {
            anchors.centerIn: parent
            textFormat: Text.PlainText
            text: "Ch " + (card.tv.scanChannel > 0 ? card.tv.scanChannel : "--")
            color: card.tv.bar.foreground
            font.family: card.tv.bar.fontFamily
            font.pixelSize: Style.font.bodySmall
            font.bold: true
          }
        }

        Column {
          anchors.verticalCenter: parent.verticalCenter
          spacing: 1

          Text {
            textFormat: Text.PlainText
            text: card.tv.scanBand !== "" ? card.tv.scanBand : "Broadcast"
            color: card.tv.bar.foreground
            font.family: card.tv.bar.fontFamily
            font.pixelSize: Style.font.caption
            font.bold: true
          }

          Text {
            textFormat: Text.PlainText
            text: Model.formatFreq(card.tv.scanFreq)
            color: Color.muted
            font.family: card.tv.bar.fontFamily
            font.pixelSize: Style.font.caption
          }
        }
      }

      Column {
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: 1

        Text {
          anchors.right: parent.right
          textFormat: Text.PlainText
          text: card.tv.scanSignal === null ? "Listening…" : (card.tv.scanSignal > -55 ? "Strong signal" : "Signal found")
          color: card.tv.scanSignal !== null && card.tv.scanSignal > -55 ? Color.accent : (card.tv.scanSignal !== null ? card.tv.bar.foreground : Color.muted)
          font.family: card.tv.bar.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: true
        }

        Text {
          anchors.right: parent.right
          textFormat: Text.PlainText
          text: card.tv.scanSignal !== null ? (card.tv.scanSignal.toFixed(1) + " dBm") : ""
          color: Color.muted
          font.family: card.tv.bar.fontFamily
          font.pixelSize: Style.font.caption
        }
      }
    }

    Column {
      width: parent.width
      spacing: Style.space(4)

      Item {
        width: parent.width
        height: Style.space(16)

        Text {
          anchors.left: parent.left
          anchors.verticalCenter: parent.verticalCenter
          textFormat: Text.PlainText
          text: "Progress"
          color: Color.muted
          font.family: card.tv.bar.fontFamily
          font.pixelSize: Style.font.caption
        }

        Text {
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          textFormat: Text.PlainText
          text: card.tv.scanPercent + "%"
          color: Color.accent
          font.family: card.tv.bar.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: true
        }
      }

      BorderSurface {
        width: parent.width
        height: Style.space(8)
        radius: 4
        color: Style.normalFillFor(card.tv.bar.foreground, Color.accent)

        Rectangle {
          height: parent.height
          width: parent.width * (Math.max(1, card.tv.scanPercent) / 100.0)
          radius: 4
          color: Color.accent

          Behavior on width {
            NumberAnimation { duration: 250; easing.type: Easing.OutQuad }
          }
        }
      }
    }
  }
}
