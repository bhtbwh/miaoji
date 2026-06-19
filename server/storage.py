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


def default_final_summary_status() -> dict[str, Any]:
    return {
        "state": "idle",
        "last_updated_at": None,
        "last_error": "",
        "model": "",
    }


def default_speaker_status() -> dict[str, Any]:
    return {
        "state": "idle",
        "last_updated_at": None,
        "last_error": "",
        "engine": "",
    }


@dataclass
class TranscriptSegment:
    index: int
    text: str
    is_final: bool
    timestamp: float


@dataclass
class SpeakerSegment:
    speaker: str
    start: float
    end: float


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
    final_summary: dict[str, list[Any]] = field(default_factory=default_rolling_summary)
    final_summary_markdown: str = ""
    final_summary_status: dict[str, Any] = field(default_factory=default_final_summary_status)
    speaker_segments: list[SpeakerSegment] = field(default_factory=list)
    speaker_status: dict[str, Any] = field(default_factory=default_speaker_status)


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
                    "speaker_segments": len(data.get("speaker_segments", [])),
                    "speaker_status": data.get("speaker_status", default_speaker_status()),
                    "final_summary_status": data.get("final_summary_status", default_final_summary_status()),
                    "has_final_summary": bool(data.get("final_summary_markdown")),
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
        data["final_summary"] = normalize_rolling_summary(data.get("final_summary"))
        data.setdefault("final_summary_markdown", "")
        data.setdefault("final_summary_status", default_final_summary_status())
        data["speaker_segments"] = normalize_speaker_segments(data.get("speaker_segments"))
        data.setdefault("speaker_status", default_speaker_status())
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

    def diarization_dir(self, meeting_id: str) -> Path:
        path = self._meeting_dir(meeting_id) / "diarization"
        path.mkdir(parents=True, exist_ok=True)
        return path

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


def normalize_speaker_segments(value: Any) -> list[SpeakerSegment]:
    if not isinstance(value, list):
        return []
    segments: list[SpeakerSegment] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        speaker = str(item.get("speaker") or "").strip()
        if not speaker:
            continue
        try:
            start = max(0.0, float(item.get("start", 0)))
            end = max(start, float(item.get("end", start)))
        except (TypeError, ValueError):
            continue
        segments.append(SpeakerSegment(speaker=speaker, start=start, end=end))
    return sorted(segments, key=lambda segment: (segment.start, segment.end, segment.speaker))


def transcript_audio_time(record: MeetingRecord, segment: TranscriptSegment) -> float | None:
    if not record.duration_seconds:
        return None
    if segment.timestamp > 1_000_000_000:
        try:
            created_at = datetime.fromisoformat(record.created_at).timestamp()
        except ValueError:
            created_at = 0
        relative = segment.timestamp - created_at
        if 0 <= relative <= record.duration_seconds + 2:
            return relative
    if 0 <= segment.timestamp <= record.duration_seconds + 2:
        return segment.timestamp
    if record.transcript:
        return ((segment.index + 0.5) / len(record.transcript)) * record.duration_seconds
    return None


def speaker_for_segment(record: MeetingRecord, segment: TranscriptSegment) -> str:
    if not record.speaker_segments:
        return "Speaker ?"
    audio_time = transcript_audio_time(record, segment)
    if audio_time is None:
        return "Speaker ?"

    for speaker_segment in record.speaker_segments:
        if speaker_segment.start <= audio_time <= speaker_segment.end:
            return speaker_segment.speaker

    nearest = min(
        record.speaker_segments,
        key=lambda item: min(abs(audio_time - item.start), abs(audio_time - item.end)),
    )
    return nearest.speaker


def transcript_line(record: MeetingRecord, segment: TranscriptSegment, include_speaker: bool = True) -> str:
    text = segment.text.strip()
    if not include_speaker or not record.speaker_segments:
        return text
    return f"[{speaker_for_segment(record, segment)}] {text}".strip()


def transcript_markdown(record: MeetingRecord) -> str:
    lines = [transcript_line(record, segment) for segment in record.transcript if segment.text.strip()]
    return "\n".join(lines).strip() + "\n"


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
