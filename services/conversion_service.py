import os
import re
import subprocess
import sys
import threading
from dataclasses import dataclass
from typing import Callable, Optional

from constants.media_formats import ffmpeg_args_for, is_video_format

ProgressCallback = Callable[[float], None]

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_STREAM_RE = re.compile(r"Stream #\d+:\d+.*?:\s*(Video|Audio):(.*)")


def _no_window_flags() -> int:
    # Evita abrir uma janela de console no Windows ao rodar o ffmpeg
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def get_ffmpeg_path() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


@dataclass
class MediaInfo:
    duration: Optional[float]
    has_video: bool
    has_audio: bool


class ConversionCancelled(Exception):
    pass


class ConversionService:
    def __init__(self):
        self.ffmpeg = get_ffmpeg_path()
        self._process: Optional[subprocess.Popen] = None
        self._cancelled = threading.Event()

    def probe(self, input_path: str) -> MediaInfo:
        result = subprocess.run(
            [self.ffmpeg, "-hide_banner", "-i", input_path],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            creationflags=_no_window_flags(),
        )
        output = result.stderr
        if result.returncode < 0:
            # O ffmpeg travou só ao inspecionar; deixa a conversão tentar mesmo assim
            return MediaInfo(None, True, True)

        duration = None
        match = _DURATION_RE.search(output)
        if match:
            h, m, s = match.groups()
            duration = int(h) * 3600 + int(m) * 60 + float(s)

        has_video = has_audio = False
        for kind, details in _STREAM_RE.findall(output):
            if kind == "Audio":
                has_audio = True
            elif "attached pic" not in details:  # capa de álbum não conta como vídeo
                has_video = True

        if not has_video and not has_audio:
            raise ValueError("O arquivo não contém áudio nem vídeo reconhecível.")
        return MediaInfo(duration, has_video, has_audio)

    def convert(self, input_path: str, output_path: str, output_format: str,
                on_progress: Optional[ProgressCallback] = None) -> None:
        if os.path.abspath(input_path) == os.path.abspath(output_path):
            raise ValueError("O arquivo de saída não pode ser o mesmo da entrada.")

        info = self.probe(input_path)
        if is_video_format(output_format) and not info.has_video:
            raise ValueError("Este arquivo só tem áudio — escolha um formato de áudio.")
        if not is_video_format(output_format) and not info.has_audio:
            raise ValueError("Este arquivo não tem faixa de áudio para extrair.")

        cmd = [self.ffmpeg, "-hide_banner", "-y", "-i", input_path,
               *ffmpeg_args_for(output_format),
               "-progress", "pipe:1", "-nostats", output_path]
        self._run(cmd, info.duration, on_progress)

    def cancel(self) -> None:
        self._cancelled.set()
        if self._process and self._process.poll() is None:
            self._process.terminate()

    def _run(self, cmd: list[str], duration: Optional[float],
             on_progress: Optional[ProgressCallback]) -> None:
        self._cancelled.clear()
        self._process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace",
            creationflags=_no_window_flags(),
        )

        stderr_tail: list[str] = []

        def drain_stderr():
            for line in self._process.stderr:
                stderr_tail.append(line.rstrip())
                del stderr_tail[:-15]

        reader = threading.Thread(target=drain_stderr, daemon=True)
        reader.start()

        for line in self._process.stdout:
            key, _, value = line.strip().partition("=")
            if key == "out_time_us" and duration and on_progress and value.isdigit():
                on_progress(min(int(value) / 1_000_000 / duration, 1.0))

        code = self._process.wait()
        reader.join(timeout=2)

        if self._cancelled.is_set():
            raise ConversionCancelled()
        if code != 0:
            detail = "\n".join(l for l in stderr_tail if l)[-600:]
            raise RuntimeError(f"O ffmpeg não conseguiu converter o arquivo.\n\n{detail}")
        if on_progress:
            on_progress(1.0)

    def merge(self, video_path: str, audio_path: str, output_path: str) -> None:
        """Junta faixas de vídeo e áudio separadas sem recodificar."""
        cmd = [self.ffmpeg, "-hide_banner", "-y", "-i", video_path, "-i", audio_path,
               "-map", "0:v:0", "-map", "1:a:0", "-c", "copy", "-movflags", "+faststart",
               "-progress", "pipe:1", "-nostats", output_path]
        self._run(cmd, None, None)
