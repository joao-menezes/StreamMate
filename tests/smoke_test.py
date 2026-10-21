"""Converte um vídeo gerado para todos os formatos suportados usando o ffmpeg empacotado."""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from constants.media_formats import AUDIO_FORMATS, VIDEO_FORMATS, extension_for  # noqa: E402
from services.conversion_service import ConversionService  # noqa: E402

service = ConversionService()
failures = []

with tempfile.TemporaryDirectory() as tmp:
    video = os.path.join(tmp, "in.mp4")
    audio = os.path.join(tmp, "in.mp3")
    subprocess.run([service.ffmpeg, "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc=size=321x241:rate=25:duration=2", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=2", "-c:v", "libx264", "-c:a", "aac",
                    "-shortest", video], check=True)
    subprocess.run([service.ffmpeg, "-loglevel", "error", "-f", "lavfi", "-i",
                    "sine=frequency=330:duration=2", audio], check=True)

    jobs = [(video, f) for f in VIDEO_FORMATS] + [(video, f) for f in AUDIO_FORMATS] \
        + [(audio, f) for f in AUDIO_FORMATS]
    for source, fmt in jobs:
        out = os.path.join(tmp, f"{os.path.basename(source)}_{fmt}.{extension_for(fmt)}")
        try:
            service.convert(source, out, fmt)
            assert os.path.getsize(out) > 0
            print(f"ok    {os.path.basename(source)} -> {fmt}")
        except Exception as error:  # noqa: BLE001
            print(f"FALHA {os.path.basename(source)} -> {fmt}: {error}")
            failures.append(fmt)

if failures:
    sys.exit(f"{len(failures)} conversões falharam: {failures}")
print(f"Todas as {len(jobs)} conversões funcionaram.")

# Playlists do VLC (.vlc em formato M3U, PLS e XSPF) apontando para arquivos e links
import pathlib  # noqa: E402

from services.playlist_service import read_playlist  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    open(os.path.join(tmp, "a.mp4"), "wb").close()
    samples = {
        "m3u.vlc": "#EXTM3U\n#EXTINF:3,Aula 1\na.mp4\nhttps://example.com/live.m3u8\n",
        "pls.vlc": "[playlist]\nFile1=a.mp4\nTitle1=Aula 1\nNumberOfEntries=1\n",
        "lista.xspf": '<?xml version="1.0"?><playlist xmlns="http://xspf.org/ns/0/"><trackList>'
                      f'<track><location>{pathlib.Path(tmp, "a.mp4").as_uri()}</location>'
                      '<title>Aula 1</title></track></trackList></playlist>',
    }
    for name, content in samples.items():
        path = os.path.join(tmp, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        entries = read_playlist(path)
        assert entries[0].title == "Aula 1" and entries[0].available, (name, entries)
        print(f"ok    playlist {name}: {len(entries)} item(ns)")
print("Playlists ok.")
