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
