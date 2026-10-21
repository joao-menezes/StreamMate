"""Catálogo de formatos de mídia suportados pelo StreamMate.

A conversão é feita pelo ffmpeg, então qualquer arquivo que o ffmpeg consiga
ler pode ser usado como entrada. As saídas abaixo têm parâmetros de codificação
escolhidos para máxima compatibilidade com players comuns.
"""

H264_AAC = ["-c:v", "libx264", "-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k"]
EVEN_DIMENSIONS = ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2"]

# formato -> (descrição, argumentos do ffmpeg)
VIDEO_FORMATS: dict[str, tuple[str, list[str]]] = {
    "mp4": ("MP4 · H.264", H264_AAC + EVEN_DIMENSIONS + ["-movflags", "+faststart"]),
    "mkv": ("Matroska · H.264", H264_AAC + EVEN_DIMENSIONS),
    "webm": ("WebM · VP9", ["-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0", "-deadline", "good",
                            "-cpu-used", "4", "-row-mt", "1", "-c:a", "libopus", "-b:a", "128k"]
                           + EVEN_DIMENSIONS),
    "mov": ("QuickTime · H.264", H264_AAC + EVEN_DIMENSIONS + ["-movflags", "+faststart"]),
    "avi": ("AVI · MPEG-4", ["-c:v", "mpeg4", "-q:v", "3", "-c:a", "libmp3lame", "-q:a", "2"]
                         + EVEN_DIMENSIONS),
    "m4v": ("M4V · H.264", H264_AAC + EVEN_DIMENSIONS + ["-movflags", "+faststart"]),
    "flv": ("Flash Video · H.264", H264_AAC + EVEN_DIMENSIONS + ["-ar", "44100"]),
    "wmv": ("Windows Media", ["-c:v", "wmv2", "-q:v", "3", "-c:a", "wmav2", "-b:a", "192k"]
                              + EVEN_DIMENSIONS),
    "mpeg": ("MPEG-2", ["-c:v", "mpeg2video", "-q:v", "3", "-c:a", "mp2", "-b:a", "192k"]
                       + EVEN_DIMENSIONS),
    "ts": ("MPEG-TS · H.264", H264_AAC + EVEN_DIMENSIONS),
    "3gp": ("3GP · celular", ["-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", "yuv420p",
                              "-crf", "26", "-c:a", "aac", "-b:a", "96k", "-ar", "44100"]
                             + EVEN_DIMENSIONS),
    "ogv": ("Ogg Theora", ["-c:v", "libtheora", "-q:v", "7", "-c:a", "libvorbis", "-q:a", "5"]
                           + EVEN_DIMENSIONS),
    "gif": ("GIF animado", ["-vf", "fps=12,scale='min(640,iw)':-1:flags=lanczos,"
                                   "split[a][b];[a]palettegen[p];[b][p]paletteuse",
                            "-an", "-loop", "0"]),
}

AUDIO_FORMATS: dict[str, tuple[str, list[str]]] = {
    "mp3": ("MP3", ["-vn", "-c:a", "libmp3lame", "-q:a", "2"]),
    "wav": ("WAV · sem perdas", ["-vn", "-c:a", "pcm_s16le"]),
    "m4a": ("M4A · AAC", ["-vn", "-c:a", "aac", "-b:a", "192k"]),
    "aac": ("AAC", ["-vn", "-c:a", "aac", "-b:a", "192k"]),
    "flac": ("FLAC · sem perdas", ["-vn", "-c:a", "flac"]),
    "ogg": ("Ogg Vorbis", ["-vn", "-c:a", "libvorbis", "-q:a", "5"]),
    "opus": ("Opus", ["-vn", "-c:a", "libopus", "-b:a", "128k"]),
    "wma": ("Windows Media Audio", ["-vn", "-c:a", "wmav2", "-b:a", "192k"]),
    "aiff": ("AIFF · sem perdas", ["-vn", "-c:a", "pcm_s16be"]),
    "ac3": ("Dolby Digital AC3", ["-vn", "-c:a", "ac3", "-b:a", "192k"]),
    "alac": ("Apple Lossless (.m4a)", ["-vn", "-c:a", "alac"]),
    "mka": ("Matroska Audio", ["-vn", "-c:a", "libopus", "-b:a", "160k"]),
}

# Extensão real do arquivo quando difere do nome do formato
OUTPUT_EXTENSION = {"alac": "m4a"}

INPUT_EXTENSIONS = sorted({
    # vídeo
    "mp4", "m4v", "mkv", "webm", "mov", "avi", "wmv", "flv", "f4v", "mpeg", "mpg", "m2v",
    "ts", "mts", "m2ts", "3gp", "3g2", "ogv", "vob", "asf", "rm", "rmvb", "divx", "dv",
    "mxf", "gif", "y4m",
    # áudio
    "mp3", "wav", "m4a", "aac", "flac", "ogg", "oga", "opus", "wma", "aiff", "aif", "aifc",
    "ac3", "eac3", "dts", "amr", "ape", "mka", "mp2", "au", "caf", "wv", "tta", "spx", "m4b",
    "mid", "ra",
    # playlists (o conteúdo de cada item é convertido)
    "vlc", "m3u", "m3u8", "pls", "xspf",
})


def extension_for(fmt: str) -> str:
    return OUTPUT_EXTENSION.get(fmt, fmt)


def format_label(fmt: str) -> str:
    """Rótulo exibido no seletor, ex.: 'MP4 — MP4 · H.264'."""
    table = VIDEO_FORMATS if fmt in VIDEO_FORMATS else AUDIO_FORMATS
    desc = table[fmt][0]
    if desc.upper().startswith(fmt.upper()):
        desc = desc[len(fmt):].lstrip(" ·")
    return f"{fmt.upper()}  —  {desc}" if desc else fmt.upper()


def ffmpeg_args_for(fmt: str) -> list[str]:
    if fmt in VIDEO_FORMATS:
        return list(VIDEO_FORMATS[fmt][1])
    if fmt in AUDIO_FORMATS:
        return list(AUDIO_FORMATS[fmt][1])
    raise ValueError(f"Formato de saída não suportado: {fmt}")


def is_video_format(fmt: str) -> bool:
    return fmt in VIDEO_FORMATS
