import QtQuick
import qs.Ui
import qs.Commons

// Favorites / All / Hidden. The channel list and the Guide share one setting.
Row {
  id: tabs
  required property var tv

  spacing: Style.space(4)

  Button {
    text: "Favorites (" + tabs.tv.favoriteVisibleCount + ")"
    tooltipText: "Channels you starred"
    selected: tabs.tv.channelFilter === "favorites"
    fontSize: Style.font.heading
    foreground: tabs.tv.bar.foreground
    onClicked: tabs.tv.setChannelFilter("favorites")
  }

  Button {
    text: "All (" + (tabs.tv.watchableChannels ? tabs.tv.watchableChannels.length : 0) + ")"
    tooltipText: "Every channel you haven't hidden"
    selected: tabs.tv.channelFilter === "all"
    fontSize: Style.font.heading
    foreground: tabs.tv.bar.foreground
    onClicked: tabs.tv.setChannelFilter("all")
  }

  Button {
    visible: tabs.tv.hiddenData && tabs.tv.hiddenData.length > 0
    text: "Hidden (" + tabs.tv.hiddenData.length + ")"
    tooltipText: "Channels you hid"
    selected: tabs.tv.channelFilter === "hidden"
    fontSize: Style.font.heading
    foreground: tabs.tv.bar.foreground
    onClicked: tabs.tv.setChannelFilter("hidden")
  }
}
