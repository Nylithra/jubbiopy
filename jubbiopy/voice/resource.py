"""Ses kaynakları ve yt-dlp ile bilgi sorgulama."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sys
from dataclasses import dataclass
from typing import Any, Optional, Union
from urllib.parse import urlparse

from .._utils import CamelCaseCompat
from .enums import StreamType

log = logging.getLogger("jubbiopy.voice")

#: yt-dlp ile çalınması gereken platformlar
STREAMING_DOMAINS = ("youtube.com", "youtu.be", "soundcloud.com", "spotify.com", "twitch.tv", "vimeo.com")


YTDLP_HELP = (
    "yt-dlp bulunamadı. Kurmak için: python -m pip install yt-dlp "
    "(veya YTDLP_PATH ortam değişkeniyle yt-dlp.exe yolunu verin)."
)
FFMPEG_HELP = (
    "FFmpeg bulunamadı. FFmpeg'i kurup 'bin' klasörünü PATH'e ekleyin "
    "(Windows: https://www.gyan.dev/ffmpeg/builds/) veya FFMPEG_PATH ortam değişkeniyle "
    "ffmpeg.exe yolunu verin."
)


def _python_scripts_dirs() -> list:
    """pip'in komut dosyalarını kurduğu klasörler (Windows'ta çoğu zaman PATH'te değildir)."""
    import sysconfig

    dirs = []
    for scheme in (None, f"{os.name}_user"):
        try:
            path = sysconfig.get_path("scripts", scheme) if scheme else sysconfig.get_path("scripts")
        except KeyError:
            continue
        if path and path not in dirs:
            dirs.append(path)
    dirs.append(os.path.dirname(sys.executable))
    return dirs


def _find_in_scripts(name: str) -> Optional[str]:
    for directory in _python_scripts_dirs():
        for candidate in (name, name + ".exe"):
            full = os.path.join(directory, candidate)
            if os.path.isfile(full):
                return full
    return None


def yt_dlp_command(path: Optional[str] = None) -> list:
    """yt-dlp'yi çalıştıracak komutu döndürür.

    Öncelik: parametre > ``YTDLP_PATH`` > PATH > Python ``Scripts`` klasörü >
    ``~/.local/bin/yt-dlp`` > ``python -m yt_dlp`` (pip paketi kuruluysa).
    """
    import importlib.util

    candidate = path or os.environ.get("YTDLP_PATH")
    if candidate:
        return [os.path.expanduser(candidate)]
    found = shutil.which("yt-dlp") or _find_in_scripts("yt-dlp")
    if found:
        return [found]
    local = os.path.expanduser("~/.local/bin/yt-dlp")
    if sys.platform != "win32" and os.path.exists(local):
        return [local]
    if importlib.util.find_spec("yt_dlp") is not None:
        return [sys.executable, "-m", "yt_dlp"]
    raise FileNotFoundError(YTDLP_HELP)


def find_yt_dlp(path: Optional[str] = None) -> str:
    """Geriye dönük uyumluluk: yt-dlp komutunun ilk parçasını döndürür."""
    return yt_dlp_command(path)[0]


def find_ffmpeg(path: Optional[str] = None) -> str:
    """FFmpeg çalıştırılabilir dosyasını bulur; bulunamazsa açıklayıcı hata fırlatır."""
    candidate = path or os.environ.get("FFMPEG_PATH")
    if candidate:
        return os.path.expanduser(candidate)
    found = shutil.which("ffmpeg") or _find_in_scripts("ffmpeg")
    if found:
        return found
    raise FileNotFoundError(FFMPEG_HELP)


def is_valid_url(value: str) -> bool:
    parsed = urlparse(value)
    return bool(parsed.scheme and parsed.netloc) or value.startswith(("http://", "https://"))


def is_streaming_url(url: str) -> bool:
    return any(domain in url for domain in STREAMING_DOMAINS)


class AudioResource(CamelCaseCompat):
    """Çalınacak ses kaynağı: dosya yolu, URL veya YouTube arama metni."""

    def __init__(
        self,
        input: Union[str, os.PathLike],  # noqa: A002 - JS API ile aynı isim
        *,
        metadata: Any = None,
        input_type: Union[StreamType, str] = StreamType.Arbitrary,
        inline_volume: bool = True,
        silence_padding_frames: int = 0,
    ) -> None:
        if not isinstance(input, (str, os.PathLike)):
            raise TypeError("Akış (stream) girişi henüz desteklenmiyor. URL veya dosya yolu kullanın.")
        self.input_source = os.fspath(input)
        self.metadata = metadata
        self.stream_type = StreamType(input_type)
        self.inline_volume = inline_volume
        self.silence_padding_frames = silence_padding_frames
        self.started = False
        self.ended = False
        self.playback_duration = 0.0  # saniye
        self.volume = 1.0

    def get_input_source(self) -> str:
        return self.input_source

    def set_volume(self, volume: float) -> None:
        """Ses seviyesini ayarlar (0.0 – 2.0). Çalma sırasında da uygulanır."""
        self.volume = max(0.0, min(2.0, float(volume)))

    def get_volume(self) -> float:
        return self.volume

    def __repr__(self) -> str:
        return f"<AudioResource {self.input_source[:60]!r}>"


def create_audio_resource(input: Union[str, os.PathLike], **options: Any) -> AudioResource:  # noqa: A002
    """Dosya yolu veya URL'den ses kaynağı oluşturur."""
    return AudioResource(input, **options)


def create_audio_resource_from_url(url: str, **options: Any) -> AudioResource:
    """URL'den (YouTube, SoundCloud vb.) ses kaynağı oluşturur.

    Akış adresi burada çözülmez; ``AudioPlayer`` çalma anında yt-dlp kullanır.
    """
    return AudioResource(url, **options)


@dataclass
class AudioInfo:
    title: str
    duration: int
    thumbnail: Optional[str]
    url: str

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


async def probe_audio_info(input: str, yt_dlp_path: Optional[str] = None, *, timeout: float = 30.0) -> AudioInfo:  # noqa: A002
    """Bir URL veya arama metni hakkında bilgi alır (başlık, süre, küçük resim).

    URL değilse YouTube'da aranır (``ytsearch1:``).
    """
    query = input if is_valid_url(input) else f"ytsearch1:{input}"
    command = yt_dlp_command(yt_dlp_path)
    # GÜVENLİK: Kullanıcı girdisi kabuktan (shell) geçirilmez, argüman listesi olarak verilir
    args = ["--no-playlist", "--no-warnings", "-j", query]
    log.debug("[probe_audio_info] %s", " ".join(command + args))
    try:
        process = await asyncio.create_subprocess_exec(
            *command, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
    except OSError as exc:
        raise RuntimeError(f"Ses bilgisi alınamadı, '{command[0]}' çalıştırılamadı: {exc}. {YTDLP_HELP}") from exc
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
    except asyncio.TimeoutError:
        process.kill()
        raise TimeoutError("Ses bilgisi beklenirken zaman aşımı") from None

    err = stderr.decode(errors="replace")
    if process.returncode != 0:
        raise RuntimeError(f"yt-dlp başarısız oldu (kod {process.returncode}): {err or 'Bilinmeyen hata'}")
    out = stdout.decode(errors="replace").strip()
    if not out:
        raise RuntimeError(f"yt-dlp boş yanıt döndürdü. stderr: {err}")
    try:
        info = json.loads(out.splitlines()[0])
    except ValueError:
        raise RuntimeError(f"yt-dlp çıktısı ayrıştırılamadı: {out[:200]}") from None
    return AudioInfo(
        title=info.get("title") or "Unknown",
        duration=int(info.get("duration") or 0),
        thumbnail=info.get("thumbnail"),
        url=info.get("webpage_url") or info.get("url") or input,
    )
