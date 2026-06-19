from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from .config import Settings
from .storage import TranscriptSegment
from .transcript import split_refined_text

logger = logging.getLogger(__name__)


class OfflineTranscriptRefiner:
    def __init__(self, settings: Settings) -> None:
        from funasr import AutoModel

        self.model = AutoModel(
            model=settings.refine_asr_model,
            model_revision=settings.refine_asr_revision,
            vad_model=settings.refine_vad_model,
            punc_model=settings.refine_punc_model,
            disable_update=settings.asr_disable_update,
            device=settings.asr_device,
        )
        logger.info(
            "Loaded offline refiner model=%s vad=%s punc=%s on %s",
            settings.refine_asr_model,
            settings.refine_vad_model,
            settings.refine_punc_model,
            settings.asr_device,
        )

    def refine(self, audio_path: Path) -> list[TranscriptSegment]:
        result = self.model.generate(
            input=str(audio_path),
            batch_size_s=300,
            merge_vad=True,
            merge_length_s=15,
        )
        chunks = split_refined_text(extract_text(result))
        now = time.time()
        return [
            TranscriptSegment(index=index, text=chunk, is_final=True, timestamp=now)
            for index, chunk in enumerate(chunks)
        ]


def extract_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        return str(result.get("text") or "")
    if isinstance(result, list):
        return "".join(extract_text(item) for item in result)
    return ""
