from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Protocol

from .config import Settings
from .storage import (
    MeetingRecord,
    MeetingStore,
    SpeakerSegment,
    default_speaker_status,
    normalize_speaker_segments,
)

logger = logging.getLogger(__name__)


class DiarizationClient(Protocol):
    async def diarize(self, audio_path: Path, output_dir: Path) -> list[SpeakerSegment]:
        ...


class MockDiarizationClient:
    async def diarize(self, audio_path: Path, output_dir: Path) -> list[SpeakerSegment]:
        duration = read_wav_duration(audio_path) or 1.0
        midpoint = max(0.1, duration / 2)
        return [
            SpeakerSegment("Speaker 1", 0.0, midpoint),
            SpeakerSegment("Speaker 2", midpoint, duration),
        ]


class ExternalDiarizationClient:
    def __init__(self, settings: Settings) -> None:
        self.command = settings.diarization_command
        self.timeout = settings.diarization_timeout_seconds

    async def diarize(self, audio_path: Path, output_dir: Path) -> list[SpeakerSegment]:
        if not self.command:
            raise RuntimeError(
                "MIAOJI_DIARIZATION_COMMAND is not set. "
                "Install 3D-Speaker and point this to its infer_diarization.py command."
            )

        output_dir.mkdir(parents=True, exist_ok=True)
        command = self.command.format(wav=str(audio_path), out_dir=str(output_dir))
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout)
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise RuntimeError("speaker diarization timed out") from exc

        if process.returncode != 0:
            detail = (stderr or stdout).decode("utf-8", errors="ignore").strip()
            raise RuntimeError(detail[:500] or "speaker diarization command failed")

        segments = parse_diarization_outputs(output_dir)
        if not segments:
            raise RuntimeError("speaker diarization produced no speaker segments")
        return segments


class DiarizationWorker:
    def __init__(
        self,
        settings: Settings,
        store: MeetingStore,
        record: MeetingRecord,
        client: DiarizationClient | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.record = record
        self.client = client or create_diarization_client(settings)

    async def run(self) -> bool:
        audio_path = self.store.audio_path(self.record.id)
        if not audio_path.exists():
            raise FileNotFoundError("Audio not found")

        self.record.speaker_status = {
            **default_speaker_status(),
            "state": "running",
            "last_updated_at": self.record.speaker_status.get("last_updated_at"),
            "last_error": "",
            "engine": self.engine_name,
        }
        self.store.save(self.record)

        try:
            output_dir = self.store.diarization_dir(self.record.id)
            segments = await self.client.diarize(audio_path, output_dir)
            segments = normalize_speaker_segments([segment.__dict__ for segment in segments])
            if not segments:
                raise RuntimeError("speaker diarization produced no speaker segments")
        except Exception as exc:
            logger.warning("Speaker diarization failed: %s", exc)
            self.record.speaker_status = {
                **default_speaker_status(),
                "state": "error",
                "last_updated_at": datetime.now().isoformat(timespec="seconds"),
                "last_error": str(exc)[:300],
                "engine": self.engine_name,
            }
            self.store.save(self.record)
            return False

        self.record.speaker_segments = segments
        self.record.speaker_status = {
            **default_speaker_status(),
            "state": "done",
            "last_updated_at": datetime.now().isoformat(timespec="seconds"),
            "last_error": "",
            "engine": self.engine_name,
        }
        self.store.save(self.record)
        return True

    @property
    def engine_name(self) -> str:
        if self.settings.diarization_mock:
            return "mock"
        return "3d-speaker"


def create_diarization_client(settings: Settings) -> DiarizationClient:
    if settings.diarization_mock:
        return MockDiarizationClient()
    return ExternalDiarizationClient(settings)


def parse_diarization_outputs(output_dir: Path) -> list[SpeakerSegment]:
    rttm_files = sorted(output_dir.rglob("*.rttm"))
    segments: list[SpeakerSegment] = []
    for path in rttm_files:
        segments.extend(parse_rttm(path.read_text(encoding="utf-8", errors="ignore")))
    return normalize_speaker_segments([segment.__dict__ for segment in segments])


def parse_rttm(text: str) -> list[SpeakerSegment]:
    segments: list[SpeakerSegment] = []
    speaker_map: dict[str, str] = {}
    for line in text.splitlines():
        parts = re.split(r"\s+", line.strip())
        if len(parts) < 8 or parts[0].upper() != "SPEAKER":
            continue
        try:
            start = float(parts[3])
            duration = float(parts[4])
        except ValueError:
            continue
        raw_speaker = parts[7]
        if raw_speaker not in speaker_map:
            speaker_map[raw_speaker] = f"Speaker {len(speaker_map) + 1}"
        segments.append(SpeakerSegment(speaker_map[raw_speaker], start, start + max(0.0, duration)))
    return segments


def read_wav_duration(audio_path: Path) -> float:
    import wave

    with wave.open(str(audio_path), "rb") as wav:
        frames = wav.getnframes()
        rate = wav.getframerate()
    return frames / rate if rate else 0.0
