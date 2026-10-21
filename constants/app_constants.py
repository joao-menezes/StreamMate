from dataclasses import dataclass


@dataclass(frozen=True)
class AppConstants:
    WINDOW_TITLE: str = "StreamMate"
    VERSION: str = "0.1.0"
    WINDOW_SIZE: str = "1000x700"
    MIN_SIZE: tuple = (880, 580)
    GITHUB_URL: str = "https://github.com/joao-menezes/StreamMate"
    ICON_PATH: str = "images/icons8-github-48.png"
    APP_ICON_PNG: str = "images/streammate.png"
    APP_ICON_ICO: str = "images/streammate.ico"
    ICON_SIZE: tuple = (22, 22)
    SIDEBAR_WIDTH: int = 220
    HISTORY_DISPLAY_LIMIT: int = 3


# Paleta (modo claro, modo escuro)
class Colors:
    ACCENT = ("#6246EA", "#7F6AFF")
    ACCENT_HOVER = ("#4F35D2", "#6A54F0")
    ACCENT_SOFT = ("#ECE8FF", "#2A2547")
    BG = ("#F4F5FA", "#111218")
    SIDEBAR = ("#FFFFFF", "#181922")
    CARD = ("#FFFFFF", "#1E1F2A")
    CARD_ALT = ("#F7F7FC", "#252634")
    BORDER = ("#E4E5EF", "#2C2D3B")
    TEXT = ("#1B1C27", "#ECECF4")
    TEXT_MUTED = ("#6B6E85", "#9A9CB2")
    SUCCESS = ("#1F9D63", "#3DD68C")
    DANGER = ("#D64545", "#FF6B6B")
    NAV_HOVER = ("#F0EEFB", "#232433")
    TRANSPARENT = "transparent"
