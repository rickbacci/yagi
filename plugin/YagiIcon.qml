import QtQuick
import QtQuick.Effects
import QtQuick.Window

// icons/yagi.svg stays pure white: colorization maps white onto `color`.
Item {
  id: icon
  property color color: "white"
  property real size: 16

  implicitWidth: size
  implicitHeight: size

  Image {
    id: art
    anchors.fill: parent
    source: Qt.resolvedUrl("icons/yagi.svg")
    fillMode: Image.PreserveAspectFit
    sourceSize.width: Math.round(icon.size * Screen.devicePixelRatio)
    sourceSize.height: Math.round(icon.size * Screen.devicePixelRatio)
    visible: false
    layer.enabled: true
  }

  MultiEffect {
    anchors.fill: art
    source: art
    colorization: 1.0
    colorizationColor: icon.color
  }
}
