from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_PATHS = [
    "docs/ARCHITECTURE.md",
    "docs/ROADMAP.md",
    "server/app.py",
    "server/asr.py",
    "server/refine.py",
    "server/storage.py",
    "server/transcript.py",
    "web/index.html",
    "web/app.js",
    "web/manifest.webmanifest",
    "scripts/setup-windows.ps1",
    "scripts/first-run.ps1",
    "scripts/download-model.ps1",
    "scripts/start.ps1",
    "scripts/start-cert-download.ps1",
    "scripts/check-env.ps1",
    "tests/test_core_flow.py",
]

FORBIDDEN_PATHS = [
    "package.json",
    "vite.config.js",
    "vite.config.ts",
    "webpack.config.js",
    "docker-compose.yml",
    "Dockerfile",
]

REQUIRED_REQUIREMENTS = {
    "fastapi",
    "uvicorn",
    "funasr",
    "modelscope",
    "websockets",
}

FORBIDDEN_REQUIREMENTS = {
    "openai-whisper",
    "whisper",
    "faster-whisper",
}


def main() -> int:
    errors: list[str] = []

    for rel in REQUIRED_PATHS:
        if not (ROOT / rel).exists():
            errors.append(f"缺少架构要求文件: {rel}")

    for rel in FORBIDDEN_PATHS:
        if (ROOT / rel).exists():
            errors.append(f"发现可能导致架构漂移的文件: {rel}")

    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    requirement_names = parse_requirement_names(requirements)
    missing = REQUIRED_REQUIREMENTS - requirement_names
    if missing:
        errors.append(f"requirements.txt 缺少依赖: {', '.join(sorted(missing))}")

    forbidden = FORBIDDEN_REQUIREMENTS & requirement_names
    if forbidden:
        errors.append(f"requirements.txt 出现非当前阶段 ASR 依赖: {', '.join(sorted(forbidden))}")

    asr_text = (ROOT / "server" / "asr.py").read_text(encoding="utf-8")
    if "from funasr import AutoModel" not in asr_text:
        errors.append("server/asr.py 必须通过 FunASR AutoModel 接入 ASR")
    if "paraformer-zh-streaming" not in (ROOT / "server" / "config.py").read_text(encoding="utf-8"):
        errors.append("server/config.py 必须保留 paraformer-zh-streaming 默认模型")

    web_text = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    if "TARGET_SAMPLE_RATE = 16000" not in web_text:
        errors.append("web/app.js 必须保持 16k 采样率输出")
    if "/ws/record" not in web_text:
        errors.append("web/app.js 必须通过 /ws/record 发送录音")

    storage_text = (ROOT / "server" / "storage.py").read_text(encoding="utf-8")
    for required in ("audio.wav", "transcript.txt", "meeting.json"):
        if required not in storage_text:
            errors.append(f"server/storage.py 必须保留 {required} 存储契约")

    if errors:
        print("Architecture guard failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Architecture guard passed.")
    return 0


def parse_requirement_names(text: str) -> set[str]:
    names: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name = re.split(r"[<>=~!;\[]", line, maxsplit=1)[0].strip().lower()
        if name:
            names.add(name)
    return names


if __name__ == "__main__":
    sys.exit(main())
