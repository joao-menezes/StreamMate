import os
import platform
import subprocess
import sys
import threading
import webbrowser
from tkinter import filedialog, messagebox
from typing import Any, Callable, Dict, Optional

import customtkinter as ctk
from PIL import Image

from constants.app_constants import AppConstants, Colors
from constants.media_formats import (AUDIO_FORMATS, INPUT_EXTENSIONS, VIDEO_FORMATS,
                                     extension_for, format_label)
from services.connection_service import ConnectionService
from services.conversion_service import ConversionCancelled, ConversionService, MediaInfo
from services.download_service import DownloadService
from services.history_service import HistoryService
from services.tooltip_service import ToolTipService

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

FONT_FAMILY = "Segoe UI" if platform.system() == "Windows" else None


def resource_path(relative: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


def font(size: int = 13, weight: str = "normal") -> ctk.CTkFont:
    if FONT_FAMILY:
        return ctk.CTkFont(family=FONT_FAMILY, size=size, weight=weight)
    return ctk.CTkFont(size=size, weight=weight)


def format_duration(seconds: Optional[float]) -> str:
    if not seconds:
        return "—"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def format_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return ""


def default_download_dir() -> str:
    downloads = os.path.join(os.path.expanduser("~"), "Downloads")
    return downloads if os.path.isdir(downloads) else os.path.expanduser("~")


class ConverterApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.constants = AppConstants()
        self.file_path: Optional[str] = None
        self.media_info: Optional[MediaInfo] = None
        self.download_dir = default_download_dir()
        self.busy = False
        self.pages: Dict[str, ctk.CTkFrame] = {}
        self.nav_buttons: Dict[str, ctk.CTkButton] = {}

        self.connection_service = ConnectionService()
        self.conversion_service = ConversionService()
        self.download_service = DownloadService(self.conversion_service)
        self.history_service = HistoryService()

        self._setup_main_window()
        self._initialize_ui()
        self._start_connection_monitor()
        self.show_page("download")

    # ------------------------------------------------------------------ janela
    def _setup_main_window(self) -> None:
        self.title(self.constants.WINDOW_TITLE)
        self.geometry(self.constants.WINDOW_SIZE)
        self.minsize(*self.constants.MIN_SIZE)
        self.configure(fg_color=Colors.BG)
        try:
            if platform.system() == "Windows":
                self.iconbitmap(resource_path(self.constants.APP_ICON_ICO))
            else:
                from PIL import ImageTk
                self._icon_photo = ImageTk.PhotoImage(
                    Image.open(resource_path(self.constants.APP_ICON_PNG)))
                self.iconphoto(True, self._icon_photo)
        except Exception:
            pass
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

    def _initialize_ui(self) -> None:
        self._create_sidebar()
        self.content = ctk.CTkFrame(self, fg_color=Colors.TRANSPARENT)
        self.content.grid(row=0, column=1, sticky="nsew", padx=32, pady=28)
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self.pages["download"] = self._build_download_page()
        self.pages["convert"] = self._build_convert_page()
        self.pages["history"] = self._build_history_page()
        for page in self.pages.values():
            page.grid(row=0, column=0, sticky="nsew")

    def _ui(self, fn: Callable, *args) -> None:
        """Agenda uma atualização de interface na thread principal."""
        self.after(0, lambda: fn(*args))

    # ----------------------------------------------------------------- sidebar
    def _create_sidebar(self) -> None:
        sidebar = ctk.CTkFrame(self, width=self.constants.SIDEBAR_WIDTH, corner_radius=0,
                               fg_color=Colors.SIDEBAR, border_width=0)
        sidebar.grid(row=0, column=0, sticky="ns")
        sidebar.grid_propagate(False)
        sidebar.grid_columnconfigure(0, weight=1)
        sidebar.grid_rowconfigure(5, weight=1)

        brand = ctk.CTkFrame(sidebar, fg_color=Colors.TRANSPARENT)
        brand.grid(row=0, column=0, sticky="ew", padx=20, pady=(26, 30))
        try:
            logo = ctk.CTkImage(Image.open(resource_path(self.constants.APP_ICON_PNG)),
                                size=(34, 34))
            ctk.CTkLabel(brand, text="", image=logo).pack(side="left")
        except Exception:
            pass
        title_box = ctk.CTkFrame(brand, fg_color=Colors.TRANSPARENT)
        title_box.pack(side="left", padx=(10, 0))
        ctk.CTkLabel(title_box, text="StreamMate", font=font(18, "bold"),
                     text_color=Colors.TEXT).pack(anchor="w")
        ctk.CTkLabel(title_box, text=f"v{self.constants.VERSION}", font=font(11),
                     text_color=Colors.TEXT_MUTED, height=14).pack(anchor="w")

        ctk.CTkLabel(sidebar, text="MENU", font=font(11, "bold"),
                     text_color=Colors.TEXT_MUTED).grid(row=1, column=0, sticky="w",
                                                         padx=24, pady=(0, 6))
        nav = [("download", "⬇   Baixar"), ("convert", "⇄   Converter"),
               ("history", "☰   Histórico")]
        for i, (key, text) in enumerate(nav, start=2):
            btn = ctk.CTkButton(
                sidebar, text=text, anchor="w", height=42, corner_radius=10,
                font=font(14), fg_color=Colors.TRANSPARENT, hover_color=Colors.NAV_HOVER,
                text_color=Colors.TEXT, command=lambda k=key: self.show_page(k))
            btn.grid(row=i, column=0, sticky="ew", padx=14, pady=3)
            self.nav_buttons[key] = btn

        footer = ctk.CTkFrame(sidebar, fg_color=Colors.TRANSPARENT)
        footer.grid(row=6, column=0, sticky="ew", padx=16, pady=(0, 18))
        footer.grid_columnconfigure(0, weight=1)

        self.connection_label = ctk.CTkLabel(
            footer, text="●  Verificando conexão", font=font(12),
            text_color=Colors.TEXT_MUTED, fg_color=Colors.CARD_ALT, corner_radius=8,
            height=32, anchor="w", padx=12)
        self.connection_label.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))

        self.theme_switch = ctk.CTkSwitch(
            footer, text="Modo escuro", font=font(12), text_color=Colors.TEXT_MUTED,
            progress_color=Colors.ACCENT, command=self._toggle_theme)
        self.theme_switch.select()
        self.theme_switch.grid(row=1, column=0, sticky="w")

        self._load_github_icon(footer)

    def _load_github_icon(self, parent) -> None:
        try:
            icon = Image.open(resource_path(self.constants.ICON_PATH))
            image = ctk.CTkImage(light_image=icon, dark_image=icon,
                                 size=self.constants.ICON_SIZE)
            link = ctk.CTkLabel(parent, text="", image=image, cursor="hand2")
            link.grid(row=1, column=1, sticky="e")
            link.bind("<Button-1>", lambda e: webbrowser.open(self.constants.GITHUB_URL))
            ToolTipService(link, "Ver no GitHub")
        except (FileNotFoundError, OSError):
            pass

    def _toggle_theme(self) -> None:
        ctk.set_appearance_mode("Dark" if self.theme_switch.get() else "Light")

    def show_page(self, key: str) -> None:
        for name, btn in self.nav_buttons.items():
            active = name == key
            btn.configure(fg_color=Colors.ACCENT_SOFT if active else Colors.TRANSPARENT,
                          text_color=Colors.ACCENT if active else Colors.TEXT,
                          font=font(14, "bold" if active else "normal"))
        if key == "history":
            self._render_history()
        elif key == "download":
            self._render_recent()
        self.pages[key].tkraise()

    # ------------------------------------------------------------- conexão
    def _start_connection_monitor(self) -> None:
        def loop():
            while True:
                online = self.connection_service.is_connected()
                self._ui(self._set_connection, online)
                threading.Event().wait(5)
        threading.Thread(target=loop, daemon=True).start()

    def _set_connection(self, online: bool) -> None:
        self.connection_label.configure(
            text="●  Online" if online else "●  Sem internet",
            text_color=Colors.SUCCESS if online else Colors.DANGER)

    # ----------------------------------------------------------- componentes
    def _page(self, title: str, subtitle: str) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self.content, fg_color=Colors.BG, corner_radius=0)
        page.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(page, text=title, font=font(26, "bold"),
                     text_color=Colors.TEXT).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(page, text=subtitle, font=font(13),
                     text_color=Colors.TEXT_MUTED).grid(row=1, column=0, sticky="w",
                                                        pady=(2, 20))
        return page

    def _card(self, parent, **grid) -> ctk.CTkFrame:
        card = ctk.CTkFrame(parent, fg_color=Colors.CARD, corner_radius=14,
                            border_width=1, border_color=Colors.BORDER)
        card.grid(sticky="ew", **grid)
        card.grid_columnconfigure(0, weight=1)
        return card

    def _field_label(self, parent, text: str, **grid) -> None:
        ctk.CTkLabel(parent, text=text, font=font(12, "bold"),
                     text_color=Colors.TEXT_MUTED).grid(sticky="w", **grid)

    def _primary_button(self, parent, text: str, command, **kw) -> ctk.CTkButton:
        return ctk.CTkButton(parent, text=text, command=command, height=44, corner_radius=10,
                             font=font(14, "bold"), fg_color=Colors.ACCENT,
                             hover_color=Colors.ACCENT_HOVER, text_color="#FFFFFF", **kw)

    def _secondary_button(self, parent, text: str, command, **kw) -> ctk.CTkButton:
        kw.setdefault("height", 38)
        return ctk.CTkButton(parent, text=text, command=command, corner_radius=10,
                             font=font(13), fg_color=Colors.CARD_ALT,
                             hover_color=Colors.NAV_HOVER, text_color=Colors.TEXT,
                             border_width=1, border_color=Colors.BORDER, **kw)

    def _option_menu(self, parent, values, **kw) -> ctk.CTkOptionMenu:
        return ctk.CTkOptionMenu(
            parent, values=values, height=40, corner_radius=10, font=font(13),
            dropdown_font=font(13), fg_color=Colors.CARD_ALT, button_color=Colors.ACCENT,
            button_hover_color=Colors.ACCENT_HOVER, text_color=Colors.TEXT,
            dropdown_fg_color=Colors.CARD, dropdown_text_color=Colors.TEXT,
            dropdown_hover_color=Colors.NAV_HOVER, dynamic_resizing=False, **kw)

    def _progress_area(self, parent, row: int) -> Dict[str, Any]:
        box = ctk.CTkFrame(parent, fg_color=Colors.TRANSPARENT)
        box.grid(row=row, column=0, sticky="ew", padx=24, pady=(4, 22))
        box.grid_columnconfigure(0, weight=1)
        status = ctk.CTkLabel(box, text="", font=font(12), text_color=Colors.TEXT_MUTED,
                              anchor="w")
        status.grid(row=0, column=0, sticky="w")
        percent = ctk.CTkLabel(box, text="", font=font(12, "bold"), text_color=Colors.TEXT)
        percent.grid(row=0, column=1, sticky="e")
        bar = ctk.CTkProgressBar(box, height=8, corner_radius=4, progress_color=Colors.ACCENT,
                                 fg_color=Colors.CARD_ALT)
        bar.set(0)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        bar.grid_remove()
        return {"status": status, "percent": percent, "bar": bar, "indeterminate": False}

    def _set_progress(self, area, message: str, value: Optional[float] = None,
                      color=None) -> None:
        area["status"].configure(text=message, text_color=color or Colors.TEXT_MUTED)
        bar = area["bar"]
        if value is None:
            area["percent"].configure(text="")
            if not area["indeterminate"]:
                bar.configure(mode="indeterminate")
                bar.start()
                area["indeterminate"] = True
        else:
            if area["indeterminate"]:
                bar.stop()
                bar.configure(mode="determinate")
                area["indeterminate"] = False
            bar.set(value)
            area["percent"].configure(text=f"{value * 100:.0f}%")
        bar.grid()

    def _finish_progress(self, area, message: str, ok: bool) -> None:
        bar = area["bar"]
        if area["indeterminate"]:
            bar.stop()
            bar.configure(mode="determinate")
            area["indeterminate"] = False
        bar.grid_remove()
        area["percent"].configure(text="")
        area["status"].configure(text=message,
                                 text_color=Colors.SUCCESS if ok else Colors.DANGER)

    # ------------------------------------------------------------- download
    def _build_download_page(self) -> ctk.CTkFrame:
        page = self._page("Baixar do YouTube",
                          "Cole o link, escolha o formato e onde salvar.")
        page.grid_rowconfigure(3, weight=1)
        card = self._card(page, row=2, column=0)

        self._field_label(card, "LINK DO VÍDEO", row=0, column=0, padx=24, pady=(22, 6))
        url_row = ctk.CTkFrame(card, fg_color=Colors.TRANSPARENT)
        url_row.grid(row=1, column=0, sticky="ew", padx=24)
        url_row.grid_columnconfigure(0, weight=1)
        self.url_entry = ctk.CTkEntry(
            url_row, height=42, corner_radius=10, font=font(13),
            placeholder_text="https://www.youtube.com/watch?v=...",
            fg_color=Colors.CARD_ALT, border_color=Colors.BORDER, text_color=Colors.TEXT)
        self.url_entry.grid(row=0, column=0, sticky="ew")
        self.url_entry.bind("<Return>", lambda e: self._start_download())
        self._secondary_button(url_row, "Colar", self._paste_url, width=80,
                               height=42).grid(row=0, column=1, padx=(8, 0))

        options = ctk.CTkFrame(card, fg_color=Colors.TRANSPARENT)
        options.grid(row=2, column=0, sticky="ew", padx=24, pady=(18, 0))
        options.grid_columnconfigure((0, 1), weight=1, uniform="opt")

        self._field_label(options, "FORMATO", row=0, column=0, pady=(0, 6))
        self.download_formats = {"MP4  —  Vídeo em melhor qualidade": "mp4"}
        self.download_formats.update({format_label(f): f for f in AUDIO_FORMATS})
        self.download_formats.update({format_label(f): f for f in VIDEO_FORMATS if f != "mp4"})
        self.download_format_menu = self._option_menu(options, list(self.download_formats))
        self.download_format_menu.grid(row=1, column=0, sticky="ew", padx=(0, 8))

        self._field_label(options, "SALVAR EM", row=0, column=1, padx=(8, 0), pady=(0, 6))
        folder_row = ctk.CTkFrame(options, fg_color=Colors.TRANSPARENT)
        folder_row.grid(row=1, column=1, sticky="ew", padx=(8, 0))
        folder_row.grid_columnconfigure(0, weight=1)
        self.folder_label = ctk.CTkLabel(
            folder_row, text=self._short_path(self.download_dir), anchor="w", height=40,
            font=font(13), fg_color=Colors.CARD_ALT, corner_radius=10,
            text_color=Colors.TEXT, padx=12)
        self.folder_label.grid(row=0, column=0, sticky="ew")
        self._secondary_button(folder_row, "Alterar", self._choose_download_dir, width=80,
                               height=40).grid(row=0, column=1, padx=(8, 0))

        self.download_button = self._primary_button(card, "Baixar", self._start_download)
        self.download_button.grid(row=3, column=0, sticky="ew", padx=24, pady=(22, 14))
        self.download_progress = self._progress_area(card, row=4)

        recent = ctk.CTkFrame(page, fg_color=Colors.TRANSPARENT)
        recent.grid(row=3, column=0, sticky="nsew", pady=(26, 0))
        recent.grid_columnconfigure(0, weight=1)
        header = ctk.CTkFrame(recent, fg_color=Colors.TRANSPARENT)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="Baixados recentemente", font=font(16, "bold"),
                     text_color=Colors.TEXT).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(header, text="Ver tudo →", width=80, height=28, font=font(12),
                      fg_color=Colors.TRANSPARENT, hover_color=Colors.NAV_HOVER,
                      text_color=Colors.ACCENT,
                      command=lambda: self.show_page("history")).grid(row=0, column=1)
        recent.grid_rowconfigure(1, weight=1)
        self.recent_container = ctk.CTkScrollableFrame(
            recent, fg_color=Colors.TRANSPARENT, corner_radius=0,
            scrollbar_button_color=Colors.BORDER, scrollbar_button_hover_color=Colors.TEXT_MUTED)
        self.recent_container.grid(row=1, column=0, sticky="nsew")
        self.recent_container.grid_columnconfigure(0, weight=1)
        return page

    def _paste_url(self) -> None:
        try:
            text = self.clipboard_get().strip()
        except Exception:
            return
        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, text)

    def _choose_download_dir(self) -> None:
        folder = filedialog.askdirectory(title="Pasta para salvar", initialdir=self.download_dir)
        if folder:
            self.download_dir = folder
            self.folder_label.configure(text=self._short_path(folder))

    @staticmethod
    def _short_path(path: str, limit: int = 34) -> str:
        home = os.path.expanduser("~")
        if path.startswith(home):
            path = "~" + path[len(home):]
        return path if len(path) <= limit else "…" + path[-(limit - 1):]

    def _start_download(self) -> None:
        if self.busy:
            return
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning("Link vazio", "Cole o link de um vídeo do YouTube.")
            return
        fmt = self.download_formats[self.download_format_menu.get()]
        self._set_busy(True)
        self._set_progress(self.download_progress, "Iniciando...", None)
        threading.Thread(target=self._download_worker, args=(url, fmt), daemon=True).start()

    def _download_worker(self, url: str, fmt: str) -> None:
        def on_status(message, value):
            self._ui(self._set_progress, self.download_progress, message, value)
        try:
            path, filename = self.download_service.download(url, self.download_dir, fmt,
                                                            on_status)
        except Exception as error:
            self._ui(self._download_failed, error)
        else:
            self._ui(self._download_done, filename, path)

    def _download_done(self, filename: str, path: str) -> None:
        self._set_busy(False)
        self.history_service.add_record("download", filename, path)
        self._finish_progress(self.download_progress, f"✓  Salvo: {filename}", ok=True)
        self.url_entry.delete(0, "end")
        self.file_path = path
        self._render_recent()

    def _download_failed(self, error: Exception) -> None:
        self._set_busy(False)
        self._finish_progress(self.download_progress, "Não foi possível baixar.", ok=False)
        messagebox.showerror("Erro no download", str(error))

    def _render_recent(self) -> None:
        for widget in self.recent_container.winfo_children():
            widget.destroy()
        items = self.history_service.get_history("download",
                                                 self.constants.HISTORY_DISPLAY_LIMIT)
        if not items:
            self._empty_state(self.recent_container, "Nenhum download ainda.")
            return
        for i, item in enumerate(items):
            self._history_row(self.recent_container, item, i)

    # ------------------------------------------------------------- conversão
    def _build_convert_page(self) -> ctk.CTkFrame:
        page = self._page("Converter arquivo",
                          "Áudio e vídeo em praticamente qualquer formato.")
        card = self._card(page, row=2, column=0)

        self._field_label(card, "ARQUIVO DE ORIGEM", row=0, column=0, padx=24, pady=(22, 6))
        source = ctk.CTkFrame(card, fg_color=Colors.CARD_ALT, corner_radius=12,
                              border_width=1, border_color=Colors.BORDER)
        source.grid(row=1, column=0, sticky="ew", padx=24)
        source.grid_columnconfigure(1, weight=1)
        self.file_badge = ctk.CTkLabel(source, text="＋", width=46, height=46,
                                       corner_radius=10, font=font(20, "bold"),
                                       fg_color=Colors.ACCENT_SOFT, text_color=Colors.ACCENT)
        self.file_badge.grid(row=0, column=0, rowspan=2, padx=14, pady=14)
        self.file_label = ctk.CTkLabel(source, text="Nenhum arquivo selecionado",
                                       font=font(14, "bold"), text_color=Colors.TEXT,
                                       anchor="w")
        self.file_label.grid(row=0, column=1, sticky="sw")
        self.file_meta = ctk.CTkLabel(
            source, text=f"Aceita {len(INPUT_EXTENSIONS)}+ formatos: MP4, MKV, MOV, AVI, "
                         "WEBM, MP3, WAV, FLAC, OGG, M4A…",
            font=font(12), text_color=Colors.TEXT_MUTED, anchor="w")
        self.file_meta.grid(row=1, column=1, sticky="nw")
        self._secondary_button(source, "Escolher arquivo", self._select_file,
                               width=140).grid(row=0, column=2, rowspan=2, padx=14)

        options = ctk.CTkFrame(card, fg_color=Colors.TRANSPARENT)
        options.grid(row=2, column=0, sticky="ew", padx=24, pady=(18, 0))
        options.grid_columnconfigure(1, weight=1)

        self._field_label(options, "CONVERTER PARA", row=0, column=0, columnspan=2,
                          pady=(0, 6))
        self.output_kind = ctk.CTkSegmentedButton(
            options, values=["Vídeo", "Áudio"], height=40, corner_radius=10, font=font(13),
            selected_color=Colors.ACCENT, selected_hover_color=Colors.ACCENT_HOVER,
            unselected_color=Colors.CARD_ALT, unselected_hover_color=Colors.NAV_HOVER,
            fg_color=Colors.CARD_ALT, text_color=Colors.TEXT,
            command=self._update_format_options)
        self.output_kind.set("Áudio")
        self.output_kind.grid(row=1, column=0, sticky="w", padx=(0, 10))
        self.format_option = self._option_menu(options, [])
        self.format_option.grid(row=1, column=1, sticky="ew")
        self._update_format_options("Áudio")

        buttons = ctk.CTkFrame(card, fg_color=Colors.TRANSPARENT)
        buttons.grid(row=3, column=0, sticky="ew", padx=24, pady=(22, 14))
        buttons.grid_columnconfigure(0, weight=1)
        self.convert_button = self._primary_button(buttons, "Converter",
                                                   self._start_conversion)
        self.convert_button.grid(row=0, column=0, sticky="ew")
        self.cancel_button = self._secondary_button(buttons, "Cancelar",
                                                    self.conversion_service.cancel,
                                                    width=110, height=44)
        self.convert_progress = self._progress_area(card, row=4)
        return page

    def _update_format_options(self, kind: str) -> None:
        formats = VIDEO_FORMATS if kind == "Vídeo" else AUDIO_FORMATS
        self.format_labels = {format_label(f): f for f in formats}
        values = list(self.format_labels)
        self.format_option.configure(values=values)
        self.format_option.set(values[0])

    def _select_file(self) -> None:
        patterns = " ".join(f"*.{e}" for e in INPUT_EXTENSIONS)
        file = filedialog.askopenfilename(
            title="Selecione um arquivo de áudio ou vídeo",
            filetypes=[("Arquivos de mídia", patterns), ("Todos os arquivos", "*.*")])
        if not file:
            return
        try:
            info = self.conversion_service.probe(file)
        except Exception as error:
            messagebox.showerror("Arquivo não suportado",
                                 f"Não consegui ler esse arquivo como mídia.\n\n{error}")
            return
        self._set_source(file, info)

    def _set_source(self, file: str, info: MediaInfo) -> None:
        self.file_path, self.media_info = file, info
        kind = "Vídeo" if info.has_video else "Áudio"
        ext = os.path.splitext(file)[1].lstrip(".").upper() or "?"
        self.file_badge.configure(text="▶" if info.has_video else "♪")
        self.file_label.configure(text=os.path.basename(file))
        self.file_meta.configure(
            text=f"{kind} · {ext} · {format_duration(info.duration)} · "
                 f"{format_size(os.path.getsize(file))}")
        if info.has_video:
            self.output_kind.configure(state="normal")
        else:
            self.output_kind.set("Áudio")
            self._update_format_options("Áudio")
            self.output_kind.configure(state="disabled")
        self.convert_progress["status"].configure(text="")

    def _start_conversion(self) -> None:
        if self.busy:
            return
        if not self.file_path:
            messagebox.showwarning("Nenhum arquivo", "Escolha um arquivo para converter.")
            return
        fmt = self.format_labels[self.format_option.get()]
        ext = extension_for(fmt)
        base = os.path.splitext(os.path.basename(self.file_path))[0]
        output = filedialog.asksaveasfilename(
            title="Salvar como", defaultextension=f".{ext}",
            initialdir=os.path.dirname(self.file_path), initialfile=f"{base}.{ext}",
            filetypes=[(f"{fmt.upper()}", f"*.{ext}"), ("Todos os arquivos", "*.*")])
        if not output:
            return
        self._set_busy(True)
        self.cancel_button.grid(row=0, column=1, padx=(8, 0))
        self._set_progress(self.convert_progress, f"Convertendo para {fmt.upper()}...", None)
        threading.Thread(target=self._convert_worker, args=(self.file_path, output, fmt),
                         daemon=True).start()

    def _convert_worker(self, source: str, output: str, fmt: str) -> None:
        def on_progress(value):
            self._ui(self._set_progress, self.convert_progress,
                     f"Convertendo para {fmt.upper()}...", value)
        try:
            self.conversion_service.convert(source, output, fmt, on_progress)
        except ConversionCancelled:
            self._ui(self._conversion_ended, "Conversão cancelada.", False, output)
        except Exception as error:
            self._ui(self._conversion_failed, error)
        else:
            self._ui(self._conversion_ended, f"✓  Salvo: {os.path.basename(output)}", True,
                     output)

    def _conversion_ended(self, message: str, ok: bool, output: str) -> None:
        self._set_busy(False)
        self.cancel_button.grid_remove()
        self._finish_progress(self.convert_progress, message, ok)
        if ok:
            self.history_service.add_record("conversion", os.path.basename(output), output)
        elif os.path.exists(output):
            try:
                os.remove(output)
            except OSError:
                pass

    def _conversion_failed(self, error: Exception) -> None:
        self._set_busy(False)
        self.cancel_button.grid_remove()
        self._finish_progress(self.convert_progress, "Não foi possível converter.", ok=False)
        messagebox.showerror("Erro na conversão", str(error))

    # -------------------------------------------------------------- histórico
    def _build_history_page(self) -> ctk.CTkFrame:
        page = self._page("Histórico", "Seus downloads e conversões.")
        page.grid_rowconfigure(3, weight=1)

        bar = ctk.CTkFrame(page, fg_color=Colors.TRANSPARENT)
        bar.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        bar.grid_columnconfigure(1, weight=1)
        self.history_filter = ctk.CTkSegmentedButton(
            bar, values=["Todos", "Downloads", "Conversões"], height=36, corner_radius=10,
            font=font(13), selected_color=Colors.ACCENT,
            selected_hover_color=Colors.ACCENT_HOVER, unselected_color=Colors.CARD,
            unselected_hover_color=Colors.NAV_HOVER, fg_color=Colors.CARD,
            text_color=Colors.TEXT, command=lambda _: self._render_history())
        self.history_filter.set("Todos")
        self.history_filter.grid(row=0, column=0, sticky="w")
        ctk.CTkButton(bar, text="Limpar histórico", width=130, height=36, corner_radius=10,
                      font=font(13), fg_color=Colors.TRANSPARENT, hover_color=Colors.NAV_HOVER,
                      text_color=Colors.DANGER, border_width=1, border_color=Colors.BORDER,
                      command=self._clear_history).grid(row=0, column=2, sticky="e")

        self.history_list = ctk.CTkScrollableFrame(
            page, fg_color=Colors.TRANSPARENT, corner_radius=0,
            scrollbar_button_color=Colors.BORDER, scrollbar_button_hover_color=Colors.TEXT_MUTED)
        self.history_list.grid(row=3, column=0, sticky="nsew")
        self.history_list.grid_columnconfigure(0, weight=1)
        return page

    def _render_history(self) -> None:
        for widget in self.history_list.winfo_children():
            widget.destroy()
        kind = {"Todos": None, "Downloads": "download",
                "Conversões": "conversion"}[self.history_filter.get()]
        items = self.history_service.get_history(kind)
        if not items:
            self._empty_state(self.history_list, "Nada por aqui ainda.")
            return
        for i, item in enumerate(items):
            self._history_row(self.history_list, item, i)

    def _clear_history(self) -> None:
        if messagebox.askyesno("Limpar histórico",
                               "Remover todos os itens do histórico?\n"
                               "Os arquivos no computador não serão apagados."):
            self.history_service.clear_history()
            self._render_history()
            self._render_recent()

    def _empty_state(self, parent, text: str) -> None:
        box = ctk.CTkFrame(parent, fg_color=Colors.CARD, corner_radius=12, border_width=1,
                           border_color=Colors.BORDER, height=70)
        box.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(box, text=text, font=font(13), text_color=Colors.TEXT_MUTED).pack(pady=22)

    def _history_row(self, parent, item: Dict[str, Any], row: int) -> None:
        path = item.get("path", "")
        exists = bool(path) and os.path.exists(path)
        is_download = item.get("type") == "download"

        frame = ctk.CTkFrame(parent, fg_color=Colors.CARD, corner_radius=12, border_width=1,
                             border_color=Colors.BORDER)
        frame.grid(row=row, column=0, sticky="ew", pady=4)
        frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(frame, text="⬇" if is_download else "⇄", width=38, height=38,
                     corner_radius=9, font=font(15, "bold"), fg_color=Colors.ACCENT_SOFT,
                     text_color=Colors.ACCENT).grid(row=0, column=0, rowspan=2, padx=12, pady=10)

        name = item.get("filename", "")
        if len(name) > 60:
            name = name[:57] + "…"
        ctk.CTkLabel(frame, text=name, font=font(13, "bold"), text_color=Colors.TEXT,
                     anchor="w").grid(row=0, column=1, sticky="sw")
        meta = "Download" if is_download else "Conversão"
        if item.get("date"):
            meta += f" · {item['date']}"
        meta += f" · {self._short_path(os.path.dirname(path), 46)}" if exists \
            else " · arquivo não encontrado"
        ctk.CTkLabel(frame, text=meta, font=font(11),
                     text_color=Colors.TEXT_MUTED if exists else Colors.DANGER,
                     anchor="w").grid(row=1, column=1, sticky="nw")

        actions = ctk.CTkFrame(frame, fg_color=Colors.TRANSPARENT)
        actions.grid(row=0, column=2, rowspan=2, padx=12)
        state = "normal" if exists else "disabled"
        self._secondary_button(actions, "Abrir", lambda p=path: self._open_path(p), width=70,
                               height=32, state=state).pack(side="left", padx=(0, 6))
        self._secondary_button(actions, "Pasta",
                               lambda p=path: self._open_path(os.path.dirname(p)), width=70,
                               height=32, state=state).pack(side="left")

    # ---------------------------------------------------------------- utilit.
    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.download_button.configure(state=state)
        self.convert_button.configure(state=state)

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
