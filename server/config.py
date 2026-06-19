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
    asr_chunk_size: tuple[int, int, int] = (0, 10, 5)
    asr_encoder_chunk_look_back: int = 4
    asr_decoder_chunk_look_back: int = 1
    asr_disable_update: bool = True
    asr_device: str = "cpu"
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
        mock_asr=os.getenv("MIAOJI_MOCK_ASR", "").lower() in {"1", "true", "yes", "on"},
    )
