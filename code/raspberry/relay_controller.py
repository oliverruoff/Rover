from __future__ import annotations

from gpiozero import OutputDevice


class DirectionRelayController:
    def __init__(self, left_pin: int, right_pin: int, *, active_high: bool = True) -> None:
        self.left = OutputDevice(left_pin, active_high=active_high, initial_value=False)
        self.right = OutputDevice(right_pin, active_high=active_high, initial_value=False)

    def set_left(self, active: bool) -> None:
        if active:
            self.left.on()
        else:
            self.left.off()

    def set_right(self, active: bool) -> None:
        if active:
            self.right.on()
        else:
            self.right.off()

    def off(self) -> None:
        self.left.off()
        self.right.off()

    def close(self) -> None:
        self.off()
        self.left.close()
        self.right.close()


class AuxOutputController:
    def __init__(
        self,
        front_light_pin: int,
        back_light_pin: int,
        dumper_up_pin: int,
        dumper_down_pin: int,
        *,
        active_high: bool = True,
    ) -> None:
        self.front_light = OutputDevice(front_light_pin, active_high=active_high, initial_value=False)
        self.back_light = OutputDevice(back_light_pin, active_high=active_high, initial_value=False)
        self.dumper_up = OutputDevice(dumper_up_pin, active_high=active_high, initial_value=False)
        self.dumper_down = OutputDevice(dumper_down_pin, active_high=active_high, initial_value=False)

    def set_front_light(self, active: bool) -> None:
        if active:
            self.front_light.on()
        else:
            self.front_light.off()

    def set_back_light(self, active: bool) -> None:
        if active:
            self.back_light.on()
        else:
            self.back_light.off()

    def set_dumper_up(self, active: bool) -> None:
        if active:
            self.dumper_down.off()
            self.dumper_up.on()
        else:
            self.dumper_up.off()

    def set_dumper_down(self, active: bool) -> None:
        if active:
            self.dumper_up.off()
            self.dumper_down.on()
        else:
            self.dumper_down.off()

    def snapshot(self) -> dict:
        return {
            "lights": {
                "front": bool(self.front_light.value),
                "back": bool(self.back_light.value),
            },
            "dumper": {
                "up": bool(self.dumper_up.value),
                "down": bool(self.dumper_down.value),
            },
        }

    def off(self) -> None:
        self.front_light.off()
        self.back_light.off()
        self.dumper_up.off()
        self.dumper_down.off()

    def close(self) -> None:
        self.off()
        self.front_light.close()
        self.back_light.close()
        self.dumper_up.close()
        self.dumper_down.close()
