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
