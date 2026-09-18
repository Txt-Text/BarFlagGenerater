# barflag/gui.py
"""图形前端：tkinter + sv-ttk。

界面上的一切都只是"收集输入 / 展示输出"：
业务规则来自 core / presets / deps，日志与状态来自 report.Reporter。

线程约定：
    主线程只跑 Tk。生成、pip 安装都丢到后台线程，通过 GuiReporter
    把事件塞进队列，主线程 after() 轮询取出后再动界面——
    tkinter 不允许从非主线程操作控件。
"""

from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from tkinter import colorchooser, filedialog, font as tkfont, simpledialog, ttk

from . import core, deps, presets, report

APP_TITLE = "条形旗帜生成器"

# ============================ 配色 ============================

#: 深色 / 浅色两套给"非 ttk 控件"（Text、Canvas）用的颜色。
#: sv-ttk 只管 ttk 控件，裸 tk 控件必须自己跟着主题换色。
PALETTE = {
    True: {   # 深色
        "surface": "#1c1c1c",
        "text": "#e8e8e8",
        "border": "#3a3a3a",
        "log": {"error": "#ff99a4", "warn": "#e8c07d", "ok": "#6ccb5f", "info": "#d8d8d8"},
    },
    False: {  # 浅色
        "surface": "#fafafa",
        "text": "#1a1a1a",
        "border": "#c8c8c8",
        "log": {"error": "#c42b1c", "warn": "#9a6700", "ok": "#0f7b0f", "info": "#3a3a3a"},
    },
}

DEFAULT_W = 900
DEFAULT_H = 600


def enable_hidpi():
    """让 Windows 高分屏用真实 DPI 渲染，否则整个界面是发虚的。

    必须在创建 Tk() 之前调用。
    """
    if os.name != "nt":
        return
    try:
        import ctypes
    except Exception:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def tune_scaling(root):
    """把 Tk 的缩放对齐到真实 DPI，让字号跟着系统走。"""
    try:
        dpi = root.winfo_fpixels("1i")
        if dpi and dpi > 0:
            root.tk.call("tk", "scaling", dpi / 72.0)
    except Exception:
        pass
    try:
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                tkfont.nametofont(name).configure(size=10)
            except Exception:
                pass
    except Exception:
        pass


# ============================ 上报实现 ============================


class GuiReporter(report.Reporter):
    """把逻辑层的话塞进队列，由主线程取出后再动界面。"""

    def __init__(self):
        self.queue = queue.Queue()

    def log(self, level, message):
        self.queue.put(("log", level, message, None))

    def status(self, state, detail=None, percent=None):
        self.queue.put(("status", state, detail, percent))

    def call(self, fn):
        """请求主线程执行 fn（用于安装完成后套主题、开拖拽）。"""
        self.queue.put(("call", fn, None, None))


# ============================ 主题 ============================


class Theme:
    """sv-ttk 的薄包装。没装 sv-ttk 时全部退化成系统原生 ttk。"""

    def __init__(self):
        self.sv_ttk = None
        self.dark = True

    def load(self):
        """尝试导入 sv_ttk。返回是否可用。"""
        if self.sv_ttk is not None:
            return True
        try:
            import sv_ttk
        except Exception:
            return False
        self.sv_ttk = sv_ttk
        return True

    @property
    def accent_button(self):
        return "Accent.TButton" if self.sv_ttk else "TButton"

    @property
    def switch_style(self):
        return "Switch.TCheckbutton" if self.sv_ttk else "TCheckbutton"

    def apply(self, dark):
        self.dark = bool(dark)
        if self.sv_ttk:
            self.sv_ttk.set_theme("dark" if self.dark else "light")

    def palette(self):
        if not self.sv_ttk:
            # 没有主题包时 ttk 一定是系统浅色，自绘控件必须跟着走，
            # 否则会出现"日志区是黑的、其他都是白的"这种割裂感。
            return PALETTE[False]
        return PALETTE[self.dark]


# ============================ 色条行 ============================


class StripRow:
    """一条色条的可编辑行：色块 + 十六进制 + 比例 + 上移/下移/删除。"""

    def __init__(self, app, color="#FFFFFF", weight=1.0):
        self.app = app
        self.var_color = tk.StringVar(value=color)
        self.var_weight = tk.StringVar(value=_fmt_weight(weight))

        self.frame = ttk.Frame(app.strips_inner)
        self.frame.pack(fill="x", pady=2)
        self.frame.columnconfigure(1, weight=1)

        self.swatch = tk.Canvas(self.frame, width=24, height=24,
                                highlightthickness=1, cursor="hand2")
        self.swatch.grid(row=0, column=0, padx=(0, 8))
        self.swatch.bind("<Button-1>", self._pick_color)

        self.entry_color = ttk.Entry(self.frame, textvariable=self.var_color, width=10)
        self.entry_color.grid(row=0, column=1, sticky="ew")

        ttk.Label(self.frame, text="比例").grid(row=0, column=2, padx=(10, 4))
        self.entry_weight = ttk.Entry(self.frame, textvariable=self.var_weight, width=6)
        self.entry_weight.grid(row=0, column=3)

        self.btn_up = ttk.Button(self.frame, text="▲", width=3,
                                 command=lambda: app.move_row(self, -1))
        self.btn_up.grid(row=0, column=4, padx=(10, 0))
        self.btn_down = ttk.Button(self.frame, text="▼", width=3,
                                   command=lambda: app.move_row(self, +1))
        self.btn_down.grid(row=0, column=5, padx=(4, 0))
        self.btn_del = ttk.Button(self.frame, text="✕", width=3,
                                  command=lambda: app.remove_row(self))
        self.btn_del.grid(row=0, column=6, padx=(4, 0))

        self.var_color.trace_add("write", lambda *_: self._refresh_swatch())
        self._refresh_swatch()

    # ---- 取值 ----

    def get(self):
        """返回 (color, weight)。非法时抛 ValueError。"""
        color = core.normalize_color(self.var_color.get())
        raw = self.var_weight.get().strip()
        if not raw:
            weight = 1.0
        else:
            try:
                weight = float(raw)
            except ValueError:
                raise ValueError(f"比例必须是数字，收到 {raw!r}")
        if weight <= 0:
            raise ValueError("比例必须为正数")
        return color, weight

    def set_color(self, color):
        self.var_color.set(color)

    # ---- 界面 ----

    def _pick_color(self, _event=None):
        try:
            current = core.normalize_color(self.var_color.get())
        except ValueError:
            current = "#FFFFFF"
        rgb, _hex = colorchooser.askcolor(color=current, parent=self.app.root,
                                          title="选择颜色")
        if rgb:
            self.var_color.set(_to_hex(rgb))

    def _refresh_swatch(self):
        pal = self.app.theme.palette()
        try:
            fill = core.normalize_color(self.var_color.get())
            border = pal["border"]
        except ValueError:
            fill = pal["surface"]
            border = "#c42b1c"        # 非法颜色用红框提示
        self.swatch.configure(background=pal["surface"],
                              highlightbackground=border)
        self.swatch.delete("all")
        self.swatch.create_rectangle(1, 1, 23, 23, fill=fill, outline="")

    def destroy(self):
        self.frame.destroy()


def _fmt_weight(weight):
    try:
        f = float(weight)
    except (TypeError, ValueError):
        return "1"
    return str(int(f)) if f.is_integer() else f"{f:g}"


def _to_hex(rgb):
    return "#%02X%02X%02X" % tuple(int(v) for v in rgb)


# ============================ 主窗口 ============================


class App:
    def __init__(self, root, auto_install=True):
        self.root = root
        self.auto_install = auto_install
        self.theme = Theme()
        self.reporter = GuiReporter()

        self.busy = False
        self.rows = []
        self.preset_paths = []
        self.dnd_ready = False
        self._preview_job = None
        self._drain_job = None
        self._deps_started = False
        self._closed = False
        #: 正在跑的后台任务数。只有归零时才把状态栏切回"空闲"，
        #: 否则"生成"和"装依赖"同时跑时，先结束的那个会误报空闲。
        self._jobs = 0

        # 表单变量
        self.var_w = tk.StringVar(value=str(DEFAULT_W))
        self.var_h = tk.StringVar(value=str(DEFAULT_H))
        self.var_fmt = tk.StringVar(value=core.DEFAULT_FORMAT)
        self.var_out = tk.StringVar(value=f"flag.{core.DEFAULT_FORMAT}")
        self.var_overwrite = tk.BooleanVar(value=False)
        self.var_preset = tk.StringVar(value="")
        self.var_preset_name = tk.StringVar(value="未命名")
        self.var_dark = tk.BooleanVar(value=True)
        self.var_status = tk.StringVar(value="状态：空闲")
        self.var_preview_info = tk.StringVar(value="")
        self.var_dnd_hint = tk.StringVar(value="")
        self.var_log_toggle = tk.StringVar(value="收起 ▾")

        self._build()
        self._bind_traces()
        self._startup()
        self._drain_job = self.root.after(60, self._drain)

    # ============================ 构建界面 ============================

    def _build(self):
        self.root.title(APP_TITLE)
        self.root.minsize(960, 720)
        self.root.geometry("1100x880")

        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)

        # 从下往上 pack：状态栏 → 日志区 → 主体
        self._build_status(outer)
        self._build_log(outer)

        body = ttk.Frame(outer)
        body.pack(side="top", fill="both", expand=True, pady=(0, 8))
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)
        self._build_form(body)
        self._build_preview(body)

        self._apply_widget_colors()

    # ---- 底部状态栏 ----

    def _build_status(self, outer):
        ttk.Separator(outer, orient="horizontal").pack(side="bottom", fill="x")
        bar = ttk.Frame(outer)
        bar.pack(side="bottom", fill="x", pady=(6, 0))

        self.lbl_status = ttk.Label(bar, textvariable=self.var_status)
        self.lbl_status.pack(side="left")

        self.progress = ttk.Progressbar(bar, mode="determinate", length=180, maximum=100)

    # ---- 可收起的日志区 ----

    def _build_log(self, outer):
        self.log_frame = ttk.Frame(outer)
        self.log_frame.pack(side="bottom", fill="x", pady=(8, 0))

        head = ttk.Frame(self.log_frame)
        head.pack(fill="x")
        ttk.Label(head, text="日志").pack(side="left")

        self.btn_log_toggle = ttk.Button(head, textvariable=self.var_log_toggle,
                                         width=9, command=self.toggle_log)
        self.btn_log_toggle.pack(side="right")
        ttk.Button(head, text="清空", width=7,
                   command=self.clear_log).pack(side="right", padx=(0, 6))

        self.log_body = ttk.Frame(self.log_frame)
        self.log_body.pack(fill="x", pady=(6, 0))

        self.log_text = tk.Text(self.log_body, height=7, wrap="none",
                                relief="flat", highlightthickness=0,
                                font=("Consolas", 9), state="disabled")
        self.log_text.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(self.log_body, orient="vertical",
                           command=self.log_text.yview)
        sb.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=sb.set)

    def toggle_log(self):
        """日志区展开 / 收起。"""
        if self.log_body.winfo_ismapped():
            self.log_body.pack_forget()
            self.var_log_toggle.set("展开 ▴")
        else:
            self.log_body.pack(fill="x", pady=(6, 0))
            self.var_log_toggle.set("收起 ▾")
            self.log_text.see("end")

    # ---- 左侧表单 ----

    def _build_form(self, parent):
        left = ttk.Frame(parent)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)

        # 基本设置
        box = ttk.LabelFrame(left, text="旗帜设置", padding=10)
        box.grid(row=0, column=0, sticky="ew")
        box.columnconfigure(1, weight=1)

        ttk.Label(box, text="分辨率").grid(row=0, column=0, sticky="w", pady=3)
        res = ttk.Frame(box)
        res.grid(row=0, column=1, sticky="w", padx=(10, 0), pady=3)
        ttk.Entry(res, textvariable=self.var_w, width=7).pack(side="left")
        ttk.Label(res, text="×").pack(side="left", padx=6)
        ttk.Entry(res, textvariable=self.var_h, width=7).pack(side="left")
        ttk.Label(res, text="像素").pack(side="left", padx=(10, 0))

        ttk.Label(box, text="输出格式").grid(row=1, column=0, sticky="w", pady=3)
        self.cmb_fmt = ttk.Combobox(box, textvariable=self.var_fmt,
                                    values=list(core.FORMATS),
                                    state="readonly", width=10)
        self.cmb_fmt.grid(row=1, column=1, sticky="w", padx=(10, 0), pady=3)

        ttk.Label(box, text="输出文件").grid(row=2, column=0, sticky="w", pady=3)
        out_row = ttk.Frame(box)
        out_row.grid(row=2, column=1, sticky="ew", padx=(10, 0), pady=3)
        out_row.columnconfigure(0, weight=1)
        ttk.Entry(out_row, textvariable=self.var_out).grid(row=0, column=0, sticky="ew")
        ttk.Button(out_row, text="浏览…", width=8,
                   command=self.browse_output).grid(row=0, column=1, padx=(6, 0))

        ttk.Checkbutton(box, text="覆盖同名文件（不勾选则自动改名）",
                        variable=self.var_overwrite
                        ).grid(row=3, column=1, sticky="w", padx=(10, 0), pady=(8, 0))

        self.chk_dark = ttk.Checkbutton(box, text="深色主题",
                                        variable=self.var_dark,
                                        command=self.toggle_theme)
        self.chk_dark.grid(row=4, column=1, sticky="w", padx=(10, 0), pady=(10, 0))

        # 色条
        sbox = ttk.LabelFrame(left, text="色条（点色块换颜色）", padding=10)
        sbox.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        sbox.columnconfigure(0, weight=1)
        sbox.rowconfigure(0, weight=1)

        holder = ttk.Frame(sbox)
        holder.grid(row=0, column=0, sticky="nsew")
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)

        self.strips_canvas = tk.Canvas(holder, highlightthickness=0, height=180)
        self.strips_canvas.grid(row=0, column=0, sticky="nsew")
        vsb = ttk.Scrollbar(holder, orient="vertical",
                            command=self.strips_canvas.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        self.strips_canvas.configure(yscrollcommand=vsb.set)

        self.strips_inner = ttk.Frame(self.strips_canvas)
        self._inner_id = self.strips_canvas.create_window(
            (0, 0), window=self.strips_inner, anchor="nw")
        self.strips_inner.bind(
            "<Configure>",
            lambda e: self.strips_canvas.configure(
                scrollregion=self.strips_canvas.bbox("all")))
        self.strips_canvas.bind(
            "<Configure>",
            lambda e: self.strips_canvas.itemconfigure(self._inner_id, width=e.width))

        bottom = ttk.Frame(sbox)
        bottom.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(bottom, text="＋ 添加色条",
                   command=lambda: self.add_row()).pack(side="left")
        ttk.Label(bottom, textvariable=self.var_dnd_hint
                  ).pack(side="left", padx=(10, 0))

        # 预设
        pbox = ttk.LabelFrame(left, text="预设", padding=10)
        pbox.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        pbox.columnconfigure(0, weight=1)

        self.cmb_preset = ttk.Combobox(pbox, textvariable=self.var_preset,
                                       state="readonly")
        self.cmb_preset.grid(row=0, column=0, sticky="ew")
        ttk.Button(pbox, text="载入", width=7,
                   command=self.load_selected_preset).grid(row=0, column=1, padx=(6, 0))
        ttk.Button(pbox, text="刷新", width=7,
                   command=self.refresh_presets).grid(row=0, column=2, padx=(6, 0))

        save_row = ttk.Frame(pbox)
        save_row.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        save_row.columnconfigure(0, weight=1)
        ttk.Label(save_row, text="预设名").grid(row=0, column=0, sticky="w")
        ttk.Entry(save_row, textvariable=self.var_preset_name
                  ).grid(row=0, column=1, sticky="ew", padx=(6, 6))
        save_row.columnconfigure(1, weight=1)
        ttk.Button(save_row, text="保存为预设", width=12,
                   command=self.save_current_preset).grid(row=0, column=2)

        # 生成
        self.btn_generate = ttk.Button(left, text="生 成", command=self.on_generate)
        self.btn_generate.grid(row=3, column=0, sticky="ew", pady=(12, 0), ipady=6)

    # ---- 右侧预览 ----

    def _build_preview(self, parent):
        right = ttk.Frame(parent)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)

        box = ttk.LabelFrame(right, text="预览", padding=10)
        box.grid(row=0, column=0, sticky="nsew")
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)

        self.preview = tk.Canvas(box, highlightthickness=0)
        self.preview.grid(row=0, column=0, sticky="nsew")
        ttk.Label(box, textvariable=self.var_preview_info,
                  anchor="center").grid(row=1, column=0, sticky="ew", pady=(8, 0))

        self.preview.bind("<Configure>", lambda e: self.schedule_preview())

    # ============================ 主题与配色 ============================

    def toggle_theme(self):
        """深色 / 浅色切换。没装 sv-ttk 时只有自绘控件跟着变。"""
        self.theme.apply(self.var_dark.get())
        self._apply_widget_colors()
        self._apply_styles()
        if not self.theme.sv_ttk:
            self.reporter.warn("未安装 sv-ttk，主题切换只影响自绘控件。")

    def _apply_widget_colors(self):
        pal = self.theme.palette()
        self.root.configure(background=pal["surface"])

        self.log_text.configure(background=pal["surface"], foreground=pal["text"],
                                insertbackground=pal["text"])
        for level, color in pal["log"].items():
            self.log_text.tag_configure(level, foreground=color)

        self.preview.configure(background=pal["surface"])
        self.strips_canvas.configure(background=pal["surface"])

        for row in self.rows:
            row._refresh_swatch()
        self.schedule_preview()

    def _apply_styles(self):
        """sv-ttk 到了之后再套它的专用样式（强调按钮、开关式复选框）。"""
        try:
            self.btn_generate.configure(style=self.theme.accent_button)
        except Exception:
            pass
        try:
            self.chk_dark.configure(style=self.theme.switch_style)
        except Exception:
            pass
        # 没装 sv-ttk 时深色开关没有意义，禁用掉避免误导
        try:
            self.chk_dark.state(["!disabled"] if self.theme.sv_ttk else ["disabled"])
        except Exception:
            pass

    # ============================ 事件绑定 ============================

    def _bind_traces(self):
        for var in (self.var_w, self.var_h):
            var.trace_add("write", lambda *_: self.schedule_preview())
        self.var_fmt.trace_add("write", lambda *_: self.on_format_change())
        self.var_out.trace_add("write", lambda *_: self.schedule_preview())

    def on_format_change(self):
        """格式变了，顺手把输出名扩展名对齐。"""
        fmt = core.normalize_format(self.var_fmt.get()) or core.DEFAULT_FORMAT
        out = self.var_out.get().strip()
        if out:
            root, ext = os.path.splitext(out)
            if core.normalize_format(ext) and core.normalize_format(ext) != fmt:
                self.var_out.set(f"{root}.{fmt}")
        self.schedule_preview()

    # ============================ 色条行管理 ============================

    def add_row(self, color="#FFFFFF", weight=1.0):
        row = StripRow(self, color, weight)
        self.rows.append(row)
        self._bind_wheel(row.frame)
        self.strips_canvas.configure(scrollregion=self.strips_canvas.bbox("all"))
        self.schedule_preview()
        return row

    def remove_row(self, row):
        if row not in self.rows:
            return
        self.rows.remove(row)
        row.destroy()
        self.strips_canvas.configure(scrollregion=self.strips_canvas.bbox("all"))
        self.schedule_preview()

    def move_row(self, row, delta):
        if row not in self.rows:
            return
        i = self.rows.index(row)
        j = i + delta
        if not (0 <= j < len(self.rows)):
            return
        self.rows[i], self.rows[j] = self.rows[j], self.rows[i]
        self._relayout_rows()
        self.schedule_preview()

    def _relayout_rows(self):
        for row in self.rows:
            row.frame.pack_forget()
        for row in self.rows:
            row.frame.pack(fill="x", pady=2)

    def _set_rows(self, pairs):
        for row in self.rows:
            row.destroy()
        self.rows = []
        for color, weight in pairs:
            self.add_row(color, weight)
        if not self.rows:
            self.add_row("#FFFFFF", 1.0)

    def _bind_wheel(self, widget):
        widget.bind("<MouseWheel>", self._on_wheel, add="+")
        for child in widget.winfo_children():
            self._bind_wheel(child)

    def _on_wheel(self, event):
        self.strips_canvas.yview_scroll(int(-event.delta / 120), "units")

    # ============================ 预览 ============================

    def schedule_preview(self):
        """输入变了就重画预览，稍作防抖，避免每敲一个字符重画一次。"""
        if self._closed:
            return
        if self._preview_job is not None:
            try:
                self.root.after_cancel(self._preview_job)
            except Exception:
                pass
        self._preview_job = self.root.after(120, self.refresh_preview)

    def refresh_preview(self):
        self._preview_job = None
        c = self.preview
        c.delete("all")
        pal = self.theme.palette()

        try:
            width = int(self.var_w.get().strip())
            height = int(self.var_h.get().strip())
            if width <= 0 or height <= 0:
                raise ValueError
        except ValueError:
            self.var_preview_info.set("分辨率无效")
            return

        strips = []
        for row in self.rows:
            try:
                strips.append(row.get())
            except ValueError:
                continue
        if not strips:
            self.var_preview_info.set("至少需要一条色条")
            return

        cw = max(c.winfo_width(), 1)
        ch = max(c.winfo_height(), 1)
        if cw < 20 or ch < 20:
            return

        pad = 14
        avail_w = max(cw - pad * 2, 10)
        avail_h = max(ch - pad * 2, 10)
        scale = min(avail_w / width, avail_h / height)
        dw, dh = width * scale, height * scale
        x0 = (cw - dw) / 2
        y0 = (ch - dh) / 2

        total = sum(w for _, w in strips)
        y = y0
        for i, (color, w) in enumerate(strips):
            h = dh * w / total if i < len(strips) - 1 else (y0 + dh) - y
            c.create_rectangle(x0, y, x0 + dw, y + h, fill=color, outline="")
            y += h
        c.create_rectangle(x0, y0, x0 + dw, y0 + dh, outline=pal["border"])

        self.var_preview_info.set(
            f"{width} × {height} · {len(strips)} 条色条 · 比例和 {total:g}")

    # ============================ 预设 ============================

    def refresh_presets(self, announce=True):
        self.preset_paths = presets.scan_presets()
        names = [os.path.basename(p) for p in self.preset_paths]
        self.cmb_preset.configure(values=names)
        if names:
            if self.var_preset.get() not in names:
                self.var_preset.set(names[0])
        else:
            self.var_preset.set("")
        if announce:
            where = f"{core.APP_DIR} 与 {core.PRESET_DIR}/"
            if names:
                self.reporter.info(f"已扫描 {where}，发现 {len(names)} 个预设文件。")
            else:
                self.reporter.info(f"已扫描 {where}，未发现预设文件。")

    def load_selected_preset(self):
        name = self.var_preset.get()
        path = next((p for p in self.preset_paths
                     if os.path.basename(p) == name), None)
        if not path:
            self.reporter.warn("请先在下拉框里选择一个预设。")
            return
        self.apply_preset(path)

    def apply_preset(self, path):
        """载入预设 → 替换当前填写的设置。不生成图片。"""
        try:
            data = presets.load_preset(path, self.reporter)
        except Exception as e:
            self.reporter.error(f"载入预设失败: {e}")
            return

        if data["width"] and data["height"]:
            self.var_w.set(str(data["width"]))
            self.var_h.set(str(data["height"]))
        self._set_rows(data["strips"])

        name = data["name"] or "未命名"
        self.var_preset_name.set(name)
        fmt = core.normalize_format(self.var_fmt.get()) or core.DEFAULT_FORMAT
        self.var_out.set(f"{core.safe_filename(name)}.{fmt}")

        # 让下拉框也跟上（拖进来的文件可能不在列表里）
        base = os.path.basename(path)
        if base in list(self.cmb_preset.cget("values")):
            self.var_preset.set(base)

        self.refresh_preview()
        self.reporter.ok(f"已载入预设：{base}。")

    def save_current_preset(self):
        try:
            cfg = self.collect_config()
        except ValueError as e:
            self.reporter.error(str(e))
            return
        name = simpledialog.askstring(
            "保存预设", "预设名称：", initialvalue=self.var_preset_name.get(),
            parent=self.root)
        if name is None:
            return
        name = name.strip() or "未命名"
        try:
            path = presets.preset_path_for(name, self.reporter)
            presets.save_preset(path, name, cfg.width, cfg.height, cfg.strips)
        except Exception as e:
            self.reporter.error(f"保存预设失败: {e}")
            return
        self.var_preset_name.set(name)
        self.reporter.ok(f"预设已保存: {path}")
        self.refresh_presets(announce=False)
        self.var_preset.set(os.path.basename(path))

    # ============================ 拖拽 ============================

    def enable_dnd(self):
        """给窗口注入 tkinterdnd2 的拖拽支持。"""
        if self.dnd_ready:
            return True
        try:
            from tkinterdnd2 import DND_FILES, TkinterDnD
        except Exception:
            return False
        try:
            # require() 把 tkdnd 载入 Tcl 解释器；
            # 而 drop_target_register 等方法是在 import tkinterdnd2 时
            # 挂到 tkinter.BaseWidget 上的。
            TkinterDnD.require(self.root)
            count = 0
            for widget in self._drop_targets(self.root):
                try:
                    widget.drop_target_register(DND_FILES)
                    widget.dnd_bind("<<Drop>>", self.on_drop)
                    count += 1
                except Exception:
                    continue
            if not count:
                raise RuntimeError("没有任何控件能被注册为放置目标")
            self.dnd_ready = True
        except Exception as e:
            self.reporter.warn(f"开启拖拽支持失败: {e}")
            return False
        self.var_dnd_hint.set("· 可直接把 .flagpreset 拖进窗口载入")
        return True

    def _drop_targets(self, widget):
        """递归收集可以作为放置目标的控件。

        注意 tkinter.Tk 本身不是 BaseWidget，拿不到 tkinterdnd2 注入的方法，
        所以必须从它的子控件开始注册。全部注册一遍，才能做到"窗口里随处可放"。
        """
        for child in widget.winfo_children():
            if isinstance(child, tk.Widget) and hasattr(child, "drop_target_register"):
                yield child
                yield from self._drop_targets(child)

    def on_drop(self, event):
        try:
            paths = list(self.root.tk.splitlist(event.data))
        except Exception:
            paths = [event.data]
        hits = [p for p in paths if str(p).lower().endswith(core.PRESET_EXT)]
        if not hits:
            self.reporter.warn("拖入的不是预设文件（需要 .flagpreset 扩展名）。")
            return
        self.apply_preset(hits[0])
        if len(hits) > 1:
            self.reporter.info(f"一次拖入了 {len(hits)} 个预设，已载入第一个。")

    # ============================ 依赖引导 ============================

    def _startup(self):
        # 主题：装了就直接用，没装就后台装
        if self.theme.load():
            self.theme.apply(self.var_dark.get())
            self._apply_widget_colors()
            self._apply_styles()
            self.reporter.info("已启用 Sun Valley 主题（sv-ttk）。")
        else:
            self.reporter.warn("未安装 sv-ttk，暂时使用系统原生主题。")

        self._apply_styles()
        self.refresh_presets(announce=True)
        self._set_rows([("#FF0000", 1.0), ("#FFFFFF", 1.0), ("#0000FF", 1.0)])
        self.refresh_preview()

        if self.enable_dnd():
            self.reporter.info("已启用拖拽载入预设。")
        elif not self.auto_install:
            self.reporter.warn("拖拽载入预设不可用（tkinterdnd2 未安装或 tkdnd 加载失败）。")

        if self.auto_install:
            self._bootstrap_deps()

    def _bootstrap_deps(self):
        """后台按顺序补齐可选依赖（一次只跑一个 pip，避免互相打架）。"""
        if self._deps_started:
            return
        self._deps_started = True

        needed = []
        if not self.theme.load():
            needed.append((deps.SV_TTK, self._on_theme_ready))
        if not self.dnd_ready:
            needed.append((deps.TKINTERDND2, self._on_dnd_ready))
        if not needed:
            return

        def work():
            self._jobs += 1
            try:
                for (import_name, pip_name, why), on_done in needed:
                    if deps.ensure_package(import_name, pip_name, self.reporter,
                                           reason=why):
                        self.reporter.call(on_done)
            finally:
                self._jobs -= 1
                if self._jobs <= 0:
                    self.reporter.status(report.IDLE)

        threading.Thread(target=work, daemon=True).start()

    def _on_theme_ready(self):
        if self.theme.load():
            self.theme.apply(self.var_dark.get())
            self._apply_widget_colors()
            self._apply_styles()
            self.reporter.ok("Sun Valley 主题已启用。")

    def _on_dnd_ready(self):
        if self.enable_dnd():
            self.reporter.ok("拖拽载入预设已启用（把 .flagpreset 拖进窗口即可）。")

    # ============================ 生成 ============================

    def collect_config(self):
        """把界面上的东西读成 FlagConfig。非法输入抛 ValueError。"""
        wtext = self.var_w.get().strip()
        htext = self.var_h.get().strip()
        if not wtext.isdigit() or not htext.isdigit():
            raise ValueError("分辨率必须是正整数，例如 900 × 600")
        width, height = int(wtext), int(htext)
        if width <= 0 or height <= 0:
            raise ValueError("分辨率必须为正数")

        strips = []
        for i, row in enumerate(self.rows, 1):
            try:
                strips.append(row.get())
            except ValueError as e:
                raise ValueError(f"第 {i} 条色条：{e}")
        if not strips:
            raise ValueError("至少需要一条色条")

        fmt = core.normalize_format(self.var_fmt.get()) or core.DEFAULT_FORMAT
        out = self.var_out.get().strip() or f"flag.{fmt}"
        return core.FlagConfig(width=width, height=height, strips=strips,
                               fmt=fmt, output=out)

    def on_generate(self):
        if self.busy:
            return
        try:
            cfg = self.collect_config()
        except ValueError as e:
            self.reporter.error(str(e))
            return
        overwrite = bool(self.var_overwrite.get())

        def work():
            core.generate(cfg, self.reporter, overwrite=overwrite)

        self._run_busy("正在生成…", work)

    def _run_busy(self, detail, fn):
        self._set_busy(True, detail, None)
        self._jobs += 1

        def runner():
            try:
                fn()
            except Exception as e:
                self.reporter.error(f"{type(e).__name__}: {e}")
            finally:
                self._jobs -= 1
                if self._jobs <= 0:
                    self.reporter.status(report.IDLE)

        threading.Thread(target=runner, daemon=True).start()

    def browse_output(self):
        fmt = core.normalize_format(self.var_fmt.get()) or core.DEFAULT_FORMAT
        initial = os.path.basename(self.var_out.get()) or f"flag.{fmt}"
        path = filedialog.asksaveasfilename(
            parent=self.root, title="选择输出文件",
            defaultextension=f".{fmt}",
            initialfile=initial,
            filetypes=[("PNG 图片", "*.png"), ("JPEG 图片", "*.jpg"),
                       ("SVG 矢量图", "*.svg"), ("所有文件", "*.*")])
        if path:
            self.var_out.set(path)
            real = core.normalize_format(os.path.splitext(path)[1])
            if real:
                self.var_fmt.set(real)

    # ============================ 队列 / 状态 ============================

    def _drain(self):
        """主线程轮询：把后台线程塞进队列的事件搬到界面上。"""
        if self._closed:
            return
        try:
            while True:
                kind, a, b, c = self.reporter.queue.get_nowait()
                if kind == "log":
                    self._append_log(a, b)
                elif kind == "status":
                    self._apply_status(a, b, c)
                elif kind == "call":
                    try:
                        a()
                    except Exception as e:
                        self._append_log(report.ERROR, f"{type(e).__name__}: {e}")
        except queue.Empty:
            pass
        self._drain_job = self.root.after(60, self._drain)

    def _append_log(self, level, message):
        text = f"{report.PREFIX.get(level, '[*]')} {message}\n"
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text, level)
        self.log_text.configure(state="disabled")
        self.log_text.see("end")
        # 出错时如果日志是收起的，自动展开，免得用户看不见
        if level == report.ERROR and not self.log_body.winfo_ismapped():
            self.toggle_log()

    def clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _apply_status(self, state, detail, percent):
        if state == report.BUSY:
            self._set_busy(True, detail, percent)
        else:
            self._set_busy(False)

    def _set_busy(self, busy, detail=None, percent=None):
        """状态栏与进度条：忙碌时禁用生成按钮。"""
        self.busy = busy
        try:
            self.progress.stop()
        except Exception:
            pass

        if busy:
            self.btn_generate.state(["disabled"])
            text = f"状态：忙碌 | {detail or '处理中…'}"
            if percent is None:
                self.progress.configure(mode="indeterminate")
                self.progress.pack(side="right", padx=(10, 0))
                self.progress.start(55)
            else:
                pct = max(0.0, min(100.0, float(percent)))
                self.progress.configure(mode="determinate", value=pct)
                self.progress.pack(side="right", padx=(10, 0))
                text += f" {pct:.0f}%"
            self.var_status.set(text)
        else:
            self.progress.pack_forget()
            self.btn_generate.state(["!disabled"])
            self.var_status.set("状态：空闲")

    # ============================ 收尾 ============================

    def close(self):
        """关窗。必须先取消挂着的 after 任务，否则 Tk 会在销毁后
        仍去调用它们，往 stderr 吐 'invalid command name'。"""
        self._closed = True
        for job in (self._drain_job, self._preview_job):
            if job is not None:
                try:
                    self.root.after_cancel(job)
                except Exception:
                    pass
        self._drain_job = self._preview_job = None
        try:
            self.root.destroy()
        except Exception:
            pass


# ============================ 入口 ============================


def main(auto_install=True):
    """启动图形界面。返回进程退出码。"""
    enable_hidpi()

    root = tk.Tk()
    root.withdraw()          # 先把界面搭好再显示，避免白屏闪烁
    tune_scaling(root)
    app = App(root, auto_install=auto_install)
    app._apply_styles()
    root.protocol("WM_DELETE_WINDOW", app.close)

    root.update_idletasks()
    _center(root)
    root.deiconify()
    root.mainloop()
    return 0


def _center(root):
    try:
        w = root.winfo_width() or 1100
        h = root.winfo_height() or 880
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        x = max((sw - w) // 2, 0)
        y = max((sh - h) // 3, 0)
        root.geometry(f"{w}x{h}+{x}+{y}")
    except Exception:
        pass
