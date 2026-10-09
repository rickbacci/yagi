import QtQuick
import qs.Ui
import qs.Commons

Row {
  id: filters
  required property var tv

  visible: filters.tv.showChannelBrowser
  spacing: Style.space(6)

  ChannelTabs {
    id: filterTabRow
    tv: filters.tv
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
    fontSize: Style.font.heading
    foreground: filters.tv.bar.foreground
    onClicked: filters.tv.startScan()
  }
}
