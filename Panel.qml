import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "aislandener.galaxy-buds"
  ipcTarget: "aislandener.galaxy-buds"
  manageIpc: false

  // The helper lives in the plugin's service, mounted once per session; this
  // widget is mounted once per monitor and only renders what the service holds.
  readonly property var service: bar && bar.shell ? bar.shell.serviceFor(moduleName) : null
  readonly property var buds: service ? service.state : ({})

  readonly property bool connected: buds.connected === true
  readonly property string noise: String(buds.noise || "off")
  readonly property var battery: buds.battery || ({})
  readonly property var touch: buds.touch || ({})
  readonly property var modes: buds.modes || ["off", "anc", "ambient"]
  readonly property string deviceName: String(buds.name || "Galaxy Buds")

  // Models differ in what they can do at all: the Buds+ has no ANC and no
  // 360 Audio, the original Buds has no case battery. The helper simply omits
  // what the earbuds never report, so absence here means "hide the control".
  readonly property bool hasSpatial: buds.spatial !== undefined
  readonly property bool hasSeamless: buds.seamless !== undefined
  readonly property bool hasTouch: touch.enabled !== undefined
  readonly property bool hasModes: modes.length > 1
  readonly property var charging: buds.charging || ({})
  readonly property var codec: buds.codec || ({})
  readonly property var codecOptions: codec.options || []
  // Two pairs can be connected at once; this says whether the one being shown
  // is the one sound is actually going to.
  readonly property bool isAudioOutput: buds.is_default_output === true

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color urgent: bar ? bar.urgent : Color.urgent
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  // Every visible string can be replaced from this widget's shell.json entry:
  //   { "id": "aislandener.galaxy-buds", "labels": { "anc": "ANC", ... } }
  readonly property var labels: setting("labels", ({}))
  function t(key, fallback) {
    var value = labels ? labels[key] : undefined
    return value === undefined || value === null ? fallback : String(value)
  }

  // Without these the bar gives the widget zero width and nothing renders.
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  property int cursorIndex: 0
  property int groupIndex: 0

  // Flat list of keyboard-reachable rows. Each entry is one stop for the
  // up/down cursor: the noise-mode chips, each settings toggle, then the
  // codec chips. `groupIndex` is the chip highlighted inside a "modes" or
  // "codec" row — a plain int because only one chip row is focused at a time.
  readonly property var focusableRows: {
    var rows = []
    if (connected && hasModes) rows.push({type: "modes"})
    for (var i = 0; i < toggleRows.length; i++)
      rows.push({type: "toggle", index: i})
    if (codecOptions.length > 1) rows.push({type: "codec"})
    return rows
  }
  readonly property int cursorCount: focusableRows.length

  onOpenedChanged: {
    if (opened) selectCursor(0)
  }

  readonly property var modeOptions: {
    var names = {
      "off": t("off", "Off"),
      "anc": t("anc", "ANC"),
      "ambient": t("ambient", "Ambient"),
      "adaptive": t("adaptive", "Adaptive")
    }
    var out = []
    for (var i = 0; i < modes.length; i++)
      out.push({value: modes[i], label: names[modes[i]] || modes[i]})
    return out
  }

  readonly property var batteryRows: {
    var rows = []
    if (!connected) return rows
    if (battery.left !== undefined)
      rows.push({label: t("left", "L"), value: battery.left, charging: charging.left === true})
    if (battery.right !== undefined)
      rows.push({label: t("right", "R"), value: battery.right, charging: charging.right === true})
    // The case only reports its own charge while the earbuds sit in it.
    if (battery.case > 0)
      rows.push({label: t("case", "Case"), value: battery.case, charging: charging.case === true})
    return rows
  }

  readonly property var toggleRows: {
    var rows = []
    if (!connected) return rows
    if (hasSpatial)
      rows.push({key: "spatial", label: t("spatial", "360 Audio"), checked: buds.spatial === true})
    if (hasTouch)
      rows.push({key: "touch", label: t("touch", "Touch controls"), checked: touch.enabled === true})
    if (hasSeamless)
      rows.push({key: "seamless", label: t("seamless", "Quick connect"), checked: buds.seamless === true})
    return rows
  }

  function setNoise(mode) { if (service) service.setNoise(mode) }
  function cycle() { if (service) service.cycle() }
  function setToggle(name, value) { if (service) service.setToggle(name, value) }
  function setCodec(profile) { if (service) service.setCodec(profile) }

  // The glyph carries the mode on its own, the way the other bar icons do:
  // an ear that hears the room for ambient, a crossed-out one for ANC.
  function modeIcon() {
    if (!connected) return "󰟎"
    if (noise === "anc" || noise === "adaptive") return "󰋏"
    if (noise === "ambient") return "󰋎"
    return "󰋋"
  }

  // The cursor walks rows up/down and, on a chip row, walks chips left/right.
  // `focusedRow()` is the row the cursor sits on; `groupIndex` is the chip
  // within a "modes"/"codec" row. Landing on a chip row resets the chip to the
  // one currently active, so the user sees their existing choice first.
  function focusedRow() {
    return cursorIndex >= 0 && cursorIndex < focusableRows.length
      ? focusableRows[cursorIndex] : null
  }

  function optionValue(o) {
    return (o && typeof o === "object") ? String(o.value) : String(o)
  }

  function groupOptions(row) {
    if (!row) return []
    return row.type === "modes" ? root.modeOptions : root.codecOptions
  }

  function rowIndexFor(type) {
    for (var i = 0; i < focusableRows.length; i++)
      if (focusableRows[i].type === type) return i
    return -1
  }

  function toggleRowIndex(toggleIndex) {
    for (var i = 0; i < focusableRows.length; i++)
      if (focusableRows[i].type === "toggle" && focusableRows[i].index === toggleIndex)
        return i
    return -1
  }

  function selectCursor(index) {
    cursorIndex = Math.max(0, Math.min(cursorCount - 1, index))
    var row = focusedRow()
    if (row && (row.type === "modes" || row.type === "codec")) {
      var opts = groupOptions(row)
      var selected = row.type === "modes"
        ? modeGroup.selectedOptionIndex() : codecGroup.selectedOptionIndex()
      groupIndex = (selected < 0 || selected >= opts.length) ? 0 : selected
    }
  }

  function moveGroupCursor(delta) {
    var row = focusedRow()
    if (!row || (row.type !== "modes" && row.type !== "codec")) return
    var opts = groupOptions(row)
    if (opts.length <= 0) return
    if (groupIndex < 0) groupIndex = 0
    groupIndex = Math.max(0, Math.min(opts.length - 1, groupIndex + delta))
  }

  function activateCursor() {
    var row = focusedRow()
    if (!row) return
    if (row.type === "modes") {
      if (!connected) return
      var mode = root.modeOptions[groupIndex]
      if (mode) setNoise(mode.value)
    } else if (row.type === "toggle") {
      var toggle = root.toggleRows[row.index]
      if (toggle) setToggle(toggle.key, !toggle.checked)
    } else if (row.type === "codec") {
      var codec = root.codecOptions[groupIndex]
      if (codec !== undefined && codec !== null) setCodec(optionValue(codec))
    }
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.modeIcon()
    opacity: root.connected ? 1.0 : 0.5
    onPressed: function(mouseButton) {
      if (mouseButton === Qt.RightButton) root.cycle()
      else root.toggle()
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    // Codec buttons sit in one row, so the popover has to grow with them
    // rather than let the last one run past its edge.
    contentWidth: panel.fittedContentWidth(Style.space(root.codecOptions.length > 2 ? 400 : 320))
    // The cap only exists to stop a runaway panel; the real limit is the
    // screen. 420 cut the codec row off once battery, modes, three toggles and
    // codecs were all on screen at once.
    contentHeight: panel.fittedContentHeight(panelColumn.implicitHeight, Style.space(620))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onMoveRequested: function(dx, dy) {
        if (dy !== 0) root.selectCursor(root.cursorIndex + dy)
        else if (dx !== 0) root.moveGroupCursor(dx)
      }
      onActivateRequested: root.activateCursor()
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(text) {
        var index = ["1", "2", "3", "4"].indexOf(text)
        if (index >= 0 && index < root.modes.length && root.connected)
          root.setNoise(root.modes[index])
      }

      Column {
        id: panelColumn
        anchors.fill: parent
        spacing: Style.space(12)

        // ---------- Hero: headphones · device name ----------
        Item {
          width: parent.width
          implicitHeight: Math.max(heroIcon.implicitHeight, heroName.implicitHeight)

          Text {
            id: heroIcon
            text: root.modeIcon()
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.display
            opacity: root.connected ? 1.0 : 0.5
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
          }

          Column {
            anchors.left: heroIcon.right
            anchors.leftMargin: Style.space(14)
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(2)

            Text {
              id: heroName
              text: root.deviceName
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.title
              font.bold: true
              elide: Text.ElideRight
              width: parent.width
            }

            Text {
              // Worth saying out loud: with two pairs connected it is easy to
              // change the mode on the one you are not listening to.
              visible: root.connected && !root.isAudioOutput
              text: root.t("notOutput", "Not the audio output")
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              elide: Text.ElideRight
              width: parent.width
            }
          }
        }

        // ---------- Battery: one bar per earbud, plus the case ----------
        Column {
          width: parent.width
          spacing: Style.space(6)
          visible: root.batteryRows.length > 0

          Repeater {
            model: root.batteryRows

            Item {
              required property var modelData
              width: panelColumn.width
              height: Style.space(16)

              Text {
                id: cellLabel
                text: modelData.label
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                width: Style.space(34)
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
              }

              Rectangle {
                id: track
                anchors.left: cellLabel.right
                anchors.right: cellValue.left
                anchors.rightMargin: Style.space(8)
                anchors.verticalCenter: parent.verticalCenter
                height: Style.space(6)
                radius: height / 2
                color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.15)

                Rectangle {
                  width: Math.max(parent.height, parent.width * Math.max(0, Math.min(100, modelData.value)) / 100)
                  height: parent.height
                  radius: parent.radius
                  // A charge this low is the one thing here worth interrupting for.
                  color: modelData.value <= 20 ? root.urgent : root.foreground
                  Behavior on width { NumberAnimation { duration: 160 } }
                }
              }

              Text {
                id: cellValue
                // The bolt reads as "this number is going up", which is the
                // whole point of showing it while an earbud sits in the case.
                text: (modelData.charging ? "󰂄 " : "") + modelData.value + "%"
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                horizontalAlignment: Text.AlignRight
                width: Style.space(52)
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
              }
            }
          }
        }

        PanelSeparator {
          width: parent.width
          foreground: root.foreground
          visible: root.connected && root.hasModes
        }

        PanelSectionHeader {
          width: parent.width
          text: root.t("noiseControl", "Noise control")
          foreground: root.foreground
          fontFamily: root.fontFamily
          visible: root.connected && root.hasModes
        }

        ButtonGroup {
          id: modeGroup
          width: parent.width
          options: root.modeOptions
          value: root.noise
          foreground: root.foreground
          fontFamily: root.fontFamily
          visible: root.connected && root.hasModes
          cursorIndex: (root.focusedRow() && root.focusedRow().type === "modes") ? root.groupIndex : -1
          onChanged: function(value) {
            root.selectCursor(root.rowIndexFor("modes"))
            root.setNoise(value)
          }
          onHovered: function(index, isHovered) {
            if (isHovered) {
              root.selectCursor(root.rowIndexFor("modes"))
              root.groupIndex = index
            }
          }
        }

        PanelSectionHeader {
          width: parent.width
          text: root.t("settings", "Settings")
          foreground: root.foreground
          fontFamily: root.fontFamily
          visible: root.toggleRows.length > 0
        }

        Repeater {
          model: root.toggleRows

          Item {
            required property var modelData
            required property int index
            width: panelColumn.width
            height: Math.max(rowLabel.implicitHeight, rowSwitch.implicitHeight)

            Text {
              id: rowLabel
              text: modelData.label
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
            }

            ToggleSwitch {
              id: rowSwitch
              checked: modelData.checked
              hasCursor: root.cursorIndex === root.toggleRowIndex(index)
              foreground: root.foreground
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              onHovered: function(on) { if (on) root.selectCursor(root.toggleRowIndex(index)) }
              onToggled: root.setToggle(modelData.key, !modelData.checked)
            }
          }
        }

        PanelSectionHeader {
          width: parent.width
          // The automatic profile does not say which codec it settled on, and
          // that is the one thing worth knowing here. The mic glyph explains
          // why the music codecs are gone: something is holding the microphone.
          text: root.t("codec", "Codec")
                + (root.codec.codec ? "  ·  " + (root.codec.mode === "headset" ? "󰍬 " : "") + root.codec.codec : "")
          foreground: root.foreground
          fontFamily: root.fontFamily
          visible: root.codecOptions.length > 1
        }

        ButtonGroup {
          id: codecGroup
          width: parent.width
          options: root.codecOptions
          value: String(root.codec.active || "")
          foreground: root.foreground
          fontFamily: root.fontFamily
          visible: root.codecOptions.length > 1
          cursorIndex: (root.focusedRow() && root.focusedRow().type === "codec") ? root.groupIndex : -1
          onChanged: function(value) {
            root.selectCursor(root.rowIndexFor("codec"))
            root.setCodec(value)
          }
          onHovered: function(index, isHovered) {
            if (isHovered) {
              root.selectCursor(root.rowIndexFor("codec"))
              root.groupIndex = index
            }
          }
        }

        Text {
          width: parent.width
          visible: !root.connected
          text: !root.service
                ? root.t("serviceOff", "The plugin service is not running.")
                : root.buds.reason === "not paired"
                  ? root.t("notPaired", "No Galaxy Buds paired.")
                  : root.t("disconnected", "Disconnected. Take them out of the case to reconnect.")
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          wrapMode: Text.WordWrap
        }
      }
    }
  }
}
