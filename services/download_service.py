import os
import re
import tempfile
from typing import Callable, Optional

from pytubefix import YouTube

from constants.media_formats import extension_for, is_video_format
from services.conversion_service import ConversionService

StatusCallback = Callable[[str, Optional[float]], None]


def _safe_name(title: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", title).strip().rstrip(".")
    return name[:150] or "video"


def _unique_path(folder: str, base: str, ext: str) -> str:
    path = os.path.join(folder, f"{base}.{ext}")
    counter = 1
    while os.path.exists(path):
        path = os.path.join(folder, f"{base} ({counter}).{ext}")
        counter += 1
    return path


class DownloadService:
    """Baixa vídeos do YouTube como vídeo (melhor qualidade em MP4) ou em qualquer formato
    suportado pelo conversor."""

    def __init__(self, conversion_service: ConversionService):
        self.converter = conversion_service

    def download(self, url: str, output_dir: str, output_format: str = "mp4",
                 on_status: Optional[StatusCallback] = None) -> tuple[str, str]:
        notify = on_status or (lambda msg, pct: None)
        stage = {"label": "Baixando"}

        def on_progress(stream, _chunk, bytes_remaining):
            total = stream.filesize or 1
            notify(f"{stage['label']}...", (total - bytes_remaining) / total)

        notify("Buscando informações do vídeo...", None)
        yt = YouTube(url, on_progress_callback=on_progress)
        base = _safe_name(yt.title)

        with tempfile.TemporaryDirectory(prefix="streammate_") as tmp:
            if output_format == "mp4":
                final_path = _unique_path(output_dir, base, "mp4")
                self._download_best_mp4(yt, tmp, final_path, stage, notify)
            else:
                source = self._download_source(yt, tmp, output_format, stage)
                final_path = _unique_path(output_dir, base, extension_for(output_format))
                notify(f"Convertendo para {output_format.upper()}...", 0.0)
                self.converter.convert(
                    source, final_path, output_format,
                    on_progress=lambda p: notify(f"Convertendo para {output_format.upper()}...", p),
                )

        return final_path, os.path.basename(final_path)

    def _download_best_mp4(self, yt, tmp, final_path, stage, notify):
        video = (yt.streams.filter(adaptive=True, only_video=True, file_extension="mp4")
                 .order_by("resolution").desc().first())
        audio = (yt.streams.filter(only_audio=True, file_extension="mp4")
                 .order_by("abr").desc().first())
        progressive = yt.streams.get_highest_resolution()

        def height(stream):
            return int((stream.resolution or "0p").rstrip("p") or 0) if stream else 0

        if video and audio and height(video) > height(progressive):
            stage["label"] = f"Baixando vídeo ({video.resolution})"
            video_file = video.download(output_path=tmp, filename="video.mp4")
            stage["label"] = "Baixando áudio"
            audio_file = audio.download(output_path=tmp, filename="audio.m4a")
            notify("Juntando vídeo e áudio...", None)
            self.converter.merge(video_file, audio_file, final_path)
        else:
            stage["label"] = f"Baixando vídeo ({progressive.resolution})"
            progressive.download(output_path=os.path.dirname(final_path),
                                 filename=os.path.basename(final_path))

    def _download_source(self, yt, tmp, output_format, stage) -> str:
        if is_video_format(output_format):
            stream = yt.streams.get_highest_resolution()
            stage["label"] = f"Baixando vídeo ({stream.resolution})"
        else:
            stream = yt.streams.filter(only_audio=True).order_by("abr").desc().first()
            stage["label"] = "Baixando áudio"
        return stream.download(output_path=tmp, filename=f"source.{stream.subtype}")
