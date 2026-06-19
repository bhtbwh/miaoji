from __future__ import annotations

import copy
import json
import logging
from datetime import datetime
from typing import Any, Protocol

import httpx

from .config import Settings
from .storage import (
    MeetingRecord,
    MeetingStore,
    SUMMARY_KEYS,
    default_final_summary_status,
    normalize_rolling_summary,
    transcript_markdown,
)
from .summary import parse_summary_content

logger = logging.getLogger(__name__)


class FinalSummaryClient(Protocol):
    async def generate(
        self,
        record: MeetingRecord,
        transcript_text: str,
        rolling_summary: dict[str, list[Any]],
        rolling_history: list[dict[str, Any]],
    ) -> dict[str, list[Any]]:
        ...


class OpenAICompatibleFinalSummaryClient:
    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.final_summary_base_url.rstrip("/")
        self.model = settings.final_summary_model
        self.api_key = settings.final_summary_api_key
        self.timeout = settings.final_summary_timeout_seconds

    async def generate(
        self,
        record: MeetingRecord,
        transcript_text: str,
        rolling_summary: dict[str, list[Any]],
        rolling_history: list[dict[str, Any]],
    ) -> dict[str, list[Any]]:
        if not self.api_key:
            raise RuntimeError("MIAOJI_FINAL_SUMMARY_API_KEY is not set")

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": build_system_prompt()},
                {
                    "role": "user",
                    "content": build_user_prompt(record, transcript_text, rolling_summary, rolling_history),
                },
            ],
            "temperature": 0.2,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        content = data["choices"][0]["message"]["content"]
        return parse_summary_content(content)


class MockFinalSummaryClient:
    async def generate(
        self,
        record: MeetingRecord,
        transcript_text: str,
        rolling_summary: dict[str, list[Any]],
        rolling_history: list[dict[str, Any]],
    ) -> dict[str, list[Any]]:
        summary = copy.deepcopy(normalize_rolling_summary(rolling_summary))
        if not any(summary.values()):
            excerpt = transcript_text.replace("\n", " ")[:80]
            summary["会议摘要"] = [f"正式纪要已根据完整逐字稿生成：{excerpt}"]
        if rolling_history:
            summary["会议摘要"] = summary["会议摘要"] or ["已合并滚动摘要历史和完整逐字稿。"]
        return summary


class FinalSummaryWorker:
    def __init__(
        self,
        settings: Settings,
        store: MeetingStore,
        record: MeetingRecord,
        client: FinalSummaryClient | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.record = record
        self.client = client or create_final_summary_client(settings)

    async def run(self) -> bool:
        transcript_text = transcript_markdown(self.record).strip()
        if not transcript_text:
            raise ValueError("Transcript not found")

        previous_status = copy.deepcopy(self.record.final_summary_status)
        self.record.final_summary_status = {
            **default_final_summary_status(),
            "state": "running",
            "last_updated_at": previous_status.get("last_updated_at"),
            "last_error": "",
            "model": self.settings.final_summary_model,
        }
        self.store.save(self.record)

        rolling_summary = copy.deepcopy(normalize_rolling_summary(self.record.rolling_summary))
        rolling_history = copy.deepcopy(self.record.rolling_summary_history)
        try:
            final_summary = await self.client.generate(
                self.record,
                transcript_text,
                rolling_summary,
                rolling_history,
            )
            final_summary = normalize_rolling_summary(final_summary)
            markdown = render_minutes_markdown(self.record, final_summary, transcript_text)
        except Exception as exc:
            logger.warning("Final summary failed: %s", exc)
            self.record.final_summary_status = {
                **default_final_summary_status(),
                "state": "error",
                "last_updated_at": datetime.now().isoformat(timespec="seconds"),
                "last_error": str(exc)[:300],
                "model": self.settings.final_summary_model,
            }
            self.store.save(self.record)
            return False

        updated_at = datetime.now().isoformat(timespec="seconds")
        self.record.final_summary = final_summary
        self.record.final_summary_markdown = markdown
        self.record.final_summary_status = {
            **default_final_summary_status(),
            "state": "done",
            "last_updated_at": updated_at,
            "last_error": "",
            "model": self.settings.final_summary_model,
        }
        self.store.save(self.record)
        return True


def create_final_summary_client(settings: Settings) -> FinalSummaryClient:
    if settings.final_summary_mock:
        return MockFinalSummaryClient()
    return OpenAICompatibleFinalSummaryClient(settings)


def build_system_prompt() -> str:
    keys = "、".join(SUMMARY_KEYS)
    return (
        "你是会议纪要整理助手。只输出 JSON，不要输出 Markdown。"
        f"JSON 必须且只能包含这些键：{keys}。每个键的值必须是数组。"
        "请基于完整逐字稿、滚动摘要历史和已有决策/待办/风险生成正式纪要。"
        "不要编造没有在材料中出现的信息。"
        "每条内容应简洁、可执行、适合会后存档。"
        "如果上下文包含 Speaker 1、Speaker 2 等编号，可以使用这些编号；"
        "不要把 Speaker 编号猜成真实姓名。"
    )


def build_user_prompt(
    record: MeetingRecord,
    transcript_text: str,
    rolling_summary: dict[str, list[Any]],
    rolling_history: list[dict[str, Any]],
) -> str:
    history_digest = [
        {
            "updated_at": item.get("updated_at"),
            "model": item.get("model"),
            "input_start_index": item.get("input_start_index"),
            "input_end_index": item.get("input_end_index"),
            "summary": normalize_rolling_summary(item.get("summary")),
        }
        for item in rolling_history[-12:]
        if isinstance(item, dict)
    ]
    return "\n\n".join(
        [
            "会议信息：",
            json.dumps(
                {
                    "title": record.title,
                    "created_at": record.created_at,
                    "duration_seconds": record.duration_seconds,
                    "segments": len(record.transcript),
                },
                ensure_ascii=False,
            ),
            "当前滚动摘要：",
            json.dumps(normalize_rolling_summary(rolling_summary), ensure_ascii=False),
            "最近滚动摘要历史：",
            json.dumps(history_digest, ensure_ascii=False),
            "完整逐字稿：",
            transcript_text,
        ]
    )


def render_minutes_markdown(
    record: MeetingRecord,
    final_summary: dict[str, list[Any]],
    transcript_text: str,
) -> str:
    summary = normalize_rolling_summary(final_summary)
    lines = [
        f"# {record.title}",
        "",
        f"- 会议时间：{record.created_at}",
        f"- 会议时长：{format_duration(record.duration_seconds)}",
        f"- 转写段数：{len(record.transcript)}",
        "",
    ]
    for key in SUMMARY_KEYS:
        lines.extend([f"## {key}", ""])
        values = summary[key]
        if values:
            lines.extend(f"- {stringify_summary_item(value)}" for value in values)
        else:
            lines.append("- 暂无")
        lines.append("")

    lines.extend(["## 完整对话转文字", "", transcript_text.strip(), ""])
    return "\n".join(lines)


def stringify_summary_item(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return "；".join(f"{key}：{item}" for key, item in value.items())
    return str(value)


def format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    hours = total // 3600
    minutes = (total % 3600) // 60
    rest = total % 60
    return f"{hours:02d}:{minutes:02d}:{rest:02d}"
