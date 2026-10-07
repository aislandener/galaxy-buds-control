#!/usr/bin/python3
"""Protocol checks that need no earbuds. Run: /usr/bin/python3 tests/test_protocol.py"""

import importlib.util
import json
import pathlib
import sys
from importlib.machinery import SourceFileLoader

# The daemon has no .py extension, so it needs an explicit source loader.
_path = pathlib.Path(__file__).resolve().parent.parent / "bin" / "galaxy-buds"
_spec = importlib.util.spec_from_loader("galaxy_buds", SourceFileLoader("galaxy_buds", str(_path)))
gb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gb)


def profile(name):
    for entry in gb.PROFILES:
        if entry["name"] == name:
            return entry
    raise AssertionError("no profile named " + name)


def test_crc_matches_reference_frame():
    # Frame documented in GalaxyBudsClient's Crc16.cs: msgId 0x61, then payload,
    # then CRC bytes 0x0F 0xF3.
    body = bytes([0x61, 0x02, 0x00, 0x4B, 0x5F, 0x01, 0x00, 0x00, 0x00, 0x01, 0x05, 0x00, 0x02, 0x00, 0x13])
    assert gb.crc16(body).to_bytes(2, "little") == bytes([0x0F, 0xF3])


def test_encode_shape():
    frame = gb.encode(gb.MSG_NOISE_CONTROLS, bytes([1]))
    assert frame[0] == gb.SOM and frame[-1] == gb.EOM
    assert frame[1:3] == (4).to_bytes(2, "little")  # msgId + 1 payload + 2 crc
    assert frame[3] == gb.MSG_NOISE_CONTROLS
    assert len(frame) == 8


def test_decode_round_trip():
    stream = gb.encode(gb.MSG_NOISE_CONTROLS, bytes([2])) + gb.encode(gb.MSG_STATUS, bytes(range(8)))
    messages, rest = gb.decode(stream)
    assert rest == b""
    assert messages == [(gb.MSG_NOISE_CONTROLS, bytes([2])), (gb.MSG_STATUS, bytes(range(8)))]


def test_decode_keeps_partial_frame_for_next_read():
    stream = gb.encode(gb.MSG_NOISE_CONTROLS_UPDATE, bytes([1]))
    messages, rest = gb.decode(stream[:5])
    assert messages == [] and rest == stream[:5]
    messages, rest = gb.decode(rest + stream[5:])
    assert messages == [(gb.MSG_NOISE_CONTROLS_UPDATE, bytes([1]))] and rest == b""


def test_decode_resynchronises_after_a_bad_frame():
    # A 0xFD that was really payload: the candidate frame completes but its CRC
    # and end byte are wrong, so the parser steps forward and finds the real one.
    garbage = bytes([0xFD, 0x04, 0x00, 0x63, 0x00, 0x00, 0x00, 0x00])
    frame = gb.encode(gb.MSG_NOISE_CONTROLS_UPDATE, bytes([2]))
    messages, rest = gb.decode(garbage + frame)
    assert messages == [(gb.MSG_NOISE_CONTROLS_UPDATE, bytes([2]))]
    assert rest == b""


def extended_payload():
    payload = bytearray(40)
    payload[0] = 5      # revision
    payload[2] = 97     # battery left
    payload[3] = 95     # battery right
    payload[6] = 0x11   # both worn
    payload[7] = 80     # battery case
    payload[10] = 0x8F  # touchpad unlocked, all four gestures on
    payload[12] = 2     # ambient
    payload[19] = 0     # seamless connection on
    payload[35] = 1     # 360 audio on
    return bytes(payload)


def test_parse_extended_status_buds2pro():
    state = gb.parse_extended_status(extended_payload(), profile("buds2pro"))
    assert state["noise"] == "ambient"
    assert state["battery"] == {"left": 97, "right": 95, "case": 80}
    assert state["wearing"] == {"left": 1, "right": 1}
    assert state["touch"]["enabled"] is True and state["touch"]["tap"] is True
    assert state["seamless"] is True
    assert state["spatial"] is True


def test_unknown_model_hides_spatial_but_keeps_the_rest():
    state = gb.parse_extended_status(extended_payload(), gb.UNKNOWN_PROFILE)
    assert "spatial" not in state
    assert state["noise"] == "ambient"


def test_parse_status():
    payload = bytes([5, 90, 88, 1, 0, 0x11, 70, 0x10])
    state = gb.parse_status(payload, profile("buds2pro"))
    assert state["battery"] == {"left": 90, "right": 88, "case": 70}
    assert state["charging"] == {"left": True, "right": False, "case": False}


def test_touchpad_locked_when_high_bit_clear():
    assert gb.parse_touch(0x0F, "bits7")["enabled"] is False
    assert gb.parse_touch(0x8F, "bits7")["enabled"] is True
    # Older models send one flag, and it means the opposite.
    assert gb.parse_touch(1, "byte")["enabled"] is False
    assert gb.parse_touch(0, "byte")["enabled"] is True


def test_device_id_resolves_to_profile():
    uuids = [gb.SPP_NEW, "d908aab5-7a90-4cbe-8641-86a553db0146"]
    assert gb.device_id_from_uuids(uuids) == 326
    assert gb.profile_for(uuids, "renamed by its owner")["name"] == "buds2pro"


def test_older_models_are_matched_by_name():
    # Buds+ and friends publish no device id, only plain SPP.
    assert gb.profile_for([gb.SPP_STANDARD], "Galaxy Buds+ (1A2B)")["name"] == "budsplus"
    assert gb.profile_for([gb.SPP_STANDARD], "Buds Live (7C3D)")["name"] == "budslive"
    assert gb.profile_for([gb.SPP_LEGACY], "Galaxy Buds (9F11)")["name"] == "buds"
    # "Buds2 Pro" must not be swallowed by the "Buds2" row.
    assert gb.profile_for([gb.SPP_NEW], "Buds2 Pro (0A0A)")["name"] == "buds2pro"
    assert gb.profile_for([gb.SPP_NEW], "Buds3 Pro (0A0A)")["name"] == "buds3pro"


def test_connected_pair_wins_when_two_are_paired():
    idle = ("/org/bluez/hci0/dev_A", {"Connected": False, "Alias": "Galaxy Buds+ (194D)"})
    live = ("/org/bluez/hci0/dev_B", {"Connected": True, "Alias": "Buds2 Pro"})
    assert gb.pick_device([idle, live])[0] == "/org/bluez/hci0/dev_B"
    assert gb.pick_device([live, idle])[0] == "/org/bluez/hci0/dev_B"
    # None connected: still name one, so the panel can say what it waits for.
    assert gb.pick_device([idle])[0] == "/org/bluez/hci0/dev_A"
    assert gb.pick_device([]) == (None, None)


def test_audio_output_decides_between_two_connected_pairs():
    plus = ("/dev_A", {"Connected": True, "Address": "AA:BB:CC:DD:EE:FF"})
    pro = ("/dev_B", {"Connected": True, "Address": "40:35:E6:0C:B4:A1"})
    # Both in your ears: the one you are listening through is the one you mean.
    assert gb.pick_device([plus, pro], "40:35:E6:0C:B4:A1")[0] == "/dev_B"
    # Sound going to the speakers: fall back to whichever is connected.
    assert gb.pick_device([plus, pro], "")[0] == "/dev_A"


def test_link_moves_to_whichever_pair_the_sound_goes_to():
    daemon = gb.Daemon()
    daemon.bus = None
    daemon.socket = object()          # already holding a link
    daemon.state["address"] = "AA:BB:CC:DD:EE:FF"
    daemon.find_device = lambda bus: ("/dev_B", {"Address": "40:35:E6:0C:B4:A1", "Connected": True})

    # Output switched to the other pair, and that pair is connected: hand over.
    daemon.default_address = "40:35:E6:0C:B4:A1"
    assert daemon.should_retarget() is True

    # Output is the pair we already hold: stay.
    daemon.default_address = "AA:BB:CC:DD:EE:FF"
    assert daemon.should_retarget() is False

    # Sound is coming out of the speakers: keep controlling what we have.
    daemon.default_address = ""
    assert daemon.should_retarget() is False

    # Output names a pair that is not there: do not drop a working link for it.
    daemon.default_address = "99:99:99:99:99:99"
    daemon.find_device = lambda bus: (None, None)
    assert daemon.should_retarget() is False


def test_address_from_sink_name():
    assert gb.address_from_sink("bluez_output.40_35_E6_0C_B4_A1.1") == "40:35:E6:0C:B4:A1"
    assert gb.address_from_sink("alsa_output.pci-0000_04_00.6.HiFi__Speaker__sink") == ""
    assert gb.address_from_sink(None) == ""


CARDS = json.dumps([
    {"name": "alsa_card.pci", "profiles": {}},
    {"name": "bluez_card.40_35_E6_0C_B4_A1",
     "active_profile": "a2dp-sink",
     "profiles": {
         "a2dp-sink": {"available": "yes"},
         "a2dp-sink-sbc": {"available": "yes"},
         "a2dp-sink-sbc_xq": {"available": "yes"},
         "a2dp-sink-ldac": {"available": "no"},
         "headset-head-unit": {"available": "yes",
                               "description": "Headset Head Unit (HSP/HFP, codec MSBC)"},
         "headset-head-unit-cvsd": {"available": "yes"},
     }},
])


def in_call(cards_json):
    """Same card, switched to the microphone profile the way PipeWire does
    when an app opens one."""
    cards = json.loads(cards_json)
    for card in cards:
        if card["name"].startswith("bluez_card"):
            card["active_profile"] = "headset-head-unit"
    return json.dumps(cards)

SINKS = json.dumps([
    {"name": "bluez_output.40_35_E6_0C_B4_A1.1",
     "properties": {"api.bluez5.address": "40:35:E6:0C:B4:A1", "api.bluez5.codec": "aac"}},
])


def test_read_codecs_offers_auto_and_the_pinned_profiles():
    codecs = gb.read_codecs(CARDS, SINKS, "40:35:E6:0C:B4:A1")
    # Auto first: it is the profile that picks the best codec both ends support.
    assert [o["label"] for o in codecs["options"]] == ["Auto", "SBC", "SBC-XQ"]
    assert codecs["mode"] == "a2dp"
    assert codecs["options"][0]["value"] == "a2dp-sink"
    # An unavailable profile is not an option.
    assert "LDAC" not in [o["label"] for o in codecs["options"]]
    # No blank buttons.
    assert all(o["label"] for o in codecs["options"])
    # A different pair's card is not this pair's codec list.
    assert gb.read_codecs(CARDS, SINKS, "AA:BB:CC:DD:EE:FF") is None


def test_codec_in_use_comes_from_the_sink():
    # The automatic profile is running AAC, which no profile name would reveal.
    codecs = gb.read_codecs(CARDS, SINKS, "40:35:E6:0C:B4:A1")
    assert codecs["active"] == "a2dp-sink"
    assert codecs["codec"] == "AAC"
    assert gb.active_codec(SINKS, "40:35:E6:0C:B4:A1") == "aac"
    assert gb.active_codec(SINKS, "AA:BB:CC:DD:EE:FF") == ""


def test_codec_labels_are_written_the_way_people_say_them():
    assert gb.codec_label("a2dp-sink-sbc_xq") == "SBC-XQ"
    assert gb.codec_label("a2dp-sink-aptx_hd") == "aptX HD"
    assert gb.codec_label("a2dp-sink-ldac") == "LDAC"
    # Something the table has never heard of still reads sanely.
    assert gb.codec_label("a2dp-sink-brand_new") == "BRAND-NEW"


def test_call_codecs_replace_the_music_ones_while_the_mic_is_open():
    codecs = gb.read_codecs(in_call(CARDS), SINKS, "40:35:E6:0C:B4:A1")
    # The music codecs are not choices at all in this mode.
    assert [o["label"] for o in codecs["options"]] == ["mSBC", "CVSD"]
    assert codecs["mode"] == "headset"
    assert codecs["active"] == "headset-head-unit"


def test_headset_codec_is_read_from_the_description():
    # Plain "headset-head-unit" is mSBC, and only its description says so.
    assert gb.codec_label("headset-head-unit",
                          "Headset Head Unit (HSP/HFP, codec MSBC)") == "mSBC"
    # Translated descriptions keep the codec word.
    assert gb.codec_label("headset-head-unit",
                          "Unidade de headset (HSP/HFP, codec MSBC)") == "mSBC"
    assert gb.codec_label("headset-head-unit-cvsd") == "CVSD"
    # No codec anywhere and not the generic A2DP profile: nothing to label.
    assert gb.codec_label("headset-head-unit", "") == ""


def test_charging_is_only_read_where_the_model_reports_it():
    payload = bytes([5, 90, 88, 1, 0, 0x11, 70, 0x10])
    assert gb.parse_status(payload, profile("buds2pro"))["charging"]["left"] is True
    # Buds+ puts something else in that byte.
    assert "charging" not in gb.parse_status(payload, profile("budsplus"))


def test_plain_spp_devices_are_not_mistaken_for_earbuds():
    assert gb.looks_like_earbuds([gb.SPP_STANDARD], "Keychron K6 Pro") is False
    assert gb.looks_like_earbuds([gb.SPP_STANDARD], "Galaxy Buds+ (1A2B)") is True
    assert gb.looks_like_earbuds([gb.SPP_NEW], "renamed") is True


def budsplus_payload():
    """Buds+ layout: ambient is a flag at 8, touch lock a byte at 12, and
    quick connect only exists from revision 11."""
    payload = bytearray(24)
    payload[0] = 12     # revision
    payload[2] = 70     # battery left
    payload[3] = 68     # battery right
    payload[6] = 0x11   # both worn
    payload[7] = 55     # battery case
    payload[8] = 1      # ambient sound on
    payload[12] = 0     # touchpad unlocked
    payload[21] = 0     # quick connect on
    return bytes(payload)


def test_parse_extended_status_budsplus():
    state = gb.parse_extended_status(budsplus_payload(), profile("budsplus"))
    assert state["noise"] == "ambient"
    assert state["battery"] == {"left": 70, "right": 68, "case": 55}
    assert state["touch"]["enabled"] is True
    assert state["seamless"] is True
    # No 360 Audio on this model: hidden, not guessed.
    assert "spatial" not in state


def test_budsplus_hides_quick_connect_on_old_firmware():
    payload = bytearray(budsplus_payload())
    payload[0] = 9  # revision below the one that reports it
    state = gb.parse_extended_status(bytes(payload), profile("budsplus"))
    assert "seamless" not in state


def test_original_buds_have_no_case_battery():
    payload = bytearray(20)
    payload[2], payload[3] = 60, 58
    payload[6] = 3   # legacy wear state: both
    payload[7] = 1   # ambient on
    state = gb.parse_extended_status(bytes(payload), profile("buds"))
    assert state["battery"] == {"left": 60, "right": 58}
    assert state["wearing"] == {"left": 1, "right": 1}
    assert state["noise"] == "ambient"


def test_noise_command_per_model():
    # Three modes on the newer models...
    assert gb.noise_command("controls", "ambient") == (gb.MSG_NOISE_CONTROLS, bytes([2]))
    # ...ambient sound is a plain toggle on Buds and Buds+...
    assert gb.noise_command("ambient", "ambient") == (gb.MSG_SET_AMBIENT_MODE, bytes([1]))
    assert gb.noise_command("ambient", "off") == (gb.MSG_SET_AMBIENT_MODE, bytes([0]))
    # ...and Buds Live only has ANC on/off.
    assert gb.noise_command("anc", "anc") == (gb.MSG_SET_NOISE_REDUCTION, bytes([1]))


def test_legacy_framing_round_trip():
    frame = gb.encode(gb.MSG_SET_AMBIENT_MODE, bytes([1]), legacy=True)
    assert frame[0] == gb.LEGACY_SOM and frame[-1] == gb.LEGACY_EOM
    assert frame[1] == 0 and frame[2] == 4  # type byte, then size byte
    messages, rest = gb.decode(frame, legacy=True)
    assert messages == [(gb.MSG_SET_AMBIENT_MODE, bytes([1]))] and rest == b""


def test_lock_payload_restores_gestures():
    touch = {"tap": True, "double": False, "triple": True, "hold": False,
             "double_call": True, "hold_call": False}
    assert gb.lock_payload("bits7", True, touch) == bytes([1, 1, 0, 1, 0, 1, 0])
    assert gb.lock_payload("bits7", False, touch) == bytes([0, 1, 0, 1, 0, 1, 0])
    # Turning gestures back on when none are set must not leave a dead touchpad.
    assert gb.lock_payload("bits7", True, {}) == bytes([1, 1, 1, 1, 1, 0, 0])
    assert gb.lock_payload("byte", False, touch) == bytes([1])


def test_cycle_wraps_through_the_models_modes_two_mode_model():
    daemon = gb.Daemon()
    daemon.profile = profile("budsplus")
    daemon.state.update({"modes": ["off", "ambient"], "noise": "ambient"})
    sent = []
    daemon.send = lambda msg_id, payload=b"": sent.append((msg_id, payload))
    daemon.emit = lambda: None
    daemon.command('{"cmd":"cycle"}')
    assert sent == [(gb.MSG_SET_AMBIENT_MODE, bytes([0]))]


def test_unsupported_toggles_are_ignored():
    daemon = gb.Daemon()
    daemon.profile = profile("budsplus")
    daemon.emit = lambda: None
    sent = []
    daemon.send = lambda *a, **k: sent.append(a)
    daemon.command('{"cmd":"spatial","value":true}')
    assert sent == []


def test_cycle_wraps_through_the_models_modes():
    daemon = gb.Daemon()
    daemon.profile = profile("buds2pro")
    daemon.state.update({"modes": ["off", "anc", "ambient"], "noise": "ambient"})
    sent = []
    daemon.send = lambda msg_id, payload=b"": sent.append((msg_id, payload))
    daemon.emit = lambda: None
    daemon.command('{"cmd":"cycle"}')
    assert sent == [(gb.MSG_NOISE_CONTROLS, bytes([0]))]


def test_ack_applies_the_value_the_earbuds_report():
    daemon = gb.Daemon()
    daemon.state["touch"] = {"enabled": False, "tap": True}
    daemon.emit = lambda: None
    daemon.handle_ack(gb.MSG_NOISE_CONTROLS, bytes([2]))
    assert daemon.state["noise"] == "ambient"
    daemon.handle_ack(gb.MSG_SET_SPATIAL_AUDIO, bytes([1]))
    assert daemon.state["spatial"] is True
    # Seamless is inverted coming back too.
    daemon.handle_ack(gb.MSG_SET_SEAMLESS_CONNECTION, bytes([0]))
    assert daemon.state["seamless"] is True
    daemon.handle_ack(gb.MSG_LOCK_TOUCHPAD, bytes([1]))
    assert daemon.state["touch"] == {"enabled": True, "tap": True}


def test_commands_do_not_guess_state_before_the_ack():
    daemon = gb.Daemon()
    daemon.profile = profile("buds2pro")
    daemon.emit = lambda: None
    daemon.send = lambda *a, **k: None
    daemon.command('{"cmd":"spatial","value":true}')
    assert "spatial" not in daemon.state


def test_stdin_handles_two_commands_arriving_together():
    import os
    read_fd, write_fd = os.pipe()
    daemon = gb.Daemon()
    daemon.profile = profile("buds2pro")
    daemon.state["modes"] = ["off", "anc", "ambient"]
    daemon.emit = lambda: None
    sent = []
    daemon.send = lambda msg_id, payload=b"": sent.append(payload)
    os.write(write_fd, b'{"cmd":"noise","value":"off"}\n{"cmd":"noise","value":"anc"}\n')
    daemon.on_stdin(read_fd, 0)
    os.close(write_fd)
    os.close(read_fd)
    assert sent == [bytes([0]), bytes([1])]


def test_seamless_is_inverted_on_the_wire():
    daemon = gb.Daemon()
    daemon.profile = profile("buds2pro")
    sent = []
    daemon.send = lambda msg_id, payload=b"": sent.append((msg_id, payload))
    daemon.emit = lambda: None
    daemon.command('{"cmd":"seamless","value":true}')
    assert sent == [(gb.MSG_SET_SEAMLESS_CONNECTION, bytes([0]))]


def buds4pro_payload():
    # Laid out after GalaxyBudsClient's decoder for Buds3 Pro and newer: the
    # shared bytes up to 35, then the Pro fields that follow call path control.
    payload = bytearray(extended_payload())
    payload = payload + bytes(20)
    payload[12] = 3      # adaptive
    payload[24] = 1      # ANC level high
    payload[26] = 1      # voice detect on
    payload[41] = 0      # head tracking off
    payload[43] = 1      # extra clear call sound on
    payload[45] = 1      # auto pause and resume on
    payload[49] = 0      # adaptive volume off
    payload[52] = 1      # siren detect on
    return bytes(payload)


def test_buds4pro_device_ids_resolve_to_profile():
    for tail in ("0167", "0168", "0169"):
        uuids = [gb.SPP_NEW, "d908aab5-7a90-4cbe-8641-86a553db" + tail]
        assert gb.profile_for(uuids, "Ram's Buds4 Pro")["name"] == "buds4pro"
    assert gb.profile_for([gb.SPP_NEW, "d908aab5-7a90-4cbe-8641-86a553db0163"], "x")["name"] == "buds4"
    # "Buds4 Pro" must not be swallowed by the "Buds4" row when matching by name.
    assert gb.profile_for([gb.SPP_NEW], "Buds4 Pro (0A0A)")["name"] == "buds4pro"
    assert gb.profile_for([gb.SPP_NEW], "Buds4 (0A0A)")["name"] == "buds4"


def test_parse_extended_status_buds4pro():
    state = gb.parse_extended_status(buds4pro_payload(), profile("buds4pro"))
    assert state["noise"] == "adaptive"
    assert state["battery"] == {"left": 97, "right": 95, "case": 80}
    assert state["spatial"] is True
    assert state["anc_high"] is True
    assert state["voice_detect"] is True
    assert state["head_tracking"] is False
    assert state["extra_clear_call"] is True
    assert state["auto_pause"] is True
    assert state["adaptive_volume"] is False
    assert state["siren_detect"] is True


def test_pro_extras_are_hidden_on_other_models():
    state = gb.parse_extended_status(buds4pro_payload(), profile("buds2pro"))
    for key in gb.PRO_EXTRAS:
        assert key not in state
    # A short payload from older firmware stops before the Pro bytes.
    state = gb.parse_extended_status(extended_payload(), profile("buds4pro"))
    assert "siren_detect" not in state and state["anc_high"] is False


def test_buds4pro_offers_adaptive_mode():
    daemon = gb.Daemon()
    daemon.profile = profile("buds4pro")
    daemon.state.update({"modes": list(profile("buds4pro")["modes"]), "noise": "ambient"})
    sent = []
    daemon.send = lambda msg_id, payload=b"": sent.append((msg_id, payload))
    daemon.emit = lambda: None
    daemon.command('{"cmd":"noise","value":"adaptive"}')
    daemon.command('{"cmd":"cycle"}')
    assert sent == [(gb.MSG_NOISE_CONTROLS, bytes([3])), (gb.MSG_NOISE_CONTROLS, bytes([3]))]
    assert gb.read_noise(3, "controls") == "adaptive"


def test_pro_toggles_use_their_own_commands():
    daemon = gb.Daemon()
    daemon.profile = profile("buds4pro")
    sent = []
    daemon.send = lambda msg_id, payload=b"": sent.append((msg_id, payload))
    daemon.emit = lambda: None
    daemon.command('{"cmd":"voice_detect","value":true}')
    daemon.command('{"cmd":"anc_high","value":false}')
    daemon.command('{"cmd":"extra_clear_call","value":true}')
    # Phone-only settings have no command and are ignored.
    daemon.command('{"cmd":"siren_detect","value":true}')
    daemon.command('{"cmd":"head_tracking","value":true}')
    assert sent == [(gb.MSG_SET_DETECT_CONVERSATIONS, bytes([1])),
                    (gb.MSG_NOISE_REDUCTION_LEVEL, bytes([0])),
                    (gb.MSG_EXTRA_CLEAR_CALL, bytes([1]))]


def test_pro_toggles_are_ignored_on_models_without_them():
    daemon = gb.Daemon()
    daemon.profile = profile("buds2pro")
    daemon.emit = lambda: None
    sent = []
    daemon.send = lambda *a, **k: sent.append(a)
    daemon.command('{"cmd":"voice_detect","value":true}')
    assert sent == []


def test_pro_acks_apply_the_reported_value():
    daemon = gb.Daemon()
    daemon.emit = lambda: None
    daemon.handle_ack(gb.MSG_SET_DETECT_CONVERSATIONS, bytes([1]))
    daemon.handle_ack(gb.MSG_NOISE_REDUCTION_LEVEL, bytes([0]))
    daemon.handle_ack(gb.MSG_EXTRA_CLEAR_CALL, bytes([1]))
    assert daemon.state["voice_detect"] is True
    assert daemon.state["anc_high"] is False
    assert daemon.state["extra_clear_call"] is True


if __name__ == "__main__":
    failures = 0
    for name, test in sorted(globals().items()):
        if not name.startswith("test_"):
            continue
        try:
            test()
            print(f"ok   {name}")
        except AssertionError as error:
            failures += 1
            print(f"FAIL {name}: {error}")
    sys.exit(1 if failures else 0)
