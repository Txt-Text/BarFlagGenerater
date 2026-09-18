# barflag/deps.py
"""依赖检测与自动安装（带进度上报）。

设计要点：
* tkinter 是标准库，PyPI 上没有真正的同名包，所以它**没法**自动安装——
  只能检测并给出明确指引。其余依赖都走同一个 ensure_package()。
* pip 的输出被解析成"进度事件"，通过 Reporter 送给前端：
  命令行丢掉即可，GUI 会拿去更新状态栏的百分比。
* pip 在 Windows 上是控制台程序，用 CREATE_NO_WINDOW 启动，避免弹黑框。
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import re
import subprocess
import sys

from . import report

#: Windows: 不弹控制台窗口
CREATE_NO_WINDOW = 0x08000000


def is_frozen():
    """是不是打包后的 exe（此时不能再用 pip 装东西）。"""
    return bool(getattr(sys, "frozen", False))

#: 依赖清单：(import 名, pip 名, 用途)
PILLOW = ("PIL", "pillow", "生成 PNG/JPG 需要")
SV_TTK = ("sv_ttk", "sv-ttk", "界面主题需要")
TKINTERDND2 = ("tkinterdnd2", "tkinterdnd2", "拖拽载入预设需要")


# ============================ pip 输出解析 ============================

#: 进度条片段里的 "816.6/816.6 kB"
_PROGRESS_RE = re.compile(r"([\d.]+)\s*/\s*([\d.]+)\s*([kKmMgG]?[bB])")


def parse_pip_line(line):
    """把 pip 的一行输出解析成事件（纯函数，便于单测）。

    返回下列之一，或 None（这行没有价值）：
        ("progress", (已完成, 总量))   下载进度条
        ("log", 文字)                  值得展示给用户的里程碑
    """
    s = (line or "").strip()
    if not s:
        return None

    # 进度条：形如 "|██████| 816.6/816.6 kB 17.4 kB/s"
    if "/" in s:
        m = _PROGRESS_RE.search(s)
        if m:
            try:
                done, total = float(m.group(1)), float(m.group(2))
            except ValueError:
                return None
            if total > 0:
                return ("progress", (done, total))

    low = s.lower()
    # 纯符号行（分割线、纯进度条残渣）不展示
    if not any(ch.isalnum() for ch in s):
        return None

    if low.startswith("collecting "):
        return ("log", f"正在解析依赖: {s.split(None, 1)[1]}")
    if low.startswith("downloading "):
        return ("log", f"正在下载: {s.split(None, 1)[1]}")
    if low.startswith("using cached "):
        return ("log", f"使用本地缓存: {s.split(None, 2)[-1]}")
    if low.startswith("installing collected packages"):
        return ("log", "正在安装到当前 Python 环境…")
    if low.startswith("successfully installed"):
        return ("log", f"安装完成: {s.split(None, 2)[-1]}")
    if low.startswith("error") or "error:" in low:
        return ("log", s)
    return None


def _iter_pip_lines(stream):
    """pip 的进度条用 \\r 原地刷新，所以要同时按 \\r 和 \\n 切行。"""
    buf = []
    while True:
        ch = stream.read(1)
        if not ch:
            break
        if ch in "\r\n":
            line = "".join(buf)
            buf = []
            if line.strip():
                yield line
        else:
            buf.append(ch)
    if buf:
        line = "".join(buf)
        if line.strip():
            yield line


# ============================ 检测 ============================


def is_installed(import_name):
    """包能不能 import 到。"""
    if import_name in sys.modules:
        return True
    try:
        return importlib.util.find_spec(import_name) is not None
    except (ImportError, ValueError, AttributeError):
        return False


def pip_available():
    """当前解释器有没有可用的 pip（Store 版 Python 常常没有）。"""
    kwargs = {"creationflags": CREATE_NO_WINDOW} if os.name == "nt" else {}
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
        return proc.returncode == 0
    except Exception:
        return False


def manual_hint(pip_name):
    return f"可手动安装: {sys.executable} -m pip install {pip_name}"


# ============================ 安装 ============================


def _pip_install(pip_name, reporter, extra_args=(), base=8.0, span=87.0):
    """跑一次 pip install。返回是否成功（不含 import 复检）。"""
    cmd = [sys.executable, "-m", "pip", "install",
           "--disable-pip-version-check", "--progress-bar", "on",
           *extra_args, pip_name]
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = CREATE_NO_WINDOW
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1, **kwargs)
    except Exception as e:
        reporter.error(f"无法启动 pip: {e}")
        return False

    detail = f"正在安装 {pip_name}…"
    reporter.status(report.BUSY, detail, base)
    try:
        for line in _iter_pip_lines(proc.stdout):
            event = parse_pip_line(line)
            if event is None:
                continue
            kind, payload = event
            if kind == "progress":
                done, total = payload
                reporter.status(report.BUSY, detail,
                                base + span * min(1.0, done / total))
            else:
                reporter.info(payload)
    except Exception as e:
        reporter.warn(f"读取 pip 输出时出错: {e}")
    finally:
        try:
            if proc.stdout:
                proc.stdout.close()
        except Exception:
            pass
        code = proc.wait()
    return code == 0


def ensure_package(import_name, pip_name, reporter, reason=""):
    """确保某个包可用，缺了就自动装。返回 True / False。

    先默认方式装，不行再退到 --user（与旧版 ensure_pillow 的策略一致）。
    """
    if is_installed(import_name):
        return True

    why = f"（{reason}）" if reason else ""

    # 打包后的程序里 sys.executable 就是 exe 自己，
    # `exe -m pip install ...` 根本跑不起来，所以直接给明确提示。
    if is_frozen():
        reporter.error(f"当前是打包版本，缺少组件 {pip_name}{why}，无法自动安装。")
        reporter.error("请改用源码版本运行，或重新下载完整的发布包。")
        return False

    reporter.info(f"检测到缺少 {pip_name}{why}，正在自动安装…")

    if not pip_available():
        reporter.error(f"当前 Python 环境没有可用的 pip，无法自动安装 {pip_name}。")
        reporter.error(manual_hint(pip_name))
        return False

    attempts = ((), ("--user",))
    for i, extra in enumerate(attempts):
        if _pip_install(pip_name, reporter, extra_args=extra):
            importlib.invalidate_caches()
            if is_installed(import_name):
                reporter.ok(f"{pip_name} 安装成功。")
                return True
        if i + 1 < len(attempts):
            reporter.warn(f"{pip_name} 这次没装上，改用 --user 再试一次…")

    reporter.error(f"{pip_name} 自动安装失败。{manual_hint(pip_name)}")
    return False


def ensure_pillow(reporter):
    """位图渲染需要的 Pillow。"""
    import_name, pip_name, reason = PILLOW
    return ensure_package(import_name, pip_name, reporter, reason)
