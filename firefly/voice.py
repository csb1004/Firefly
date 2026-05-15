import asyncio
import base64
import io
import json
import time
import wave
from collections import deque
from functools import partial

import discord
from discord import opus as discord_opus
from openai import OpenAI

try:
    import audioop
except ImportError:  # pragma: no cover - Python 3.13 needs audioop-lts.
    audioop = None

try:
    import websockets
except ImportError:  # pragma: no cover - handled at command time.
    websockets = None

try:
    from discord.ext import voice_recv
except ImportError:  # pragma: no cover - handled at command time.
    voice_recv = None

try:
    import davey
except ImportError:  # pragma: no cover - DAVE can be unavailable on older discord.py installs.
    davey = None

from .config import (
    OPENAI_API_KEY,
    VOICE_FALLBACK_SESSION_MAX_SECONDS,
    VOICE_FALLBACK_TRANSCRIPTION_MODEL,
    VOICE_REALTIME_TRANSCRIPTION_URL,
    VOICE_TRANSCRIBER_QUEUE_SIZE,
    VOICE_TRANSCRIPTION_COMMIT_SECONDS,
    VOICE_TRANSCRIPTION_IDLE_COMMIT_SECONDS,
    VOICE_TRANSCRIPTION_MIN_COMMIT_MS,
    VOICE_TRANSCRIPT_LANGUAGE,
    VOICE_TRANSCRIPTION_MODEL,
)
from .voice_records import (
    append_recording_event,
    append_transcript,
    create_recording,
    finish_recording,
)

DISCORD_PCM_RATE = 48000
OPENAI_PCM_RATE = 24000
SAMPLE_WIDTH = 2
TRANSCRIBER_DRAIN_SECONDS = 4
TRANSCRIBER_FINAL_DRAIN_SECONDS = 15

_active_recordings: dict[int, "ActiveVoiceRecording"] = {}
_openai_client = OpenAI(api_key=OPENAI_API_KEY)


def _display_name(user: object) -> str:
    return str(getattr(user, "display_name", getattr(user, "name", "알 수 없음")))


def _voice_dependency_error() -> str | None:
    if voice_recv is None:
        return "음성 수신 모듈이 없어. `discord-ext-voice-recv` 의존성을 설치한 뒤 다시 배포해야 해."
    if websockets is None:
        return "OpenAI Realtime 연결 모듈이 없어. `websockets` 의존성을 설치한 뒤 다시 배포해야 해."
    if audioop is None:
        return "PCM 변환 모듈이 없어. Python 3.13 이상이면 `audioop-lts` 의존성이 필요해."
    return None


async def _connect_realtime_websocket(safety_identifier: str):
    if websockets is None:
        raise RuntimeError("websockets is not installed")

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "OpenAI-Safety-Identifier": safety_identifier,
    }

    try:
        return await websockets.connect(
            VOICE_REALTIME_TRANSCRIPTION_URL,
            additional_headers=headers,
            max_size=None,
        )
    except TypeError:
        return await websockets.connect(
            VOICE_REALTIME_TRANSCRIPTION_URL,
            extra_headers=headers,
            max_size=None,
        )


class RealtimeTranscriber:
    def __init__(
        self,
        *,
        recording_filename: str,
        speaker_id: int,
        speaker_name: str,
    ) -> None:
        self.recording_filename = recording_filename
        self.speaker_id = speaker_id
        self.speaker_name = speaker_name
        self.queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=VOICE_TRANSCRIBER_QUEUE_SIZE)
        self.task: asyncio.Task | None = None
        self.rate_state = None
        self.dropped_chunks = 0
        self.sent_audio = False
        self.pending_audio = False
        self.pending_audio_bytes = bytearray()
        self.pending_audio_ms = 0.0
        self.pending_max_rms = 0
        self.last_audio_at: float | None = None
        self.transcript_parts: dict[str, list[str]] = {}
        self.pending_commits: deque[dict] = deque()
        self.committed_audio: dict[str, bytes] = {}
        self.session_audio_bytes = bytearray()
        self.session_audio_truncated = False
        self.saved_transcript_count = 0
        self.logged_pcm_observation = False
        self.closed = False

    def start(self) -> None:
        if self.task is None:
            self.task = asyncio.create_task(self._run())

    def push(self, pcm: bytes) -> None:
        if self.closed:
            return
        try:
            self.queue.put_nowait(pcm)
        except asyncio.QueueFull:
            self.dropped_chunks += 1
            if self.dropped_chunks in {1, 50, 100} or self.dropped_chunks % 250 == 0:
                append_recording_event(
                    self.recording_filename,
                    "audio_queue_full",
                    speaker_id=self.speaker_id,
                    speaker_name=self.speaker_name,
                    dropped_chunks=self.dropped_chunks,
                )

    def stop(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            self.queue.put_nowait(None)
        except asyncio.QueueFull:
            asyncio.create_task(self.queue.put(None))

    async def wait_closed(self) -> None:
        if self.task is None:
            return
        await self.task

    def _store_transcript(self, text: str, item_id: str | None = None) -> bool:
        text = text.strip()
        if not text:
            return False

        append_transcript(
            self.recording_filename,
            speaker_id=self.speaker_id,
            speaker_name=self.speaker_name,
            text=text,
            item_id=item_id,
        )
        self.saved_transcript_count += 1
        return True

    def _convert_pcm(self, pcm: bytes) -> bytes:
        if audioop is None or not pcm:
            return b""

        try:
            if not self.logged_pcm_observation:
                self.logged_pcm_observation = True
                append_recording_event(
                    self.recording_filename,
                    "pcm_input_observed",
                    speaker_id=self.speaker_id,
                    speaker_name=self.speaker_name,
                    bytes=len(pcm),
                    input_ms=round(len(pcm) / SAMPLE_WIDTH / 2 / DISCORD_PCM_RATE * 1000, 2),
                    assumed_rate=DISCORD_PCM_RATE,
                    assumed_channels=2,
                )
            mono = audioop.tomono(pcm, SAMPLE_WIDTH, 0.5, 0.5)
            resampled, self.rate_state = audioop.ratecv(
                mono,
                SAMPLE_WIDTH,
                1,
                DISCORD_PCM_RATE,
                OPENAI_PCM_RATE,
                self.rate_state,
            )
            return resampled
        except audioop.error as e:
            append_recording_event(
                self.recording_filename,
                "pcm_convert_error",
                speaker_id=self.speaker_id,
                speaker_name=self.speaker_name,
                error=str(e),
            )
            return b""

    async def _commit_audio(self, websocket, reason: str) -> None:
        if not self.pending_audio:
            return

        if self.pending_audio_ms < VOICE_TRANSCRIPTION_MIN_COMMIT_MS:
            append_recording_event(
                self.recording_filename,
                "audio_buffer_commit_skipped",
                speaker_id=self.speaker_id,
                speaker_name=self.speaker_name,
                reason=reason,
                audio_ms=round(self.pending_audio_ms, 2),
                min_audio_ms=VOICE_TRANSCRIPTION_MIN_COMMIT_MS,
                max_rms=self.pending_max_rms,
            )
            self.pending_audio = False
            self.pending_audio_bytes.clear()
            self.pending_audio_ms = 0.0
            self.pending_max_rms = 0
            return

        try:
            await websocket.send(json.dumps({"type": "input_audio_buffer.commit"}))
            self.pending_commits.append({
                "audio": bytes(self.pending_audio_bytes),
                "audio_ms": self.pending_audio_ms,
                "max_rms": self.pending_max_rms,
                "reason": reason,
            })
            append_recording_event(
                self.recording_filename,
                "audio_buffer_committed",
                speaker_id=self.speaker_id,
                speaker_name=self.speaker_name,
                reason=reason,
                audio_ms=round(self.pending_audio_ms, 2),
                max_rms=self.pending_max_rms,
            )
        except Exception as e:
            append_recording_event(
                self.recording_filename,
                "transcription_commit_error",
                speaker_id=self.speaker_id,
                speaker_name=self.speaker_name,
                reason=reason,
                error=str(e),
            )
        finally:
            self.pending_audio = False
            self.pending_audio_bytes.clear()
            self.pending_audio_ms = 0.0
            self.pending_max_rms = 0

    async def _send_audio(self, websocket) -> None:
        last_commit_at = time.monotonic()

        while True:
            try:
                pcm = await asyncio.wait_for(self.queue.get(), timeout=0.25)
            except asyncio.TimeoutError:
                now = time.monotonic()
                if (
                    self.pending_audio
                    and self.last_audio_at is not None
                    and now - self.last_audio_at >= VOICE_TRANSCRIPTION_IDLE_COMMIT_SECONDS
                ):
                    await self._commit_audio(websocket, "idle")
                    last_commit_at = now
                continue

            if pcm is None:
                break

            converted = self._convert_pcm(pcm)
            if not converted:
                continue

            payload = {
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(converted).decode("ascii"),
            }
            await websocket.send(json.dumps(payload))
            self.sent_audio = True
            self.pending_audio = True
            self.pending_audio_bytes.extend(converted)
            self._append_session_audio(converted)
            self.pending_audio_ms += len(converted) / SAMPLE_WIDTH / OPENAI_PCM_RATE * 1000
            if audioop is not None:
                self.pending_max_rms = max(self.pending_max_rms, audioop.rms(converted, SAMPLE_WIDTH))
            self.last_audio_at = time.monotonic()

            if self.last_audio_at - last_commit_at >= VOICE_TRANSCRIPTION_COMMIT_SECONDS:
                await self._commit_audio(websocket, "interval")
                last_commit_at = self.last_audio_at

        await self._commit_audio(websocket, "stop")

    async def _receive_events(self, websocket) -> None:
        async for message in websocket:
            try:
                event = json.loads(message)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type")
            if event_type == "input_audio_buffer.committed":
                item_id = str(event.get("item_id") or "")
                if item_id and self.pending_commits:
                    self.committed_audio[item_id] = self.pending_commits.popleft()["audio"]
            elif event_type == "conversation.item.input_audio_transcription.completed":
                item_id = str(event.get("item_id") or "")
                buffered_text = "".join(self.transcript_parts.pop(item_id, []))
                transcript = str(event.get("transcript") or buffered_text).strip()
                if not transcript:
                    audio_bytes = self._take_committed_audio(item_id)
                    transcript = await self._fallback_transcribe(audio_bytes, item_id)
                append_recording_event(
                    self.recording_filename,
                    "transcription_completed",
                    speaker_id=self.speaker_id,
                    speaker_name=self.speaker_name,
                    item_id=item_id or None,
                    text_length=len(transcript),
                )
                self._store_transcript(transcript, item_id or None)
            elif event_type == "conversation.item.input_audio_transcription.delta":
                item_id = str(event.get("item_id") or "")
                delta = str(event.get("delta") or "")
                if delta:
                    self.transcript_parts.setdefault(item_id, []).append(delta)
            elif event_type == "conversation.item.input_audio_transcription.failed":
                error = event.get("error") or {}
                append_recording_event(
                    self.recording_filename,
                    "transcription_failed",
                    speaker_id=self.speaker_id,
                    speaker_name=self.speaker_name,
                    item_id=event.get("item_id"),
                    code=error.get("code"),
                    message=error.get("message"),
                )
                self._take_committed_audio(str(event.get("item_id") or ""))
            elif event_type == "error":
                error = event.get("error") or {}
                append_recording_event(
                    self.recording_filename,
                    "transcription_error",
                    speaker_id=self.speaker_id,
                    speaker_name=self.speaker_name,
                    code=error.get("code"),
                    message=error.get("message"),
                )

    def _take_committed_audio(self, item_id: str) -> bytes | None:
        audio = self.committed_audio.pop(item_id, None) if item_id else None
        if audio is None and self.pending_commits:
            audio = self.pending_commits.popleft()["audio"]
        return audio

    def _append_session_audio(self, pcm: bytes) -> None:
        if not VOICE_FALLBACK_SESSION_MAX_SECONDS or VOICE_FALLBACK_SESSION_MAX_SECONDS <= 0:
            return

        max_bytes = int(VOICE_FALLBACK_SESSION_MAX_SECONDS * OPENAI_PCM_RATE * SAMPLE_WIDTH)
        if len(self.session_audio_bytes) >= max_bytes:
            if not self.session_audio_truncated:
                self.session_audio_truncated = True
                append_recording_event(
                    self.recording_filename,
                    "fallback_session_audio_truncated",
                    speaker_id=self.speaker_id,
                    speaker_name=self.speaker_name,
                    max_seconds=VOICE_FALLBACK_SESSION_MAX_SECONDS,
                )
            return

        remaining = max_bytes - len(self.session_audio_bytes)
        self.session_audio_bytes.extend(pcm[:remaining])

    @staticmethod
    def _pcm_to_wav_bytes(pcm: bytes) -> bytes:
        output = io.BytesIO()
        with wave.open(output, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(SAMPLE_WIDTH)
            wav_file.setframerate(OPENAI_PCM_RATE)
            wav_file.writeframes(pcm)
        return output.getvalue()

    def _fallback_transcribe_sync(self, pcm: bytes) -> str:
        wav_bytes = self._pcm_to_wav_bytes(pcm)
        audio_file = io.BytesIO(wav_bytes)
        audio_file.name = "discord-voice.wav"
        request_kwargs = {
            "model": VOICE_FALLBACK_TRANSCRIPTION_MODEL,
            "file": audio_file,
            "response_format": "text",
        }
        if VOICE_TRANSCRIPT_LANGUAGE:
            request_kwargs["language"] = VOICE_TRANSCRIPT_LANGUAGE
        result = _openai_client.audio.transcriptions.create(**request_kwargs)
        if isinstance(result, str):
            return result.strip()
        return str(getattr(result, "text", "") or "").strip()

    async def _fallback_transcribe(self, pcm: bytes | None, item_id: str) -> str:
        if not pcm or not VOICE_FALLBACK_TRANSCRIPTION_MODEL:
            return ""

        audio_ms = len(pcm) / SAMPLE_WIDTH / OPENAI_PCM_RATE * 1000
        append_recording_event(
            self.recording_filename,
            "fallback_transcription_started",
            speaker_id=self.speaker_id,
            speaker_name=self.speaker_name,
            item_id=item_id or None,
            model=VOICE_FALLBACK_TRANSCRIPTION_MODEL,
            audio_ms=round(audio_ms, 2),
        )

        try:
            transcript = await asyncio.to_thread(self._fallback_transcribe_sync, pcm)
        except Exception as e:
            append_recording_event(
                self.recording_filename,
                "fallback_transcription_error",
                speaker_id=self.speaker_id,
                speaker_name=self.speaker_name,
                item_id=item_id or None,
                error=str(e),
            )
            return ""

        append_recording_event(
            self.recording_filename,
            "fallback_transcription_completed",
            speaker_id=self.speaker_id,
            speaker_name=self.speaker_name,
            item_id=item_id or None,
            text_length=len(transcript),
        )
        return transcript

    def _flush_partial_transcripts(self, reason: str) -> None:
        for item_id, parts in list(self.transcript_parts.items()):
            transcript = "".join(parts).strip()
            if not transcript:
                continue

            append_recording_event(
                self.recording_filename,
                "partial_transcript_flushed",
                speaker_id=self.speaker_id,
                speaker_name=self.speaker_name,
                item_id=item_id or None,
                reason=reason,
                text_length=len(transcript),
            )
            self._store_transcript(transcript, f"{item_id}:partial" if item_id else None)
            self.transcript_parts.pop(item_id, None)

    async def _fallback_session_transcribe_if_needed(self) -> None:
        if self.saved_transcript_count > 0:
            return
        if len(self.session_audio_bytes) < SAMPLE_WIDTH * OPENAI_PCM_RATE:
            return

        transcript = await self._fallback_transcribe(
            bytes(self.session_audio_bytes),
            "session_fallback",
        )
        if not transcript:
            return

        append_recording_event(
            self.recording_filename,
            "session_fallback_transcript_saved",
            speaker_id=self.speaker_id,
            speaker_name=self.speaker_name,
            text_length=len(transcript),
        )
        self._store_transcript(transcript, "session_fallback")

    async def _run(self) -> None:
        websocket = None
        sender = None
        receiver = None

        try:
            websocket = await _connect_realtime_websocket(f"discord-user-{self.speaker_id}")
            transcription = {"model": VOICE_TRANSCRIPTION_MODEL}
            if VOICE_TRANSCRIPT_LANGUAGE:
                transcription["language"] = VOICE_TRANSCRIPT_LANGUAGE

            await websocket.send(json.dumps({
                "type": "session.update",
                "session": {
                    "type": "transcription",
                    "audio": {
                        "input": {
                            "format": {
                                "type": "audio/pcm",
                                "rate": OPENAI_PCM_RATE,
                            },
                            "transcription": transcription,
                            "turn_detection": None,
                        },
                    },
                },
            }))

            append_recording_event(
                self.recording_filename,
                "transcriber_started",
                speaker_id=self.speaker_id,
                speaker_name=self.speaker_name,
                model=VOICE_TRANSCRIPTION_MODEL,
            )

            sender = asyncio.create_task(self._send_audio(websocket))
            receiver = asyncio.create_task(self._receive_events(websocket))
            await sender

            try:
                await asyncio.wait_for(receiver, timeout=TRANSCRIBER_FINAL_DRAIN_SECONDS)
            except asyncio.TimeoutError:
                receiver.cancel()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            append_recording_event(
                self.recording_filename,
                "transcriber_error",
                speaker_id=self.speaker_id,
                speaker_name=self.speaker_name,
                error=str(e),
            )
        finally:
            if sender and not sender.done():
                sender.cancel()
            if receiver and not receiver.done():
                receiver.cancel()
            if websocket is not None:
                try:
                    await websocket.close()
                except Exception:
                    pass
            self._flush_partial_transcripts("transcriber_stopped")
            await self._fallback_session_transcribe_if_needed()
            append_recording_event(
                self.recording_filename,
                "transcriber_stopped",
                speaker_id=self.speaker_id,
                speaker_name=self.speaker_name,
                dropped_chunks=self.dropped_chunks,
            )


if voice_recv is not None:
    from discord.ext.voice_recv import opus as voice_recv_opus

    _ORIGINAL_DECODE_PACKET = voice_recv_opus.PacketDecoder._decode_packet

    def _maybe_decrypt_dave_packet(decoder, packet) -> bool | None:
        if not packet or davey is None:
            return None

        sink = getattr(decoder, "sink", None)
        voice_client = getattr(sink, "voice_client", None)
        connection = getattr(voice_client, "_connection", None)
        dave_session = getattr(connection, "dave_session", None)
        if dave_session is None or int(getattr(connection, "dave_protocol_version", 0) or 0) <= 0:
            return None

        user_id = None
        try:
            user_id = voice_client._get_id_from_ssrc(packet.ssrc)
        except Exception:
            user_id = None

        if not user_id:
            if hasattr(sink, "handle_dave_decrypt_waiting"):
                sink.handle_dave_decrypt_waiting(packet)
            return False

        try:
            decrypted_data = dave_session.decrypt(
                int(user_id),
                davey.MediaType.audio,
                bytes(packet.decrypted_data or b""),
            )
            if not decrypted_data:
                raise ValueError("DAVE decrypt returned no audio data")

            packet.decrypted_data = decrypted_data
            if hasattr(sink, "handle_dave_decrypt_success"):
                sink.handle_dave_decrypt_success(packet, user_id)
            return True
        except Exception as e:
            if hasattr(sink, "handle_dave_decrypt_error"):
                sink.handle_dave_decrypt_error(packet, user_id, e)
            return False

    def _safe_decode_packet(self, packet):
        try:
            if not packet:
                return packet, b""
            dave_result = _maybe_decrypt_dave_packet(self, packet)
            if dave_result is False:
                return packet, b""
            return _ORIGINAL_DECODE_PACKET(self, packet)
        except discord_opus.OpusError as e:
            sink = getattr(self, "sink", None)
            if hasattr(sink, "handle_decode_error"):
                sink.handle_decode_error(packet, e)
            try:
                self._decoder = voice_recv_opus.Decoder()
            except Exception:
                pass
            return packet, b""

    if not getattr(voice_recv_opus.PacketDecoder._decode_packet, "_firefly_safe", False):
        _safe_decode_packet._firefly_safe = True
        voice_recv_opus.PacketDecoder._decode_packet = _safe_decode_packet

    class TranscriptSink(voice_recv.AudioSink):
        def __init__(self, recording: "ActiveVoiceRecording") -> None:
            super().__init__()
            self.recording = recording
            self.cleaned_up = False
            self.decode_error_counts: dict[int, int] = {}
            self.dave_decrypt_success_logged = False
            self.dave_decrypt_waiting_logged = False
            self.dave_decrypt_error_counts: dict[int, int] = {}

        def wants_opus(self) -> bool:
            return False

        def handle_decode_error(self, packet, error: Exception) -> None:
            ssrc = int(getattr(packet, "ssrc", 0) or 0)
            count = self.decode_error_counts.get(ssrc, 0) + 1
            self.decode_error_counts[ssrc] = count

            if count in {1, 5, 10} or count % 50 == 0:
                self.recording.add_event_threadsafe(
                    "opus_decode_error",
                    ssrc=ssrc,
                    count=count,
                    error=str(error),
                )

        def handle_dave_decrypt_waiting(self, packet) -> None:
            if self.dave_decrypt_waiting_logged:
                return
            self.dave_decrypt_waiting_logged = True
            self.recording.add_event_threadsafe(
                "dave_decrypt_waiting_for_speaker",
                ssrc=int(getattr(packet, "ssrc", 0) or 0),
            )

        def handle_dave_decrypt_success(self, packet, user_id: int) -> None:
            if self.dave_decrypt_success_logged:
                return
            self.dave_decrypt_success_logged = True
            self.recording.add_event_threadsafe(
                "dave_decrypt_enabled",
                ssrc=int(getattr(packet, "ssrc", 0) or 0),
                speaker_id=int(user_id),
            )

        def handle_dave_decrypt_error(self, packet, user_id: int | None, error: Exception) -> None:
            ssrc = int(getattr(packet, "ssrc", 0) or 0)
            count = self.dave_decrypt_error_counts.get(ssrc, 0) + 1
            self.dave_decrypt_error_counts[ssrc] = count

            if count in {1, 5, 10} or count % 50 == 0:
                self.recording.add_event_threadsafe(
                    "dave_decrypt_error",
                    ssrc=ssrc,
                    speaker_id=int(user_id) if user_id else None,
                    count=count,
                    error=str(error),
                )

        def write(self, user: discord.User | discord.Member | None, data) -> None:
            try:
                if user is None or getattr(user, "bot", False):
                    return

                pcm = getattr(data, "pcm", None)
                if not pcm:
                    return

                self.recording.push_audio(user, bytes(pcm))
            except Exception as e:
                self.recording.add_event_threadsafe(
                    "sink_write_error",
                    speaker_id=getattr(user, "id", None),
                    speaker_name=_display_name(user) if user is not None else None,
                    error=str(e),
                )

        def cleanup(self) -> None:
            if self.cleaned_up:
                return
            self.cleaned_up = True
            self.recording.add_event_threadsafe("sink_cleanup")

else:
    TranscriptSink = None


class ActiveVoiceRecording:
    def __init__(
        self,
        *,
        client: discord.Client,
        voice_client,
        metadata: dict,
    ) -> None:
        self.client = client
        self.voice_client = voice_client
        self.metadata = metadata
        self.filename = str(metadata["filename"])
        self.guild_id = int(metadata["guild_id"])
        self.loop = asyncio.get_running_loop()
        self.transcribers: dict[int, RealtimeTranscriber] = {}
        self.sink = None
        self.audio_chunk_counts: dict[int, int] = {}
        self.stopping = False

    def add_event_threadsafe(self, event: str, **extra) -> None:
        callback = partial(self.add_event, event, **extra)
        if self.loop.is_closed():
            callback()
            return
        try:
            self.loop.call_soon_threadsafe(callback)
        except RuntimeError:
            callback()

    def add_event(self, event: str, **extra) -> None:
        append_recording_event(self.filename, event, **extra)

    def push_audio(self, user: discord.User | discord.Member, pcm: bytes) -> None:
        user_id = int(getattr(user, "id", 0) or 0)
        speaker_name = _display_name(user)
        try:
            self.loop.call_soon_threadsafe(self._push_audio, user_id, speaker_name, pcm)
        except RuntimeError:
            return

    def _push_audio(self, user_id: int, speaker_name: str, pcm: bytes) -> None:
        if self.stopping or user_id <= 0:
            return

        chunk_count = self.audio_chunk_counts.get(user_id, 0) + 1
        self.audio_chunk_counts[user_id] = chunk_count
        if chunk_count == 1 or chunk_count % 500 == 0:
            self.add_event(
                "audio_chunk_received",
                speaker_id=user_id,
                speaker_name=speaker_name,
                chunk_count=chunk_count,
                bytes=len(pcm),
            )

        transcriber = self.transcribers.get(user_id)
        if transcriber is None:
            transcriber = RealtimeTranscriber(
                recording_filename=self.filename,
                speaker_id=user_id,
                speaker_name=speaker_name,
            )
            transcriber.start()
            self.transcribers[user_id] = transcriber

        transcriber.push(pcm)

    def after_listening(self, error: Exception | None) -> None:
        event = "voice_listen_error" if error is not None else "voice_listen_stopped"
        self.add_event_threadsafe(event, error=str(error) if error is not None else None)

    async def stop(self, *, disconnect: bool = True) -> None:
        if self.stopping:
            return

        self.stopping = True
        try:
            if hasattr(self.voice_client, "is_listening") and self.voice_client.is_listening():
                self.voice_client.stop_listening()
        except Exception as e:
            self.add_event("voice_stop_listening_error", error=str(e))

        for transcriber in list(self.transcribers.values()):
            transcriber.stop()

        if self.transcribers:
            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        *(transcriber.wait_closed() for transcriber in self.transcribers.values()),
                        return_exceptions=True,
                    ),
                    timeout=TRANSCRIBER_FINAL_DRAIN_SECONDS + 6,
                )
            except asyncio.TimeoutError:
                self.add_event("transcriber_shutdown_timeout")

        if disconnect:
            try:
                await self.voice_client.disconnect(force=True)
            except Exception as e:
                self.add_event("voice_disconnect_error", error=str(e))

        finish_recording(self.filename)
        self.sink = None


def _find_voice_client(client: discord.Client, guild: discord.Guild):
    for voice_client in client.voice_clients:
        if getattr(getattr(voice_client, "guild", None), "id", None) == guild.id:
            return voice_client
    return None


def _missing_voice_permissions(channel: discord.VoiceChannel | discord.StageChannel) -> list[str]:
    guild = getattr(channel, "guild", None)
    bot_member = getattr(guild, "me", None)
    if bot_member is None:
        return []

    permissions = channel.permissions_for(bot_member)
    required = (
        ("view_channel", "채널 보기"),
        ("connect", "연결"),
    )
    return [label for attr, label in required if hasattr(permissions, attr) and not getattr(permissions, attr)]


def _voice_connection_info(voice_client) -> dict:
    connection = getattr(voice_client, "_connection", None)
    dave_session = getattr(connection, "dave_session", None)
    return {
        "voice_mode": str(getattr(voice_client, "mode", "") or ""),
        "dave_available": bool(davey is not None),
        "dave_protocol_version": int(getattr(connection, "dave_protocol_version", 0) or 0),
        "dave_ready": bool(getattr(dave_session, "ready", False)) if dave_session is not None else False,
        "dave_can_decrypt": dave_session is not None and davey is not None,
    }


async def start_voice_recording(
    client: discord.Client,
    *,
    user: discord.User | discord.Member,
    text_channel: discord.abc.Messageable,
) -> tuple[bool, str, str | None]:
    dependency_error = _voice_dependency_error()
    if dependency_error:
        return False, dependency_error, None

    guild = getattr(text_channel, "guild", None)
    if guild is None:
        return False, "통화 기록은 서버 안의 음성 채널에서만 시작할 수 있어.", None

    if guild.id in _active_recordings:
        active = _active_recordings[guild.id]
        return False, f"이미 기록 중이야. 파일: `{active.filename}`", active.filename

    voice_state = getattr(user, "voice", None)
    voice_channel = getattr(voice_state, "channel", None)
    if voice_channel is None:
        return False, "먼저 기록할 통화방에 들어가 있어야 해.", None

    missing_permissions = _missing_voice_permissions(voice_channel)
    if missing_permissions:
        return False, "통화방에 들어가려면 봇에게 이 권한이 필요해: " + ", ".join(missing_permissions), None

    voice_client = _find_voice_client(client, guild)
    try:
        if voice_client is not None:
            if getattr(getattr(voice_client, "channel", None), "id", None) != voice_channel.id:
                await voice_client.disconnect(force=True)
                voice_client = None
            elif not hasattr(voice_client, "listen"):
                await voice_client.disconnect(force=True)
                voice_client = None

        if voice_client is None:
            voice_client = await voice_channel.connect(
                cls=voice_recv.VoiceRecvClient,
                self_deaf=False,
            )
    except Exception as e:
        return False, f"통화방에 들어가지 못했어: {e}", None

    metadata = create_recording(
        guild_id=guild.id,
        guild_name=str(getattr(guild, "name", "알 수 없는 서버")),
        voice_channel_id=voice_channel.id,
        voice_channel_name=str(getattr(voice_channel, "name", "알 수 없는 통화방")),
        text_channel_id=int(getattr(text_channel, "id", 0) or 0),
        text_channel_name=str(getattr(text_channel, "name", "DM")),
        author_id=int(getattr(user, "id", 0) or 0),
        author_name=_display_name(user),
    )

    recording = ActiveVoiceRecording(
        client=client,
        voice_client=voice_client,
        metadata=metadata,
    )
    sink = TranscriptSink(recording)
    recording.sink = sink

    try:
        voice_client.listen(sink, after=recording.after_listening)
    except Exception as e:
        await voice_client.disconnect(force=True)
        finish_recording(recording.filename)
        return False, f"통화방 음성 수신을 시작하지 못했어: {e}", recording.filename

    _active_recordings[guild.id] = recording
    append_recording_event(
        recording.filename,
        "recording_started",
        voice_channel_id=voice_channel.id,
        voice_channel_name=str(getattr(voice_channel, "name", "알 수 없는 통화방")),
        text_channel_id=int(getattr(text_channel, "id", 0) or 0),
        **_voice_connection_info(voice_client),
    )
    return True, f"기록을 시작했어. 파일: `{recording.filename}`", recording.filename


async def stop_voice_recording(guild_id: int) -> tuple[bool, str, str | None]:
    recording = _active_recordings.pop(guild_id, None)
    if recording is None:
        return False, "지금 이 서버에서 기록 중인 통화가 없어.", None

    await recording.stop(disconnect=True)
    return True, f"기록을 마쳤어. 파일: `{recording.filename}`", recording.filename


async def handle_bot_voice_disconnect(member: discord.Member, after: discord.VoiceState) -> None:
    if after.channel is not None:
        return

    guild_id = getattr(getattr(member, "guild", None), "id", None)
    if guild_id is None:
        return

    recording = _active_recordings.pop(guild_id, None)
    if recording is None:
        return

    await recording.stop(disconnect=False)


def get_active_recording(guild_id: int) -> "ActiveVoiceRecording | None":
    return _active_recordings.get(guild_id)
