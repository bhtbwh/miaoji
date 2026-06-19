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
    "server/diarization.py",
    "server/final_summary.py",
    "server/refine.py",
    "server/storage.py",
    "server/summary.py",
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
    "httpx",
    "modelscope",
    "websockets",
}

SUMMARY_KEYS = ["会议摘要", "决策事项", "待办事项", "每个人负责什么", "风险/问题"]

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
    for required in ("final-summary", "minutes.md", "生成纪要"):
        if required not in web_text:
            errors.append(f"web/app.js 缺少会后正式纪要入口: {required}")

    storage_text = (ROOT / "server" / "storage.py").read_text(encoding="utf-8")
    for required in ("audio.wav", "transcript.txt", "meeting.json"):
        if required not in storage_text:
            errors.append(f"server/storage.py 必须保留 {required} 存储契约")
    for required in ("rolling_summary", "rolling_summary_history", "summary_status"):
        if required not in storage_text:
            errors.append(f"server/storage.py 必须保留 {required} 摘要存储字段")
    for required in ("final_summary", "final_summary_markdown", "final_summary_status"):
        if required not in storage_text:
            errors.append(f"server/storage.py 必须保留 {required} 会后纪要存储字段")
    for required in ("speaker_segments", "speaker_status"):
        if required not in storage_text:
            errors.append(f"server/storage.py 必须保留 {required} 说话人分离字段")
    for key in SUMMARY_KEYS:
        if key not in storage_text:
            errors.append(f"server/storage.py 必须保留摘要固定字段: {key}")

    summary_text = (ROOT / "server" / "summary.py").read_text(encoding="utf-8")
    for required in ("SummaryWorker", "chat/completions", "MIAOJI_SUMMARY_API_KEY", "summary_min_new_chars"):
        if required not in summary_text:
            errors.append(f"server/summary.py 缺少摘要约束: {required}")
    if "item.is_final" not in summary_text:
        errors.append("server/summary.py 必须只读取正式 transcript segment 做摘要")

    app_text = (ROOT / "server" / "app.py").read_text(encoding="utf-8")
    if "SummaryWorker" not in app_text or '"type": "summary"' not in summary_text:
        errors.append("server/app.py 必须启动 SummaryWorker，并通过 WebSocket 发送 summary 消息")
    if "DiarizationWorker" not in app_text or "/diarize" not in app_text:
        errors.append("server/app.py 必须提供会后说话人分离 API")
    record_audio_body = app_text.split('@app.websocket("/ws/record")', 1)[-1].split("\ndef write_transcript_text", 1)[0]
    if "DiarizationWorker" in record_audio_body:
        errors.append("说话人分离不能进入 /ws/record 实时录音主循环")

    diarization_text = (ROOT / "server" / "diarization.py").read_text(encoding="utf-8")
    for required in ("DiarizationWorker", "MIAOJI_DIARIZATION_COMMAND", "MockDiarizationClient", "parse_rttm"):
        if required not in diarization_text:
            errors.append(f"server/diarization.py 缺少说话人分离约束: {required}")

    final_summary_text = (ROOT / "server" / "final_summary.py").read_text(encoding="utf-8")
    for required in (
        "FinalSummaryWorker",
        "chat/completions",
        "MIAOJI_FINAL_SUMMARY_API_KEY",
        "render_minutes_markdown",
    ):
        if required not in final_summary_text:
            errors.append(f"server/final_summary.py 缺少会后正式纪要约束: {required}")
    if "FinalSummaryWorker" not in app_text or "/final-summary" not in app_text or "/minutes.md" not in app_text:
        errors.append("server/app.py 必须提供会后正式纪要 API 和 Markdown 导出")
    if "FinalSummaryWorker" in record_audio_body:
        errors.append("会后正式纪要不能进入 /ws/record 实时录音主循环")

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
