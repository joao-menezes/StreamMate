import customtkinter as ctk
from typing import Optional


class ToolTipService:
    def __init__(self, widget: ctk.CTkBaseClass, text: str):
        self.widget = widget
        self.text = text
        self.tooltip: Optional[ctk.CTkToplevel] = None
        self.widget.bind("<Enter>", self._show_tooltip, add="+")
        self.widget.bind("<Leave>", self._hide_tooltip, add="+")

    def _show_tooltip(self, event=None) -> None:
        if self.tooltip:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() - 34

        self.tooltip = ctk.CTkToplevel(self.widget)
        self.tooltip.wm_overrideredirect(True)
        self.tooltip.wm_geometry(f"+{x}+{y}")
        self.tooltip.attributes("-topmost", True)

        ctk.CTkLabel(
            self.tooltip, text=self.text, corner_radius=6,
            fg_color=("#1B1C27", "#ECECF4"), text_color=("#FFFFFF", "#111218"),
            font=ctk.CTkFont(size=12), padx=8, pady=4,
        ).pack()

    def _hide_tooltip(self, event=None) -> None:
        if self.tooltip:
            self.tooltip.destroy()
            self.tooltip = None
