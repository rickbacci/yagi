import QtQuick
import qs.Ui
import qs.Commons

Item {
  id: list
  required property var tv
  required property real room
  property alias flick: channelFlickable
  property alias rows: channelRepeater

  visible: list.tv.showChannelBrowser && list.tv.displayChannels.length > 0
  implicitHeight: height
  height: {
    if (!visible) return 0
    var content = channelListView.implicitHeight
    if (content > 0) return Math.min(content, list.room)
    return Math.min(Style.space(160), list.room)
  }
  clip: true

  Flickable {
    id: channelFlickable
    anchors.fill: parent
    contentWidth: width
    contentHeight: channelListView.implicitHeight
    boundsBehavior: Flickable.StopAtBounds
    flickableDirection: Flickable.VerticalFlick
    clip: true

    Column {
      id: channelListView
      width: channelFlickable.width
      spacing: Style.space(4)

      Repeater {
        id: channelRepeater
        model: list.tv.displayChannels
        delegate: ChannelRow {
          tv: list.tv
          width: channelListView.width
        }
      }
    }
  }

  BorderSurface {
    anchors.right: parent.right
    anchors.top: parent.top
    anchors.bottom: parent.bottom
    anchors.margins: 2
    width: 4
    radius: 2
    color: Style.normalFillFor(list.tv.bar.foreground, Color.accent)
    visible: channelFlickable.contentHeight > channelFlickable.height

    Rectangle {
      width: parent.width
      radius: 2
      color: Color.accent
      height: Math.max(16, channelFlickable.height * (channelFlickable.height / Math.max(1, channelFlickable.contentHeight)))
      y: (channelFlickable.contentHeight > channelFlickable.height) ? ((channelFlickable.contentY / (channelFlickable.contentHeight - channelFlickable.height)) * (parent.height - height)) : 0
    }
  }
}
