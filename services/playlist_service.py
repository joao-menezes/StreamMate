"""Leitura de playlists (.vlc, .m3u, .m3u8, .pls, .xspf).

Um arquivo .vlc não contém vídeo: é uma playlist do VLC no mesmo formato de M3U ou PLS
(às vezes XSPF), que só aponta para os arquivos ou links de mídia. Aqui ela é aberta e
cada item vira uma entrada que pode ser convertida.
"""
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional
from urllib.parse import unquote, urlparse

PLAYLIST_EXTENSIONS = ("vlc", "m3u", "m3u8", "pls", "xspf")


@dataclass
class PlaylistEntry:
    source: str            # caminho local ou URL
    title: str
    is_url: bool
    duration: Optional[float] = None

    @property
    def available(self) -> bool:
        return self.is_url or os.path.isfile(self.source)


def is_playlist(path: str) -> bool:
    return os.path.splitext(path)[1].lower().lstrip(".") in PLAYLIST_EXTENSIONS


def _read_text(path: str) -> str:
    with open(path, "rb") as f:
        raw = f.read()
    for encoding in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            text = raw.decode(encoding)
            if "\x00" not in text:
                return text
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def _resolve(location: str, base_dir: str) -> tuple[str, bool]:
    location = location.strip()
    parsed = urlparse(location)
    scheme = parsed.scheme.lower()
    if scheme == "file":
        path = unquote(parsed.path)
        if re.match(r"^/[A-Za-z]:", path):  # file:///C:/videos/a.mp4
            path = path[1:]
        if parsed.netloc and parsed.netloc not in ("", "localhost"):  # compartilhamento de rede
            path = f"//{parsed.netloc}{path}"
        return os.path.normpath(path), False
    if scheme in ("http", "https", "rtmp", "rtsp", "mms", "ftp", "udp", "rtp", "srt"):
        return location, True
    path = location if os.path.isabs(location) or re.match(r"^[A-Za-z]:[\\/]", location) \
        else os.path.join(base_dir, location)
    return os.path.normpath(path), False


def _title_from(source: str) -> str:
    name = os.path.basename(urlparse(source).path if "://" in source else source)
    return unquote(name) or source


def _parse_m3u(text: str, base_dir: str) -> list[PlaylistEntry]:
    entries, title, duration = [], None, None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.upper().startswith("#EXTINF:"):
            info = line[8:]
            length, _, name = info.partition(",")
            try:
                duration = float(length.split()[0]) if length.split() else None
                duration = duration if duration and duration > 0 else None
            except ValueError:
                duration = None
            title = name.strip() or None
            continue
        if line.startswith("#"):
            continue
        source, is_url = _resolve(line, base_dir)
        entries.append(PlaylistEntry(source, title or _title_from(source), is_url, duration))
        title = duration = None
    return entries


def _parse_pls(text: str, base_dir: str) -> list[PlaylistEntry]:
    files, titles, lengths = {}, {}, {}
    for line in text.splitlines():
        key, sep, value = line.strip().partition("=")
        if not sep:
            continue
        match = re.match(r"(?i)(file|title|length)(\d+)$", key.strip())
        if not match:
            continue
        kind, index = match.group(1).lower(), int(match.group(2))
        {"file": files, "title": titles, "length": lengths}[kind][index] = value.strip()
    entries = []
    for index in sorted(files):
        source, is_url = _resolve(files[index], base_dir)
        try:
            duration = float(lengths.get(index, "-1"))
        except ValueError:
            duration = -1
        entries.append(PlaylistEntry(source, titles.get(index) or _title_from(source), is_url,
                                     duration if duration > 0 else None))
    return entries


def _parse_xspf(text: str, base_dir: str) -> list[PlaylistEntry]:
    root = ET.fromstring(text)
    entries = []
    for track in root.iter():
        if not track.tag.endswith("track"):
            continue
        fields = {child.tag.split("}")[-1]: (child.text or "").strip() for child in track}
        if not fields.get("location"):
            continue
        source, is_url = _resolve(fields["location"], base_dir)
        duration = None
        if fields.get("duration", "").isdigit():
            duration = int(fields["duration"]) / 1000 or None
        entries.append(PlaylistEntry(source, fields.get("title") or _title_from(source),
                                     is_url, duration))
    return entries


def read_playlist(path: str) -> list[PlaylistEntry]:
    text = _read_text(path)
    base_dir = os.path.dirname(os.path.abspath(path))
    head = text.lstrip()[:200].lower()

    if "#ext-x-" in text.lower():
        # .m3u8 do tipo HLS: o próprio arquivo é o vídeo (segmentado), não uma lista de vídeos
        return [PlaylistEntry(os.path.abspath(path), _title_from(path), False)]

    if head.startswith("<?xml") or "<playlist" in head:
        entries = _parse_xspf(text, base_dir)
    elif head.startswith("[playlist]") or re.search(r"(?im)^file\d+=", text):
        entries = _parse_pls(text, base_dir)
    else:
        entries = _parse_m3u(text, base_dir)

    if not entries:
        raise ValueError("A playlist está vazia ou em um formato que não reconheci.")
    return entries
