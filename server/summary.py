from __future__ import annotations

import asyncio
import copy
import json
import logging
from contextlib import suppress
from datetime import datetime
from typing import Any, Awaitable, Callable, Protocol

import httpx

from .config import Settings
from .storage import (
    MeetingRecord,
    MeetingStore,
    SUMMARY_KEYS,
    default_summary_status,
    normalize_rolling_summary,
    transcript_line,
)

logger = logging.getLogger(__name__)

SendJson = Callable[[dict[str, Any]], Awaitable[None]]


class SummaryClient(Protocol):
    async def summarize(
        self,
        previous_summary: dict[str, list[Any]],
        new_text: str,
        transcript_context: str,
    ) -> dict[str, list[Any]]:
        ...


class OpenAICompatibleSummaryClient:
    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.summary_base_url.rstrip("/")
        self.model = settings.summary_model
        self.api_key = settings.summary_api_key
        self.timeout = settings.summary_timeout_seconds

    async def summarize(
        self,
        previous_summary: dict[str, list[Any]],
        new_text: str,
        transcript_context: str,
    ) -> dict[str, list[Any]]:
        if not self.api_key:
            raise RuntimeError("MIAOJI_SUMMARY_API_KEY is not set")

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": build_system_prompt()},
                {
                    "role": "user",
                    "content": build_user_prompt(previous_summary, new_text, transcript_context),
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


class MockSummaryClient:
    async def summarize(
        self,
        previous_summary: dict[str, list[Any]],
        new_text: str,
        transcript_context: str,
    ) -> dict[str, list[Any]]:
        summary = copy.deepcopy(normalize_rolling_summary(previous_summary))
        excerpt = new_text[:80]
        if excerpt:
            summary["会议摘要"] = [f"已处理新增转写：{excerpt}"]
        return summary


class SummaryWorker:
    def __init__(
        self,
        settings: Settings,
        store: MeetingStore,
        record: MeetingRecord,
        save_lock: asyncio.Lock,
        send_json: SendJson,
        client: SummaryClient | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.record = record
        self.save_lock = save_lock
        self.send_json = send_json
        self.client = client or create_summary_client(settings)
        self.task: asyncio.Task[None] | None = None
        self.stop_event = asyncio.Event()
        self.last_summarized_index = self._initial_summary_index()

    def start(self) -> None:
        if not self.settings.summary_enabled:
            return
        self.task = asyncio.create_task(self._run(), name=f"summary-{self.record.id}")

    async def finalize(self) -> None:
        if not self.settings.summary_enabled:
            return
        self.stop_event.set()
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
        await self.summarize_once(force=True)

    async def summarize_once(self, force: bool = False) -> bool:
        running_payload: dict[str, Any] | None = None
        async with self.save_lock:
            start_index = self.last_summarized_index
            new_segments = [
                item
                for item in self.record.transcript[start_index:]
                if item.is_final and item.text
            ]
            new_text = "\n".join(item.text for item in new_segments).strip()
            new_chars = len(new_text)
            if not new_segments or (not force and new_chars < self.settings.summary_min_new_chars):
                return False
            end_index = new_segments[-1].index
            previous_summary = copy.deepcopy(normalize_rolling_summary(self.record.rolling_summary))
            context_segments = self.record.transcript[max(0, start_index - 8) :]
            transcript_context = "\n".join(
                transcript_line(self.record, item) for item in context_segments if item.text
            ).strip()
            self.record.summary_status = {
                **default_summary_status(),
                "state": "running",
                "last_updated_at": self.record.summary_status.get("last_updated_at"),
                "last_error": "",
                "model": self.settings.summary_model,
            }
            self.store.save(self.record)
            running_payload = self._build_summary_payload()

        await self._send_summary_payload(running_payload)

        try:
            next_summary = await self.client.summarize(previous_summary, new_text, transcript_context)
            next_summary = normalize_rolling_summary(next_summary)
        except Exception as exc:
            logger.warning("Summary update failed: %s", exc)
            error_payload: dict[str, Any]
            async with self.save_lock:
                self.record.summary_status = {
                    **default_summary_status(),
                    "state": "error",
                    "last_updated_at": self.record.summary_status.get("last_updated_at"),
                    "last_error": str(exc)[:300],
                    "model": self.settings.summary_model,
                }
                self.store.save(self.record)
                error_payload = self._build_summary_payload()
            await self._send_summary_payload(error_payload)
            return False

        updated_at = datetime.now().isoformat(timespec="seconds")
        done_payload: dict[str, Any]
        async with self.save_lock:
            self.record.rolling_summary = next_summary
            self.record.rolling_summary_history.append(
                {
                    "updated_at": updated_at,
                    "model": self.settings.summary_model,
                    "input_start_index": start_index,
                    "input_end_index": end_index,
                    "summary": copy.deepcopy(next_summary),
                }
            )
            self.record.summary_status = {
                **default_summary_status(),
                "state": "idle",
                "last_updated_at": updated_at,
                "last_error": "",
                "model": self.settings.summary_model,
            }
            self.last_summarized_index = end_index + 1
            self.store.save(self.record)
            done_payload = self._build_summary_payload()
        await self._send_summary_payload(done_payload)
        return True

    async def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=self.settings.summary_interval_seconds)
            except asyncio.TimeoutError:
                try:
                    await self.summarize_once(force=False)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Summary worker loop failed")

    async def send_current(self) -> None:
        if not self.settings.summary_enabled:
            return
        async with self.save_lock:
            payload = self._build_summary_payload()
        await self._send_summary_payload(payload)

    def _build_summary_payload(self) -> dict[str, Any]:
        return {
            "type": "summary",
            "summary": copy.deepcopy(self.record.rolling_summary),
            "summary_status": copy.deepcopy(self.record.summary_status),
            "history_count": len(self.record.rolling_summary_history),
        }

    async def _send_summary_payload(self, payload: dict[str, Any] | None) -> None:
        if payload is None:
            return
        try:
            await self.send_json(payload)
        except Exception as exc:
            logger.debug("Failed to send summary websocket payload: %s", exc)

    def _initial_summary_index(self) -> int:
        history = self.record.rolling_summary_history
        if not history:
            return 0
        last = history[-1]
        try:
            return int(last.get("input_end_index", -1)) + 1
        except (TypeError, ValueError):
            return 0


def create_summary_client(settings: Settings) -> SummaryClient:
    if settings.summary_mock:
        return MockSummaryClient()
    return OpenAICompatibleSummaryClient(settings)


def build_system_prompt() -> str:
    keys = "、".join(SUMMARY_KEYS)
    return (
        "你是会议实时摘要助手。只输出 JSON，不要输出 Markdown。"
        f"JSON 必须且只能包含这些键：{keys}。每个键的值必须是数组。"
        "你会收到当前摘要状态和新增逐字稿，请在保留重要旧信息的基础上滚动更新。"
        "不要编造没有在逐字稿中出现的信息。"
        "“每个人负责什么”只能在文本明确出现姓名、称呼或负责人时填写；"
        "如果上下文包含 Speaker 1、Speaker 2 等编号，可以使用这些编号；"
        "不要把 Speaker 编号猜成真实姓名。"
    )


def build_user_prompt(
    previous_summary: dict[str, list[Any]],
    new_text: str,
    transcript_context: str,
) -> str:
    return "\n\n".join(
        [
            "当前结构化摘要：",
            json.dumps(normalize_rolling_summary(previous_summary), ensure_ascii=False),
            "最近上下文：",
            transcript_context or "无",
            "本次新增逐字稿：",
            new_text,
        ]
    )


def parse_summary_content(content: str) -> dict[str, list[Any]]:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("summary response is not JSON")
    parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("summary JSON must be an object")
    return normalize_rolling_summary(parsed)
