from __future__ import annotations

import asyncio
import json
import math
import struct
import sys
import time
from urllib.parse import quote

import websockets


async def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else "ws://127.0.0.1:8765/ws/record?title=smoke"
    seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    sample_rate = 16_000
    chunk_ms = 200
    samples_per_chunk = sample_rate * chunk_ms // 1000

    if "title=" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}title={quote('smoke')}"

    async with websockets.connect(url, max_size=8 * 1024 * 1024) as websocket:
        print(await websocket.recv())
        started_at = time.monotonic()
        sent = 0
        while sent < seconds * sample_rate:
            chunk = bytearray()
            for i in range(samples_per_chunk):
                t = (sent + i) / sample_rate
                value = int(0.08 * 32767 * math.sin(2 * math.pi * 440 * t))
                chunk.extend(struct.pack("<h", value))
            await websocket.send(bytes(chunk))
            sent += samples_per_chunk
            await asyncio.sleep(max(0, chunk_ms / 1000 - (time.monotonic() - started_at - sent / sample_rate)))

            while True:
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=0.01)
                except asyncio.TimeoutError:
                    break
                print(message)

        await websocket.send(json.dumps({"type": "stop"}, ensure_ascii=False))
        while True:
            try:
                print(await asyncio.wait_for(websocket.recv(), timeout=2))
            except (asyncio.TimeoutError, websockets.ConnectionClosed):
                break


if __name__ == "__main__":
    asyncio.run(main())
