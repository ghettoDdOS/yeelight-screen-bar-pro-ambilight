import argparse
import json
import logging
import socket
import sys
import threading
import time
import tkinter
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from typing import Any, Generator, Iterable, Self

from PIL import ImageGrab

_log = logging.getLogger(__name__)


@dataclass
class CommandPayload:
    id: int = field(
        init=False,
        default_factory=lambda: CommandPayload._next_id,
    )
    method: str
    params: Iterable[int | str]

    _next_id: int = field(
        repr=False,
        init=False,
        hash=False,
        compare=False,
        default=-1,
    )

    def __new__(cls, *args, **kwargs) -> Self:
        CommandPayload._next_id += 1
        return super().__new__(cls)

    def as_bytes(self) -> bytes:
        return f"{json.dumps(asdict(self))}\r\n".encode(encoding="utf-8")

    @staticmethod
    @lru_cache
    def convert_rgb(r: int, g: int, b: int) -> int:
        return (r * 65536) + (g * 256) + b

    @classmethod
    def bg_set_rgb(
        cls, r: int, g: int, b: int, effect="smooth", duration=500
    ) -> Self:
        return cls(
            "bg_set_rgb",
            (
                CommandPayload.convert_rgb(r, g, b),
                effect,
                duration,
            ),
        )

    @classmethod
    def bg_set_bright(cls, value: int, effect="smooth", duration=500) -> Self:
        return cls(
            "bg_set_bright",
            (
                value,
                effect,
                duration,
            ),
        )


class LampController:
    def __init__(self, ip: str, port=55443) -> None:
        self.ip = ip
        self.port = port

    @contextmanager
    def send(self) -> Generator[socket.socket, Any, None]:
        tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_socket.connect((self.ip, self.port))
        try:
            yield tcp_socket
        finally:
            tcp_socket.close()
            del tcp_socket

    def send_command(self, payload: CommandPayload) -> int:
        with self.send() as tcp_socket:
            return tcp_socket.send(payload.as_bytes())


class ScreenController:
    @classmethod
    def get_screen_resolution(cls):
        window = tkinter.Tk()
        return (
            window.winfo_screenwidth(),
            window.winfo_screenheight(),
        )

    @classmethod
    def get_screnshot(cls):
        width, height = cls.get_screen_resolution()
        return ImageGrab.grab(
            (
                0,
                0,
                width,
                height // 10 * 3,
            )
        )

    @classmethod
    def calculate_average_rgb(
        cls, colors: list[tuple[int, tuple[int, int, int]]]
    ):
        pixels_count = len(colors)

        avg_red = 0
        avg_green = 0
        avg_blue = 0

        for _, (r, g, b) in colors:
            avg_red += r
            avg_green += g
            avg_blue += b

        return (
            avg_red // pixels_count,
            avg_green // pixels_count,
            avg_blue // pixels_count,
        )


class Ambilight:
    def __init__(
        self,
        screen_controller: ScreenController,
        lamp_controller: LampController,
        refresh_rate=1,
        initial_brightness=100,
    ) -> None:
        self._running = False

        self.screen_controller = screen_controller
        self.lamp_controller = lamp_controller

        self.refresh_rate = refresh_rate

        self.set_brightness(initial_brightness)

    def set_brightness(self, value: int):
        command = CommandPayload.bg_set_bright(value)
        return self.lamp_controller.send_command(command)

    def get_color(self):
        screen_sample = self.screen_controller.get_screnshot()
        screen_colors = screen_sample.getcolors(
            screen_sample.width * screen_sample.height
        )
        return self.screen_controller.calculate_average_rgb(screen_colors)  # type: ignore

    def send_set_color_command(self, color: tuple[int, int, int]):
        command = CommandPayload.bg_set_rgb(*color)
        return self.lamp_controller.send_command(command)

    def process(self):
        while self._running:
            start_time = time.time()

            color = self.get_color()
            ret = self.send_set_color_command(color)
            _log.debug("Set color with status: %d", ret)

            delta = time.time() - start_time

            if delta < self.refresh_rate:
                time.sleep(self.refresh_rate - delta)

    def start(self):
        if not self._running:
            self._running = True
            threading.Thread(target=self.process).start()

    def stop(self):
        self._running = False


def setup_logging(debug: bool):
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)
    _log.addHandler(handler)
    _log.setLevel(logging.DEBUG if debug else logging.INFO)


def main():
    parser = argparse.ArgumentParser(
        prog="Yeelight Ambilight",
        description="Set yeelight screen bar background "
        "color from average screen color",
    )
    parser.add_argument("ip")
    parser.add_argument("-d", "--debug", action="store_true")

    args = parser.parse_args()

    setup_logging(args.debug)

    screen_controller = ScreenController()
    lamp_controller = LampController(args.ip)
    ambilight_controller = Ambilight(screen_controller, lamp_controller)

    _log.info("Start Yeelight Ambilight on %s lamp.", args.ip)

    while True:
        try:
            ambilight_controller.start()
        except KeyboardInterrupt:
            ambilight_controller.stop()
            _log.info("GoodBye!")
            exit(1)


if __name__ == "__main__":
    main()
