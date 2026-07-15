"""CARL application icon support for Tk and macOS Dock windows."""

from __future__ import annotations

import os
import sys
import tkinter as tk


def bundled_path(filename: str) -> str:
    """Return a data-file path in development and PyInstaller builds."""
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, filename)


def set_application_icon(
        root: tk.Misc, logo_path: str | None = None) -> bool:
    """Use the CARL logo for Tk windows and the macOS Dock icon."""
    logo_path = logo_path or bundled_path("CARL_Logo.png")
    try:
        try:
            from PIL import Image, ImageTk
            with Image.open(logo_path) as source:
                source = source.convert("RGBA")
                # Aqua uses the first image for the application/Dock icon.
                icons = [
                    ImageTk.PhotoImage(
                        source.resize((size, size), Image.LANCZOS),
                        master=root,
                    )
                    for size in (512, 256, 128, 64, 32, 16)
                ]
        except ImportError:
            icons = [tk.PhotoImage(master=root, file=logo_path)]
        root.iconphoto(True, *icons)
        # Tk images vanish if their final Python references are collected.
        root._carl_icon_images = icons
        return True
    except Exception as exc:
        print(f"[WARNING] Could not set CARL application icon: {exc}")
        return False
