"""Main popover window and settings window using tkinter."""

from __future__ import annotations

import tkinter as tk
import traceback
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from usage_service import UsageService
    from history_service import HistoryService
    from notification_service import NotificationService

# -- Colors (dark theme) --
BG = "#16161e"
BG_CARD = "#1e1e2e"
BG_SECONDARY = "#24243a"
BG_HOVER = "#2e2e4a"
FG = "#e8e8f0"
FG_DIM = "#b0b0c8"
FG_MUTED = "#606078"
ACCENT = "#7c3aed"
ACCENT_HOVER = "#6d28d9"
BORDER = "#2e2e48"
BAR_BG = "#2a2a42"
RED = "#f43f5e"
BLUE = "#60a5fa"
GREEN = "#34d399"
YELLOW = "#fbbf24"
ORANGE = "#fb923c"

PROGRESS_HEIGHT = 18
CHART_HEIGHT = 180
CHART_WIDTH = 380
CORNER_R = 10


def _relative_time(dt: datetime) -> str:
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    secs = int((now - dt).total_seconds())
    if secs < 0:
        secs = abs(secs)
        if secs < 60: return f"in {secs}s"
        if secs < 3600: return f"in {secs // 60}m"
        if secs < 86400: return f"in {secs // 3600}h {(secs % 3600) // 60}m"
        return f"in {secs // 86400}d"
    if secs < 60: return f"{secs}s ago"
    if secs < 3600: return f"{secs // 60}m ago"
    if secs < 86400: return f"{secs // 3600}h {(secs % 3600) // 60}m ago"
    return f"{secs // 86400}d ago"


def _future_relative(dt: Optional[datetime]) -> str:
    if dt is None:
        return ""
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    secs = int((dt - now).total_seconds())
    if secs <= 0: return "Resetting..."
    if secs < 60: return f"Resets in {secs}s"
    if secs < 3600: return f"Resets in {secs // 60}m"
    if secs < 86400:
        h = secs // 3600
        m = (secs % 3600) // 60
        return f"Resets {h} hr, {m} min"
    d = secs // 86400
    h = (secs % 86400) // 3600
    return f"Resets {d} day, {h} hr"


def _pct_color(pct: float) -> str:
    if pct < 0.50: return GREEN
    if pct < 0.75: return YELLOW
    if pct < 0.90: return ORANGE
    return RED


def _catmull_rom_chain(pts, segments=8):
    """Convert a list of (x, y) points into a smooth curve.

    X is linearly interpolated (keeps time monotonic),
    Y uses Catmull-Rom spline (smooth value transitions).
    """
    if len(pts) < 2:
        return [c for p in pts for c in p]
    # Extract Y values and pad for Catmull-Rom
    ys = [p[1] for p in pts]
    ys_padded = [ys[0]] + ys + [ys[-1]]
    coords = []
    for i in range(len(pts) - 1):
        x0, x1 = pts[i][0], pts[i + 1][0]
        # Catmull-Rom indices (shifted by 1 due to padding)
        y0 = ys_padded[i]
        y1 = ys_padded[i + 1]
        y2 = ys_padded[i + 2]
        y3 = ys_padded[i + 3]
        for s in range(segments):
            t = s / segments
            t2 = t * t
            t3 = t2 * t
            x = x0 + (x1 - x0) * t
            y = 0.5 * (
                (2 * y1) +
                (-y0 + y2) * t +
                (2 * y0 - 5 * y1 + 4 * y2 - y3) * t2 +
                (-y0 + 3 * y1 - 3 * y2 + y3) * t3
            )
            coords.extend([x, y])
    # Add the last point
    coords.extend([pts[-1][0], pts[-1][1]])
    return coords


def _rounded_rect(canvas: tk.Canvas, x1, y1, x2, y2, r, **kwargs):
    """Draw a rounded rectangle on a canvas."""
    r = min(r, (x2 - x1) // 2, (y2 - y1) // 2)
    points = [
        x1 + r, y1,
        x2 - r, y1,
        x2, y1,
        x2, y1 + r,
        x2, y2 - r,
        x2, y2,
        x2 - r, y2,
        x1 + r, y2,
        x1, y2,
        x1, y2 - r,
        x1, y1 + r,
        x1, y1,
        x1 + r, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


class PillButton(tk.Canvas):
    """A pill-shaped button drawn on a canvas."""

    def __init__(self, parent, text, command=None,
                 bg_color=BG_SECONDARY, fg_color=FG_DIM, hover_color=BG_HOVER,
                 font=("Segoe UI", 9), height=28, padx=14, bold=False, **kwargs):
        super().__init__(parent, highlightthickness=0, bd=0, bg=BG,
                         height=height, **kwargs)
        self._text = text
        self._command = command
        self._bg_color = bg_color
        self._fg_color = fg_color
        self._hover_color = hover_color
        self._font_spec = font
        self._bold = bold
        self._height = height
        self._padx = padx
        self._hovered = False

        # Measure text width
        self._tmp_label = tk.Label(self, text=text, font=self._get_font())
        self._tmp_label.update_idletasks()
        text_w = self._tmp_label.winfo_reqwidth()
        self._tmp_label.destroy()

        self._width = text_w + padx * 2
        self.configure(width=self._width)

        self.bind("<Configure>", self._on_configure)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        self.bind("<ButtonRelease-1>", self._on_release)

    def _get_font(self):
        if self._bold:
            return (*self._font_spec, "bold")
        return self._font_spec

    def _on_configure(self, event=None):
        self._draw()

    def _draw(self):
        self.delete("all")
        w = self.winfo_width() or self._width
        h = self._height
        r = h // 2
        bg = self._hover_color if self._hovered else self._bg_color
        _rounded_rect(self, 0, 0, w, h, r, fill=bg, outline=bg)
        self.create_text(w // 2, h // 2, text=self._text,
                         fill=self._fg_color, font=self._get_font())

    def _on_enter(self, e):
        self._hovered = True
        self._draw()
        self.configure(cursor="hand2")

    def _on_leave(self, e):
        self._hovered = False
        self._draw()

    def _on_click(self, e):
        pass

    def _on_release(self, e):
        if self._command:
            self._command()


class RoundedBar(tk.Canvas):
    """Rounded progress bar."""

    def __init__(self, parent, height=PROGRESS_HEIGHT, **kwargs):
        kwargs.setdefault("highlightthickness", 0)
        kwargs.setdefault("bd", 0)
        kwargs.setdefault("bg", BG)
        # Add 2px padding so the smooth polygon isn't clipped at the bottom
        super().__init__(parent, height=height + 2, **kwargs)
        self._bar_height = height

    def draw_bar(self, pct: float, width: int = 0):
        self.delete("all")
        if width <= 0:
            self.update_idletasks()
            width = self.winfo_width() or 300

        h = self._bar_height
        r = h // 2

        # Background
        _rounded_rect(self, 0, 0, width, h, r, fill=BAR_BG, outline=BAR_BG)

        # Fill
        clamped = max(0.0, min(1.0, pct))
        if clamped > 0.01:
            fill_w = max(h, int(width * clamped))
            color = _pct_color(clamped)
            _rounded_rect(self, 0, 0, fill_w, h, r, fill=color, outline=color)


class MainWindow:
    """Main usage popover window shown when tray icon is clicked."""

    WIDTH = 420

    def __init__(self, service, history_service, notification_service):
        self.service = service
        self.history_service = history_service
        self.notification_service = notification_service
        self.window: Optional[tk.Toplevel] = None
        self._root: Optional[tk.Tk] = None
        self._settings_window: Optional[SettingsWindow] = None
        self._selected_range_idx = 2  # default: 1d
        self._widget_mode = False
        self._drag_data = {"x": 0, "y": 0}

    def set_root(self, root: tk.Tk):
        self._root = root

    def toggle(self):
        if self._widget_mode:
            # In widget mode, toggle just brings to front
            if self.window:
                try:
                    self.window.lift()
                    self.window.focus_force()
                except tk.TclError:
                    pass
            return
        if self.window is not None:
            try:
                if self.window.winfo_exists():
                    self.window.destroy()
                    self.window = None
                    return
            except tk.TclError:
                self.window = None
        self.show()

    def toggle_widget_mode(self):
        """Toggle between popover and widget (always-on) mode."""
        if self._widget_mode:
            # Exit widget mode
            self._widget_mode = False
            if self.window:
                try:
                    self.window.destroy()
                except tk.TclError:
                    pass
                self.window = None
        else:
            # Enter widget mode
            self._widget_mode = True
            if self.window:
                try:
                    self.window.destroy()
                except tk.TclError:
                    pass
                self.window = None
            self.show()

    @property
    def is_widget_mode(self) -> bool:
        return self._widget_mode

    def show(self):
        if self.window is not None:
            try:
                if self.window.winfo_exists():
                    self.window.lift()
                    self.window.focus_force()
                    return
            except tk.TclError:
                self.window = None

        win = tk.Toplevel()
        self.window = win
        win.withdraw()  # hide completely until positioned
        win.title("Claude Usage")
        win.resizable(False, False)
        win.configure(bg=BG)
        win.overrideredirect(True)  # borderless popover

        # Build content while hidden
        try:
            self._build_ui(win)
        except Exception:
            traceback.print_exc()

        # Calculate size and position near system tray
        win.update_idletasks()
        req_w = self.WIDTH
        req_h = win.winfo_reqheight()

        screen_w = win.winfo_screenwidth()
        screen_h = win.winfo_screenheight()
        x = screen_w - req_w - 12
        y = screen_h - req_h - 52
        win.geometry(f"{req_w}x{req_h}+{x}+{y}")

        # Now show at correct position
        win.deiconify()
        win.attributes("-topmost", True)
        win.focus_force()
        if not self._widget_mode:
            win.bind("<FocusOut>", self._on_focus_out)
        else:
            # Widget mode: make draggable
            win.bind("<Button-1>", self._on_drag_start)
            win.bind("<B1-Motion>", self._on_drag_motion)

    def _on_focus_out(self, event):
        if self.window:
            # Don't close if settings window is open
            if self._settings_window and self._settings_window.window:
                try:
                    if self._settings_window.window.winfo_exists():
                        return
                except tk.TclError:
                    pass
            try:
                focus_widget = self.window.focus_get()
                if focus_widget and str(focus_widget).startswith(str(self.window)):
                    return
            except (tk.TclError, KeyError):
                pass
            try:
                if self.window.winfo_exists():
                    self.window.destroy()
            except tk.TclError:
                pass
            self.window = None

    def _on_drag_start(self, event):
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y

    def _on_drag_motion(self, event):
        if self.window:
            x = self.window.winfo_x() + (event.x - self._drag_data["x"])
            y = self.window.winfo_y() + (event.y - self._drag_data["y"])
            self.window.geometry(f"+{x}+{y}")

    def _build_ui(self, win: tk.Toplevel):
        # Outer border
        outer = tk.Frame(win, bg=BORDER, padx=1, pady=1)
        outer.pack(fill="both", expand=True)

        main_frame = tk.Frame(outer, bg=BG, padx=22, pady=16)
        main_frame.pack(fill="both", expand=True)

        # Title bar
        title_frame = tk.Frame(main_frame, bg=BG)
        title_frame.pack(fill="x", pady=(0, 4))

        tk.Label(title_frame, text="Claude Usage", bg=BG, fg="#ffffff",
                 font=("Segoe UI", 16, "bold")).pack(side="left")

        if self._widget_mode:
            close_btn = PillButton(title_frame, text="X",
                                    command=self.toggle_widget_mode,
                                    bg_color=BG_SECONDARY, fg_color=FG,
                                    hover_color=RED,
                                    height=26, padx=10,
                                    font=("Segoe UI", 10), bold=True)
            close_btn.pack(side="right")

        if not self.service.is_authenticated:
            self._build_sign_in_ui(main_frame)
        else:
            self._build_usage_ui(main_frame)

    def _build_sign_in_ui(self, parent: tk.Frame):
        if self.service.is_awaiting_code:
            self._build_code_entry(parent)
            return

        tk.Label(parent, text="Sign in to view your usage.",
                 bg=BG, fg=FG_DIM, font=("Segoe UI", 10)).pack(anchor="w", pady=(10, 8))

        btn = PillButton(parent, text="Sign in with Claude", command=self._on_sign_in,
                         bg_color=ACCENT, fg_color="white", hover_color=ACCENT_HOVER,
                         font=("Segoe UI", 11), height=40, bold=True)
        btn.pack(fill="x", pady=(4, 10))

        if self.service.last_error:
            tk.Label(parent, text=self.service.last_error, bg=BG, fg=RED,
                     font=("Segoe UI", 9), wraplength=340).pack(anchor="w", pady=4)

        self._separator(parent)
        self._bottom_bar(parent)

    def _build_code_entry(self, parent: tk.Frame):
        tk.Label(parent, text="Paste the code from your browser:",
                 bg=BG, fg=FG_DIM, font=("Segoe UI", 10)).pack(anchor="w", pady=(10, 6))

        entry_frame = tk.Frame(parent, bg=BG)
        entry_frame.pack(fill="x", pady=4)

        code_var = tk.StringVar()
        entry = tk.Entry(entry_frame, textvariable=code_var, font=("Consolas", 11),
                         bg=BG_SECONDARY, fg=FG, insertbackground=FG,
                         relief="flat", bd=8)
        entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        entry.focus_set()

        def paste():
            try:
                text = self._root.clipboard_get() if self._root else ""
                code_var.set(text.strip())
            except tk.TclError:
                pass

        PillButton(entry_frame, text="Paste", command=paste,
                   height=32, padx=12).pack(side="right")

        btn_frame = tk.Frame(parent, bg=BG)
        btn_frame.pack(fill="x", pady=(8, 4))

        def cancel():
            self.service.is_awaiting_code = False
            self._refresh_window()

        def submit():
            val = code_var.get().strip()
            if not val:
                return
            import threading
            def do_submit():
                self.service.submit_oauth_code(val)
                if self._root:
                    self._root.after(0, self._refresh_window)
            threading.Thread(target=do_submit, daemon=True).start()

        PillButton(btn_frame, text="Cancel", command=cancel,
                   height=30, padx=16).pack(side="left")
        PillButton(btn_frame, text="Submit", command=submit,
                   bg_color=ACCENT, fg_color="white", hover_color=ACCENT_HOVER,
                   height=30, padx=16, bold=True).pack(side="right")

        entry.bind("<Return>", lambda e: submit())

    def _build_usage_ui(self, parent: tk.Frame):
        usage = self.service.usage

        # 5-Hour Window
        self._usage_bucket(parent, "5-Hour Window",
                           usage.five_hour if usage else None)

        # 7-Day Window
        self._usage_bucket(parent, "7-Day Window",
                           usage.seven_day if usage else None)

        # Per-model breakdown
        if usage and usage.seven_day_opus and usage.seven_day_opus.utilization is not None:
            self._separator(parent)
            tk.Label(parent, text="Per-Model (7 day)", bg=BG, fg=FG_MUTED,
                     font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 2))
            self._usage_bucket(parent, "Opus", usage.seven_day_opus, compact=True)
            if usage.seven_day_sonnet:
                self._usage_bucket(parent, "Sonnet", usage.seven_day_sonnet, compact=True)

        # Extra usage
        if usage and usage.extra_usage and usage.extra_usage.is_enabled:
            self._separator(parent)
            self._extra_usage(parent, usage.extra_usage)

        # Chart
        self._separator(parent)
        self._chart(parent)

        # Error
        if self.service.last_error:
            self._separator(parent)
            tk.Label(parent, text=self.service.last_error, bg=BG, fg=RED,
                     font=("Segoe UI", 9), wraplength=340).pack(anchor="w")

        # Bottom
        self._separator(parent)
        self._bottom_bar_usage(parent)

    def _usage_bucket(self, parent: tk.Frame, label: str, bucket, compact: bool = False):
        frame = tk.Frame(parent, bg=BG)
        frame.pack(fill="x", pady=(10 if not compact else 4, 2))

        pct = (bucket.utilization / 100.0) if bucket and bucket.utilization is not None else 0.0

        # Header
        header = tk.Frame(frame, bg=BG)
        header.pack(fill="x")
        tk.Label(header, text=label, bg=BG, fg=FG,
                 font=("Segoe UI", 13 if not compact else 10,
                       "bold" if not compact else "")).pack(side="left")
        pct_text = f"{int(round(bucket.utilization))}%" if bucket and bucket.utilization is not None else "--"
        color = _pct_color(pct) if pct > 0 else FG_DIM
        tk.Label(header, text=pct_text, bg=BG, fg=color,
                 font=("Segoe UI", 13 if not compact else 10, "bold")).pack(side="right")

        # Bar
        bar_h = PROGRESS_HEIGHT if not compact else 10
        bar = RoundedBar(frame, height=bar_h)
        bar.pack(fill="x", pady=(5, 0))
        bar.after(10, lambda: bar.draw_bar(pct))

        # Reset time - color matches the bar
        if bucket and bucket.resets_at_date:
            reset_color = _pct_color(pct) if pct > 0 else FG_MUTED
            tk.Label(frame, text=_future_relative(bucket.resets_at_date),
                     bg=BG, fg=reset_color, font=("Segoe UI", 10)).pack(anchor="w", pady=(4, 0))

    def _extra_usage(self, parent: tk.Frame, extra):
        frame = tk.Frame(parent, bg=BG)
        frame.pack(fill="x", pady=(4, 2))

        header = tk.Frame(frame, bg=BG)
        header.pack(fill="x")
        tk.Label(header, text="Extra Usage", bg=BG, fg=FG,
                 font=("Segoe UI", 11, "bold")).pack(side="left")

        if extra.used_credits_amount is not None and extra.monthly_limit_amount is not None:
            from models import ExtraUsage
            tk.Label(header,
                     text=f"{ExtraUsage.format_usd(extra.used_credits_amount)} / {ExtraUsage.format_usd(extra.monthly_limit_amount)}",
                     bg=BG, fg=FG_DIM, font=("Segoe UI", 10)).pack(side="right")

            pct = (extra.utilization or 0) / 100.0
            bar = RoundedBar(frame, height=PROGRESS_HEIGHT)
            bar.pack(fill="x", pady=(4, 0))
            bar.after(10, lambda: bar.draw_bar(pct))

    def _chart(self, parent: tk.Frame):
        from models import TimeRange

        frame = tk.Frame(parent, bg=BG)
        frame.pack(fill="x", pady=(4, 2))

        # Range selector - pill buttons
        ranges = list(TimeRange)
        sel_frame = tk.Frame(frame, bg=BG)
        sel_frame.pack(anchor="w", pady=(0, 8))

        # Build pill button group with rounded container
        pill_container = tk.Canvas(sel_frame, bg=BG, highlightthickness=0, bd=0,
                                    height=30)
        pill_container.pack(side="left")

        # Calculate total width
        btn_labels = [tr.label for tr in ranges]
        btn_w = 44
        total_w = btn_w * len(btn_labels)
        pill_container.configure(width=total_w)

        # Draw rounded background
        _rounded_rect(pill_container, 0, 0, total_w, 30, 15,
                      fill=BAR_BG, outline=BAR_BG)

        # Draw buttons
        for i, tr in enumerate(ranges):
            is_sel = (i == self._selected_range_idx)
            x1 = btn_w * i
            x2 = x1 + btn_w

            if is_sel:
                _rounded_rect(pill_container, x1 + 2, 2, x2 - 2, 28, 13,
                              fill=ACCENT, outline=ACCENT)

            txt_id = pill_container.create_text(
                (x1 + x2) // 2, 15, text=tr.label,
                fill="white" if is_sel else FG_MUTED,
                font=("Segoe UI", 9, "bold" if is_sel else ""))

            # Bind click events
            idx = i
            pill_container.tag_bind(txt_id, "<Button-1>",
                                     lambda e, idx=idx: self._select_range(idx))

        # Make the background also clickable
        def _chart_click(e):
            idx = int(e.x / btn_w)
            idx = max(0, min(len(ranges) - 1, idx))
            self._select_range(idx)
        pill_container.bind("<Button-1>", _chart_click)

        # Chart canvas with rounded corners
        canvas_w, canvas_h = CHART_WIDTH, CHART_HEIGHT
        canvas = tk.Canvas(frame, bg=BG, width=canvas_w, height=canvas_h,
                           highlightthickness=0, bd=0)
        canvas.pack(fill="x", pady=(0, 4))

        # Rounded background for chart
        _rounded_rect(canvas, 0, 0, canvas_w, canvas_h, CORNER_R,
                      fill=BG_CARD, outline=BG_CARD)

        selected = ranges[self._selected_range_idx]
        points = self.history_service.downsampled_points(selected)

        margin = {"l": 38, "r": 12, "t": 14, "b": 28}
        plot_w = canvas_w - margin["l"] - margin["r"]
        plot_h = canvas_h - margin["t"] - margin["b"]

        # Grid lines
        for pv in [0, 25, 50, 75, 100]:
            y = margin["t"] + plot_h * (1 - pv / 100)
            canvas.create_line(margin["l"], y, canvas_w - margin["r"], y,
                               fill=BORDER, dash=(2, 4))
            canvas.create_text(margin["l"] - 6, y, text=f"{pv}%", anchor="e",
                               fill=FG_MUTED, font=("Segoe UI", 8))

        if not points or len(points) < 2:
            # Show current values as dashed horizontal lines if we have usage data
            usage = self.service.usage
            if usage:
                if usage.five_hour and usage.five_hour.utilization is not None:
                    pct5 = usage.five_hour.utilization / 100.0
                    y5 = margin["t"] + plot_h * (1 - min(1, pct5))
                    canvas.create_line(margin["l"], y5, canvas_w - margin["r"], y5,
                                       fill=BLUE, dash=(6, 4), width=2)
                    canvas.create_text(canvas_w - margin["r"] + 2, y5,
                                       text=f"{int(usage.five_hour.utilization)}%",
                                       anchor="w", fill=BLUE, font=("Segoe UI", 7))
                if usage.seven_day and usage.seven_day.utilization is not None:
                    pct7 = usage.seven_day.utilization / 100.0
                    y7 = margin["t"] + plot_h * (1 - min(1, pct7))
                    canvas.create_line(margin["l"], y7, canvas_w - margin["r"], y7,
                                       fill=ORANGE, dash=(6, 4), width=2)

                canvas.create_text(canvas_w // 2, canvas_h // 2,
                                   text="Collecting data...",
                                   fill=FG_MUTED, font=("Segoe UI", 9))
            else:
                canvas.create_text(canvas_w // 2, canvas_h // 2,
                                   text="No history data yet.",
                                   fill=FG_MUTED, font=("Segoe UI", 9))
        else:
            ts_min = points[0].timestamp.timestamp()
            ts_max = points[-1].timestamp.timestamp()
            ts_range = max(ts_max - ts_min, 1)

            pts_5h, pts_7d = [], []
            for p in points:
                x = margin["l"] + ((p.timestamp.timestamp() - ts_min) / ts_range) * plot_w
                pts_5h.append((x, margin["t"] + plot_h * (1 - min(1, p.pct_5h))))
                pts_7d.append((x, margin["t"] + plot_h * (1 - min(1, p.pct_7d))))

            # Smooth 7d points with moving average (Y only) before spline
            if len(pts_7d) > 5:
                w = 5
                half = w // 2
                smoothed_7d = []
                for i in range(len(pts_7d)):
                    lo = max(0, i - half)
                    hi = min(len(pts_7d), i + half + 1)
                    avg_y = sum(p[1] for p in pts_7d[lo:hi]) / (hi - lo)
                    smoothed_7d.append((pts_7d[i][0], avg_y))
                pts_7d = smoothed_7d

            if len(pts_7d) >= 2:
                coords_7d = _catmull_rom_chain(pts_7d)
                canvas.create_line(*coords_7d, fill=ORANGE, width=2)
            if len(pts_5h) >= 2:
                coords_5h = _catmull_rom_chain(pts_5h)
                canvas.create_line(*coords_5h, fill=BLUE, width=2)

            self._draw_time_labels(canvas, points, margin, canvas_w, canvas_h, plot_w)

        # Legend
        legend_y = canvas_h - 10
        canvas.create_oval(margin["l"], legend_y - 4, margin["l"] + 8, legend_y + 4,
                           fill=BLUE, outline=BLUE)
        canvas.create_text(margin["l"] + 12, legend_y, text="5h", anchor="w",
                           fill=FG_DIM, font=("Segoe UI", 8))
        canvas.create_oval(margin["l"] + 38, legend_y - 4, margin["l"] + 46, legend_y + 4,
                           fill=ORANGE, outline=ORANGE)
        canvas.create_text(margin["l"] + 50, legend_y, text="7d", anchor="w",
                           fill=FG_DIM, font=("Segoe UI", 8))

    def _draw_time_labels(self, canvas, points, margin, canvas_w, canvas_h, plot_w):
        if len(points) < 2:
            return

        ts_min = points[0].timestamp.timestamp()
        ts_max = points[-1].timestamp.timestamp()
        ts_range = max(ts_max - ts_min, 1)

        label_count = 3
        for i in range(label_count):
            frac = i / (label_count - 1) if label_count > 1 else 0.5
            ts = ts_min + ts_range * frac
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
            x = margin["l"] + frac * plot_w

            try:
                if ts_range < 86400:
                    label = dt.strftime("%I %p").lstrip("0")
                else:
                    label = dt.strftime("%m/%d")
            except Exception:
                label = ""

            canvas.create_text(x, canvas_h - margin["b"] + 12, text=label,
                               fill=FG_MUTED, font=("Segoe UI", 8), anchor="n")

    def _select_range(self, idx: int):
        self._selected_range_idx = idx
        self._refresh_window()

    def _separator(self, parent: tk.Frame):
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=6)

    def _bottom_bar(self, parent: tk.Frame):
        bottom = tk.Frame(parent, bg=BG)
        bottom.pack(fill="x", pady=(8, 0))
        PillButton(bottom, text="Quit", command=self._quit,
                   height=28, padx=14).pack(side="right")

    def _bottom_bar_usage(self, parent: tk.Frame):
        # Updated time + text link buttons (like macOS version)
        bottom_info = tk.Frame(parent, bg=BG)
        bottom_info.pack(fill="x", pady=(4, 0))

        if self.service.last_updated:
            tk.Label(bottom_info, text=f"Updated {_relative_time(self.service.last_updated)}",
                     bg=BG, fg=FG_MUTED, font=("Segoe UI", 10)).pack(side="left")

        # Text link style buttons (right side)
        for text, cmd in [("Quit", self._quit), ("Sign Out", self._sign_out), ("Refresh", self._on_refresh)]:
            lbl = tk.Label(bottom_info, text=text, bg=BG, fg=FG_DIM,
                           font=("Segoe UI", 10), cursor="hand2")
            lbl.pack(side="right", padx=(12, 0))
            lbl.bind("<Button-1>", lambda e, c=cmd: c())
            lbl.bind("<Enter>", lambda e, l=lbl: l.config(fg=FG))
            lbl.bind("<Leave>", lambda e, l=lbl: l.config(fg=FG_DIM))

        # Launch at Login toggle (like macOS version)
        self._separator(parent)
        login_frame = tk.Frame(parent, bg=BG)
        login_frame.pack(fill="x", pady=(0, 2))
        tk.Label(login_frame, text="Launch at Login", bg=BG, fg=FG,
                 font=("Segoe UI", 10)).pack(side="left")
        self._startup_var = tk.BooleanVar(value=SettingsWindow._is_startup_enabled())
        ToggleSwitch(login_frame, variable=self._startup_var,
                     command=lambda: SettingsWindow._set_startup(self._startup_var.get())
                     ).pack(side="right")

        # Settings button (small, bottom left)
        settings_frame = tk.Frame(parent, bg=BG)
        settings_frame.pack(fill="x", pady=(4, 0))
        settings_lbl = tk.Label(settings_frame, text="Settings", bg=BG, fg=FG_MUTED,
                                font=("Segoe UI", 9), cursor="hand2")
        settings_lbl.pack(side="left")
        settings_lbl.bind("<Button-1>", lambda e: self._open_settings())
        settings_lbl.bind("<Enter>", lambda e: settings_lbl.config(fg=FG_DIM))
        settings_lbl.bind("<Leave>", lambda e: settings_lbl.config(fg=FG_MUTED))

    # -- Actions --

    def _on_sign_in(self):
        self.service.start_oauth_flow()
        self._refresh_window()

    def _on_refresh(self):
        import threading
        def do_refresh():
            self.service.fetch_usage()
            if self._root:
                self._root.after(0, self._refresh_window)
        threading.Thread(target=do_refresh, daemon=True).start()

    def _sign_out(self):
        self.service.sign_out()
        self._refresh_window()

    def _open_settings(self):
        # Just open settings - don't close main window
        try:
            if self._settings_window:
                try:
                    self._settings_window.show()
                    return
                except (tk.TclError, Exception):
                    self._settings_window = None
            self._settings_window = SettingsWindow(
                self._root, self.service, self.notification_service
            )
            self._settings_window.show()
        except Exception:
            traceback.print_exc()

    def _quit(self):
        self.history_service.flush_to_disk()
        if self._root:
            self._root.quit()

    def _refresh_window(self):
        # Save position in widget mode
        saved_pos = None
        if self._widget_mode and self.window:
            try:
                saved_pos = (self.window.winfo_x(), self.window.winfo_y())
            except tk.TclError:
                pass
        if self.window is not None:
            try:
                if self.window.winfo_exists():
                    self.window.destroy()
            except tk.TclError:
                pass
            self.window = None
        self.show()
        # Restore position in widget mode
        if saved_pos and self._widget_mode and self.window:
            try:
                self.window.geometry(f"+{saved_pos[0]}+{saved_pos[1]}")
            except tk.TclError:
                pass


class ToggleSwitch(tk.Canvas):
    """Custom toggle switch widget."""

    def __init__(self, parent, variable: tk.BooleanVar, command=None,
                 width=36, height=20, **kwargs):
        super().__init__(parent, width=width, height=height,
                         bg=BG, highlightthickness=0, bd=0, **kwargs)
        self._var = variable
        self._command = command
        self._sw_width = width
        self._sw_height = height
        self.bind("<Button-1>", self._on_click)
        self._var.trace_add("write", lambda *_: self._draw())
        self.after(10, self._draw)

    def _draw(self):
        self.delete("all")
        w, h = self._sw_width, self._sw_height
        r = h // 2
        on = self._var.get()
        cy = h // 2
        if on:
            # ON: accent track + dark knob (Windows 11 style)
            _rounded_rect(self, 0, 0, w, h, r, fill="#4cc2ff", outline="#4cc2ff")
            knob_r = h // 2 - 3
            knob_x = w - r
            self.create_oval(knob_x - knob_r, cy - knob_r,
                             knob_x + knob_r, cy + knob_r,
                             fill="#1a1a2e", outline="#1a1a2e")
        else:
            # OFF: border track + light knob (Windows 11 style)
            border_color = "#9a9aaa"
            _rounded_rect(self, 0, 0, w, h, r,
                          fill=border_color, outline=border_color)
            _rounded_rect(self, 2, 2, w - 2, h - 2, r - 2,
                          fill=BG, outline=BG)
            knob_r = h // 2 - 5
            knob_x = r
            self.create_oval(knob_x - knob_r, cy - knob_r,
                             knob_x + knob_r, cy + knob_r,
                             fill=border_color, outline=border_color)

    def _on_click(self, e):
        self._var.set(not self._var.get())
        if self._command:
            self._command()


class SettingsWindow:
    """Settings/preferences window - borderless, matching main window style."""

    WIDTH = 420

    def __init__(self, root, service, notification_service):
        self._root = root
        self.service = service
        self.notification_service = notification_service
        self.window: Optional[tk.Toplevel] = None

    def show(self):
        if self.window is not None:
            try:
                if self.window.winfo_exists():
                    self.window.lift()
                    self.window.focus_force()
                    return
            except tk.TclError:
                self.window = None

        win = tk.Toplevel()
        self.window = win
        win.withdraw()  # hide until positioned
        win.title("Settings")
        win.configure(bg=BG)
        win.protocol("WM_DELETE_WINDOW", self._close)

        main = tk.Frame(win, bg=BG, padx=18, pady=14)
        main.pack(fill="both", expand=True)

        # Title
        tk.Label(main, text="Settings", bg=BG, fg="#ffffff",
                 font=("Segoe UI", 15, "bold")).pack(anchor="w", pady=(0, 8))

        # -- General section --
        self._section_header(main, "General")

        # Launch at login
        startup_frame = tk.Frame(main, bg=BG)
        startup_frame.pack(fill="x", pady=(4, 8))
        tk.Label(startup_frame, text="Launch at login", bg=BG, fg=FG,
                 font=("Segoe UI", 10)).pack(side="left")
        self._startup_var = tk.BooleanVar(value=self._is_startup_enabled())
        ToggleSwitch(startup_frame, variable=self._startup_var,
                     command=self._toggle_startup).pack(side="right")

        # Polling interval
        poll_label_frame = tk.Frame(main, bg=BG)
        poll_label_frame.pack(fill="x", pady=(0, 6))
        tk.Label(poll_label_frame, text="Polling Interval", bg=BG, fg=FG,
                 font=("Segoe UI", 10)).pack(side="left")

        from usage_service import UsageService as US
        self._poll_var = tk.IntVar(value=self.service.polling_minutes)

        # Pill-group selector for polling
        poll_sel = tk.Canvas(main, bg=BG, highlightthickness=0, bd=0, height=32)
        poll_sel.pack(anchor="w", pady=(0, 8))

        options = US.POLLING_OPTIONS
        btn_w = 52
        total_w = btn_w * len(options)
        poll_sel.configure(width=total_w)
        _rounded_rect(poll_sel, 0, 0, total_w, 32, 16, fill=BAR_BG, outline=BAR_BG)

        for i, mins in enumerate(options):
            is_sel = (mins == self.service.polling_minutes)
            x1 = btn_w * i
            x2 = x1 + btn_w
            label = f"{mins}m" if mins < 60 else f"{mins // 60}h"
            if is_sel:
                _rounded_rect(poll_sel, x1 + 2, 2, x2 - 2, 30, 14,
                               fill=ACCENT, outline=ACCENT)
            poll_sel.create_text((x1 + x2) // 2, 16, text=label,
                                 fill="white" if is_sel else FG_MUTED,
                                 font=("Segoe UI", 9, "bold" if is_sel else ""))

        def _poll_click(e):
            idx = int(e.x / btn_w)
            idx = max(0, min(len(options) - 1, idx))
            self._poll_var.set(options[idx])
            self._update_polling()
            # Redraw
            self._refresh()
        poll_sel.bind("<Button-1>", _poll_click)

        # -- Notifications section --
        self._section_header(main, "Notifications")

        self._threshold_slider(main, "5-hour window",
                                self.notification_service.threshold_5h,
                                self.notification_service.set_threshold_5h)
        self._threshold_slider(main, "7-day window",
                                self.notification_service.threshold_7d,
                                self.notification_service.set_threshold_7d)
        self._threshold_slider(main, "Extra usage",
                                self.notification_service.threshold_extra,
                                self.notification_service.set_threshold_extra)

        # -- Account section --
        if self.service.is_authenticated:
            self._section_header(main, "Account")

            if self.service.account_email:
                tk.Label(main, text=self.service.account_email, bg=BG, fg=FG,
                         font=("Segoe UI", 10)).pack(anchor="w", pady=(4, 6))

            PillButton(main, text="Sign Out", command=self._sign_out,
                       fg_color=RED, height=30, padx=16).pack(anchor="w", pady=(0, 4))

        # Position: center on screen with explicit size
        win_h = 580
        screen_w = win.winfo_screenwidth()
        screen_h = win.winfo_screenheight()
        x = (screen_w - self.WIDTH) // 2
        y = (screen_h - win_h) // 2
        win.geometry(f"{self.WIDTH}x{win_h}+{x}+{y}")
        win.resizable(False, False)
        win.deiconify()
        win.attributes("-topmost", True)
        win.focus_force()

    def _section_header(self, parent, text):
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=(4, 2))
        tk.Label(parent, text=text, bg=BG, fg=FG_MUTED,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(4, 6))

    def _threshold_slider(self, parent, label: str, value: int, setter):
        frame = tk.Frame(parent, bg=BG)
        frame.pack(fill="x", pady=4)

        header = tk.Frame(frame, bg=BG)
        header.pack(fill="x")
        tk.Label(header, text=label, bg=BG, fg=FG,
                 font=("Segoe UI", 10)).pack(side="left")
        val_label = tk.Label(header, text=f"{value}%" if value > 0 else "Off",
                             bg=BG, fg=ACCENT if value > 0 else FG_MUTED,
                             font=("Segoe UI", 10))
        val_label.pack(side="right")

        var = tk.IntVar(value=value)

        # Custom slider using canvas
        slider_h = 28
        slider = tk.Canvas(frame, bg=BG, height=slider_h, highlightthickness=0, bd=0)
        slider.pack(fill="x", pady=(4, 0))

        def _draw_slider(canvas_w=None):
            slider.delete("all")
            if canvas_w is None:
                slider.update_idletasks()
                canvas_w = slider.winfo_width() or 340
            track_y = slider_h // 2
            track_h = 6
            # Track background
            _rounded_rect(slider, 0, track_y - track_h // 2,
                          canvas_w, track_y + track_h // 2,
                          track_h // 2, fill=BAR_BG, outline=BAR_BG)
            # Filled portion
            pct = var.get() / 100.0
            fill_w = int(canvas_w * pct)
            if fill_w > 0:
                _rounded_rect(slider, 0, track_y - track_h // 2,
                              fill_w, track_y + track_h // 2,
                              track_h // 2, fill=ACCENT, outline=ACCENT)
            # Knob
            knob_r = 8
            knob_x = max(knob_r, min(canvas_w - knob_r, fill_w))
            slider.create_oval(knob_x - knob_r, track_y - knob_r,
                               knob_x + knob_r, track_y + knob_r,
                               fill="white", outline="white")

        def _on_slider_click(e):
            canvas_w = slider.winfo_width() or 340
            pct = max(0, min(1, e.x / canvas_w))
            iv = round(int(pct * 100) / 5) * 5
            var.set(iv)
            val_label.config(text=f"{iv}%" if iv > 0 else "Off",
                             fg=ACCENT if iv > 0 else FG_MUTED)
            setter(iv)
            _draw_slider(canvas_w)

        slider.bind("<Button-1>", _on_slider_click)
        slider.bind("<B1-Motion>", _on_slider_click)
        slider.after(10, _draw_slider)

    def _update_polling(self):
        self.service.update_polling_interval(self._poll_var.get())

    def _sign_out(self):
        self.service.sign_out()
        self._close()

    def _close(self):
        if self.window:
            try:
                self.window.destroy()
            except tk.TclError:
                pass
            self.window = None

    def _refresh(self):
        """Refresh settings window to reflect changes."""
        pos = None
        if self.window:
            try:
                pos = (self.window.winfo_x(), self.window.winfo_y())
            except tk.TclError:
                pass
        self._close()
        self.show()
        if pos and self.window:
            try:
                self.window.geometry(f"+{pos[0]}+{pos[1]}")
            except tk.TclError:
                pass

    def _toggle_startup(self):
        self._set_startup(self._startup_var.get())

    @staticmethod
    def _is_startup_enabled() -> bool:
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_READ)
            try:
                winreg.QueryValueEx(key, "ClaudeUsageBar")
                return True
            except FileNotFoundError:
                return False
            finally:
                winreg.CloseKey(key)
        except Exception:
            return False

    @staticmethod
    def _set_startup(enabled: bool):
        try:
            import winreg, sys
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_SET_VALUE)
            if enabled:
                exe = sys.executable
                script = sys.argv[0] if sys.argv else ""
                cmd = f'"{exe}" "{script}"' if script else f'"{exe}"'
                winreg.SetValueEx(key, "ClaudeUsageBar", 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(key, "ClaudeUsageBar")
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except Exception:
            pass
