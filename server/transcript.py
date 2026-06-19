from __future__ import annotations

import re
import time

from .asr import TranscriptUpdate
from .config import Settings


SENTENCE_END_RE = re.compile(r"[。！？!?；;]$")


class TranscriptAssembler:
    """Turn streaming ASR fragments into readable draft/final transcript chunks."""

    def __init__(self, settings: Settings) -> None:
        self.min_chars = settings.transcript_min_chars
        self.max_chars = settings.transcript_max_chars
        self.pending = ""
        self.last_final_text = ""

    def accept_many(
        self,
        updates: list[TranscriptUpdate],
        force: bool = False,
    ) -> list[TranscriptUpdate]:
        output: list[TranscriptUpdate] = []
        for update in updates:
            output.extend(self.accept(update))
        if force:
            flushed = self.flush()
            if flushed:
                output.append(flushed)
        return output

    def accept(self, update: TranscriptUpdate) -> list[TranscriptUpdate]:
        text = normalize_fragment(update.text)
        if not text:
            return []

        self.pending = merge_fragment(self.pending, text)
        if not self.pending:
            return []

        now = update.timestamp or time.time()
        if should_finalize(self.pending, self.min_chars, self.max_chars, update.is_final):
            final_text = self.pending.strip()
            self.pending = ""
            if final_text == self.last_final_text:
                return []
            self.last_final_text = final_text
            return [TranscriptUpdate(text=final_text, is_final=True, timestamp=now)]

        return [TranscriptUpdate(text=self.pending.strip(), is_final=False, timestamp=now)]

    def flush(self) -> TranscriptUpdate | None:
        text = self.pending.strip()
        if not text:
            return None
        self.pending = ""
        if text == self.last_final_text:
            return None
        self.last_final_text = text
        return TranscriptUpdate(text=text, is_final=True, timestamp=time.time())


def normalize_fragment(text: str) -> str:
    return re.sub(r"\s+", "", text or "").strip()


def merge_fragment(existing: str, incoming: str) -> str:
    if not existing:
        return incoming
    if not incoming:
        return existing
    if existing.endswith(incoming):
        return existing
    if incoming.startswith(existing):
        return incoming

    max_overlap = min(len(existing), len(incoming), 20)
    for size in range(max_overlap, 1, -1):
        if existing[-size:] == incoming[:size]:
            return existing + incoming[size:]
    return existing + incoming


def should_finalize(text: str, min_chars: int, max_chars: int, is_final: bool) -> bool:
    if is_final:
        return True
    if len(text) >= max_chars:
        return True
    return len(text) >= min_chars and SENTENCE_END_RE.search(text) is not None


def split_refined_text(text: str, max_chars: int = 120) -> list[str]:
    text = normalize_fragment(text)
    if not text:
        return []

    chunks: list[str] = []
    current = ""
    for char in text:
        current += char
        if SENTENCE_END_RE.search(char) or len(current) >= max_chars:
            chunks.append(current.strip())
            current = ""
    if current.strip():
        chunks.append(current.strip())
    return chunks
