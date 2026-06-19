from __future__ import annotations

import json
import wave
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


SUMMARY_KEYS = ["会议摘要", "决策事项", "待办事项", "每个人负责什么", "风险/问题"]


def default_rolling_summary() -> dict[str, list[Any]]:
    return {key: [] for key in SUMMARY_KEYS}


def default_summary_status() -> dict[str, Any]:
    return {
        "state": "idle",
        "last_updated_at": None,
        "last_error": "",
        "model": "",
    }


@dataclass
class TranscriptSegment:
    index: int
    text: str
    is_final: bool
    timestamp: float


@dataclass
class MeetingRecord:
    id: str
    title: str
    created_at: str
    updated_at: str
    status: str = "recording"
    sample_rate: int = 16_000
    duration_seconds: float = 0
    transcript: list[TranscriptSegment] = field(default_factory=list)
    rolling_summary: dict[str, list[Any]] = field(default_factory=default_rolling_summary)
    rolling_summary_history: list[dict[str, Any]] = field(default_factory=list)
    summary_status: dict[str, Any] = field(default_factory=default_summary_status)


class MeetingStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def create_meeting(self, title: str | None, sample_rate: int) -> MeetingRecord:
        now = datetime.now().isoformat(timespec="seconds")
        meeting_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8]
        record = MeetingRecord(
            id=meeting_id,
            title=title or f"会议 {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            created_at=now,
            updated_at=now,
            sample_rate=sample_rate,
        )
        self._meeting_dir(meeting_id).mkdir(parents=True, exist_ok=True)
        self.save(record)
        return record

    def list_meetings(self) -> list[dict[str, Any]]:
        meetings = []
        for meta_path in sorted(self.data_dir.glob("*/meeting.json"), reverse=True):
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            meetings.append(
                {
                    "id": data["id"],
                    "title": data["title"],
                    "created_at": data["created_at"],
                    "updated_at": data["updated_at"],
                    "status": data["status"],
                    "duration_seconds": data.get("duration_seconds", 0),
                    "segments": len(data.get("transcript", [])),
                }
            )
        return meetings

    def get_meeting(self, meeting_id: str) -> MeetingRecord:
        meta_path = self._meeting_dir(meeting_id) / "meeting.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        data["transcript"] = [TranscriptSegment(**item) for item in data.get("transcript", [])]
        data["rolling_summary"] = normalize_rolling_summary(data.get("rolling_summary"))
        data.setdefault("rolling_summary_history", [])
        data.setdefault("summary_status", default_summary_status())
        return MeetingRecord(**data)

    def save(self, record: MeetingRecord) -> None:
        record.updated_at = datetime.now().isoformat(timespec="seconds")
        meta_path = self._meeting_dir(record.id) / "meeting.json"
        meta_path.write_text(
            json.dumps(asdict(record), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def transcript_path(self, meeting_id: str) -> Path:
        return self._meeting_dir(meeting_id) / "transcript.txt"

    def audio_path(self, meeting_id: str) -> Path:
        return self._meeting_dir(meeting_id) / "audio.wav"

    def _meeting_dir(self, meeting_id: str) -> Path:
        if any(part in meeting_id for part in ("/", "\\", "..")):
            raise ValueError("Invalid meeting id")
        return self.data_dir / meeting_id


def normalize_rolling_summary(value: Any) -> dict[str, list[Any]]:
    normalized = default_rolling_summary()
    if not isinstance(value, dict):
        return normalized
    for key in SUMMARY_KEYS:
        item = value.get(key, [])
        if isinstance(item, list):
            normalized[key] = item
        elif item:
            normalized[key] = [item]
    return normalized


class MeetingAudioWriter:
    def __init__(self, path: Path, sample_rate: int) -> None:
        self.frames = 0
        self.wav = wave.open(str(path), "wb")
        self.wav.setnchannels(1)
        self.wav.setsampwidth(2)
        self.wav.setframerate(sample_rate)
        self.sample_rate = sample_rate

    def write(self, pcm: bytes) -> None:
        self.frames += len(pcm) // 2
        self.wav.writeframes(pcm)

    @property
    def duration_seconds(self) -> float:
        return self.frames / self.sample_rate

    def close(self) -> None:
        self.wav.close()
