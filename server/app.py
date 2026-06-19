from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .asr import TranscriptUpdate, create_transcriber
from .config import Settings, get_settings
from .diarization import DiarizationWorker
from .refine import OfflineTranscriptRefiner
from .storage import MeetingAudioWriter, MeetingRecord, MeetingStore, TranscriptSegment, transcript_markdown
from .summary import SummaryWorker
from .transcript import TranscriptAssembler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

settings = get_settings()
store = MeetingStore(settings.data_dir)
app = FastAPI(title=settings.app_name)


class StopRecording(Exception):
    pass


@app.get("/api/health")
def health() -> dict[str, object]:
    return {
        "ok": True,
        "sample_rate": settings.sample_rate,
        "asr_model": settings.asr_model,
        "mock_asr": settings.mock_asr,
        "summary_enabled": settings.summary_enabled,
        "diarization_enabled": settings.diarization_enabled,
        "data_dir": str(settings.data_dir),
    }


@app.get("/api/meetings")
def list_meetings() -> list[dict[str, object]]:
    return store.list_meetings()


@app.get("/api/meetings/{meeting_id}")
def get_meeting(meeting_id: str) -> MeetingRecord:
    try:
        return store.get_meeting(meeting_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Meeting not found") from exc


@app.get("/api/meetings/{meeting_id}/transcript.md")
def export_transcript(meeting_id: str) -> Response:
    try:
        record = store.get_meeting(meeting_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Meeting not found") from exc
    if not record.transcript:
        raise HTTPException(status_code=404, detail="Transcript not found")
    return Response(
        content=transcript_markdown(record),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="{record.id}.md"'},
    )


@app.post("/api/meetings/{meeting_id}/refine-transcript")
async def refine_transcript(meeting_id: str) -> dict[str, object]:
    try:
        record = store.get_meeting(meeting_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Meeting not found") from exc

    audio_path = store.audio_path(meeting_id)
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio not found")

    refiner = OfflineTranscriptRefiner(settings)
    segments = await asyncio.to_thread(refiner.refine, audio_path)
    if not segments:
        raise HTTPException(status_code=422, detail="No speech recognized")

    record.transcript = segments
    record.status = "finished"
    store.save(record)
    write_transcript_text(record)
    return {"ok": True, "meeting_id": meeting_id, "segments": len(segments)}


@app.post("/api/meetings/{meeting_id}/diarize")
async def diarize_meeting(meeting_id: str) -> dict[str, object]:
    try:
        record = store.get_meeting(meeting_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Meeting not found") from exc

    if not settings.diarization_enabled:
        raise HTTPException(status_code=400, detail="Speaker diarization is disabled")

    audio_path = store.audio_path(meeting_id)
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio not found")

    worker = DiarizationWorker(settings, store, record)
    ok = await worker.run()
    refreshed = store.get_meeting(meeting_id)
    if refreshed.speaker_segments:
        write_transcript_text(refreshed)
    return {
        "ok": ok,
        "meeting_id": meeting_id,
        "speaker_segments": len(refreshed.speaker_segments),
        "speaker_status": refreshed.speaker_status,
    }


@app.websocket("/ws/record")
async def record_audio(websocket: WebSocket) -> None:
    await websocket.accept()
    title = websocket.query_params.get("title") or None
    record = store.create_meeting(title, settings.sample_rate)
    writer = MeetingAudioWriter(store.audio_path(record.id), settings.sample_rate)
    save_lock = asyncio.Lock()
    send_lock = asyncio.Lock()

    async def send_json(payload: dict[str, object]) -> None:
        async with send_lock:
            await websocket.send_json(payload)

    try:
        transcriber = create_transcriber(settings)
    except Exception as exc:
        writer.close()
        logger.exception("Failed to initialize ASR")
        await send_json({"type": "error", "message": f"ASR 初始化失败：{exc}"})
        await websocket.close(code=1011)
        return

    assembler = TranscriptAssembler(settings)
    summary_worker = SummaryWorker(settings, store, record, save_lock, send_json)

    await send_json(
        {
            "type": "meeting_started",
            "meeting": {
                "id": record.id,
                "title": record.title,
                "sample_rate": record.sample_rate,
                "created_at": record.created_at,
            },
        }
    )
    summary_worker.start()
    await summary_worker.send_current()

    async def persist_update(update: TranscriptUpdate) -> TranscriptSegment:
        async with save_lock:
            segment = TranscriptSegment(
                index=len(record.transcript),
                text=update.text,
                is_final=update.is_final,
                timestamp=update.timestamp,
            )
            if update.is_final:
                record.transcript.append(segment)
                record.duration_seconds = writer.duration_seconds
                store.save(record)
                write_transcript_text(record)
            return segment

    async def handle_updates(updates: list[TranscriptUpdate], force: bool = False) -> None:
        for update in assembler.accept_many(updates, force=force):
            segment = await persist_update(update)
            await send_json(
                {
                    "type": "transcript",
                    "segment": {
                        "index": segment.index,
                        "text": segment.text,
                        "is_final": segment.is_final,
                        "timestamp": segment.timestamp,
                    },
                    "duration_seconds": writer.duration_seconds,
                }
            )

    try:
        while True:
            message = await websocket.receive()
            if "bytes" in message and message["bytes"] is not None:
                pcm = message["bytes"]
                writer.write(pcm)
                updates = await transcriber.accept_audio(pcm)
                await handle_updates(updates)
            elif "text" in message and message["text"] is not None:
                await _handle_text_message(message["text"], transcriber, handle_updates)
    except StopRecording:
        logger.info("Recorder websocket stopped: %s", record.id)
    except WebSocketDisconnect:
        logger.info("Recorder websocket disconnected: %s", record.id)
    except RuntimeError as exc:
        if "disconnect message" in str(exc):
            logger.info("Recorder websocket disconnected: %s", record.id)
        else:
            raise
    except Exception:
        logger.exception("Recorder websocket failed")
        with suppress(RuntimeError):
            await send_json({"type": "error", "message": "录音连接异常，已尽量保存当前内容。"})
    finally:
        with suppress(Exception):
            await handle_updates(await transcriber.close(), force=True)
        writer.close()
        async with save_lock:
            record.status = "finished"
            record.duration_seconds = writer.duration_seconds
            store.save(record)
        with suppress(Exception):
            await summary_worker.finalize()
        with suppress(RuntimeError):
            await send_json(
                {
                    "type": "meeting_finished",
                    "meeting_id": record.id,
                    "duration_seconds": record.duration_seconds,
                }
            )


async def _handle_text_message(text: str, transcriber, handle_updates) -> None:
    try:
        event = json.loads(text)
    except json.JSONDecodeError:
        return

    if event.get("type") == "stop":
        await handle_updates(await transcriber.close(), force=True)
        raise StopRecording()


def write_transcript_text(record: MeetingRecord) -> None:
    store.transcript_path(record.id).write_text(
        transcript_markdown(record),
        encoding="utf-8",
    )


@app.exception_handler(404)
def not_found(_, __) -> JSONResponse:
    return JSONResponse({"detail": "Not found"}, status_code=404)


web_dir = Path(settings.static_dir)
app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
