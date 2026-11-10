"""Animations the DOT plays on its LED ring and speaker.

``DotAnimation`` holds one animation and ``to_bytes`` builds the
10-byte packet for the animation characteristic. The preset functions
return the packets the Flitsmeister app sends for each situation,
``PROTOCOL.md`` in the repository root documents the wire format.
"""

from dataclasses import dataclass
from enum import IntEnum
from math import floor

from .exceptions import DotValidationError

__all__ = [
    "DotAnimation",
    "DotAnimationType",
    "DotColor",
    "DotEnd",
    "DotSound",
    "ambulance",
    "avg_speed_check_end",
    "avg_speed_check_start",
    "brightness_sample",
    "emergency_vehicle",
    "fade_out",
    "fade_out_without_cut_off",
    "fire_truck",
    "incident",
    "lane_closure",
    "orientation_sample",
    "overspeed",
    "police",
    "police_hotspot",
    "progress",
    "railway_crossing",
    "reporting",
    "roadworks",
    "speed_cam",
    "speed_trap",
    "startup",
    "traffic_camera",
    "traffic_jam_end",
    "traffic_jam_start",
    "updating",
    "wrong_way_driver",
    "wrong_way_driving",
]


class DotAnimationType(IntEnum):
    """Pattern the LEDs play, byte 0 of the animation packet."""

    NONE = 0
    MID_TO_OUTWARD_AND_BREATHE = 1
    WAVE = 2
    PROGRESSION_TOP_TO_BOTTOM = 3
    FADE_OUT = 4
    PROGRESSION_BLINK = 5
    BLINK_DOWN_UP_AND_MID_TO_OUT = 6
    FLASH_AND_STATIC = 7
    REPORTING = 8
    BLUETOOTH_CONNECTED = 9
    WAITING_TO_DRIVE = 10
    START_DRIVING = 11


class DotColor(IntEnum):
    """Named ARGB colors of the LED ring.

    ``DotAnimation.color`` also accepts any custom 32-bit ARGB int.
    """

    DANGER = 0xFFFF0505
    AVG_SPEED_CHECK = 0xFF0000CE
    SPEED_TRAP = 0xFF00284A
    SPEED_CAM = 0xFF02F2FF
    WHITE = 0xFFFFFFFF
    PRO = 0xFF8000FF
    SUCCESS = 0xFF003B09
    WARNING = 0xFFFF3000


class DotEnd(IntEnum):
    """What the device does when the animation ends, byte 8."""

    FADE_OUT = 0
    RATE = 1
    PROGRESSION = 2


class DotSound(IntEnum):
    """Sound the DOT speaker plays, bytes 6 and 7 of the packet.

    Slot 14 and slots 17 to 29 carry no sound, the Flitsmeister app
    leaves them unused.
    """

    NO_AUDIO = 0
    SFX_ERROR = 1
    SFX_EXIT = 2
    SFX_SOUND_LOGO_SHORT = 3
    SFX_CONFIRM = 4
    SFX_AMBULANCE = 5
    SFX_EMERGENCY_VEHICLE = 6
    SFX_END_OF_REPORT = 7
    SFX_POLICE_HOTSPOT = 8
    SFX_REDUCE_SPEED = 9
    SFX_AVG_SPEED_CHECK_START = 10
    SFX_SAFETY_NOTIFICATION_2 = 11
    SFX_SPEED_CAMERA = 12
    SFX_AVG_SPEED_CHECK_END = 13
    SFX_WRONG_DIRECTION = 15
    SFX_WRONG_WAY_DRIVER = 16
    SPEECH_TRAFFIC_JAM = 30
    SPEECH_ROADWORKS = 31
    SPEECH_SPEED_TRAP = 32
    SPEECH_SPEED_CAM = 33
    SPEECH_AVG_SPEED_CHECK = 34
    SPEECH_END_OF_AVG_SPEED_CHECK = 35
    SPEECH_HOTSPOT = 36
    SPEECH_DANGEROUS_SITUATION_1 = 37
    SPEECH_ACCIDENT = 38
    SPEECH_STATIONARY_VEHICLE = 39
    SPEECH_OBJECT_ON_ROAD = 40
    SPEECH_EMERGENCY_VEHICLE = 41
    SPEECH_AMBULANCE = 42
    SPEECH_FIRE_TRUCK = 43
    SPEECH_SLIPPERY_ROAD = 44
    SPEECH_BUMPY_ROAD = 45
    SPEECH_ANIMAL_ON_THE_ROAD = 46
    SPEECH_PERSON_ON_THE_ROAD = 47
    SPEECH_DANGEROUS_SITUATION_2 = 48
    SPEECH_IMPACT_ATTENUATOR = 49
    SPEECH_TEXT_CAR = 50
    SPEECH_DANGEROUS_SITUATION_3 = 51
    SPEECH_REINDEER_ON_ROAD = 52
    SPEECH_MOOSE_NEARBY = 53
    SPEECH_POOR_VISIBILITY = 54
    SPEECH_SNOW_ON_ROAD = 55
    SPEECH_STRONG_WIND = 56
    SPEECH_ICE_ON_ROAD = 57
    SPEECH_REINDEER_NEAR_ROAD = 58
    SPEECH_RAILWAY_CROSSING = 59
    SPEECH_WRONG_WAY_DRIVER = 60
    SPEECH_WRONG_WAY_DRIVING = 61
    SPEECH_BRIDGE_OPEN = 62
    SPEECH_TRAFFIC_CAMERA = 63
    SPEECH_LANE_CLOSED = 64
    SPEECH_LEFT_LANE_CLOSED = 65
    SPEECH_RIGHT_LANE_CLOSED = 66


@dataclass(frozen=True, slots=True)
class DotAnimation:
    """One animation for the DOT LED ring and speaker.

    Attributes:
        type: The pattern the LEDs play.
        color: The ARGB color, a ``DotColor`` member or a custom
            32-bit int.
        value: The number of LEDs to light, for the progression types.
        primary_sound: The sound the speaker plays first.
        secondary_sound: The sound the speaker plays after the primary
            one.
        end: What the device does when the animation ends.
        cut_off: Whether the packet stops the animation already running
            on the device.
    """

    type: DotAnimationType
    color: int | None = None
    value: int | None = None
    primary_sound: DotSound | None = None
    secondary_sound: DotSound | None = None
    end: DotEnd | None = None
    cut_off: bool = False

    def to_bytes(self) -> bytes:
        """Build the 10-byte packet for the animation characteristic.

        Returns:
            The packet with the type, color, value, primary sound,
            secondary sound, end behavior and cut off flag.

        Raises:
            DotValidationError: The color is not a 32-bit value or the
                value does not fit one byte.
        """
        if self.color is not None and not 0 <= self.color <= 0xFFFFFFFF:
            raise DotValidationError(f"Color {self.color} is not a 32-bit value")
        if self.value is not None and not 0 <= self.value <= 0xFF:
            raise DotValidationError(f"Value {self.value} does not fit one byte")
        color = (
            self.color.to_bytes(4, "big")
            if self.color is not None
            else b"\x00\x00\x00\x00"
        )
        return bytes(
            (
                self.type,
                *color,
                self.value or 0,
                self.primary_sound or 0,
                self.secondary_sound or 0,
                self.end or 0,
                0 if self.cut_off else 1,
            )
        )


def _led_count(fraction: float) -> int:
    """Scale a fraction to a LED count clamped between 1 and 8.

    The Flitsmeister app rounds halves up, like ``Math.round`` in Java.
    """
    return min(8, max(1, floor(fraction * 8 + 0.5)))


def startup() -> DotAnimation:
    """Return the animation the app plays right after connecting.

    The LEDs play the start driving pattern in the speed trap color.
    """
    return DotAnimation(
        type=DotAnimationType.START_DRIVING,
        color=DotColor.SPEED_TRAP,
        cut_off=True,
    )


def fade_out() -> DotAnimation:
    """Return the animation that stops everything on the device.

    The running animation stops and the LEDs go dark.
    """
    return DotAnimation(type=DotAnimationType.FADE_OUT, cut_off=True)


def fade_out_without_cut_off() -> DotAnimation:
    """Return a fade out that keeps the prior state on the device.

    The LEDs go dark while the animation that was running is allowed
    to continue.
    """
    return DotAnimation(type=DotAnimationType.FADE_OUT)


def speed_trap(*, rateable: bool = True) -> DotAnimation:
    """Return the alert for a speed trap.

    The LEDs breathe from the middle outward in the speed trap color
    while the speaker plays the speed camera sound and the speed trap
    announcement.

    Args:
        rateable: Whether a button press rates the alert and ends it.
    """
    return DotAnimation(
        type=DotAnimationType.MID_TO_OUTWARD_AND_BREATHE,
        color=DotColor.SPEED_TRAP,
        value=3,
        primary_sound=DotSound.SFX_SPEED_CAMERA,
        secondary_sound=DotSound.SPEECH_SPEED_TRAP,
        end=DotEnd.RATE if rateable else None,
        cut_off=True,
    )


def speed_cam(*, rateable: bool = True) -> DotAnimation:
    """Return the alert for a speed camera.

    The LEDs breathe from the middle outward in the speed cam color
    while the speaker plays the speed camera sound and the speed cam
    announcement.

    Args:
        rateable: Whether a button press rates the alert and ends it.
    """
    return DotAnimation(
        type=DotAnimationType.MID_TO_OUTWARD_AND_BREATHE,
        color=DotColor.SPEED_CAM,
        value=3,
        primary_sound=DotSound.SFX_SPEED_CAMERA,
        secondary_sound=DotSound.SPEECH_SPEED_CAM,
        end=DotEnd.RATE if rateable else None,
        cut_off=True,
    )


def traffic_camera(*, rateable: bool = True) -> DotAnimation:
    """Return the alert for a traffic camera.

    The LEDs breathe from the middle outward in the speed cam color
    while the speaker plays the traffic camera announcement.

    Args:
        rateable: Whether a button press rates the alert and ends it.
    """
    return DotAnimation(
        type=DotAnimationType.MID_TO_OUTWARD_AND_BREATHE,
        color=DotColor.SPEED_CAM,
        value=3,
        primary_sound=DotSound.SPEECH_TRAFFIC_CAMERA,
        end=DotEnd.RATE if rateable else None,
        cut_off=True,
    )


def avg_speed_check_start(*, rateable: bool = True) -> DotAnimation:
    """Return the alert for the start of an average speed check.

    The LEDs breathe from the middle outward in the average speed
    check color while the speaker plays the average speed check start
    sound and the average speed check announcement.

    Args:
        rateable: Whether a button press rates the alert and ends it.
    """
    return DotAnimation(
        type=DotAnimationType.MID_TO_OUTWARD_AND_BREATHE,
        color=DotColor.AVG_SPEED_CHECK,
        value=2,
        primary_sound=DotSound.SFX_AVG_SPEED_CHECK_START,
        secondary_sound=DotSound.SPEECH_AVG_SPEED_CHECK,
        end=DotEnd.RATE if rateable else None,
        cut_off=True,
    )


def avg_speed_check_end() -> DotAnimation:
    """Return the animation for the end of an average speed check.

    The LEDs wave in the average speed check color while the speaker
    plays the average speed check end sound and the end of average
    speed check announcement.
    """
    return DotAnimation(
        type=DotAnimationType.WAVE,
        color=DotColor.AVG_SPEED_CHECK,
        value=0,
        primary_sound=DotSound.SFX_AVG_SPEED_CHECK_END,
        secondary_sound=DotSound.SPEECH_END_OF_AVG_SPEED_CHECK,
        cut_off=True,
    )


def traffic_jam_start() -> DotAnimation:
    """Return the alert for the start of a traffic jam.

    The LEDs breathe from the middle outward in the warning color
    while the speaker plays the safety notification sound and the
    traffic jam announcement.
    """
    return DotAnimation(
        type=DotAnimationType.MID_TO_OUTWARD_AND_BREATHE,
        color=DotColor.WARNING,
        value=2,
        primary_sound=DotSound.SFX_SAFETY_NOTIFICATION_2,
        secondary_sound=DotSound.SPEECH_TRAFFIC_JAM,
        end=DotEnd.FADE_OUT,
        cut_off=True,
    )


def traffic_jam_end() -> DotAnimation:
    """Return the animation for the end of a traffic jam.

    The LEDs wave in the warning color while the speaker plays the
    end of report sound.
    """
    return DotAnimation(
        type=DotAnimationType.WAVE,
        color=DotColor.WARNING,
        value=0,
        primary_sound=DotSound.SFX_END_OF_REPORT,
        cut_off=True,
    )


def police_hotspot(*, rateable: bool = True) -> DotAnimation:
    """Return the alert for a police hotspot.

    The LEDs breathe from the middle outward in the pro color while
    the speaker plays the police hotspot sound and the hotspot
    announcement.

    Args:
        rateable: Whether a button press rates the alert and ends it.
    """
    return DotAnimation(
        type=DotAnimationType.MID_TO_OUTWARD_AND_BREATHE,
        color=DotColor.PRO,
        value=3,
        primary_sound=DotSound.SFX_POLICE_HOTSPOT,
        secondary_sound=DotSound.SPEECH_HOTSPOT,
        end=DotEnd.RATE if rateable else None,
        cut_off=True,
    )


def roadworks(*, rateable: bool = True) -> DotAnimation:
    """Return the alert for roadworks.

    The LEDs breathe from the middle outward in the warning color
    while the speaker plays the safety notification sound and the
    roadworks announcement.

    Args:
        rateable: Whether a button press rates the alert and ends it.
    """
    return DotAnimation(
        type=DotAnimationType.MID_TO_OUTWARD_AND_BREATHE,
        color=DotColor.WARNING,
        value=2,
        primary_sound=DotSound.SFX_SAFETY_NOTIFICATION_2,
        secondary_sound=DotSound.SPEECH_ROADWORKS,
        end=DotEnd.RATE if rateable else None,
        cut_off=True,
    )


def incident(*, speech: DotSound, rateable: bool = True) -> DotAnimation:
    """Return the alert for a general incident.

    The LEDs breathe from the middle outward in the danger color
    while the speaker plays the safety notification sound and the
    given speech.

    Args:
        speech: The announcement for the incident, for example
            ``SPEECH_ACCIDENT`` or ``SPEECH_OBJECT_ON_ROAD``.
        rateable: Whether a button press rates the alert and ends it.
    """
    return DotAnimation(
        type=DotAnimationType.MID_TO_OUTWARD_AND_BREATHE,
        color=DotColor.DANGER,
        value=2,
        primary_sound=DotSound.SFX_SAFETY_NOTIFICATION_2,
        secondary_sound=speech,
        end=DotEnd.RATE if rateable else None,
        cut_off=True,
    )


def lane_closure(*, speech: DotSound) -> DotAnimation:
    """Return the alert for a closed lane.

    The LEDs breathe from the middle outward in the danger color
    while the speaker plays the safety notification sound and the
    given lane closure speech.

    Args:
        speech: One of ``SPEECH_LEFT_LANE_CLOSED``,
            ``SPEECH_LANE_CLOSED`` or ``SPEECH_RIGHT_LANE_CLOSED``.
    """
    return DotAnimation(
        type=DotAnimationType.MID_TO_OUTWARD_AND_BREATHE,
        color=DotColor.DANGER,
        value=3,
        primary_sound=DotSound.SFX_SAFETY_NOTIFICATION_2,
        secondary_sound=speech,
        end=DotEnd.FADE_OUT,
        cut_off=True,
    )


def ambulance() -> DotAnimation:
    """Return the alert for an approaching ambulance.

    The LEDs blink down, up and from the middle outward in the speed
    trap color while the speaker plays the ambulance sound and the
    ambulance announcement.
    """
    return DotAnimation(
        type=DotAnimationType.BLINK_DOWN_UP_AND_MID_TO_OUT,
        color=DotColor.SPEED_TRAP,
        value=4,
        primary_sound=DotSound.SFX_AMBULANCE,
        secondary_sound=DotSound.SPEECH_AMBULANCE,
        cut_off=True,
    )


def fire_truck() -> DotAnimation:
    """Return the alert for an approaching fire truck.

    The LEDs blink down, up and from the middle outward in the speed
    trap color while the speaker plays the emergency vehicle sound
    and the fire truck announcement.
    """
    return DotAnimation(
        type=DotAnimationType.BLINK_DOWN_UP_AND_MID_TO_OUT,
        color=DotColor.SPEED_TRAP,
        value=4,
        primary_sound=DotSound.SFX_EMERGENCY_VEHICLE,
        secondary_sound=DotSound.SPEECH_FIRE_TRUCK,
        cut_off=True,
    )


def police() -> DotAnimation:
    """Return the alert for a police vehicle ahead.

    The LEDs breathe from the middle outward in the speed trap color
    while the speaker plays the emergency vehicle sound.
    """
    return DotAnimation(
        type=DotAnimationType.MID_TO_OUTWARD_AND_BREATHE,
        color=DotColor.SPEED_TRAP,
        value=4,
        primary_sound=DotSound.SFX_EMERGENCY_VEHICLE,
        cut_off=True,
    )


def emergency_vehicle() -> DotAnimation:
    """Return the alert for an emergency vehicle ahead.

    The LEDs breathe from the middle outward in the danger color
    while the speaker plays the emergency vehicle sound and the
    emergency vehicle announcement.
    """
    return DotAnimation(
        type=DotAnimationType.MID_TO_OUTWARD_AND_BREATHE,
        color=DotColor.DANGER,
        value=4,
        primary_sound=DotSound.SFX_EMERGENCY_VEHICLE,
        secondary_sound=DotSound.SPEECH_EMERGENCY_VEHICLE,
        cut_off=True,
    )


def railway_crossing() -> DotAnimation:
    """Return the alert for a railway crossing.

    The LEDs breathe from the middle outward in the danger color
    while the speaker plays the safety notification sound and the
    railway crossing announcement.
    """
    return DotAnimation(
        type=DotAnimationType.MID_TO_OUTWARD_AND_BREATHE,
        color=DotColor.DANGER,
        primary_sound=DotSound.SFX_SAFETY_NOTIFICATION_2,
        secondary_sound=DotSound.SPEECH_RAILWAY_CROSSING,
        cut_off=True,
    )


def wrong_way_driving() -> DotAnimation:
    """Return the warning that the car drives the wrong way.

    The LEDs flash and then stay lit in the danger color while the
    speaker plays the wrong direction sound.
    """
    return DotAnimation(
        type=DotAnimationType.FLASH_AND_STATIC,
        color=DotColor.DANGER,
        value=0,
        primary_sound=DotSound.SFX_WRONG_DIRECTION,
        end=DotEnd.FADE_OUT,
        cut_off=True,
    )


def wrong_way_driver() -> DotAnimation:
    """Return the alert for an oncoming wrong way driver.

    The LEDs breathe from the middle outward in the danger color
    while the speaker plays the wrong way driver sound and the wrong
    way driver announcement. A button press rates the alert.
    """
    return DotAnimation(
        type=DotAnimationType.MID_TO_OUTWARD_AND_BREATHE,
        color=DotColor.DANGER,
        value=2,
        primary_sound=DotSound.SFX_WRONG_WAY_DRIVER,
        secondary_sound=DotSound.SPEECH_WRONG_WAY_DRIVER,
        end=DotEnd.RATE,
        cut_off=True,
    )


def progress(*, color: int, fraction: float) -> DotAnimation:
    """Return the approach progress animation.

    The LEDs light one by one from the top down, the fraction sets
    how many of the eight LEDs are lit.

    Args:
        color: The ARGB color of the lit LEDs, a ``DotColor`` member
            or a custom int.
        fraction: The progress from 0 to 1, values outside that range
            clamp to between one and eight lit LEDs.
    """
    return DotAnimation(
        type=DotAnimationType.PROGRESSION_TOP_TO_BOTTOM,
        color=color,
        value=_led_count(fraction),
    )


def overspeed(*, fraction: float) -> DotAnimation:
    """Return the overspeed warning.

    The lit LEDs blink in the danger color while the speaker plays
    the reduce speed sound.

    Args:
        fraction: The progress from 0 to 1, values outside that range
            clamp to between one and eight lit LEDs.
    """
    return DotAnimation(
        type=DotAnimationType.PROGRESSION_BLINK,
        color=DotColor.DANGER,
        value=_led_count(fraction),
        primary_sound=DotSound.SFX_REDUCE_SPEED,
        cut_off=True,
    )


def reporting() -> DotAnimation:
    """Return the animation while a button is held to file a report.

    The LEDs play the reporting pattern while the speaker plays the
    confirm sound.
    """
    return DotAnimation(
        type=DotAnimationType.REPORTING,
        value=0,
        primary_sound=DotSound.SFX_CONFIRM,
        cut_off=True,
    )


def brightness_sample() -> DotAnimation:
    """Return the sample the app plays after a brightness change.

    All eight LEDs light in white from the top down.
    """
    return DotAnimation(
        type=DotAnimationType.PROGRESSION_TOP_TO_BOTTOM,
        color=DotColor.WHITE,
        value=8,
        end=DotEnd.FADE_OUT,
    )


def orientation_sample() -> DotAnimation:
    """Return the sample the app plays after an LED rotation change.

    The LEDs breathe from the middle outward in the speed trap color.
    """
    return DotAnimation(
        type=DotAnimationType.MID_TO_OUTWARD_AND_BREATHE,
        color=DotColor.SPEED_TRAP,
        value=0,
    )


def updating() -> DotAnimation:
    """Return the animation while the firmware updates.

    The LEDs wave in white.
    """
    return DotAnimation(
        type=DotAnimationType.WAVE,
        color=DotColor.WHITE,
        cut_off=True,
    )
