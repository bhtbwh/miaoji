from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import numpy as np

from .config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TranscriptUpdate:
    text: str
    is_final: bool
    timestamp: float


class StreamingTranscriber(ABC):
    @abstractmethod
    async def accept_audio(self, pcm: bytes, is_final: bool = False) -> list[TranscriptUpdate]:
        """Accept little-endian int16 PCM at the configured sample rate."""

    @abstractmethod
    async def close(self) -> list[TranscriptUpdate]:
        """Flush pending audio and release the stream."""


class MockStreamingTranscriber(StreamingTranscriber):
    """Tiny fallback for UI and WebSocket testing before FunASR is installed."""

    def __init__(self, sample_rate: int) -> None:
        self.sample_rate = sample_rate
        self.total_samples = 0
        self.last_emit_at = 0

    async def accept_audio(self, pcm: bytes, is_final: bool = False) -> list[TranscriptUpdate]:
        samples = len(pcm) // 2
        self.total_samples += samples
        second = self.total_samples // self.sample_rate
        if is_final or second > self.last_emit_at:
            self.last_emit_at = second
            return [
                TranscriptUpdate(
                    text=f"[模拟转写] 已收到 {second} 秒音频。",
                    is_final=is_final,
                    timestamp=time.time(),
                )
            ]
        return []

    async def close(self) -> list[TranscriptUpdate]:
        return await self.accept_audio(b"", is_final=True)


class FunASRStreamingTranscriber(StreamingTranscriber):
    def __init__(self, settings: Settings) -> None:
        from funasr import AutoModel

        self.settings = settings
        self.cache: dict[str, Any] = {}
        self.closed = False
        self.chunk_samples = settings.asr_chunk_size[1] * 960
        self.buffer = bytearray()
        self.model = AutoModel(
            model=settings.asr_model,
            model_revision=settings.asr_revision,
            disable_update=settings.asr_disable_update,
            device=settings.asr_device,
        )
        logger.info("Loaded FunASR model %s on %s", settings.asr_model, settings.asr_device)

    async def accept_audio(self, pcm: bytes, is_final: bool = False) -> list[TranscriptUpdate]:
        if self.closed:
            return []

        self.buffer.extend(pcm)
        updates: list[TranscriptUpdate] = []
        frame_bytes = self.chunk_samples * 2

        while len(self.buffer) >= frame_bytes:
            chunk = bytes(self.buffer[:frame_bytes])
            del self.buffer[:frame_bytes]
            update = await asyncio.to_thread(self._infer_chunk, chunk, False)
            if update:
                updates.append(update)

        if is_final:
            updates.extend(await self.close())

        return updates

    async def close(self) -> list[TranscriptUpdate]:
        if self.closed:
            return []
        self.closed = True
        if not self.buffer:
            return []
        chunk = bytes(self.buffer)
        self.buffer.clear()
        update = await asyncio.to_thread(self._infer_chunk, chunk, True)
        return [update] if update else []

    def _infer_chunk(self, pcm: bytes, is_final: bool) -> TranscriptUpdate | None:
        speech = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        if speech.size == 0:
            return None

        result = self.model.generate(
            input=speech,
            cache=self.cache,
            is_final=is_final,
            chunk_size=list(self.settings.asr_chunk_size),
            encoder_chunk_look_back=self.settings.asr_encoder_chunk_look_back,
            decoder_chunk_look_back=self.settings.asr_decoder_chunk_look_back,
        )
        text = _extract_text(result).strip()
        if not text:
            return None
        return TranscriptUpdate(text=text, is_final=is_final, timestamp=time.time())


def create_transcriber(settings: Settings) -> StreamingTranscriber:
    if settings.mock_asr:
        logger.warning("MIAOJI_MOCK_ASR is enabled; using mock transcription.")
        return MockStreamingTranscriber(settings.sample_rate)
    return FunASRStreamingTranscriber(settings)


def _extract_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        return str(result.get("text") or "")
    if isinstance(result, list):
        return "".join(_extract_text(item) for item in result)
    return ""
