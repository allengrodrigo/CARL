"""
run_ui.py  ← Run this instead of ui_app.py
Shows the splash screen immediately, then loads TaxonGPT in the background.
"""
import sys
import os

# When running as a PyInstaller bundle, put the folder that contains the
# exe on sys.path first so that the external config.py (which users edit
# to add their API key) can be imported by name.
if getattr(sys, 'frozen', False):
    _exe_dir = os.path.dirname(sys.executable)
    if _exe_dir not in sys.path:
        sys.path.insert(0, _exe_dir)

import threading
import time
import tkinter as tk
from PIL import Image, ImageTk
from app_icon import set_application_icon


def _app_dir() -> str:
    """Directory where bundled data files live (frozen) or this script (dev)."""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS  # _internal/ in PyInstaller 6 one-folder builds
    return os.path.dirname(os.path.abspath(__file__))


def create_splash(root):
    splash = tk.Toplevel(root)
    splash.overrideredirect(True)
    splash.attributes("-topmost", True)

    width, height = 400, 400
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    x = (sw - width) // 2
    y = (sh - height) // 2
    splash.geometry(f"{width}x{height}+{x}+{y}")
    splash.configure(bg="#fdf9ec")

    border = tk.Frame(splash, bg="black")
    border.pack(fill="both", expand=True)
    inner = tk.Frame(border, bg="#fdf9ec")
    inner.pack(fill="both", expand=True, padx=3, pady=3)

    canvas = tk.Canvas(inner, width=350, height=350, bg="#fdf9ec",
                       highlightthickness=0, bd=0)
    canvas.pack()

    try:
        image = Image.open(os.path.join(_app_dir(), "CARL_Logo.png"))
        image = image.resize((350, 350), Image.LANCZOS)
        img = ImageTk.PhotoImage(image)
        canvas.image = img  # prevent garbage collection
        canvas.create_image(0, 0, anchor="nw", image=img)
    except Exception as e:
        print(f"[WARNING] Could not load splash image: {e}")
        canvas.create_text(175, 175, text="Loading CARL...",
                           fill="#555555", font=("Helvetica", 14), anchor="center")

    # Status text overlay — sits in the bottom strip, just above the border
    canvas.create_rectangle(0, 334, 350, 350, fill="#fdf9ec", outline="")
    status_id = canvas.create_text(175, 342, text="Starting...",
                                   fill="#666666", font=("TkDefaultFont", 9),
                                   anchor="center")

    splash.update()

    def update_status(text):
        try:
            canvas.itemconfig(status_id, text=text)
        except Exception:
            pass

    return splash, update_status


def main():
    root = tk.Tk()
    # Set the application icon before withdrawing the root so Aqua never
    # presents Python/Tk's default icon while the splash is visible.
    set_application_icon(root, os.path.join(_app_dir(), "CARL_Logo.png"))
    root.withdraw()  # hide main window until app is ready

    splash, update_splash_status = create_splash(root)
    splash_start = time.time()
    splash_closed = threading.Event()

    def close_splash_when_ready():
        """Called by warm_up_llm when LLMs are ready."""
        # Enforce minimum 3-second display time
        elapsed = time.time() - splash_start
        delay_ms = max(0, int((3.0 - elapsed) * 1000))
        root.after(delay_ms, _do_close)

    def _do_close():
        if not splash_closed.is_set():
            splash_closed.set()
            try:
                splash.attributes("-topmost", False)
                splash.destroy()
            except Exception:
                pass
            root.deiconify()
            root.lift()
            root.attributes("-topmost", True)
            root.after(500, lambda: root.attributes("-topmost", False))

    def load_app():
        try:
            import ui_app  # heavy imports happen here, off the main thread
            # Signal that imports are done; __init__ will update from here.
            root.after(0, lambda: update_splash_status("Building interface..."))
            root.after(0, lambda: launch(ui_app))
        except Exception:
            import traceback
            msg = traceback.format_exc()
            root.after(0, lambda m=msg: _show_startup_error(m))

    def _show_startup_error(msg):
        from tkinter import messagebox
        messagebox.showerror("CARL — Startup Error", msg)
        root.quit()

    def launch(ui_app):
        ui_app.TaxonGPT_UI(root,
                           on_ready_callback=close_splash_when_ready,
                           on_status_callback=update_splash_status)
        # Safety net: if warm_up never fires the callback, close after 10s
        root.after(10000, close_splash_when_ready)

    threading.Thread(target=load_app, daemon=True).start()
    root.mainloop()


if __name__ == "__main__":
    main()