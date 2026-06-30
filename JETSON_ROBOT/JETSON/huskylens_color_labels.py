#!/usr/bin/env python3
"""
HuskyLens color label reader.

ID mapping used by this script:
  1 RED
  2 ORANGE
  3 YELLOW
  4 GREEN
  5 BLUE
  6 PURPLE

Example:
  python D:\huskylens_color_labels.py --port COM3
"""

from __future__ import annotations

import argparse
import struct
import sys
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

try:
    import serial
except ImportError:
    serial = None


HEADER = bytes([0x55, 0xAA, 0x11])

COMMAND_REQUEST_BLOCKS_LEARNED = 0x24
COMMAND_RETURN_INFO = 0x29
COMMAND_RETURN_BLOCK = 0x2A
COMMAND_RETURN_OK = 0x2E
COMMAND_REQUEST_ALGORITHM = 0x2D

ALGORITHM_COLOR_RECOGNITION = 0x03

COLOR_LABELS: Dict[int, str] = {
    1: "RED",
    2: "ORANGE",
    3: "YELLOW",
    4: "GREEN",
    5: "BLUE",
    6: "PURPLE",
}


@dataclass(frozen=True)
class Block:
    x_center: int
    y_center: int
    width: int
    height: int
    learned_id: int

    @property
    def area(self) -> int:
        return self.width * self.height

    @property
    def label(self) -> str:
        return COLOR_LABELS.get(self.learned_id, f"UNKNOWN_ID_{self.learned_id}")


class HuskyLens:
    def __init__(self, port: str, baudrate: int = 9600, timeout: float = 0.5) -> None:
        if serial is None:
            raise RuntimeError("pyserial is required. Install it with: pip install pyserial")

        self.serial = serial.Serial(port=port, baudrate=baudrate, timeout=timeout)
        time.sleep(0.2)
        self.serial.reset_input_buffer()

    def close(self) -> None:
        self.serial.close()

    def set_color_recognition_mode(self) -> None:
        self._write_packet(COMMAND_REQUEST_ALGORITHM, bytes([ALGORITHM_COLOR_RECOGNITION]))
        self._read_until_ok_or_timeout()

    def get_learned_color_blocks(self) -> List[Block]:
        self._write_packet(COMMAND_REQUEST_BLOCKS_LEARNED)
        packets = self._read_response_packets()
        return [self._parse_block(data) for command, data in packets if command == COMMAND_RETURN_BLOCK]

    def _write_packet(self, command: int, data: bytes = b"") -> None:
        packet_without_checksum = HEADER + bytes([len(data), command]) + data
        checksum = sum(packet_without_checksum) & 0xFF
        self.serial.write(packet_without_checksum + bytes([checksum]))

    def _read_response_packets(self) -> List[tuple[int, bytes]]:
        packets: List[tuple[int, bytes]] = []
        expected_blocks: Optional[int] = None
        deadline = time.monotonic() + 0.8

        while time.monotonic() < deadline:
            packet = self._read_packet()
            if packet is None:
                continue

            command, data = packet
            if command == COMMAND_RETURN_INFO:
                expected_blocks = self._parse_info_count(data)
                if expected_blocks == 0:
                    return packets
            elif command == COMMAND_RETURN_BLOCK:
                packets.append(packet)
                if expected_blocks is not None and len(packets) >= expected_blocks:
                    return packets
            elif command == COMMAND_RETURN_OK:
                return packets

        return packets

    def _read_until_ok_or_timeout(self) -> None:
        deadline = time.monotonic() + 0.8
        while time.monotonic() < deadline:
            packet = self._read_packet()
            if packet and packet[0] == COMMAND_RETURN_OK:
                return

    def _read_packet(self) -> Optional[tuple[int, bytes]]:
        if not self._read_header():
            return None

        length_raw = self.serial.read(1)
        command_raw = self.serial.read(1)
        if len(length_raw) != 1 or len(command_raw) != 1:
            return None

        length = length_raw[0]
        command = command_raw[0]
        data = self.serial.read(length)
        checksum_raw = self.serial.read(1)

        if len(data) != length or len(checksum_raw) != 1:
            return None

        checksum_expected = (sum(HEADER) + length + command + sum(data)) & 0xFF
        if checksum_raw[0] != checksum_expected:
            return None

        return command, data

    def _read_header(self) -> bool:
        window = bytearray()
        deadline = time.monotonic() + 0.5

        while time.monotonic() < deadline:
            byte = self.serial.read(1)
            if not byte:
                continue
            window += byte
            if len(window) > len(HEADER):
                del window[0]
            if bytes(window) == HEADER:
                return True

        return False

    @staticmethod
    def _parse_info_count(data: bytes) -> int:
        if len(data) < 2:
            return 0
        return struct.unpack_from("<H", data, 0)[0]

    @staticmethod
    def _parse_block(data: bytes) -> Block:
        if len(data) < 10:
            raise ValueError(f"Invalid block data length: {len(data)}")

        x_center, y_center, width, height, learned_id = struct.unpack("<HHHHH", data[:10])
        return Block(x_center, y_center, width, height, learned_id)


def pick_main_block(blocks: Iterable[Block]) -> Optional[Block]:
    known_blocks = [block for block in blocks if block.learned_id in COLOR_LABELS]
    if not known_blocks:
        return None
    return max(known_blocks, key=lambda block: block.area)


def print_block(block: Optional[Block], show_all: bool, blocks: List[Block]) -> None:
    if block is None:
        print("NO_LABEL")
        return

    print(
        f"{block.learned_id} {block.label} "
        f"x={block.x_center} y={block.y_center} w={block.width} h={block.height}"
    )

    if show_all:
        for other in sorted(blocks, key=lambda item: item.area, reverse=True):
            print(
                f"  - {other.learned_id} {other.label} "
                f"x={other.x_center} y={other.y_center} w={other.width} h={other.height}"
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read HuskyLens color-recognition labels.")
    parser.add_argument("--port", required=True, help="Serial port, e.g. COM3 on Windows or /dev/ttyUSB0 on Linux.")
    parser.add_argument("--baudrate", type=int, default=9600, help="Serial baudrate. Default: 9600.")
    parser.add_argument("--once", action="store_true", help="Read once and exit.")
    parser.add_argument("--all", action="store_true", help="Also print every detected block.")
    parser.add_argument("--interval", type=float, default=0.2, help="Loop interval in seconds. Default: 0.2.")
    parser.add_argument(
        "--no-mode-change",
        action="store_true",
        help="Do not send the command that switches HuskyLens to color recognition mode.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        lens = HuskyLens(args.port, args.baudrate)
    except Exception as exc:
        print(f"Connection failed: {exc}", file=sys.stderr)
        return 1

    try:
        if not args.no_mode_change:
            lens.set_color_recognition_mode()

        while True:
            blocks = lens.get_learned_color_blocks()
            main_block = pick_main_block(blocks)
            print_block(main_block, args.all, blocks)

            if args.once:
                break
            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\nExit")
    finally:
        lens.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
