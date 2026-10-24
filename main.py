import os
import re
import sys
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, messagebox

IS_WIN = os.name == "nt"
if getattr(sys, "frozen", False):
    SCRIPT_DIR = sys._MEIPASS
else:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(SCRIPT_DIR, "assets", "ZeroTrace.png")

try:
    import backend
    WIPE_IMPORT_ERROR = None
except Exception as e:
    backend = None
    WIPE_IMPORT_ERROR = str(e)

def list_disks():
    disks = []
    if IS_WIN:
        try:
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command",
                 "Get-Disk | Select-Object Number,FriendlyName,Size,BusType,IsSystem "
                 "| ConvertTo-Csv -NoTypeInformation"],
                text=True, stderr=subprocess.DEVNULL)
            lines = out.strip().splitlines()
            for line in lines[1:]:
                parts = [p.strip('"') for p in line.split('","')]
                parts[0] = parts[0].lstrip('"')
                parts[-1] = parts[-1].rstrip('"')
                if len(parts) < 5:
                    continue
                number, name, size, bus, is_system = parts
                try:
                    size_fmt = fmt_bytes(int(size))
                except ValueError:
                    size_fmt = "?"
                path = f"\\\\.\\PhysicalDrive{number}"
                sys_tag = "  [SYSTEM]" if is_system.strip().lower() == "true" else ""
                disks.append((path, f"Disk {number}: {name} - {size_fmt} ({bus}){sys_tag}"))
        except Exception:
            pass
    elif sys.platform.startswith("linux"):
        try:
            out = subprocess.check_output(
                ["lsblk", "-dno", "NAME,SIZE,MODEL,TYPE"], text=True)
            for line in out.strip().splitlines():
                fields = line.split(None, 3)
                if len(fields) < 2:
                    continue
                name, size = fields[0], fields[1]
                model = fields[3] if len(fields) > 3 else ""
                typ = fields[2] if len(fields) > 2 else ""
                if typ != "disk":
                    continue
                path = f"/dev/{name}"
                disks.append((path, f"{path}: {size} {model}".strip()))
        except Exception:
            pass
    elif sys.platform == "darwin":
        try:
            out = subprocess.check_output(["diskutil", "list"], text=True)
            for line in out.splitlines():
                m = re.match(r"^(/dev/disk\d+)\s*\(?(external|internal)?", line)
                if m:
                    path = m.group(1)
                    disks.append((path, line.strip()))
        except Exception:
            pass
    return disks


def fmt_bytes(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}"
        n /= 1024

BG = "#0f1222"
GLASS = "#1b1f36"
GLASS_LIGHT = "#262b4a"
ACCENT = "#7dd3fc"
DANGER = "#f87171"
DANGER_DIM = "#5c2626"
TEXT = "#e8eaf6"
SUBTEXT = "#9aa0c3"


class GlassFrame(tk.Frame):
    """A flat-color frame standing in for a frosted-glass panel."""
    def __init__(self, master, **kw):
        kw.setdefault("bg", GLASS)
        kw.setdefault("highlightthickness", 1)
        kw.setdefault("highlightbackground", "#333a5c")
        kw.setdefault("highlightcolor", "#333a5c")
        super().__init__(master, **kw)


class WipeDiskApp:
    def __init__(self, root):
        self.root = root
        self.wiping = False
        self._stop_event = None

        root.title("ZeroTrace")
        root.geometry("640x560")
        root.configure(bg=BG)
        root.minsize(560, 500)

        self.logo_img, self.logo_error = self._load_logo()
        if self.logo_img is not None:
            try:
                root.iconphoto(True, self.logo_img)
            except tk.TclError as e:
                self.logo_error = f"iconphoto() rejected the image: {e}"

            if IS_WIN:
                try:
                    import ctypes
                    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                        "ZeroTrace.DiskWiper")
                except Exception:
                    pass

        self._build_style()
        self._build_ui()
        self.refresh_disks()

        if not IS_WIN and os.geteuid() != 0:
            self._log("Warning: not running as root. Launch with sudo for the wipe to work.\n", DANGER)
        if backend is None:
            self._log(f"Warning: could not import wipe_disk ({WIPE_IMPORT_ERROR}). "
                       f"Make sure wipe_disk.py is next to this script.\n", DANGER)
        if self.logo_error:
            self._log(f"Logo not loaded: {self.logo_error}\n", DANGER)
        elif self.logo_img is None:
            self._log(f"Logo not loaded: no file at {LOGO_PATH}\n", DANGER)

    # -- logo ------------------------------------------------------------
    def _load_logo(self, max_size=40):
        """Load assets/ZeroTrace.png, if present, scaled down to fit the header.

        Returns (PhotoImage_or_None, error_message_or_None) so the caller
        can report exactly why the logo didn't show instead of failing silently.
        """
        if not os.path.exists(LOGO_PATH):
            return None, None

        pillow_error = None
        try:
            # Pillow gives clean resizing and handles any PNG variant
            # (interlaced, 16-bit, indexed+alpha, etc).
            from PIL import Image, ImageTk
            img = Image.open(LOGO_PATH)
            img.load()
            img = img.convert("RGBA")
            scale = max_size / max(img.width, img.height)
            if scale < 1:
                img = img.resize((max(1, int(img.width * scale)),
                                   max(1, int(img.height * scale))),
                                  Image.LANCZOS)
            return ImageTk.PhotoImage(img), None
        except ImportError:
            pillow_error = "Pillow (PIL) is not installed"
        except Exception as e:
            pillow_error = f"Pillow failed to open the file ({e})"

        try:
            img = tk.PhotoImage(file=LOGO_PATH)
            factor = max(1, max(img.width(), img.height()) // max_size)
            if factor > 1:
                img = img.subsample(factor, factor)
            return img, None
        except tk.TclError as e:
            return None, f"{pillow_error}; Tk's built-in PNG loader also failed ({e})"

    def _build_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Glass.TCombobox",
                         fieldbackground=GLASS_LIGHT, background=GLASS_LIGHT,
                         foreground=TEXT, arrowcolor=ACCENT, bordercolor="#333a5c",
                         lightcolor=GLASS_LIGHT, darkcolor=GLASS_LIGHT)
        style.map("Glass.TCombobox", fieldbackground=[("readonly", GLASS_LIGHT)])
        style.configure("Glass.Horizontal.TProgressbar",
                         troughcolor=GLASS_LIGHT, background=ACCENT,
                         bordercolor=GLASS, lightcolor=ACCENT, darkcolor=ACCENT)

    def _build_ui(self):
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=24, pady=(22, 10))

        title_row = tk.Frame(header, bg=BG)
        title_row.pack(fill="x", anchor="w")

        if self.logo_img is not None:
            tk.Label(title_row, image=self.logo_img, bg=BG).pack(side="left", padx=(0, 10))

        title_col = tk.Frame(title_row, bg=BG)
        title_col.pack(side="left")
        tk.Label(title_col, text="ZeroTrace", font=("Segoe UI", 20, "bold"),
                 bg=BG, fg=TEXT).pack(anchor="w")
        tk.Label(title_col, text="Overwrites an entire physical disk with zeros. This cannot be undone.",
                 font=("Segoe UI", 10), bg=BG, fg=SUBTEXT).pack(anchor="w", pady=(2, 0))

        # Disk picker panel
        panel = GlassFrame(self.root)
        panel.pack(fill="x", padx=24, pady=10)
        inner = tk.Frame(panel, bg=GLASS)
        inner.pack(fill="x", padx=16, pady=16)

        row1 = tk.Frame(inner, bg=GLASS)
        row1.pack(fill="x")
        tk.Label(row1, text="Target disk", font=("Segoe UI", 10, "bold"),
                 bg=GLASS, fg=TEXT).pack(side="left")
        tk.Button(row1, text="Refresh", command=self.refresh_disks,
                  bg=GLASS_LIGHT, fg=ACCENT, activebackground=GLASS_LIGHT,
                  activeforeground=ACCENT, relief="flat", bd=0,
                  font=("Segoe UI", 9), padx=10, pady=3,
                  cursor="hand2").pack(side="right")

        self.disk_var = tk.StringVar()
        self.disk_combo = ttk.Combobox(inner, textvariable=self.disk_var,
                                        state="readonly", style="Glass.TCombobox",
                                        font=("Segoe UI", 10))
        self.disk_combo.pack(fill="x", pady=(8, 10))
        self.disk_combo.bind("<<ComboboxSelected>>", lambda e: self._on_disk_pick())

        tk.Label(inner, text="Or enter a path manually:", font=("Segoe UI", 9),
                 bg=GLASS, fg=SUBTEXT).pack(anchor="w")
        self.path_var = tk.StringVar()
        path_entry = tk.Entry(inner, textvariable=self.path_var, bg=GLASS_LIGHT,
                               fg=TEXT, insertbackground=TEXT, relief="flat",
                               font=("Consolas" if IS_WIN else "Menlo", 10))
        path_entry.pack(fill="x", pady=(4, 0), ipady=6)

        # Danger confirmation panel
        confirm_panel = GlassFrame(self.root, highlightbackground=DANGER_DIM,
                                    highlightcolor=DANGER_DIM)
        confirm_panel.pack(fill="x", padx=24, pady=10)
        cinner = tk.Frame(confirm_panel, bg=GLASS)
        cinner.pack(fill="x", padx=16, pady=16)

        tk.Label(cinner, text="Type the exact disk path to confirm",
                 font=("Segoe UI", 10, "bold"), bg=GLASS, fg=DANGER).pack(anchor="w")
        self.confirm_var = tk.StringVar()
        self.confirm_entry = tk.Entry(cinner, textvariable=self.confirm_var,
                                       bg=GLASS_LIGHT, fg=TEXT, insertbackground=TEXT,
                                       relief="flat", font=("Consolas" if IS_WIN else "Menlo", 10))
        self.confirm_entry.pack(fill="x", pady=(8, 0), ipady=6)

        # Action button
        action_row = tk.Frame(self.root, bg=BG)
        action_row.pack(fill="x", padx=24, pady=(4, 10))
        self.wipe_btn = tk.Button(action_row, text="Wipe Disk", command=self.start_wipe,
                                   bg=DANGER, fg="#1a0a0a", activebackground="#fca5a5",
                                   activeforeground="#1a0a0a", relief="flat", bd=0,
                                   font=("Segoe UI", 11, "bold"), padx=16, pady=10,
                                   cursor="hand2")
        self.wipe_btn.pack(side="left")

        self.cancel_btn = tk.Button(action_row, text="Cancel", command=self.cancel_wipe,
                                     bg=GLASS_LIGHT, fg=TEXT, activebackground=GLASS_LIGHT,
                                     activeforeground=TEXT, relief="flat", bd=0,
                                     font=("Segoe UI", 10), padx=14, pady=10,
                                     cursor="hand2", state="disabled")
        self.cancel_btn.pack(side="left", padx=(10, 0))

        # Progress
        self.progress = ttk.Progressbar(self.root, style="Glass.Horizontal.TProgressbar",
                                         mode="determinate")
        self.progress.pack(fill="x", padx=24, pady=(0, 10))

        self.status_var = tk.StringVar(value="Idle")
        tk.Label(self.root, textvariable=self.status_var, font=("Segoe UI", 9),
                 bg=BG, fg=SUBTEXT, anchor="w").pack(fill="x", padx=24)

        # Log panel
        log_panel = GlassFrame(self.root)
        log_panel.pack(fill="both", expand=True, padx=24, pady=(10, 22))
        self.log = tk.Text(log_panel, bg="#0a0d1a", fg="#b7bdE0", relief="flat",
                            font=("Consolas" if IS_WIN else "Menlo", 9), wrap="word",
                            padx=10, pady=10, state="disabled")
        self.log.pack(fill="both", expand=True)
        self.log.tag_configure("danger", foreground=DANGER)
        self.log.tag_configure("ok", foreground="#86efac")
        self.log.tag_configure("accent", foreground=ACCENT)

    def _log(self, text, color_tag=None):
        self.log.configure(state="normal")
        if color_tag:
            self.log.insert("end", text, color_tag)
        else:
            self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def refresh_disks(self):
        disks = list_disks()
        self.disk_combo["values"] = [label for _, label in disks]
        self._disk_paths = [path for path, _ in disks]
        if disks:
            self.disk_combo.current(0)
            self._on_disk_pick()
        self._log(f"Found {len(disks)} disk(s).\n", "accent")

    def _on_disk_pick(self):
        idx = self.disk_combo.current()
        if 0 <= idx < len(self._disk_paths):
            self.path_var.set(self._disk_paths[idx])

    def current_target(self):
        return self.path_var.get().strip()

    def start_wipe(self):
        if self.wiping:
            return
        target = self.current_target()
        if not target:
            messagebox.showerror("No target", "Pick or enter a disk path first.")
            return
        if self.confirm_var.get().strip() != target:
            messagebox.showerror("Confirmation mismatch",
                                  "The confirmation field must exactly match the target disk path.")
            return
        if backend is None:
            messagebox.showerror("Missing module",
                                  f"Could not import wipe_disk: {WIPE_IMPORT_ERROR}")
            return
        if not IS_WIN and os.geteuid() != 0:
            messagebox.showerror("Not root", "Re-launch this app with sudo to wipe a disk.")
            return

        if backend.is_system_disk(target):
            messagebox.showerror("Refused", f"{target} looks like your system/boot disk.\n"
                                             "Wiping it is blocked for safety.")
            return

        ok = messagebox.askyesno(
            "Final confirmation",
            f"This will PERMANENTLY ERASE ALL DATA on:\n\n{target}\n\n"
            "This action cannot be undone. Continue?",
            icon="warning")
        if not ok:
            return

        self.wiping = True
        self._stop_event = threading.Event()
        self.wipe_btn.configure(state="disabled", bg=GLASS_LIGHT)
        self.cancel_btn.configure(state="normal")
        self.progress.configure(value=0)
        self.status_var.set(f"Wiping {target} ...")
        self._log(f"\n--- Starting wipe of {target} ---\n", "danger")

        threading.Thread(target=self._run_wipe, args=(target,), daemon=True).start()

    def _run_wipe(self, target):
        try:
            size = backend.disk_size(target)
            self.root.after(0, self._log, f"Target : {target}\n")
            self.root.after(0, self._log,
                             f"Size   : {backend.fmt(size) if size else 'unknown'}\n")

            backend.windows_clean_partitions(
                target, log=lambda msg: self.root.after(0, self._log, msg + "\n"))

            def progress(written, total, rate):
                self.root.after(0, self._on_progress, written, total, rate)

            written = backend.wipe(target, progress=progress,
                                      should_stop=self._stop_event.is_set)
        except backend.WipeError as e:
            self.root.after(0, self._on_done, False, str(e))
            return
        except Exception as e:
            self.root.after(0, self._on_done, False, f"Unexpected error: {e}")
            return

        if self._stop_event.is_set():
            self.root.after(0, self._on_done, False,
                             f"Cancelled after {backend.fmt(written)} written.")
        else:
            self.root.after(0, self._on_done, True,
                             f"Done. {backend.fmt(written)} zeroed.")

    def _on_progress(self, written, total, rate):
        pct = f"{written / total * 100:5.1f}%" if total else ""
        line = f"{backend.fmt(written)} written  {pct}  {backend.fmt(rate)}/s"
        self.status_var.set(line)
        if total:
            try:
                self.progress.configure(value=written / total * 100)
            except ZeroDivisionError:
                pass

    def _on_done(self, success, message):
        self.wiping = False
        self.wipe_btn.configure(state="normal", bg=DANGER)
        self.cancel_btn.configure(state="disabled")
        self.status_var.set(message)
        self._log(f"\n{message}\n", "ok" if success else "danger")
        if success:
            self.progress.configure(value=100)
            messagebox.showinfo("Done", message)
        else:
            messagebox.showerror("Wipe did not complete", message)

    def cancel_wipe(self):
        if self.wiping and self._stop_event is not None:
            if messagebox.askyesno("Cancel wipe",
                                    "Stop the wipe now? The disk may be left "
                                    "partially overwritten."):
                self._stop_event.set()
                self._log("\nCancelling...\n", "danger")


def backend():
    root = tk.Tk()
    WipeDiskApp(root)
    root.mainloop()


if __name__ == "__main__":
    backend()