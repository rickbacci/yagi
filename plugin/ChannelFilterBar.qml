import QtQuick
import qs.Ui
import qs.Commons

Row {
  id: filters
  required property var tv

  visible: filters.tv.showChannelBrowser
  spacing: Style.space(6)

  Row {
    id: filterTabRow
    spacing: Style.space(4)

    Button {
      text: "Favorites (" + filters.tv.favoriteVisibleCount + ")"
      tooltipText: "Channels you starred"
      selected: filters.tv.channelFilter === "favorites"
      fontSize: Style.font.caption
      foreground: filters.tv.bar.foreground
      onClicked: filters.tv.setChannelFilter("favorites")
    }

    Button {
      text: "All (" + (filters.tv.watchableChannels ? filters.tv.watchableChannels.length : 0) + ")"
      tooltipText: "Every channel you haven't hidden"
      selected: filters.tv.channelFilter === "all"
      fontSize: Style.font.caption
      foreground: filters.tv.bar.foreground
      onClicked: filters.tv.setChannelFilter("all")
    }

    Button {
      visible: filters.tv.hiddenData && filters.tv.hiddenData.length > 0
      text: "Hidden (" + filters.tv.hiddenData.length + ")"
      tooltipText: "Channels you hid"
      selected: filters.tv.channelFilter === "hidden"
      fontSize: Style.font.caption
      foreground: filters.tv.bar.foreground
      onClicked: filters.tv.setChannelFilter("hidden")
    }
  }

  Item {
    width: Math.max(0, parent.width - filterTabRow.width - rescanBtn.width - parent.spacing * 2)
    height: 1
  }

  Button {
    id: rescanBtn
    visible: filters.tv.channelsData.length > 0 && !filters.tv.isScanning
    text: "Rescan"
    tooltipText: "Look for channels again. Takes a free tuner for a few minutes"
    enabled: filters.tv.tunersFree > 0
    fontSize: Style.font.caption
    foreground: filters.tv.bar.foreground
    onClicked: filters.tv.startScan()
  }
}
