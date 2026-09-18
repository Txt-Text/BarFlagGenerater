# barflag/report.py
"""日志与状态上报层。

逻辑层（core / render / presets / deps）只通过 Reporter 说话：
不 print、不 input、不 import tkinter。这样同一套业务逻辑可以同时
喂给命令行和图形界面——命令行就是本文件里的 ConsoleReporter。

日志级别沿用旧版约定：
    [-]  失败  红色
    <!>  警告  黄色
    [+]  成功  绿色
    [*]  普通  白色
"""

from __future__ import annotations

import os
import sys

# ============================ 日志级别 ============================

ERROR = "error"
WARN = "warn"
OK = "ok"
INFO = "info"

#: 级别 → 命令行前缀，与旧版输出保持一致
PREFIX = {
    ERROR: "[-]",
    WARN: "<!>",
    OK: "[+]",
    INFO: "[*]",
}

# ============================ 状态栏状态 ============================

IDLE = "idle"   #: 空闲
BUSY = "busy"   #: 忙碌


class Reporter:
    """逻辑层唯一的对外出口，前端各自实现。

    只需要实现 log() 和 status() 两个方法。
    """

    def log(self, level, message):
        """输出一行日志。level 取 ERROR / WARN / OK / INFO。"""

    def status(self, state, detail=None, percent=None):
        """更新状态栏。

        state   : IDLE 或 BUSY
        detail  : BUSY 时的描述文字，例如 "正在安装 sv-ttk…"
        percent : 0~100 的确定进度；None 表示进度未知（转圈）
        """

    def call(self, fn):
        """请求前端在主线程里执行 fn。

        命令行是单线程，直接执行即可；GUI 需要把它排队回主线程。
        """

    # ---- 便捷方法 ----
    def error(self, message):
        self.log(ERROR, message)

    def warn(self, message):
        self.log(WARN, message)

    def ok(self, message):
        self.log(OK, message)

    def info(self, message):
        self.log(INFO, message)


class NullReporter(Reporter):
    """什么都不做。给单元测试和"我不关心输出"的调用方用。"""


# ============================ 命令行实现 ============================

_RESET = "\033[0m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_GREEN = "\033[32m"
_WHITE = "\033[37m"
_GRAY = "\033[90m"

_COLOR_OF = {
    ERROR: _RED,
    WARN: _YELLOW,
    OK: _GREEN,
    INFO: _WHITE,
}


def gray(text):
    """把文字包成灰色（给横幅用）。"""
    return f"{_GRAY}{text}{_RESET}"


def enable_ansi():
    """让 Windows 终端也能显示 ANSI 颜色。

    优先用 colorama（如果装了），否则用 os.system("") 的兼容做法。
    失败也不影响运行，只是没颜色。
    """
    try:
        import colorama
        colorama.just_fix_windows_console()
        return
    except Exception:
        pass
    if os.name == "nt":
        try:
            os.system("")
        except Exception:
            pass


def _safe_stream(stream):
    """pythonw / 无控制台时 sys.stdout 是 None，退回 devnull，避免 print 崩掉。"""
    if stream is not None:
        return stream
    try:
        return open(os.devnull, "w", encoding="utf-8")
    except Exception:
        return None


class ConsoleReporter(Reporter):
    """命令行前端：print 到标准输出，行为与旧版日志完全一致。"""

    def __init__(self, stream=None, show_progress=False):
        self.stream = _safe_stream(stream if stream is not None else sys.stdout)
        self.show_progress = show_progress
        #: 记录上一次打印的百分比，避免进度刷屏
        self._last_percent = None

    def log(self, level, message):
        color = _COLOR_OF.get(level, _WHITE)
        prefix = PREFIX.get(level, "[*]")
        print(f"{color}{prefix} {message}{_RESET}", file=self.stream)

    def status(self, state, detail=None, percent=None):
        if not self.show_progress:
            return
        if state != BUSY:
            if self._last_percent is not None:
                self._last_percent = None
            return
        if percent is None:
            return
        if self._last_percent is not None and percent - self._last_percent < 10:
            return
        self._last_percent = percent
        text = f"{detail or '处理中…'} {percent:.0f}%"
        print(f"{_GRAY}[*] {text}{_RESET}", file=self.stream)

    def call(self, fn):
        # 命令行是单线程，直接执行
        fn()
