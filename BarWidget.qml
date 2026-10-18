import QtQuick
import Quickshell
import qs.Ui

// Bar entry point for the Omarchy App Manager: a single launcher button.
// Left click spawns run_final.sh from the plugin folder, so the widget works
// both from this checkout and from an installed copy under
// ~/.config/omarchy/plugins/<id>/.
BarWidget {
  id: root
  moduleName: "com.mostafa.omarchy-app-manager"

  // Absolute path of the plugin folder (decode the file:// URL so spaces and
  // other escaped characters survive).
  readonly property string pluginDir: {
    var url = Qt.resolvedUrl(".").toString()
    if (url.indexOf("file://") === 0) url = url.substring(7)
    if (url.length > 1 && url.charAt(url.length - 1) === "/") url = url.substring(0, url.length - 1)
    return decodeURIComponent(url)
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "󰀻"
    fontFamily: "JetBrainsMono Nerd Font"
    tooltipText: "Launch Omarchy App Manager"
    horizontalMargin: 8.5
    onPressed: function(buttonCode) {
      if (buttonCode === Qt.LeftButton)
        Quickshell.execDetached([root.pluginDir + "/run_final.sh"])
    }
  }
}
