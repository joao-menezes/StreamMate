import os
import platform
import subprocess
import sys
import threading
import tkinter.font as tkfont
import webbrowser
from tkinter import filedialog, messagebox
from typing import Any, Callable, Dict, List, Optional

import customtkinter as ctk
from PIL import Image

from constants.app_constants import AppConstants, Colors, Fonts
from constants.media_formats import (AUDIO_FORMATS, INPUT_EXTENSIONS, VIDEO_FORMATS,
                                     extension_for)
from services.connection_service import ConnectionService
from services.conversion_service import ConversionCancelled, ConversionService, MediaInfo
from services.download_service import DownloadService
from services.history_service import HistoryService
from services.playlist_service import PLAYLIST_EXTENSIONS, is_playlist, read_playlist

ctk.set_appearance_mode("Dark")

QUICK_DOWNLOAD_FORMATS = ["mp4", "mp3", "m4a", "wav", "flac", "opus", "webm", "mkv"]
ALL_FORMATS = list(VIDEO_FORMATS) + list(AUDIO_FORMATS)


def resource_path(relative: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


def format_duration(seconds: Optional[float]) -> str:
    if not seconds:
        return "—"
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def format_size(num_bytes: Optional[int]) -> str:
    if num_bytes is None:
        return "—"
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return "—"


def default_download_dir() -> str:
    downloads = os.path.join(os.path.expanduser("~"), "Downloads")
    return downloads if os.path.isdir(downloads) else os.path.expanduser("~")


def short_path(path: str, limit: int = 48) -> str:
    home = os.path.expanduser("~")
    if path.startswith(home):
        path = "~" + path[len(home):]
    return path if len(path) <= limit else "…" + path[-(limit - 1):]


def unique_path(folder: str, base: str, ext: str) -> str:
    path = os.path.join(folder, f"{base}.{ext}")
    n = 1
    while os.path.exists(path):
        path = os.path.join(folder, f"{base} ({n}).{ext}")
        n += 1
    return path


class QueueItem:
    def __init__(self, source: str, title: str, is_url: bool,
                 duration: Optional[float] = None, available: bool = True):
        self.source = source
        self.title = title
        self.is_url = is_url
        self.duration = duration
        self.available = available
        self.info: Optional[MediaInfo] = None
        self.format = "mp4"
        self.state = "pending" if available else "missing"   # pending/running/done/error/missing
        self.message = ""
        self.output: Optional[str] = None
        self.widgets: Dict[str, Any] = {}

    @property
    def size(self) -> Optional[int]:
        if self.is_url or not self.available:
            return None
        try:
            return os.path.getsize(self.source)
        except OSError:
            return None


class ConverterApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.constants = AppConstants()
        self._load_fonts()

        self.download_dir = default_download_dir()
        self.convert_dir: Optional[str] = None      # None = mesma pasta do original
        self.download_format = "mp4"
        self.busy = False
        self.queue: List[QueueItem] = []
        self.queue_cancelled = threading.Event()
        self.pages: Dict[str, ctk.CTkFrame] = {}
        self.tabs: Dict[str, Dict[str, Any]] = {}

        self.connection_service = ConnectionService()
        self.conversion_service = ConversionService()
        self.download_service = DownloadService(ConversionService())
        self.history_service = HistoryService()

        self._setup_window()
        self._build_top_bar()
        self._build_pages()
        self._start_connection_monitor()
        self.show_page("download")

    # ------------------------------------------------------------- fontes
    def _load_fonts(self) -> None:
        for path in Fonts.FILES:
            try:
                ctk.FontManager.load_font(resource_path(path))
            except Exception:
                pass
        available = set(tkfont.families(self))
        fallback_sans = "Segoe UI" if platform.system() == "Windows" else "DejaVu Sans"
        fallback_mono = "Consolas" if platform.system() == "Windows" else "DejaVu Sans Mono"
        self.font_family = {
            "sans": Fonts.SANS if Fonts.SANS in available else fallback_sans,
            # no Windows o SemiBold vira uma família própria; no Linux/macOS é o peso "bold"
            "sans_strong": Fonts.SANS_STRONG if Fonts.SANS_STRONG in available
            else Fonts.SANS if Fonts.SANS in available else fallback_sans,
            "mono": Fonts.MONO if Fonts.MONO in available else fallback_mono,
            "mono_strong": Fonts.MONO_STRONG if Fonts.MONO_STRONG in available
            else Fonts.MONO if Fonts.MONO in available else fallback_mono,
        }
        self._font_cache: Dict[tuple, ctk.CTkFont] = {}

    def f(self, size: int = 13, kind: str = "sans") -> ctk.CTkFont:
        key = (size, kind)
        if key not in self._font_cache:
            family = self.font_family[kind]
            weight = "bold" if kind.endswith("strong") and family not in (
                Fonts.SANS_STRONG, Fonts.MONO_STRONG) else "normal"
            self._font_cache[key] = ctk.CTkFont(family=family, size=size, weight=weight)
        return self._font_cache[key]

    # ------------------------------------------------------------- janela
    def _setup_window(self) -> None:
        self.title(self.constants.WINDOW_TITLE)
        self.geometry(self.constants.WINDOW_SIZE)
        self.minsize(*self.constants.MIN_SIZE)
        self.configure(fg_color=Colors.BG)
        try:
            if platform.system() == "Windows":
                self.iconbitmap(resource_path(self.constants.APP_ICON_ICO))
            else:
                from PIL import ImageTk
                self._icon = ImageTk.PhotoImage(
                    Image.open(resource_path(self.constants.APP_ICON_PNG)))
                self.iconphoto(True, self._icon)
        except Exception:
            pass
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

    def _ui(self, fn: Callable, *args) -> None:
        self.after(0, lambda: fn(*args))

    # ------------------------------------------------------- componentes
    def _label(self, parent, text="", size=13, kind="sans", color=Colors.TEXT, **kw):
        return ctk.CTkLabel(parent, text=text, font=self.f(size, kind), text_color=color,
                            anchor="w", justify="left", **kw)

    def _line(self, parent) -> ctk.CTkFrame:
        return ctk.CTkFrame(parent, height=1, corner_radius=0, fg_color=Colors.LINE)

    def _button(self, parent, text, command, primary=False, **kw) -> ctk.CTkButton:
        kw.setdefault("height", 36)
        if primary:
            style = dict(fg_color=Colors.ACCENT, hover_color=Colors.ACCENT_HOVER,
                         text_color=Colors.ON_ACCENT, font=self.f(14, "sans_strong"),
                         border_width=0)
        else:
            style = dict(fg_color=Colors.TRANSPARENT, hover_color=Colors.HOVER,
                         text_color=Colors.TEXT, font=self.f(13), border_width=1,
                         border_color=Colors.LINE)
        style.update(kw)
        return ctk.CTkButton(parent, text=text, command=command, corner_radius=4, **style)

    def _link(self, parent, text, command, color=Colors.ACCENT, **kw) -> ctk.CTkButton:
        width = kw.pop("width", max(24, len(text) * 8))
        return ctk.CTkButton(parent, text=text, command=command, width=width, height=24,
                             corner_radius=4, fg_color=Colors.TRANSPARENT,
                             hover_color=Colors.HOVER, text_color=color,
                             text_color_disabled=Colors.LINE, font=self.f(12, "mono"),
                             border_spacing=2, **kw)

    def _menu(self, parent, values, command=None, width=110, height=32) -> ctk.CTkOptionMenu:
        return ctk.CTkOptionMenu(
            parent, values=values, command=command, width=width, height=height,
            corner_radius=4, font=self.f(12, "mono"), dropdown_font=self.f(12, "mono"),
            fg_color=Colors.SURFACE, button_color=Colors.SURFACE,
            button_hover_color=Colors.HOVER, text_color=Colors.TEXT,
            dropdown_fg_color=Colors.SURFACE, dropdown_text_color=Colors.TEXT,
            dropdown_hover_color=Colors.HOVER, dynamic_resizing=False)

    def _progress(self, parent) -> Dict[str, Any]:
        box = ctk.CTkFrame(parent, fg_color=Colors.TRANSPARENT)
        box.grid_columnconfigure(0, weight=1)
        status = self._label(box, "", 12, "mono", Colors.MUTED)
        status.grid(row=0, column=0, sticky="w")
        percent = self._label(box, "", 12, "mono_strong", Colors.TEXT)
        percent.grid(row=0, column=1, sticky="e")
        bar = ctk.CTkProgressBar(box, height=3, corner_radius=0, progress_color=Colors.ACCENT,
                                 fg_color=Colors.LINE)
        bar.set(0)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        bar.grid_remove()
        return {"box": box, "status": status, "percent": percent, "bar": bar, "spin": False}

    def _set_progress(self, p, message: str, value: Optional[float]) -> None:
        p["status"].configure(text=message, text_color=Colors.MUTED)
        bar = p["bar"]
        if value is None:
            p["percent"].configure(text="")
            if not p["spin"]:
                bar.configure(mode="indeterminate")
                bar.start()
                p["spin"] = True
        else:
            if p["spin"]:
                bar.stop()
                bar.configure(mode="determinate")
                p["spin"] = False
            bar.set(value)
            p["percent"].configure(text=f"{value * 100:3.0f}%")
        bar.grid()

    def _end_progress(self, p, message: str, ok: bool) -> None:
        if p["spin"]:
            p["bar"].stop()
            p["bar"].configure(mode="determinate")
            p["spin"] = False
        p["bar"].grid_remove()
        p["percent"].configure(text="")
        p["status"].configure(text=message, text_color=Colors.OK if ok else Colors.ERROR)

    # ------------------------------------------------------------ topo
    def _build_top_bar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color=Colors.BG, corner_radius=0, height=58)
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_columnconfigure(2, weight=1)

        brand = ctk.CTkFrame(bar, fg_color=Colors.TRANSPARENT)
        brand.grid(row=0, column=0, padx=(28, 36), pady=(16, 0), sticky="w")
        self._label(brand, "streammate", 16, "mono_strong").pack(side="left")
        self._label(brand, f" {self.constants.VERSION}", 11, "mono", Colors.MUTED).pack(
            side="left", pady=(3, 0))

        tabs = ctk.CTkFrame(bar, fg_color=Colors.TRANSPARENT)
        tabs.grid(row=0, column=1, pady=(12, 0), sticky="sw")
        for i, (key, text) in enumerate([("download", "Baixar"), ("convert", "Converter"),
                                         ("history", "Histórico")]):
            btn = ctk.CTkButton(tabs, text=text, command=lambda k=key: self.show_page(k),
                                width=10, height=34, corner_radius=4, font=self.f(14),
                                fg_color=Colors.TRANSPARENT, hover_color=Colors.HOVER,
                                text_color=Colors.MUTED)
            btn.grid(row=0, column=i, padx=(0, 6))
            mark = ctk.CTkFrame(tabs, width=1, height=2, corner_radius=0,
                                fg_color=Colors.TRANSPARENT)
            mark.grid(row=1, column=i, sticky="ew", padx=(8, 14), pady=(4, 0))
            self.tabs[key] = {"button": btn, "mark": mark}

        side = ctk.CTkFrame(bar, fg_color=Colors.TRANSPARENT)
        side.grid(row=0, column=3, padx=(0, 22), pady=(16, 0), sticky="e")
        self.connection_label = self._label(side, "verificando…", 12, "mono", Colors.MUTED)
        self.connection_label.pack(side="left", padx=(0, 14))
        self.theme_button = self._link(side, "tema claro", self._toggle_theme,
                                       color=Colors.MUTED, width=90)
        self.theme_button.pack(side="left")
        self._link(side, "github", lambda: webbrowser.open(self.constants.GITHUB_URL),
                   color=Colors.MUTED, width=60).pack(side="left", padx=(4, 0))

        self._line(self).grid(row=1, column=0, sticky="ew")

    def _toggle_theme(self) -> None:
        dark = ctk.get_appearance_mode() == "Dark"
        ctk.set_appearance_mode("Light" if dark else "Dark")
        self.theme_button.configure(text="tema escuro" if dark else "tema claro")

    def show_page(self, key: str) -> None:
        for name, tab in self.tabs.items():
            active = name == key
            tab["button"].configure(text_color=Colors.TEXT if active else Colors.MUTED,
                                    font=self.f(14, "sans_strong" if active else "sans"))
            tab["mark"].configure(fg_color=Colors.ACCENT if active else Colors.TRANSPARENT)
        if key == "history":
            self._render_history()
        elif key == "download":
            self._render_recent()
        self.pages[key].tkraise()

    def _build_pages(self) -> None:
        holder = ctk.CTkFrame(self, fg_color=Colors.BG, corner_radius=0)
        holder.grid(row=2, column=0, sticky="nsew")
        holder.grid_columnconfigure(0, weight=1)
        holder.grid_rowconfigure(0, weight=1)
        self.page_holder = holder
        self.pages["download"] = self._build_download_page()
        self.pages["convert"] = self._build_convert_page()
        self.pages["history"] = self._build_history_page()
        for page in self.pages.values():
            page.grid(row=0, column=0, sticky="nsew")

    def _page(self, title: str, subtitle: str) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self.page_holder, fg_color=Colors.BG, corner_radius=0)
        page.grid_columnconfigure(0, weight=1)
        self._label(page, title, 24, "sans_strong").grid(row=0, column=0, sticky="w",
                                                         padx=36, pady=(30, 0))
        self._label(page, subtitle, 13, color=Colors.MUTED).grid(row=1, column=0, sticky="w",
                                                                 padx=36, pady=(2, 22))
        return page

    # ------------------------------------------------------------ conexão
    def _start_connection_monitor(self) -> None:
        def loop():
            while True:
                self._ui(self._set_connection, self.connection_service.is_connected())
                threading.Event().wait(5)
        threading.Thread(target=loop, daemon=True).start()

    def _set_connection(self, online: bool) -> None:
        self.connection_label.configure(text="● online" if online else "● sem internet",
                                        text_color=Colors.OK if online else Colors.ERROR)

    # ------------------------------------------------------------ baixar
    def _build_download_page(self) -> ctk.CTkFrame:
        page = self._page("Baixar do YouTube",
                          "Cole o link de um vídeo. O arquivo vai direto pra pasta escolhida.")
        page.grid_rowconfigure(6, weight=1)

        row = ctk.CTkFrame(page, fg_color=Colors.TRANSPARENT)
        row.grid(row=2, column=0, sticky="ew", padx=36)
        row.grid_columnconfigure(0, weight=1)
        self.url_entry = ctk.CTkEntry(
            row, height=50, corner_radius=4, border_width=1, font=self.f(15, "mono"),
            placeholder_text="https://www.youtube.com/watch?v=…",
            placeholder_text_color=Colors.MUTED, fg_color=Colors.SURFACE,
            border_color=Colors.LINE, text_color=Colors.TEXT)
        self.url_entry.grid(row=0, column=0, sticky="ew")
        self.url_entry.bind("<Return>", lambda e: self._start_download())
        self.download_button = self._button(row, "Baixar", self._start_download, primary=True,
                                            height=50, width=130)
        self.download_button.grid(row=0, column=1, padx=(8, 0))

        options = ctk.CTkFrame(page, fg_color=Colors.TRANSPARENT)
        options.grid(row=3, column=0, sticky="ew", padx=36, pady=(18, 0))
        self._label(options, "formato", 12, "mono", Colors.MUTED, width=70).grid(
            row=0, column=0, sticky="w")
        chips = ctk.CTkFrame(options, fg_color=Colors.TRANSPARENT)
        chips.grid(row=0, column=1, sticky="w")
        self.format_chips: Dict[str, ctk.CTkButton] = {}
        for i, fmt in enumerate(QUICK_DOWNLOAD_FORMATS):
            chip = ctk.CTkButton(chips, text=fmt, width=54, height=30, corner_radius=4,
                                 border_width=1, font=self.f(12, "mono"),
                                 command=lambda x=fmt: self._pick_download_format(x))
            chip.grid(row=0, column=i, padx=(0, 6))
            self.format_chips[fmt] = chip
        others = [f for f in ALL_FORMATS if f not in QUICK_DOWNLOAD_FORMATS]
        self.other_formats_menu = self._menu(chips, ["outros…"] + others,
                                             command=self._pick_download_format, width=104,
                                             height=30)
        self.other_formats_menu.grid(row=0, column=len(QUICK_DOWNLOAD_FORMATS))

        self._label(options, "destino", 12, "mono", Colors.MUTED, width=70).grid(
            row=1, column=0, sticky="w", pady=(14, 0))
        dest = ctk.CTkFrame(options, fg_color=Colors.TRANSPARENT)
        dest.grid(row=1, column=1, sticky="w", pady=(14, 0))
        self.folder_label = self._label(dest, short_path(self.download_dir), 13, "mono")
        self.folder_label.pack(side="left")
        self._link(dest, "alterar", self._choose_download_dir).pack(side="left", padx=(10, 0))
        self._pick_download_format("mp4")

        self.download_progress = self._progress(page)
        self.download_progress["box"].grid(row=4, column=0, sticky="ew", padx=36, pady=(22, 0))

        head = ctk.CTkFrame(page, fg_color=Colors.TRANSPARENT)
        head.grid(row=5, column=0, sticky="ew", padx=36, pady=(30, 0))
        head.grid_columnconfigure(0, weight=1)
        self._label(head, "Recentes", 15, "sans_strong").grid(row=0, column=0, sticky="w")
        self._link(head, "ver histórico →", lambda: self.show_page("history"),
                   width=120).grid(row=0, column=1, sticky="e")
        self._line(head).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        self.recent_list = self._scroll(page)
        self.recent_list.grid(row=6, column=0, sticky="nsew", padx=(36, 26), pady=(0, 18))
        return page

    def _scroll(self, parent) -> ctk.CTkScrollableFrame:
        frame = ctk.CTkScrollableFrame(parent, fg_color=Colors.TRANSPARENT, corner_radius=0,
                                       scrollbar_button_color=Colors.LINE,
                                       scrollbar_button_hover_color=Colors.MUTED)
        frame.grid_columnconfigure(0, weight=1)
        return frame

    def _pick_download_format(self, fmt: str) -> None:
        if fmt == "outros…":
            return
        self.download_format = fmt
        for name, chip in self.format_chips.items():
            on = name == fmt
            chip.configure(fg_color=Colors.TEXT if on else Colors.TRANSPARENT,
                           text_color=Colors.BG if on else Colors.TEXT,
                           hover_color=Colors.TEXT if on else Colors.HOVER,
                           border_color=Colors.TEXT if on else Colors.LINE)
        in_menu = fmt not in self.format_chips
        self.other_formats_menu.set(fmt if in_menu else "outros…")
        self.other_formats_menu.configure(
            fg_color=Colors.TEXT if in_menu else Colors.SURFACE,
            button_color=Colors.TEXT if in_menu else Colors.SURFACE,
            text_color=Colors.BG if in_menu else Colors.TEXT)

    def _choose_download_dir(self) -> None:
        folder = filedialog.askdirectory(title="Pasta de destino", initialdir=self.download_dir)
        if folder:
            self.download_dir = folder
            self.folder_label.configure(text=short_path(folder))

    def _start_download(self) -> None:
        if self.busy:
            return
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning("Sem link", "Cole o link de um vídeo do YouTube.")
            return
        self._set_busy(True)
        self._set_progress(self.download_progress, "iniciando…", None)
        threading.Thread(target=self._download_worker, args=(url, self.download_format),
                         daemon=True).start()

    def _download_worker(self, url: str, fmt: str) -> None:
        def status(message, value):
            self._ui(self._set_progress, self.download_progress, message.lower(), value)
        try:
            path, name = self.download_service.download(url, self.download_dir, fmt, status)
        except Exception as error:
            self._ui(self._download_failed, error)
        else:
            self._ui(self._download_done, name, path)

    def _download_done(self, name: str, path: str) -> None:
        self._set_busy(False)
        self.history_service.add_record("download", name, path)
        self._end_progress(self.download_progress, f"salvo: {name}", ok=True)
        self.url_entry.delete(0, "end")
        self._render_recent()

    def _download_failed(self, error: Exception) -> None:
        self._set_busy(False)
        self._end_progress(self.download_progress, "não foi possível baixar", ok=False)
        messagebox.showerror("Erro no download", str(error))

    def _render_recent(self) -> None:
        self._fill_list(self.recent_list,
                        self.history_service.get_history("download",
                                                         self.constants.HISTORY_DISPLAY_LIMIT),
                        "Nada baixado ainda.")

    # ---------------------------------------------------------- converter
    def _build_convert_page(self) -> ctk.CTkFrame:
        page = self._page("Converter",
                          "Vídeo, áudio ou playlist do VLC (.vlc, .m3u, .pls, .xspf). "
                          "Tudo entra numa fila.")
        page.grid_rowconfigure(4, weight=1)

        tools = ctk.CTkFrame(page, fg_color=Colors.TRANSPARENT)
        tools.grid(row=2, column=0, sticky="ew", padx=36)
        tools.grid_columnconfigure(2, weight=1)
        self._button(tools, "Adicionar arquivos", self._add_files, width=160).grid(
            row=0, column=0)
        self._button(tools, "Abrir playlist .vlc", self._add_playlist, width=160).grid(
            row=0, column=1, padx=(8, 0))
        self._link(tools, "limpar fila", self._clear_queue, color=Colors.MUTED,
                   width=90).grid(row=0, column=3, sticky="e")

        header = ctk.CTkFrame(page, fg_color=Colors.TRANSPARENT)
        header.grid(row=3, column=0, sticky="ew", padx=36, pady=(22, 0))
        self._queue_columns(header)
        for col, text in enumerate(["arquivo", "duração", "tamanho", "saída", "status", ""]):
            self._label(header, text, 11, "mono", Colors.MUTED).grid(row=0, column=col,
                                                                     sticky="w")
        self._line(header).grid(row=1, column=0, columnspan=6, sticky="ew", pady=(6, 0))

        self.queue_list = self._scroll(page)
        self.queue_list.grid(row=4, column=0, sticky="nsew", padx=(36, 26))

        self._line(page).grid(row=5, column=0, sticky="ew")
        bottom = ctk.CTkFrame(page, fg_color=Colors.TRANSPARENT)
        bottom.grid(row=6, column=0, sticky="ew", padx=36, pady=16)
        bottom.grid_columnconfigure(4, weight=1)
        self._label(bottom, "todos para", 12, "mono", Colors.MUTED).grid(row=0, column=0)
        self.all_format_menu = self._menu(bottom, ALL_FORMATS, command=self._set_all_formats,
                                          width=96)
        self.all_format_menu.set("mp4")
        self.all_format_menu.grid(row=0, column=1, padx=(10, 24))
        self._label(bottom, "salvar em", 12, "mono", Colors.MUTED).grid(row=0, column=2)
        dest = ctk.CTkFrame(bottom, fg_color=Colors.TRANSPARENT)
        dest.grid(row=0, column=3, padx=(10, 0), sticky="w")
        self.convert_dest_label = self._label(dest, "mesma pasta do original", 12, "mono")
        self.convert_dest_label.pack(side="left")
        self._link(dest, "alterar", self._choose_convert_dir).pack(side="left", padx=(8, 0))

        self.queue_status = self._label(bottom, "", 12, "mono", Colors.MUTED)
        self.queue_status.grid(row=0, column=4, sticky="e", padx=(0, 14))
        self.cancel_button = self._button(bottom, "Cancelar", self._cancel_queue, width=100,
                                          height=40)
        self.convert_button = self._button(bottom, "Converter fila", self._start_queue,
                                           primary=True, width=150, height=40)
        self.convert_button.grid(row=0, column=6)

        self._render_queue()
        return page

    @staticmethod
    def _queue_columns(frame) -> None:
        frame.grid_columnconfigure(0, weight=1)
        for col, width in enumerate([0, 74, 86, 112, 130, 34]):
            if col:
                frame.grid_columnconfigure(col, minsize=width)

    def _add_files(self) -> None:
        patterns = " ".join(f"*.{e}" for e in INPUT_EXTENSIONS)
        files = filedialog.askopenfilenames(
            title="Adicionar arquivos de áudio ou vídeo",
            filetypes=[("Mídia e playlists", patterns), ("Todos os arquivos", "*.*")])
        self._add_sources(list(files))

    def _add_playlist(self) -> None:
        patterns = " ".join(f"*.{e}" for e in PLAYLIST_EXTENSIONS)
        file = filedialog.askopenfilename(
            title="Abrir playlist do VLC",
            filetypes=[("Playlists", patterns), ("Todos os arquivos", "*.*")])
        if file:
            self._add_sources([file])

    def _add_sources(self, paths: List[str]) -> None:
        added: List[QueueItem] = []
        for path in paths:
            if is_playlist(path):
                try:
                    entries = read_playlist(path)
                except Exception as error:
                    messagebox.showerror("Playlist inválida",
                                         f"Não consegui ler {os.path.basename(path)}.\n\n{error}")
                    continue
                for e in entries:
                    added.append(QueueItem(e.source, e.title, e.is_url, e.duration, e.available))
            else:
                added.append(QueueItem(path, os.path.basename(path), False))
        target = self.all_format_menu.get()
        for item in added:
            item.format = target
            if not item.available:
                item.message = "não encontrado"
        self.queue.extend(added)
        self._render_queue()
        for item in added:
            if item.available and not item.is_url:
                threading.Thread(target=self._probe_item, args=(item,), daemon=True).start()

    def _probe_item(self, item: QueueItem) -> None:
        try:
            info = ConversionService().probe(item.source)
        except Exception as error:
            item.state, item.message = "error", "não é mídia"
            item.available = False
            self._ui(self._refresh_row, item, str(error))
            return
        item.info = info
        item.duration = info.duration or item.duration
        if not info.has_video and item.format in VIDEO_FORMATS:
            item.format = "mp3"
        self._ui(self._refresh_row, item)

    def _render_queue(self) -> None:
        for w in self.queue_list.winfo_children():
            w.destroy()
        if not self.queue:
            box = ctk.CTkFrame(self.queue_list, fg_color=Colors.TRANSPARENT)
            box.grid(row=0, column=0, sticky="ew", pady=28)
            self._label(box, "A fila está vazia.", 14, "sans_strong").pack(anchor="w")
            self._label(box, "Adicione vídeos, áudios ou uma playlist .vlc — cada item é "
                             "convertido pro formato escolhido na coluna “saída”.",
                        13, color=Colors.MUTED).pack(anchor="w", pady=(2, 0))
            self._update_queue_summary()
            return
        for i, item in enumerate(self.queue):
            self._queue_row(item, i)
        self._update_queue_summary()

    def _queue_row(self, item: QueueItem, index: int) -> None:
        row = ctk.CTkFrame(self.queue_list, fg_color=Colors.TRANSPARENT, corner_radius=0)
        row.grid(row=index, column=0, sticky="ew")
        self._queue_columns(row)

        name = item.title if len(item.title) <= 58 else item.title[:55] + "…"
        name_box = ctk.CTkFrame(row, fg_color=Colors.TRANSPARENT)
        name_box.grid(row=0, column=0, sticky="w", pady=9)
        self._label(name_box, name, 13).pack(anchor="w")
        origin = item.source if item.is_url else short_path(os.path.dirname(item.source), 60)
        self._label(name_box, origin, 11, "mono", Colors.MUTED).pack(anchor="w")

        duration = self._label(row, format_duration(item.duration), 12, "mono")
        duration.grid(row=0, column=1, sticky="w")
        self._label(row, format_size(item.size), 12, "mono").grid(row=0, column=2, sticky="w")

        formats = list(AUDIO_FORMATS) if item.info and not item.info.has_video else ALL_FORMATS
        menu = self._menu(row, formats, width=96, height=30,
                          command=lambda v, it=item: setattr(it, "format", v))
        menu.set(item.format)
        menu.grid(row=0, column=3, sticky="w")
        if not item.available or self.busy:
            menu.configure(state="disabled")

        status = self._label(row, "", 12, "mono")
        status.grid(row=0, column=4, sticky="w")
        remove = self._link(row, "×", lambda it=item: self._remove_item(it), color=Colors.MUTED,
                            width=26)
        remove.grid(row=0, column=5, sticky="e")
        self._line(row).grid(row=1, column=0, columnspan=6, sticky="ew")
        item.widgets = {"duration": duration, "menu": menu, "status": status, "remove": remove}
        self._paint_status(item)

    def _paint_status(self, item: QueueItem) -> None:
        label = item.widgets.get("status")
        if not label:
            return
        text, color = {
            "pending": ("na fila", Colors.MUTED),
            "running": (item.message or "convertendo", Colors.ACCENT),
            "done": ("pronto", Colors.OK),
            "error": (item.message or "erro", Colors.ERROR),
            "missing": (item.message or "não encontrado", Colors.ERROR),
        }[item.state]
        label.configure(text=text, text_color=color)

    def _refresh_row(self, item: QueueItem, tooltip: str = "") -> None:
        w = item.widgets
        if not w:
            return
        w["duration"].configure(text=format_duration(item.duration))
        formats = list(AUDIO_FORMATS) if item.info and not item.info.has_video else ALL_FORMATS
        w["menu"].configure(values=formats, state="normal" if item.available and not self.busy
                            else "disabled")
        w["menu"].set(item.format)
        self._paint_status(item)
        self._update_queue_summary()

    def _remove_item(self, item: QueueItem) -> None:
        if item.state == "running":
            return
        self.queue.remove(item)
        self._render_queue()

    def _clear_queue(self) -> None:
        if self.busy:
            return
        self.queue.clear()
        self._render_queue()

    def _set_all_formats(self, fmt: str) -> None:
        for item in self.queue:
            if item.state in ("pending", "done", "error") and item.available:
                if item.info and not item.info.has_video and fmt in VIDEO_FORMATS:
                    continue
                item.format = fmt
                if item.widgets:
                    item.widgets["menu"].set(fmt)

    def _choose_convert_dir(self) -> None:
        folder = filedialog.askdirectory(title="Salvar conversões em")
        if folder:
            self.convert_dir = folder
            self.convert_dest_label.configure(text=short_path(folder, 34))

    def _update_queue_summary(self) -> None:
        total = len(self.queue)
        done = sum(1 for i in self.queue if i.state == "done")
        ready = sum(1 for i in self.queue if i.state == "pending")
        if not total:
            text = ""
        elif self.busy:
            text = f"{done} de {done + ready + (1 if any(i.state == 'running' for i in self.queue) else 0)}"
        else:
            text = f"{total} {'item' if total == 1 else 'itens'} · {ready} na fila"
        self.queue_status.configure(text=text)

    def _start_queue(self) -> None:
        if self.busy:
            return
        pending = [i for i in self.queue if i.state in ("pending", "error") and i.available]
        if not pending:
            messagebox.showinfo("Fila", "Não há itens para converter.")
            return
        for item in pending:
            item.state, item.message = "pending", ""
            self._paint_status(item)
        self.queue_cancelled.clear()
        self._set_busy(True)
        for item in self.queue:
            if item.widgets:
                item.widgets["menu"].configure(state="disabled")
        self.convert_button.grid_remove()
        self.cancel_button.grid(row=0, column=5, padx=(0, 8))
        self.convert_button.grid(row=0, column=6)
        self.convert_button.configure(state="disabled")
        threading.Thread(target=self._queue_worker, args=(pending,), daemon=True).start()

    def _cancel_queue(self) -> None:
        self.queue_cancelled.set()
        self.conversion_service.cancel()

    def _queue_worker(self, items: List[QueueItem]) -> None:
        for item in items:
            if self.queue_cancelled.is_set():
                break
            if item not in self.queue:
                continue
            ext = extension_for(item.format)
            base = os.path.splitext(item.title if item.is_url else
                                    os.path.basename(item.source))[0] or "convertido"
            base = "".join(c for c in base if c not in '<>:"/\\|?*').strip() or "convertido"
            folder = self.convert_dir or (self.download_dir if item.is_url
                                          else os.path.dirname(item.source))
            output = unique_path(folder, base, ext)
            item.state, item.message = "running", "convertendo"
            self._ui(self._paint_status, item)

            def progress(value, it=item):
                it.message = f"convertendo {value * 100:.0f}%"
                self._ui(self._paint_status, it)
            try:
                self.conversion_service.convert(item.source, output, item.format, progress,
                                                info=item.info)
            except ConversionCancelled:
                item.state, item.message = "pending", ""
                self._remove_partial(output)
                self._ui(self._paint_status, item)
                break
            except Exception as error:
                item.state, item.message = "error", "erro"
                self._remove_partial(output)
                self._ui(self._item_failed, item, error)
            else:
                item.state, item.output = "done", output
                self.history_service.add_record("conversion", os.path.basename(output), output)
                self._ui(self._paint_status, item)
            self._ui(self._update_queue_summary)
        self._ui(self._queue_finished)

    @staticmethod
    def _remove_partial(path: str) -> None:
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass

    def _item_failed(self, item: QueueItem, error: Exception) -> None:
        self._paint_status(item)
        first_line = str(error).strip().splitlines()[0] if str(error).strip() else "erro"
        item.message = "erro" if len(first_line) > 22 else first_line.lower()
        self._paint_status(item)
        self._last_error = (item.title, str(error))

    def _queue_finished(self) -> None:
        self._set_busy(False)
        self.cancel_button.grid_remove()
        self.convert_button.configure(state="normal")
        for item in self.queue:
            self._refresh_row(item)
        errors = [i for i in self.queue if i.state == "error"]
        if errors and getattr(self, "_last_error", None):
            title, detail = self._last_error
            messagebox.showerror("Alguns itens falharam",
                                 f"{len(errors)} item(ns) não foram convertidos.\n\n"
                                 f"Último erro ({title}):\n{detail[-500:]}")
            self._last_error = None
        self._update_queue_summary()

    # ---------------------------------------------------------- histórico
    def _build_history_page(self) -> ctk.CTkFrame:
        page = self._page("Histórico", "Tudo que foi baixado ou convertido neste computador.")
        page.grid_rowconfigure(3, weight=1)

        bar = ctk.CTkFrame(page, fg_color=Colors.TRANSPARENT)
        bar.grid(row=2, column=0, sticky="ew", padx=36)
        bar.grid_columnconfigure(3, weight=1)
        self.history_filter = "Tudo"
        self.history_filter_buttons: Dict[str, ctk.CTkButton] = {}
        for i, name in enumerate(["Tudo", "Downloads", "Conversões"]):
            btn = ctk.CTkButton(bar, text=name, width=10, height=30, corner_radius=4,
                                font=self.f(13), fg_color=Colors.TRANSPARENT,
                                hover_color=Colors.HOVER, text_color=Colors.MUTED,
                                command=lambda n=name: self._set_history_filter(n))
            btn.grid(row=0, column=i, padx=(0, 4))
            self.history_filter_buttons[name] = btn
        self._link(bar, "limpar histórico", self._clear_history, color=Colors.ERROR,
                   width=130).grid(row=0, column=4, sticky="e")
        self._line(bar).grid(row=1, column=0, columnspan=5, sticky="ew", pady=(10, 0))

        self.history_list = self._scroll(page)
        self.history_list.grid(row=3, column=0, sticky="nsew", padx=(36, 26), pady=(0, 18))
        return page

    def _set_history_filter(self, name: str) -> None:
        self.history_filter = name
        self._render_history()

    def _render_history(self) -> None:
        for name, btn in self.history_filter_buttons.items():
            on = name == self.history_filter
            btn.configure(text_color=Colors.TEXT if on else Colors.MUTED,
                          fg_color=Colors.HOVER if on else Colors.TRANSPARENT,
                          font=self.f(13, "sans_strong" if on else "sans"))
        kind = {"Tudo": None, "Downloads": "download",
                "Conversões": "conversion"}[self.history_filter]
        self._fill_list(self.history_list, self.history_service.get_history(kind),
                        "Nada por aqui ainda.")

    def _clear_history(self) -> None:
        if messagebox.askyesno("Limpar histórico", "Remover todos os itens do histórico?\n"
                               "Os arquivos no computador não serão apagados."):
            self.history_service.clear_history()
            self._render_history()
            self._render_recent()

    def _fill_list(self, container, items: List[Dict[str, Any]], empty: str) -> None:
        for w in container.winfo_children():
            w.destroy()
        if not items:
            self._label(container, empty, 13, color=Colors.MUTED).grid(row=0, column=0,
                                                                      sticky="w", pady=16)
            return
        for i, item in enumerate(items):
            self._history_row(container, item, i)

    def _history_row(self, parent, item: Dict[str, Any], index: int) -> None:
        path = item.get("path", "")
        exists = bool(path) and os.path.exists(path)
        row = ctk.CTkFrame(parent, fg_color=Colors.TRANSPARENT, corner_radius=0)
        row.grid(row=index, column=0, sticky="ew")
        row.grid_columnconfigure(0, weight=1)

        name = item.get("filename", "")
        name = name if len(name) <= 64 else name[:61] + "…"
        box = ctk.CTkFrame(row, fg_color=Colors.TRANSPARENT)
        box.grid(row=0, column=0, sticky="w", pady=10)
        self._label(box, name, 13).pack(anchor="w")
        where = short_path(os.path.dirname(path), 60) if exists else "arquivo não encontrado"
        self._label(box, where, 11, "mono", Colors.MUTED if exists else Colors.ERROR).pack(
            anchor="w")

        kind = "download" if item.get("type") == "download" else "conversão"
        ext = os.path.splitext(name)[1].lstrip(".").lower() or "—"
        date = item.get("date", "")
        self._label(row, f"{ext:<5} {kind:<10} {date}", 11, "mono", Colors.MUTED).grid(
            row=0, column=1, padx=(12, 18))
        state = "normal" if exists else "disabled"
        self._link(row, "abrir", lambda p=path: self._open_path(p), state=state,
                   width=50).grid(row=0, column=2)
        self._link(row, "pasta", lambda p=path: self._open_path(os.path.dirname(p)),
                   state=state, width=50).grid(row=0, column=3)
        self._line(row).grid(row=1, column=0, columnspan=4, sticky="ew")

    # ---------------------------------------------------------- utilitários
    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.download_button.configure(state="disabled" if busy else "normal")
        self.convert_button.configure(state="disabled" if busy else "normal")

    def _open_path(self, path: str) -> None:
        try:
            if platform.system() == "Windows":
                os.startfile(path)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            messagebox.showerror("Erro", f"Não foi possível abrir.\n{e}")


if __name__ == "__main__":
    app = ConverterApp()
    app.mainloop()
