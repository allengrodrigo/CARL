#!/usr/bin/env python3
"""Simple image pop-out.

Displays the image on a matplotlib canvas whose navigation toolbar already
provides pan, zoom, home, and save-to-disk — so no custom buttons are needed.
"""

from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import ttk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from PIL import Image


class ImageViewerWindow:
    def __init__(self, parent, image_path: str):
        self.source = Path(image_path).expanduser().resolve()
        img = Image.open(self.source)      # raises on SVG / unreadable formats
        img.load()
        image_array = np.array(img)

        self.window = tk.Toplevel(parent)
        self.window.title(f"Image Viewer - {self.source.name}")
        self.window.geometry("1000x760")
        self.window.minsize(600, 440)

        self.figure = Figure(figsize=(8, 6), dpi=100, facecolor="white")
        ax = self.figure.add_subplot(111)
        ax.imshow(image_array)
        ax.axis("off")
        self.figure.tight_layout(pad=0.5)

        self.canvas = FigureCanvasTkAgg(self.figure, master=self.window)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=6, pady=(6, 2))

        toolbar_frame = ttk.Frame(self.window)
        toolbar_frame.pack(fill=tk.X, padx=6, pady=(0, 4))
        self.toolbar = NavigationToolbar2Tk(self.canvas, toolbar_frame, pack_toolbar=False)
        self.toolbar.update()
        self.toolbar.pack(side=tk.LEFT, fill=tk.X)

        self.canvas.draw()
        self.window.protocol("WM_DELETE_WINDOW", self._close)

    def _close(self):
        try:
            self.figure.clear()
        except Exception:
            pass
        try:
            self.window.destroy()
        except tk.TclError:
            pass


def open_image_viewer(parent, image_path: str) -> ImageViewerWindow:
    """Open a viewer window for the given image file."""
    return ImageViewerWindow(parent, image_path)
