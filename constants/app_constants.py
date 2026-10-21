from dataclasses import dataclass


@dataclass(frozen=True)
class AppConstants:
    WINDOW_TITLE: str = "StreamMate"
    VERSION: str = "0.2.0"
    WINDOW_SIZE: str = "1040x700"
    MIN_SIZE: tuple = (900, 600)
    GITHUB_URL: str = "https://github.com/joao-menezes/StreamMate"
    APP_ICON_PNG: str = "images/streammate.png"
    APP_ICON_ICO: str = "images/streammate.ico"
    HISTORY_DISPLAY_LIMIT: int = 5


class Colors:
    """Paleta (modo claro, modo escuro). Grafite e papel, um único acento laranja."""
    BG = ("#F2F1EE", "#141414")
    SURFACE = ("#FFFFFF", "#1B1B1B")
    LINE = ("#D9D7D2", "#2B2B2B")
    TEXT = ("#161616", "#EDEDED")
    MUTED = ("#6F6D68", "#8C8C8C")
    ACCENT = ("#E56A00", "#FF8A1F")
    ACCENT_HOVER = ("#C95C00", "#FF9E47")
    ON_ACCENT = ("#FFFFFF", "#141414")
    HOVER = ("#E8E6E1", "#232323")
    OK = ("#2E7D4F", "#6BC48F")
    ERROR = ("#B3261E", "#F2766B")
    TRANSPARENT = "transparent"


class Fonts:
    SANS = "IBM Plex Sans"
    SANS_STRONG = "IBM Plex Sans SmBld"
    MONO = "IBM Plex Mono"
    MONO_STRONG = "IBM Plex Mono Medm"
    FILES = ("fonts/IBMPlexSans-Regular.ttf", "fonts/IBMPlexSans-SemiBold.ttf",
             "fonts/IBMPlexMono-Regular.ttf", "fonts/IBMPlexMono-Medium.ttf")
