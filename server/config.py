from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    app_name: str = "秒记"
    sample_rate: int = 16_000
    data_dir: Path = ROOT_DIR / "data" / "meetings"
    static_dir: Path = ROOT_DIR / "web"
    asr_model: str = "paraformer-zh-streaming"
    asr_revision: str = "v2.0.4"
    asr_chunk_size: tuple[int, int, int] = (0, 16, 8)
    asr_encoder_chunk_look_back: int = 8
    asr_decoder_chunk_look_back: int = 2
    asr_disable_update: bool = True
    asr_device: str = "cpu"
    transcript_min_chars: int = 18
    transcript_max_chars: int = 80
    refine_asr_model: str = "paraformer-zh"
    refine_asr_revision: str = "v2.0.4"
    refine_vad_model: str = "fsmn-vad"
    refine_punc_model: str = "ct-punc"
    summary_enabled: bool = False
    summary_base_url: str = "https://ark.cn-beijing.volces.com/api/coding/v3"
    summary_model: str = "doubao-seed-2.0-lite"
    summary_api_key: str = ""
    summary_interval_seconds: float = 15
    summary_min_new_chars: int = 80
    summary_timeout_seconds: float = 45
    summary_mock: bool = False
    mock_asr: bool = False


def get_settings() -> Settings:
    cache_dir = Path(os.getenv("MIAOJI_MODELSCOPE_CACHE", ROOT_DIR / "data" / "modelscope_cache"))
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MODELSCOPE_CACHE", str(cache_dir))
    os.environ.setdefault("MODELSCOPE_CACHE_HOME", str(cache_dir))

    return Settings(
        data_dir=Path(os.getenv("MIAOJI_DATA_DIR", ROOT_DIR / "data" / "meetings")),
        asr_model=os.getenv("MIAOJI_ASR_MODEL", "paraformer-zh-streaming"),
        asr_revision=os.getenv("MIAOJI_ASR_REVISION", "v2.0.4"),
        asr_device=os.getenv("MIAOJI_ASR_DEVICE", "cpu"),
        transcript_min_chars=int(os.getenv("MIAOJI_TRANSCRIPT_MIN_CHARS", "18")),
        transcript_max_chars=int(os.getenv("MIAOJI_TRANSCRIPT_MAX_CHARS", "80")),
        refine_asr_model=os.getenv("MIAOJI_REFINE_ASR_MODEL", "paraformer-zh"),
        refine_asr_revision=os.getenv("MIAOJI_REFINE_ASR_REVISION", "v2.0.4"),
        refine_vad_model=os.getenv("MIAOJI_REFINE_VAD_MODEL", "fsmn-vad"),
        refine_punc_model=os.getenv("MIAOJI_REFINE_PUNC_MODEL", "ct-punc"),
        summary_enabled=os.getenv("MIAOJI_SUMMARY_ENABLED", "").lower() in {"1", "true", "yes", "on"},
        summary_base_url=os.getenv("MIAOJI_SUMMARY_BASE_URL", "https://ark.cn-beijing.volces.com/api/coding/v3"),
        summary_model=os.getenv("MIAOJI_SUMMARY_MODEL", "doubao-seed-2.0-lite"),
        summary_api_key=os.getenv("MIAOJI_SUMMARY_API_KEY", ""),
        summary_interval_seconds=float(os.getenv("MIAOJI_SUMMARY_INTERVAL_SECONDS", "15")),
        summary_min_new_chars=int(os.getenv("MIAOJI_SUMMARY_MIN_NEW_CHARS", "80")),
        summary_timeout_seconds=float(os.getenv("MIAOJI_SUMMARY_TIMEOUT_SECONDS", "45")),
        summary_mock=os.getenv("MIAOJI_SUMMARY_MOCK", "").lower() in {"1", "true", "yes", "on"},
        mock_asr=os.getenv("MIAOJI_MOCK_ASR", "").lower() in {"1", "true", "yes", "on"},
    )
