import pytest
from flitsmeister_dot_ble import animations
from flitsmeister_dot_ble.exceptions import DotValidationError


def test_startup() -> None:
    assert animations.startup().to_bytes() == bytes.fromhex("0bff00284a0000000000")


def test_fade_out() -> None:
    assert animations.fade_out().to_bytes() == bytes.fromhex("04000000000000000000")


def test_fade_out_without_cut_off() -> None:
    assert animations.fade_out_without_cut_off().to_bytes() == bytes.fromhex(
        "04000000000000000001"
    )


def test_speed_trap() -> None:
    assert animations.speed_trap().to_bytes() == bytes.fromhex("01ff00284a030c200100")


def test_speed_trap_not_rateable() -> None:
    assert animations.speed_trap(rateable=False).to_bytes() == bytes.fromhex(
        "01ff00284a030c200000"
    )


def test_speed_cam() -> None:
    assert animations.speed_cam().to_bytes() == bytes.fromhex("01ff02f2ff030c210100")


def test_traffic_camera() -> None:
    assert animations.traffic_camera().to_bytes() == bytes.fromhex(
        "01ff02f2ff033f000100"
    )


def test_avg_speed_check_start() -> None:
    assert animations.avg_speed_check_start().to_bytes() == bytes.fromhex(
        "01ff0000ce020a220100"
    )


def test_avg_speed_check_end() -> None:
    assert animations.avg_speed_check_end().to_bytes() == bytes.fromhex(
        "02ff0000ce000d230000"
    )


def test_traffic_jam_start() -> None:
    assert animations.traffic_jam_start().to_bytes() == bytes.fromhex(
        "01ffff3000020b1e0000"
    )


def test_traffic_jam_end() -> None:
    assert animations.traffic_jam_end().to_bytes() == bytes.fromhex(
        "02ffff30000007000000"
    )


def test_police_hotspot() -> None:
    assert animations.police_hotspot().to_bytes() == bytes.fromhex(
        "01ff8000ff0308240100"
    )


def test_roadworks() -> None:
    assert animations.roadworks().to_bytes() == bytes.fromhex("01ffff3000020b1f0100")


def test_incident() -> None:
    animation = animations.incident(speech=animations.DotSound.SPEECH_ACCIDENT)

    assert animation.to_bytes() == bytes.fromhex("01ffff0505020b260100")


def test_incident_not_rateable() -> None:
    animation = animations.incident(
        speech=animations.DotSound.SPEECH_ACCIDENT, rateable=False
    )

    assert animation.to_bytes() == bytes.fromhex("01ffff0505020b260000")


def test_lane_closure() -> None:
    left = animations.lane_closure(speech=animations.DotSound.SPEECH_LEFT_LANE_CLOSED)
    middle = animations.lane_closure(speech=animations.DotSound.SPEECH_LANE_CLOSED)
    right = animations.lane_closure(speech=animations.DotSound.SPEECH_RIGHT_LANE_CLOSED)

    assert left.to_bytes() == bytes.fromhex("01ffff0505030b410000")
    assert middle.to_bytes() == bytes.fromhex("01ffff0505030b400000")
    assert right.to_bytes() == bytes.fromhex("01ffff0505030b420000")


def test_ambulance() -> None:
    assert animations.ambulance().to_bytes() == bytes.fromhex("06ff00284a04052a0000")


def test_fire_truck() -> None:
    assert animations.fire_truck().to_bytes() == bytes.fromhex("06ff00284a04062b0000")


def test_police() -> None:
    assert animations.police().to_bytes() == bytes.fromhex("01ff00284a0406000000")


def test_emergency_vehicle() -> None:
    assert animations.emergency_vehicle().to_bytes() == bytes.fromhex(
        "01ffff05050406290000"
    )


def test_railway_crossing() -> None:
    assert animations.railway_crossing().to_bytes() == bytes.fromhex(
        "01ffff0505000b3b0000"
    )


def test_wrong_way_driving() -> None:
    assert animations.wrong_way_driving().to_bytes() == bytes.fromhex(
        "07ffff0505000f000000"
    )


def test_wrong_way_driver() -> None:
    assert animations.wrong_way_driver().to_bytes() == bytes.fromhex(
        "01ffff050502103c0100"
    )


def test_progress() -> None:
    animation = animations.progress(color=animations.DotColor.SPEED_TRAP, fraction=0.5)

    assert animation.to_bytes() == bytes.fromhex("03ff00284a0400000001")


def test_progress_clamps_the_led_count() -> None:
    color = animations.DotColor.SUCCESS

    assert animations.progress(color=color, fraction=0.0).value == 1
    assert animations.progress(color=color, fraction=0.5).value == 4
    assert animations.progress(color=color, fraction=1.0).value == 8
    assert animations.progress(color=color, fraction=1.5).value == 8


def test_progress_rounds_halves_up_like_the_app() -> None:
    color = animations.DotColor.SUCCESS

    assert animations.progress(color=color, fraction=0.3125).value == 3
    assert animations.progress(color=color, fraction=0.25).value == 2


def test_overspeed() -> None:
    assert animations.overspeed(fraction=0.5).to_bytes() == bytes.fromhex(
        "05ffff05050409000000"
    )


def test_overspeed_clamps_the_led_count() -> None:
    assert animations.overspeed(fraction=0.0).value == 1
    assert animations.overspeed(fraction=0.5).value == 4
    assert animations.overspeed(fraction=1.0).value == 8
    assert animations.overspeed(fraction=1.5).value == 8


def test_reporting() -> None:
    assert animations.reporting().to_bytes() == bytes.fromhex("08000000000004000000")


def test_brightness_sample() -> None:
    assert animations.brightness_sample().to_bytes() == bytes.fromhex(
        "03ffffffff0800000001"
    )


def test_orientation_sample() -> None:
    assert animations.orientation_sample().to_bytes() == bytes.fromhex(
        "01ff00284a0000000001"
    )


def test_updating() -> None:
    assert animations.updating().to_bytes() == bytes.fromhex("02ffffffff0000000000")


def test_to_bytes_accepts_a_custom_color() -> None:
    animation = animations.DotAnimation(
        type=animations.DotAnimationType.PROGRESSION_TOP_TO_BOTTOM,
        color=0x12345678,
        value=2,
    )

    assert animation.to_bytes() == bytes.fromhex("03123456780200000001")


def test_to_bytes_rejects_a_color_above_the_32_bit_range() -> None:
    animation = animations.DotAnimation(
        type=animations.DotAnimationType.WAVE,
        color=0x100000000,
    )

    with pytest.raises(DotValidationError):
        animation.to_bytes()


def test_to_bytes_rejects_a_negative_color() -> None:
    animation = animations.DotAnimation(
        type=animations.DotAnimationType.WAVE,
        color=-1,
    )

    with pytest.raises(DotValidationError):
        animation.to_bytes()


def test_to_bytes_rejects_a_value_above_one_byte() -> None:
    animation = animations.DotAnimation(
        type=animations.DotAnimationType.PROGRESSION_TOP_TO_BOTTOM,
        value=256,
    )

    with pytest.raises(DotValidationError):
        animation.to_bytes()


def test_sound_enum_covers_every_named_sound() -> None:
    assert len(animations.DotSound) == 53
    assert {sound.value for sound in animations.DotSound} == {
        0,
        *range(1, 14),
        15,
        16,
        *range(30, 67),
    }


def test_sound_ids_match_the_protocol() -> None:
    assert animations.DotSound.NO_AUDIO.value == 0
    assert animations.DotSound.SFX_SPEED_CAMERA.value == 12
    assert animations.DotSound.SPEECH_SPEED_TRAP.value == 32
    assert animations.DotSound.SPEECH_RIGHT_LANE_CLOSED.value == 66


def test_color_enum_covers_every_named_color() -> None:
    assert len(animations.DotColor) == 8
    assert animations.DotColor.DANGER.value == 0xFFFF0505
    assert animations.DotColor.SUCCESS.value == 0xFF003B09
