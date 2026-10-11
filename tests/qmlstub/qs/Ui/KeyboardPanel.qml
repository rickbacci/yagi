import QtQuick
Item {
  id: panel
  required property var anchorItem
  required property var bar
  property var owner: null
  property bool open: false
  property var focusTarget: null
  property real contentWidth: 0
  property real contentHeight: 0
  property real margin: 0
  default property alias contentItem: content.children
  function fittedContentHeight(h) { return h }
  function fittedContentWidth(w) { return w }
  Item {
    id: content
    anchors.fill: parent
  }
}
