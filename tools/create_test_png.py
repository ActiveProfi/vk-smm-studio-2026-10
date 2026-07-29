"""
Создаёт простую PNG-картинку для теста браузерной публикации VK.
Без внешних библиотек.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "output" / "test-media" / "vk-test-nds-operations.png"


def chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def main() -> int:
    width, height = 1000, 1000
    bg = (18, 24, 38)
    yellow = (245, 190, 52)
    blue = (42, 111, 219)
    white = (245, 247, 250)

    rows = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            color = bg
            if 80 <= x <= 920 and 80 <= y <= 210:
                color = yellow
            elif 120 <= x <= 880 and 300 <= y <= 410:
                color = white
            elif 120 <= x <= 880 and 470 <= y <= 580:
                color = blue
            elif 120 <= x <= 880 and 640 <= y <= 750:
                color = white
            elif 120 <= x <= 880 and 810 <= y <= 900:
                color = yellow
            row.extend(color)
        rows.append(b"\x00" + bytes(row))

    raw = b"".join(rows)
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, level=6))
    png += chunk(b"IEND", b"")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(png)
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
