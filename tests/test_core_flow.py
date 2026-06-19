from __future__ import annotations

import asyncio
import importlib
import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from server.asr import TranscriptUpdate
from server.config import get_settings
from server.diarization import DiarizationWorker
from server.final_summary import FinalSummaryWorker
from server.storage import MeetingStore, SpeakerSegment, TranscriptSegment, default_rolling_summary
from server.summary import SummaryWorker
from server.transcript import TranscriptAssembler, merge_fragment


class FakeSummaryClient:
    def __init__(self, response: dict[str, list[Any]] | None = None, error: Exception | None = None) -> None:
        self.response = response or {
            "会议摘要": ["讨论了项目进度"],
            "决策事项": ["继续按当前节奏推进"],
            "待办事项": ["整理下周计划"],
            "每个人负责什么": [],
            "风险/问题": ["依赖确认较晚"],
        }
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def summarize(
        self,
        previous_summary: dict[str, list[Any]],
        new_text: str,
        transcript_context: str,
    ) -> dict[str, list[Any]]:
        self.calls.append(
            {
                "previous_summary": previous_summary,
                "new_text": new_text,
                "transcript_context": transcript_context,
            }
        )
        if self.error:
            raise self.error
        return self.response


class FakeDiarizationClient:
    def __init__(self, response: list[SpeakerSegment] | None = None, error: Exception | None = None) -> None:
        self.response = response or [
            SpeakerSegment("Speaker 1", 0.0, 0.5),
            SpeakerSegment("Speaker 2", 0.5, 1.0),
        ]
        self.error = error
        self.calls: list[Path] = []

    async def diarize(self, audio_path: Path, output_dir: Path) -> list[SpeakerSegment]:
        self.calls.append(audio_path)
        if self.error:
            raise self.error
        return self.response


class FakeFinalSummaryClient:
    def __init__(self, response: dict[str, list[Any]] | None = None, error: Exception | None = None) -> None:
        self.response = response or {
            "会议摘要": ["形成正式会议纪要"],
            "决策事项": ["确认继续推进"],
            "待办事项": ["Speaker 1 整理行动项"],
            "每个人负责什么": ["Speaker 1：整理行动项"],
            "风险/问题": ["时间节点需要跟进"],
        }
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def generate(
        self,
        record,
        transcript_text: str,
        rolling_summary: dict[str, list[Any]],
        rolling_history: list[dict[str, Any]],
    ) -> dict[str, list[Any]]:
        self.calls.append(
            {
                "record_id": record.id,
                "transcript_text": transcript_text,
                "rolling_summary": rolling_summary,
                "rolling_history": rolling_history,
            }
        )
        if self.error:
            raise self.error
        return self.response


class CoreFlowTest(unittest.TestCase):
    def setUp(self) -> None:
        for name in (
            "MIAOJI_DATA_DIR",
            "MIAOJI_MOCK_ASR",
            "MIAOJI_SUMMARY_ENABLED",
            "MIAOJI_SUMMARY_MOCK",
            "MIAOJI_SUMMARY_MIN_NEW_CHARS",
            "MIAOJI_SUMMARY_INTERVAL_SECONDS",
            "MIAOJI_TRANSCRIPT_MIN_CHARS",
            "MIAOJI_FINAL_SUMMARY_ENABLED",
            "MIAOJI_FINAL_SUMMARY_MOCK",
            "MIAOJI_FINAL_SUMMARY_MODEL",
            "MIAOJI_FINAL_SUMMARY_API_KEY",
            "MIAOJI_DIARIZATION_MOCK",
            "MIAOJI_DIARIZATION_COMMAND",
        ):
            os.environ.pop(name, None)

    def test_mock_recording_flow(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["MIAOJI_MOCK_ASR"] = "1"
            os.environ["MIAOJI_DATA_DIR"] = temp_dir

            import server.config
            import server.app

            importlib.reload(server.config)
            app_module = importlib.reload(server.app)
            client = TestClient(app_module.app)

            health = client.get("/api/health")
            self.assertEqual(health.status_code, 200)
            self.assertTrue(health.json()["mock_asr"])

            home = client.get("/")
            self.assertEqual(home.status_code, 200)
            self.assertIn("秒记", home.text)

            pcm_second = b"\x00\x00" * 16_000
            with client.websocket_connect("/ws/record?title=test") as websocket:
                started = websocket.receive_json()
                self.assertEqual(started["type"], "meeting_started")
                meeting_id = started["meeting"]["id"]

                websocket.send_bytes(pcm_second)
                update = websocket.receive_json()
                self.assertEqual(update["type"], "transcript")
                self.assertIn("已收到1秒音频", update["segment"]["text"])

                websocket.send_text(json.dumps({"type": "stop"}))
                finished = websocket.receive_json()
                if finished["type"] == "transcript":
                    finished = websocket.receive_json()
                self.assertEqual(finished["type"], "meeting_finished")

            meeting_dir = Path(temp_dir) / meeting_id
            self.assertTrue((meeting_dir / "audio.wav").exists())
            transcript = (meeting_dir / "transcript.txt").read_text(encoding="utf-8").strip()
            self.assertTrue(transcript)

            saved = json.loads((meeting_dir / "meeting.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["title"], "test")
            self.assertEqual(saved["duration_seconds"], 1)
            self.assertGreaterEqual(len(saved["transcript"]), 1)
            self.assertIn("rolling_summary", saved)
            self.assertIn("rolling_summary_history", saved)
            self.assertIn("summary_status", saved)
            self.assertIn("final_summary", saved)
            self.assertIn("final_summary_markdown", saved)
            self.assertIn("final_summary_status", saved)
            self.assertIn("speaker_segments", saved)
            self.assertIn("speaker_status", saved)

    def test_mock_recording_flow_sends_summary_message(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["MIAOJI_MOCK_ASR"] = "1"
            os.environ["MIAOJI_SUMMARY_ENABLED"] = "1"
            os.environ["MIAOJI_SUMMARY_MOCK"] = "1"
            os.environ["MIAOJI_SUMMARY_MIN_NEW_CHARS"] = "1"
            os.environ["MIAOJI_SUMMARY_INTERVAL_SECONDS"] = "0.01"
            os.environ["MIAOJI_TRANSCRIPT_MIN_CHARS"] = "1"
            os.environ["MIAOJI_DATA_DIR"] = temp_dir

            import server.config
            import server.app

            importlib.reload(server.config)
            app_module = importlib.reload(server.app)
            client = TestClient(app_module.app)

            pcm_second = b"\x00\x00" * 16_000
            with client.websocket_connect("/ws/record?title=summary") as websocket:
                self.assertEqual(websocket.receive_json()["type"], "meeting_started")
                first_summary = websocket.receive_json()
                self.assertEqual(first_summary["type"], "summary")

                websocket.send_bytes(pcm_second)
                seen_types = []
                for _ in range(8):
                    message = websocket.receive_json()
                    seen_types.append(message["type"])
                    if message["type"] == "summary" and message["history_count"] >= 1:
                        break
                self.assertIn("transcript", seen_types)
                self.assertIn("summary", seen_types)

                websocket.send_text(json.dumps({"type": "stop"}))
                for _ in range(6):
                    message = websocket.receive_json()
                    if message["type"] == "meeting_finished":
                        break
                else:
                    self.fail("meeting_finished was not sent")

    def test_mock_recording_flow_can_diarize_after_meeting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["MIAOJI_MOCK_ASR"] = "1"
            os.environ["MIAOJI_DIARIZATION_MOCK"] = "1"
            os.environ["MIAOJI_DATA_DIR"] = temp_dir

            import server.config
            import server.app

            importlib.reload(server.config)
            app_module = importlib.reload(server.app)
            client = TestClient(app_module.app)

            pcm_second = b"\x00\x00" * 16_000
            with client.websocket_connect("/ws/record?title=diarize") as websocket:
                meeting_id = websocket.receive_json()["meeting"]["id"]
                websocket.send_bytes(pcm_second)
                websocket.receive_json()
                websocket.send_text(json.dumps({"type": "stop"}))
                for _ in range(4):
                    message = websocket.receive_json()
                    if message["type"] == "meeting_finished":
                        break

            response = client.post(f"/api/meetings/{meeting_id}/diarize")
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["speaker_status"]["state"], "done")
            self.assertGreaterEqual(payload["speaker_segments"], 1)

            saved = json.loads((Path(temp_dir) / meeting_id / "meeting.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["speaker_status"]["state"], "done")
            self.assertGreaterEqual(len(saved["speaker_segments"]), 1)

            transcript = client.get(f"/api/meetings/{meeting_id}/transcript.md").text
            self.assertIn("[Speaker", transcript)

    def test_mock_recording_flow_can_generate_final_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["MIAOJI_MOCK_ASR"] = "1"
            os.environ["MIAOJI_FINAL_SUMMARY_MOCK"] = "1"
            os.environ["MIAOJI_DATA_DIR"] = temp_dir

            import server.config
            import server.app

            importlib.reload(server.config)
            app_module = importlib.reload(server.app)
            client = TestClient(app_module.app)

            pcm_second = b"\x00\x00" * 16_000
            with client.websocket_connect("/ws/record?title=minutes") as websocket:
                meeting_id = websocket.receive_json()["meeting"]["id"]
                websocket.send_bytes(pcm_second)
                websocket.receive_json()
                websocket.send_text(json.dumps({"type": "stop"}))
                for _ in range(4):
                    message = websocket.receive_json()
                    if message["type"] == "meeting_finished":
                        break

            response = client.post(f"/api/meetings/{meeting_id}/final-summary")
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["has_final_summary"])
            self.assertEqual(payload["final_summary_status"]["state"], "done")

            minutes = client.get(f"/api/meetings/{meeting_id}/minutes.md")
            self.assertEqual(minutes.status_code, 200)
            self.assertIn("# minutes", minutes.text)
            self.assertIn("## 会议摘要", minutes.text)
            self.assertIn("## 完整对话转文字", minutes.text)

    def test_streaming_fragments_are_assembled(self) -> None:
        class SettingsStub:
            transcript_min_chars = 8
            transcript_max_chars = 40

        assembler = TranscriptAssembler(SettingsStub())  # type: ignore[arg-type]
        updates = []
        updates.extend(assembler.accept(TranscriptUpdate("今天我们", False, 1.0)))
        updates.extend(assembler.accept(TranscriptUpdate("今天我们讨论一下项目进度。", False, 2.0)))

        self.assertEqual(updates[-1].text, "今天我们讨论一下项目进度。")
        self.assertTrue(updates[-1].is_final)
        self.assertEqual(merge_fragment("今天我们讨论", "讨论一下"), "今天我们讨论一下")

    def test_summary_worker_skips_small_updates(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings = replace(
                    get_settings(),
                    data_dir=Path(temp_dir),
                    summary_enabled=True,
                    summary_min_new_chars=80,
                )
                store = MeetingStore(settings.data_dir)
                record = store.create_meeting("small", settings.sample_rate)
                record.transcript.append(
                    TranscriptSegment(index=0, text="太短了", is_final=True, timestamp=1.0)
                )
                store.save(record)
                client = FakeSummaryClient()
                sent: list[dict[str, Any]] = []

                async def send(payload: dict[str, Any]) -> None:
                    sent.append(payload)

                worker = SummaryWorker(settings, store, record, asyncio.Lock(), send, client)

                updated = await worker.summarize_once()

                self.assertFalse(updated)
                self.assertEqual(client.calls, [])
                self.assertEqual(sent, [])
                saved = store.get_meeting(record.id)
                self.assertEqual(saved.rolling_summary_history, [])

        asyncio.run(scenario())

    def test_summary_worker_updates_summary_and_history(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings = replace(
                    get_settings(),
                    data_dir=Path(temp_dir),
                    summary_enabled=True,
                    summary_model="mock-model",
                    summary_min_new_chars=5,
                )
                store = MeetingStore(settings.data_dir)
                record = store.create_meeting("success", settings.sample_rate)
                record.transcript.append(
                    TranscriptSegment(
                        index=0,
                        text="今天讨论项目进度，决定下周继续推进，王工负责整理计划。",
                        is_final=True,
                        timestamp=1.0,
                    )
                )
                store.save(record)
                sent: list[dict[str, Any]] = []

                async def send(payload: dict[str, Any]) -> None:
                    sent.append(payload)

                worker = SummaryWorker(settings, store, record, asyncio.Lock(), send, FakeSummaryClient())

                updated = await worker.summarize_once()

                self.assertTrue(updated)
                saved = store.get_meeting(record.id)
                self.assertEqual(saved.rolling_summary["会议摘要"], ["讨论了项目进度"])
                self.assertEqual(len(saved.rolling_summary_history), 1)
                self.assertEqual(saved.rolling_summary_history[0]["input_start_index"], 0)
                self.assertEqual(saved.rolling_summary_history[0]["input_end_index"], 0)
                self.assertEqual(saved.summary_status["state"], "idle")
                self.assertEqual(saved.summary_status["model"], "mock-model")
                self.assertGreaterEqual(len(sent), 2)
                self.assertEqual(sent[-1]["type"], "summary")

        asyncio.run(scenario())

    def test_summary_worker_preserves_old_summary_on_error(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings = replace(
                    get_settings(),
                    data_dir=Path(temp_dir),
                    summary_enabled=True,
                    summary_model="broken-model",
                    summary_min_new_chars=5,
                )
                store = MeetingStore(settings.data_dir)
                record = store.create_meeting("error", settings.sample_rate)
                old_summary = default_rolling_summary()
                old_summary["会议摘要"] = ["旧摘要"]
                record.rolling_summary = old_summary
                record.transcript.append(
                    TranscriptSegment(index=0, text="这是一段足够长的新增正式转写。", is_final=True, timestamp=1.0)
                )
                store.save(record)
                sent: list[dict[str, Any]] = []

                async def send(payload: dict[str, Any]) -> None:
                    sent.append(payload)

                worker = SummaryWorker(
                    settings,
                    store,
                    record,
                    asyncio.Lock(),
                    send,
                    FakeSummaryClient(error=RuntimeError("model timeout")),
                )

                updated = await worker.summarize_once()

                self.assertFalse(updated)
                saved = store.get_meeting(record.id)
                self.assertEqual(saved.rolling_summary["会议摘要"], ["旧摘要"])
                self.assertEqual(saved.rolling_summary_history, [])
                self.assertEqual(saved.summary_status["state"], "error")
                self.assertIn("model timeout", saved.summary_status["last_error"])
                self.assertEqual(sent[-1]["summary"]["会议摘要"], ["旧摘要"])

        asyncio.run(scenario())

    def test_final_summary_api_without_transcript_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["MIAOJI_DATA_DIR"] = temp_dir
            os.environ["MIAOJI_FINAL_SUMMARY_MOCK"] = "1"

            import server.config
            import server.app

            importlib.reload(server.config)
            app_module = importlib.reload(server.app)
            client = TestClient(app_module.app)
            record = app_module.store.create_meeting("empty", 16_000)

            response = client.post(f"/api/meetings/{record.id}/final-summary")

            self.assertEqual(response.status_code, 404)
            saved = app_module.store.get_meeting(record.id)
            self.assertEqual(saved.final_summary_markdown, "")
            self.assertEqual(saved.final_summary_status["state"], "idle")

    def test_final_summary_worker_updates_minutes(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings = replace(
                    get_settings(),
                    data_dir=Path(temp_dir),
                    final_summary_model="final-model",
                )
                store = MeetingStore(settings.data_dir)
                record = store.create_meeting("final-success", settings.sample_rate)
                record.transcript.append(
                    TranscriptSegment(
                        index=0,
                        text="Speaker 1 说今天确认继续推进，Speaker 1 负责整理行动项。",
                        is_final=True,
                        timestamp=1.0,
                    )
                )
                store.save(record)
                worker = FinalSummaryWorker(settings, store, record, FakeFinalSummaryClient())

                updated = await worker.run()

                self.assertTrue(updated)
                saved = store.get_meeting(record.id)
                self.assertEqual(saved.final_summary["会议摘要"], ["形成正式会议纪要"])
                self.assertIn("## 待办事项", saved.final_summary_markdown)
                self.assertIn("Speaker 1 整理行动项", saved.final_summary_markdown)
                self.assertEqual(saved.final_summary_status["state"], "done")
                self.assertEqual(saved.final_summary_status["model"], "final-model")

        asyncio.run(scenario())

    def test_final_summary_worker_failure_preserves_old_minutes(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings = replace(
                    get_settings(),
                    data_dir=Path(temp_dir),
                    final_summary_model="broken-final",
                )
                store = MeetingStore(settings.data_dir)
                record = store.create_meeting("final-error", settings.sample_rate)
                record.transcript.append(
                    TranscriptSegment(index=0, text="这是一段正式逐字稿。", is_final=True, timestamp=1.0)
                )
                old_summary = default_rolling_summary()
                old_summary["会议摘要"] = ["旧正式纪要"]
                record.final_summary = old_summary
                record.final_summary_markdown = "# 旧纪要\n"
                store.save(record)
                worker = FinalSummaryWorker(
                    settings,
                    store,
                    record,
                    FakeFinalSummaryClient(error=RuntimeError("final model failed")),
                )

                updated = await worker.run()

                self.assertFalse(updated)
                saved = store.get_meeting(record.id)
                self.assertEqual(saved.final_summary["会议摘要"], ["旧正式纪要"])
                self.assertEqual(saved.final_summary_markdown, "# 旧纪要\n")
                self.assertEqual(saved.final_summary_status["state"], "error")
                self.assertIn("final model failed", saved.final_summary_status["last_error"])

        asyncio.run(scenario())

    def test_diarization_missing_audio_returns_error_without_transcript_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["MIAOJI_DATA_DIR"] = temp_dir
            os.environ["MIAOJI_DIARIZATION_MOCK"] = "1"

            import server.config
            import server.app

            importlib.reload(server.config)
            app_module = importlib.reload(server.app)
            client = TestClient(app_module.app)
            record = app_module.store.create_meeting("missing-audio", 16_000)
            record.transcript.append(TranscriptSegment(0, "保留这段转写。", True, 0.1))
            app_module.store.save(record)

            response = client.post(f"/api/meetings/{record.id}/diarize")

            self.assertEqual(response.status_code, 404)
            saved = app_module.store.get_meeting(record.id)
            self.assertEqual(saved.transcript[0].text, "保留这段转写。")
            self.assertEqual(saved.speaker_segments, [])

    def test_diarization_worker_updates_speaker_segments(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings = replace(
                    get_settings(),
                    data_dir=Path(temp_dir),
                    diarization_mock=True,
                )
                store = MeetingStore(settings.data_dir)
                record = store.create_meeting("speaker-success", settings.sample_rate)
                store.audio_path(record.id).write_bytes(make_silent_wav_bytes())
                worker = DiarizationWorker(settings, store, record, FakeDiarizationClient())

                updated = await worker.run()

                self.assertTrue(updated)
                saved = store.get_meeting(record.id)
                self.assertEqual(saved.speaker_status["state"], "done")
                self.assertEqual(saved.speaker_segments[0].speaker, "Speaker 1")

        asyncio.run(scenario())

    def test_diarization_worker_failure_preserves_old_segments(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings = replace(
                    get_settings(),
                    data_dir=Path(temp_dir),
                    diarization_mock=True,
                )
                store = MeetingStore(settings.data_dir)
                record = store.create_meeting("speaker-error", settings.sample_rate)
                store.audio_path(record.id).write_bytes(make_silent_wav_bytes())
                record.speaker_segments = [SpeakerSegment("Speaker 1", 0.0, 1.0)]
                store.save(record)
                worker = DiarizationWorker(
                    settings,
                    store,
                    record,
                    FakeDiarizationClient(error=RuntimeError("diarization failed")),
                )

                updated = await worker.run()

                self.assertFalse(updated)
                saved = store.get_meeting(record.id)
                self.assertEqual(saved.speaker_segments[0].speaker, "Speaker 1")
                self.assertEqual(saved.speaker_status["state"], "error")
                self.assertIn("diarization failed", saved.speaker_status["last_error"])

        asyncio.run(scenario())


def make_silent_wav_bytes() -> bytes:
    import io
    import wave

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16_000)
        wav.writeframes(b"\x00\x00" * 16_000)
    return buffer.getvalue()


if __name__ == "__main__":
    unittest.main()
