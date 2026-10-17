"""``AudioPlayer``: FFmpeg ile ses çözer ve LiveKit odasına PCM kareleri gönderir."""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
import sys
from array import array
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Set, Union

from .._utils import CamelCaseCompat
from ..events import EventEmitter
from .enums import AudioPlayerStatus, NoSubscriberBehavior
from .resource import FFMPEG_HELP, AudioResource, find_ffmpeg, yt_dlp_command

if TYPE_CHECKING:
    from .connection import VoiceConnection

log = logging.getLogger("jubbio.voice")

# LiveKit ses ayarları (48kHz stereo, 20ms kareler)
SAMPLE_RATE = 48000
CHANNELS = 2
FRAME_DURATION_MS = 20
SAMPLES_PER_FRAME = SAMPLE_RATE * FRAME_DURATION_MS // 1000  # 960
FRAME_SIZE = SAMPLES_PER_FRAME * CHANNELS * 2  # s16le -> 3840 bayt

MIN_BUFFER_FRAMES = 75  # ~1.5 sn — çalmaya başlamadan önce gereken tampon
MAX_BUFFER_FRAMES = 500  # ~10 sn — bellek sınırı
INITIAL_BUFFER_TIMEOUT = 10.0  # sn

_YTDLP_TRIGGERS = ("youtube.com", "youtu.be", "soundcloud.com", "twitch.tv")


def _import_rtc():
    try:
        from livekit import rtc
    except ImportError as exc:  # pragma: no cover - ortam bağımlı
        raise ImportError(
            "Ses desteği için 'livekit' paketi gerekli: pip install \"jubbio.py[voice]\""
        ) from exc
    return rtc


def _import_av():
    try:
        import av
    except ImportError:
        return None
    return av


class _DecoderStopped(Exception):
    """PyAV iş parçacığına çalmanın durdurulduğunu bildirir."""


@dataclass
class AudioPlayerState:
    status: AudioPlayerStatus
    resource: Optional[AudioResource] = None


class AudioPlayerError(Exception):
    """Çalma sırasında oluşan hata. ``resource`` hangi kaynakta olduğunu belirtir."""

    def __init__(self, message: str, resource: Optional[AudioResource] = None) -> None:
        super().__init__(message)
        self.message = message
        self.resource = resource


def _apply_volume(frame: bytes, volume: float) -> bytes:
    samples = array("h")
    samples.frombytes(frame)
    if sys.byteorder == "big":
        samples.byteswap()
    scaled = array("h", (max(-32768, min(32767, int(s * volume))) for s in samples))
    if sys.byteorder == "big":
        scaled.byteswap()
    return scaled.tobytes()


class AudioPlayer(EventEmitter, CamelCaseCompat):
    """Ses çalar. Olaylar: ``stateChange(old, new)``, ``error(AudioPlayerError)``.

    Örnek::

        player = create_audio_player()
        connection.subscribe(player)
        player.play(create_audio_resource_from_url("https://youtube.com/watch?v=..."))
    """

    def __init__(self, *, behaviors: Optional[Mapping[str, Any]] = None, ffmpeg_path: Optional[str] = None,
                 yt_dlp_path: Optional[str] = None, decoder: str = "auto") -> None:
        """``decoder``: ``"auto"`` (FFmpeg programı varsa onu, yoksa PyAV'ı kullanır),
        ``"ffmpeg"`` veya ``"pyav"`` (``pip install av`` — ayrı FFmpeg kurulumu gerekmez)."""
        super().__init__()
        if decoder not in ("auto", "ffmpeg", "pyav"):
            raise ValueError("decoder 'auto', 'ffmpeg' veya 'pyav' olmalı")
        self.decoder = decoder
        merged = {"no_subscriber": NoSubscriberBehavior.Pause, "max_missed_frames": 5}
        for key, value in (behaviors or {}).items():
            merged["no_subscriber" if key in ("noSubscriber", "no_subscriber") else key] = value
        merged["no_subscriber"] = NoSubscriberBehavior(merged["no_subscriber"])
        self.behaviors = merged
        self.ffmpeg_path = ffmpeg_path
        self.yt_dlp_path = yt_dlp_path
        self.state = AudioPlayerState(AudioPlayerStatus.Idle)
        self.subscriptions: Set["VoiceConnection"] = set()
        self.current_resource: Optional[AudioResource] = None
        self.frames_played = 0
        self.buffer_underruns = 0

        self._audio_source: Any = None
        self._audio_track: Any = None
        self._published_room: Any = None
        self._processes: List[asyncio.subprocess.Process] = []
        self._queue: Optional[asyncio.Queue] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._playback_task: Optional[asyncio.Task] = None
        self._start_task: Optional[asyncio.Task] = None
        self._ffmpeg_done = False
        self._decoder_error: Optional[str] = None
        self._resume = asyncio.Event()
        self._generation = 0

    # ============================================================ kontroller
    @property
    def playable(self) -> List["VoiceConnection"]:
        return [c for c in self.subscriptions if c.get_room() is not None]

    def play(self, resource: AudioResource) -> None:
        """Kaynağı çalmaya başlar (önceki çalma durdurulur)."""
        self.stop()
        self.current_resource = resource
        self._set_state(AudioPlayerState(AudioPlayerStatus.Buffering, resource))
        ready = self.playable
        if ready:
            self._schedule_start(ready[0])

    def pause(self) -> bool:
        if self.state.status != AudioPlayerStatus.Playing:
            return False
        self._set_state(AudioPlayerState(AudioPlayerStatus.Paused, self.current_resource))
        return True

    def unpause(self) -> bool:
        if self.state.status not in (AudioPlayerStatus.Paused, AudioPlayerStatus.AutoPaused):
            return False
        self._set_state(AudioPlayerState(AudioPlayerStatus.Playing, self.current_resource))
        return True

    resume = unpause

    def stop(self, force: bool = False) -> bool:
        if self.state.status == AudioPlayerStatus.Idle and not force:
            return False
        self._cleanup()
        resource, self.current_resource = self.current_resource, None
        if resource is not None:
            resource.ended = True
        self._set_state(AudioPlayerState(AudioPlayerStatus.Idle))
        return True

    # ======================================================== abonelikler
    def subscribe(self, connection: "VoiceConnection") -> None:
        self.subscriptions.add(connection)
        if self.state.status == AudioPlayerStatus.AutoPaused and connection.get_room() is not None:
            self.unpause()

    def unsubscribe(self, connection: "VoiceConnection") -> None:
        self.subscriptions.discard(connection)
        if self.subscriptions:
            return
        behavior = self.behaviors["no_subscriber"]
        if behavior == NoSubscriberBehavior.Pause and self.state.status == AudioPlayerStatus.Playing:
            self._set_state(AudioPlayerState(AudioPlayerStatus.AutoPaused, self.current_resource))
        elif behavior == NoSubscriberBehavior.Stop:
            self.stop()

    def on_connection_ready(self, connection: "VoiceConnection") -> None:
        """Bağlantı hazır olduğunda çağrılır; bekleyen kaynak varsa çalmaya başlar."""
        # Yeni odada eski yayın geçersizdir
        if self._published_room is not None and self._published_room is not connection.get_room():
            self._audio_source = self._audio_track = self._published_room = None
        if self.current_resource is not None and self.state.status == AudioPlayerStatus.Buffering:
            self._schedule_start(connection)
        elif self.state.status == AudioPlayerStatus.AutoPaused:
            self.unpause()

    # ============================================================ çalma
    def _schedule_start(self, connection: "VoiceConnection") -> None:
        if self._start_task is not None and not self._start_task.done():
            return
        self._start_task = asyncio.get_running_loop().create_task(self._start_playback(connection, self._generation))

    async def _start_playback(self, connection: "VoiceConnection", generation: int) -> None:
        room = connection.get_room()
        resource = self.current_resource
        if room is None or resource is None:
            return
        try:
            await self._setup_audio_track(room)
            await self._start_ffmpeg(resource, generation)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            if generation != self._generation:
                return
            self._cleanup()
            self.emit("error", AudioPlayerError(str(exc), resource))
            self._set_state(AudioPlayerState(AudioPlayerStatus.Idle))

    async def _setup_audio_track(self, room: Any) -> None:
        if self._published_room is room and self._audio_source is not None:
            return
        rtc = _import_rtc()
        self._audio_source = rtc.AudioSource(SAMPLE_RATE, CHANNELS)
        self._audio_track = rtc.LocalAudioTrack.create_audio_track("music", self._audio_source)
        options = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        await room.local_participant.publish_track(self._audio_track, options)
        self._published_room = room

    @staticmethod
    def _normalize_source(source: str) -> str:
        is_url = source.startswith(("http://", "https://", "ytsearch"))
        if not is_url and not os.path.exists(source):
            # URL veya dosya değilse YouTube'da ara
            log.debug("YouTube aramasına dönüştürüldü: %s", source)
            return f"ytsearch1:{source}"
        return source

    @staticmethod
    def _needs_yt_dlp(source: str) -> bool:
        return any(t in source for t in _YTDLP_TRIGGERS) or source.startswith("ytsearch")

    def _select_backend(self) -> str:
        if self.decoder != "auto":
            if self.decoder == "pyav" and _import_av() is None:
                raise RuntimeError("PyAV kurulu değil: python -m pip install av")
            return self.decoder
        try:
            find_ffmpeg(self.ffmpeg_path)
            return "ffmpeg"
        except FileNotFoundError:
            if _import_av() is not None:
                log.debug("FFmpeg programı bulunamadı, PyAV kullanılıyor")
                return "pyav"
            raise RuntimeError(f"{FFMPEG_HELP} Alternatif olarak FFmpeg kurmadan: python -m pip install av") from None

    async def _spawn_decoder(self, source: str) -> asyncio.subprocess.Process:
        ffmpeg = find_ffmpeg(self.ffmpeg_path)
        output_args = ["-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS), "-acodec", "pcm_s16le", "-"]
        source = self._normalize_source(source)

        if self._needs_yt_dlp(source):
            # GÜVENLİK: kabuk kullanılmaz, argümanlar liste olarak verilir
            ytdlp_args = ["-f", "bestaudio/best", "-o", "-", "--no-playlist", "--no-warnings",
                          "--default-search", "ytsearch", source]
            read_fd, write_fd = os.pipe()
            try:
                ytdlp = await asyncio.create_subprocess_exec(
                    *yt_dlp_command(self.yt_dlp_path), *ytdlp_args,
                    stdin=asyncio.subprocess.DEVNULL, stdout=write_fd, stderr=asyncio.subprocess.DEVNULL,
                )
                self._processes.append(ytdlp)
                decoder = await asyncio.create_subprocess_exec(
                    ffmpeg, "-loglevel", "error", "-i", "pipe:0", *output_args,
                    stdin=read_fd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
            finally:
                os.close(read_fd)
                os.close(write_fd)
        else:
            input_args = ["-i", source]
            if source.startswith(("http://", "https://")):
                input_args = ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5", *input_args]
            decoder = await asyncio.create_subprocess_exec(
                ffmpeg, "-loglevel", "error", *input_args, *output_args,
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
        self._processes.append(decoder)
        return decoder

    async def _start_ffmpeg(self, resource: AudioResource, generation: int) -> None:
        backend = self._select_backend()
        queue: asyncio.Queue = asyncio.Queue(maxsize=MAX_BUFFER_FRAMES)
        self._queue = queue
        self._ffmpeg_done = False
        self._decoder_error = None
        loop = asyncio.get_running_loop()
        decoder: Optional[asyncio.subprocess.Process] = None
        if backend == "ffmpeg":
            decoder = await self._spawn_decoder(resource.get_input_source())
            self._reader_task = loop.create_task(self._read_frames(decoder, queue, generation))
        else:
            self._reader_task = loop.create_task(self._run_pyav(resource.get_input_source(), queue, generation))

        # İlk tamponun dolmasını bekle
        waited = 0.0
        while queue.qsize() < MIN_BUFFER_FRAMES and waited < INITIAL_BUFFER_TIMEOUT:
            if self._ffmpeg_done:
                break
            await asyncio.sleep(0.1)
            waited += 0.1
        if generation != self._generation:
            return
        if queue.empty():
            if decoder is None:
                if self._ffmpeg_done:
                    raise RuntimeError(f"PyAV ses verisi üretemedi{': ' + self._decoder_error if self._decoder_error else ''}")
                raise RuntimeError("Ses verisi beklenirken zaman aşımı")
            stderr = b""
            if decoder.stderr is not None:
                try:
                    stderr = await asyncio.wait_for(decoder.stderr.read(), 1)
                except asyncio.TimeoutError:
                    pass
            detail = stderr.decode(errors="replace").strip()
            if self._ffmpeg_done:
                raise RuntimeError(f"FFmpeg ses verisi üretemedi{': ' + detail if detail else ''}")
            raise RuntimeError("Ses verisi beklenirken zaman aşımı")

        log.debug("Çalma başlıyor, %d kare tamponda", queue.qsize())
        resource.started = True
        self._playback_task = loop.create_task(self._playback_loop(queue, resource, generation))
        self._set_state(AudioPlayerState(AudioPlayerStatus.Playing, resource))

    async def _read_frames(self, decoder: asyncio.subprocess.Process, queue: asyncio.Queue, generation: int) -> None:
        assert decoder.stdout is not None
        try:
            while True:
                try:
                    frame = await decoder.stdout.readexactly(FRAME_SIZE)
                except asyncio.IncompleteReadError as exc:
                    if exc.partial:
                        await queue.put(exc.partial + b"\x00" * (FRAME_SIZE - len(exc.partial)))
                    break
                await queue.put(frame)
        finally:
            if generation == self._generation:
                self._ffmpeg_done = True
            code = await decoder.wait()
            log.debug("FFmpeg kapandı (kod %s), kuyruk: %d", code, queue.qsize())

    async def _resolve_stream(self, source: str) -> tuple:
        """yt-dlp ile doğrudan ses akışı adresini ve gerekli HTTP başlıklarını bulur."""
        args = ["-f", "bestaudio/best", "-j", "--no-playlist", "--no-warnings", "--default-search", "ytsearch", source]
        process = await asyncio.create_subprocess_exec(
            *yt_dlp_command(self.yt_dlp_path), *args,
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        self._processes.append(process)
        stdout, stderr = await asyncio.wait_for(process.communicate(), 30)
        lines = stdout.decode(errors="replace").strip().splitlines()
        if process.returncode != 0 or not lines:
            raise RuntimeError(f"yt-dlp akış adresi alınamadı: {stderr.decode(errors='replace').strip()}")
        info = json.loads(lines[0])
        url = info.get("url")
        if not url and info.get("requested_formats"):
            url = info["requested_formats"][0].get("url")
        if not url:
            raise RuntimeError("yt-dlp akış adresi döndürmedi")
        return url, info.get("http_headers") or {}

    async def _run_pyav(self, source: str, queue: asyncio.Queue, generation: int) -> None:
        loop = asyncio.get_running_loop()
        try:
            source = self._normalize_source(source)
            headers: Mapping[str, str] = {}
            if self._needs_yt_dlp(source):
                source, headers = await self._resolve_stream(source)
            await loop.run_in_executor(None, self._pyav_decode, source, dict(headers), queue, loop, generation)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            if generation == self._generation:
                self._decoder_error = str(exc)
                log.debug("PyAV hatası: %s", exc)
        finally:
            if generation == self._generation:
                self._ffmpeg_done = True

    def _pyav_decode(self, source: str, headers: Dict[str, str], queue: asyncio.Queue,
                     loop: asyncio.AbstractEventLoop, generation: int) -> None:
        """İş parçacığında çalışır: kaynağı çözer, 48kHz stereo s16 karelerini kuyruğa koyar."""
        av = _import_av()
        options: Dict[str, str] = {}
        if source.startswith(("http://", "https://")):
            options = {"reconnect": "1", "reconnect_streamed": "1", "reconnect_delay_max": "5"}
            if headers:
                options["headers"] = "".join(f"{k}: {v}\r\n" for k, v in headers.items())

        def put(chunk: bytes) -> None:
            future = asyncio.run_coroutine_threadsafe(queue.put(chunk), loop)
            while True:
                if generation != self._generation:
                    future.cancel()
                    raise _DecoderStopped
                try:
                    future.result(0.25)
                    return
                except concurrent.futures.TimeoutError:
                    continue

        buffer = bytearray()
        try:
            with av.open(source, options=options) as container:
                stream = container.streams.audio[0]
                resampler = av.AudioResampler(format="s16", layout="stereo", rate=SAMPLE_RATE)

                def feed(frames: Any) -> None:
                    for out in frames:
                        buffer.extend(bytes(out.planes[0])[: out.samples * CHANNELS * 2])
                        while len(buffer) >= FRAME_SIZE:
                            put(bytes(buffer[:FRAME_SIZE]))
                            del buffer[:FRAME_SIZE]

                for packet in container.demux(stream):
                    if generation != self._generation:
                        return
                    for frame in packet.decode():
                        feed(resampler.resample(frame))
                feed(resampler.resample(None))
            if buffer:
                put(bytes(buffer) + b"\x00" * (FRAME_SIZE - len(buffer)))
        except _DecoderStopped:
            return

    async def _playback_loop(self, queue: asyncio.Queue, resource: AudioResource, generation: int) -> None:
        rtc = _import_rtc()
        while generation == self._generation:
            if self.state.status != AudioPlayerStatus.Playing:
                self._resume.clear()
                await self._resume.wait()
                continue
            if queue.empty():
                if self._ffmpeg_done:
                    log.debug("Çalma bitti — kuyruk boş ve FFmpeg tamamlandı")
                    self.stop()
                    return
                self.buffer_underruns += 1
                await asyncio.sleep(0.05)
                continue
            frame = queue.get_nowait()
            volume = resource.volume
            if resource.inline_volume and volume != 1.0:
                frame = _apply_volume(frame, volume)
            audio_frame = rtc.AudioFrame(frame, SAMPLE_RATE, CHANNELS, SAMPLES_PER_FRAME)
            try:
                # capture_frame LiveKit'in iç tamponu dolunca bekler; gerçek zamanlı hız sağlar
                await self._audio_source.capture_frame(audio_frame)
            except Exception as exc:  # noqa: BLE001
                log.warning("Kare gönderilemedi: %s", exc)
            self.frames_played += 1
            resource.playback_duration = self.frames_played * FRAME_DURATION_MS / 1000

    def _cleanup(self) -> None:
        self._generation += 1
        for task in (self._start_task, self._reader_task, self._playback_task):
            if task is not None and not task.done() and task is not asyncio.current_task():
                task.cancel()
        self._start_task = self._reader_task = self._playback_task = None
        for process in self._processes:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
        self._processes = []
        self._queue = None
        self._ffmpeg_done = False
        if self._audio_source is not None:
            try:
                self._audio_source.clear_queue()
            except Exception:  # noqa: BLE001
                pass
        if self.frames_played:
            log.debug("Çalma istatistikleri: %d kare, %d tampon boşalması", self.frames_played, self.buffer_underruns)
        self.frames_played = 0
        self.buffer_underruns = 0
        # Not: Track yayında kalır, sonraki çalmada tekrar kullanılır

    def _set_state(self, new_state: AudioPlayerState) -> None:
        old_state, self.state = self.state, new_state
        if new_state.status == AudioPlayerStatus.Playing:
            self._resume.set()
        self.emit("stateChange", old_state, new_state)


def create_audio_player(*, behaviors: Optional[Mapping[str, Union[str, int]]] = None, **options: Any) -> AudioPlayer:
    """Yeni bir ``AudioPlayer`` oluşturur.

    ``behaviors={"no_subscriber": "pause"}`` — abone kalmadığında ne yapılacağı
    (``"pause"`` | ``"play"`` | ``"stop"``).
    """
    return AudioPlayer(behaviors=behaviors, **options)
