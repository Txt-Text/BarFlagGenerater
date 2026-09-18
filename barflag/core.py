# barflag/core.py
"""逻辑层核心：解析、计算、配置与生成编排。

分层约定（务必遵守）：
    core / render / presets / deps  —— 逻辑层。
        不许 import tkinter 或 argparse，不许 print / input / 读 sys.stdin。
        所有对外表达都走 report.Reporter。
    cli / gui                       —— 前端。
        只负责收集输入、展示输出；业务规则一律调用逻辑层。

这条约定是硬边界：core 里根本拿不到 tkinter，想破坏分层都做不到。
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field

from . import report
from .deps import ensure_pillow
from .render import gen_raster, gen_svg

# ============================ 常量 ============================

PRESET_EXT = ".flagpreset"      # 预设文件扩展名
PRESET_DIR = "presets"          # 预设子目录（会自动创建）
DEFAULT_FORMAT = "png"          # 默认输出格式
FORMATS = ("svg", "png", "jpg")  # 界面/命令行暴露的格式

#: barflag/ 包的所在目录
PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))


def is_frozen():
    """是不是 PyInstaller 之类的打包版本。"""
    return bool(getattr(sys, "frozen", False))


def detect_app_dir(frozen=None, executable=None):
    """决定"程序自己的目录"——预设就放这儿。

    源码运行 = 项目根目录（barflag/ 的上一级）。
    打包之后 = exe 所在目录。

    打包后绝不能用 __file__ 推导：onefile 模式下它在 _MEIxxxx 临时目录里，
    程序一退出整个目录就被删掉，预设会"保存成功但下次启动全没了"，
    而且不报任何错。
    """
    if frozen is None:
        frozen = is_frozen()
    if frozen:
        exe = sys.executable if executable is None else executable
        return os.path.dirname(os.path.abspath(exe))
    return os.path.dirname(PACKAGE_DIR)


#: 程序根目录。预设扫描以它为基准，这样双击启动（工作目录可能是桌面或
#: System32）和打包成 exe 之后都能找到自己的 presets/。
APP_DIR = detect_app_dir()

# ============================ 分辨率 ============================


def parse_resolution(text):
    """
    解析分辨率字符串，返回 (宽, 高)。
    接受: '900x600' / '900X600' / '900 x 600' / '900 × 600'
    非法则抛 ValueError。
    """
    m = re.match(r'^\s*(\d+)\s*[xX×]\s*(\d+)\s*$', text)
    if not m:
        raise ValueError(f"分辨率格式不对: {text!r}（应形如 900x600）")
    w, h = int(m.group(1)), int(m.group(2))
    if w <= 0 or h <= 0:
        raise ValueError("分辨率必须为正数")
    return w, h


# ============================ 色带 ============================

# 合法颜色：3/4/6/8 位十六进制，或字母颜色名（red、blue 等）
_HEX_LENS = (3, 4, 6, 8)
_HEX_RE = re.compile(
    r'^(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{4}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$'
)

#: 颜色（可带 # 的十六进制，或字母颜色名）+ 可选比例
_STRIP_RE = re.compile(
    r'^(?P<color>#?(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{4}'
    r'|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})|[A-Za-z]+)'
    r'(?:\s*[:：\s]\s*(?P<weight>\d+(?:\.\d+)?))?$'
)


def is_valid_hex(hexpart):
    """长度是 3/4/6/8 且全是十六进制字符"""
    return len(hexpart) in _HEX_LENS and bool(_HEX_RE.match(hexpart))


def normalize_color(text):
    """把用户输入的颜色规范化成可用的 Tk/渲染颜色。

    接受 '#FF0000' / 'FF0000' / 'red'，返回 '#FF0000' 或 'red'。
    非法则抛 ValueError。这是界面实时取色用的入口。
    """
    s = (text or "").strip()
    if not s:
        raise ValueError("颜色不能为空")
    if s.startswith('#'):
        body = s[1:]
        if not is_valid_hex(body):
            raise ValueError(f"颜色不是合法的 3/4/6/8 位十六进制: {s!r}")
        return '#' + body
    # 先判十六进制再判颜色名："FFFFFF" 全是字母但其实是颜色值
    if is_valid_hex(s):
        return '#' + s
    if s.isalpha():
        return s
    raise ValueError(f"颜色不是合法的 3/4/6/8 位十六进制或颜色名: {s!r}")


def parse_strips(text):
    """
    解析色带列表，返回 [(color, weight), ...]。
    接受: '#FF0000 1.0, #FFFFFF 1.5' / 'FF0000 1,FFFFFF' / 逗号或换行分隔。
    颜色可带/不带 #，自动补 #；比例可省略，默认 1.0。
    """
    strips = []
    # 先按逗号或换行切分
    for item in re.split(r'[,\n]', text):
        item = item.strip()
        if not item:
            continue
        # 比例必须用空格/冒号与颜色分隔；没有分隔符时整串只能是颜色
        m = _STRIP_RE.match(item)
        if not m:
            raise ValueError(
                f"无法解析这条色带: {item!r}"
                f"（颜色应为 3/4/6/8 位十六进制或颜色名）"
            )
        color = m.group('color')
        weight_str = m.group('weight')
        # 十六进制没带 # 就补上。
        # 注意顺序：必须先判十六进制再判颜色名——"FFFFFF" 既是字母串
        # 又是合法十六进制，按颜色名处理就错了（旧版在这里把 FFFFFF 当成了颜色名）。
        if color.startswith('#'):
            if not is_valid_hex(color[1:]):
                raise ValueError(
                    f"颜色不是合法的 3/4/6/8 位十六进制: {item!r}"
                )
        elif is_valid_hex(color):
            color = '#' + color
        elif not color.isalpha():
            raise ValueError(
                f"颜色不是合法的 3/4/6/8 位十六进制或颜色名: {item!r}"
            )
        # 纯字母且不是十六进制 → 当作颜色名（red、blue 等），保持原样
        weight = float(weight_str) if weight_str else 1.0
        if weight <= 0:
            raise ValueError(f"比例必须为正数: {item!r}")
        strips.append((color, weight))
    if not strips:
        raise ValueError("至少要有一条颜色")
    return strips


def resolve_heights(strips, total_height):
    """
    按比例把总高分配给每条色带，返回浮点高度列表。
    末条用"总高 - 前面之和"补齐，消除浮点累积误差。
    """
    weights = [w for _, w in strips]
    total = sum(weights)
    heights = [total_height * w / total for w in weights]
    heights[-1] = total_height - sum(heights[:-1])
    return heights


# ============================ 输出路径 ============================


def normalize_format(fmt):
    """把格式字符串规范成 svg / png / jpg；不认识则返回空串。"""
    f = (fmt or "").strip().lower().lstrip(".")
    if f in ("jpg", "jpeg"):
        return "jpg"
    if f in ("svg", "png"):
        return f
    return ""


def finalize_output(path, fmt):
    """补扩展名 / 按扩展名反推格式。返回 (path, fmt)。"""
    root, ext = os.path.splitext(path)
    if not ext:
        return f"{path}.{fmt}", fmt
    real = normalize_format(ext)
    if real:
        return path, real
    return path, fmt


def unique_path(path):
    """
    若 path 已存在，返回 path(1).ext、path(2).ext … 直到不冲突。
    path 无扩展名时按整体加括号序号。
    """
    if not os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    i = 1
    while True:
        candidate = f"{root}({i}){ext}"
        if not os.path.exists(candidate):
            return candidate
        i += 1


def safe_filename(name):
    """清洗成可当文件名用的名字。"""
    cleaned = re.sub(r'[\\/:*?"<>|]', '_', (name or "").strip()).strip()
    return cleaned or "未命名"


# ============================ 配置 ============================


@dataclass
class FlagConfig:
    """一次生成的完整输入。逻辑层与前端之间传递的就是它。"""

    width: int
    height: int
    strips: list = field(default_factory=list)   # [(color, weight), ...]
    fmt: str = DEFAULT_FORMAT                    # svg / png / jpg
    output: str = ""                             # 输出路径

    def total_weight(self):
        return sum(w for _, w in self.strips)

    def percentages(self):
        total = self.total_weight()
        if total <= 0:
            return [0.0 for _ in self.strips]
        return [w / total * 100 for _, w in self.strips]

    def heights(self):
        return resolve_heights(self.strips, self.height)

    def summary_lines(self):
        """概览文字。命令行和 GUI 日志共用，保证两边说法一致。"""
        total = self.total_weight()
        lines = [f"共 {len(self.strips)} 条色带，比例总和 = {total:g}"]
        lines.append("各条占比: " + " / ".join(f"{p:.2f}%" for p in self.percentages()))
        return lines


# ============================ 生成 ============================


def write_output(cfg, reporter):
    """把配置渲染成文件。返回 True / False。

    位图路径需要 Pillow，缺失时会尝试自动安装。
    """
    heights = cfg.heights()
    if cfg.fmt == "svg":
        gen_svg(cfg.width, cfg.height, cfg.strips, heights, cfg.output)
        return True
    if cfg.fmt in ("png", "jpg", "jpeg"):
        if not ensure_pillow(reporter):
            reporter.error("缺少 Pillow，无法生成位图；可改用 svg，或先手动安装")
            return False
        gen_raster(cfg.width, cfg.height, cfg.strips, heights,
                   cfg.output, fmt=cfg.fmt)
        return True
    reporter.error(f"不支持的格式: {cfg.fmt!r}")
    return False


def generate(cfg, reporter, overwrite=False):
    """端到端生成：决定最终文件名 → 渲染 → 汇报。

    命名冲突策略由 overwrite 决定：True 直接覆盖，False 自动改名。
    （"询问用户"属于前端交互，不在这里做。）

    返回实际写出的路径，失败返回 None。
    """
    if not cfg.output:
        cfg.output = f"flag.{cfg.fmt}"
    out, fmt = finalize_output(cfg.output, normalize_format(cfg.fmt) or DEFAULT_FORMAT)
    cfg.output, cfg.fmt = out, fmt

    if os.path.exists(out):
        if overwrite:
            reporter.warn(f"文件已存在，按设置覆盖: {out}")
        else:
            renamed = unique_path(out)
            reporter.warn(f"文件已存在，自动改名: {out} → {renamed}")
            cfg.output = renamed

    for line in cfg.summary_lines():
        reporter.info(line)

    reporter.status(report.BUSY, f"正在写入 {os.path.basename(cfg.output)}…")
    try:
        if not write_output(cfg, reporter):
            return None
    except Exception as e:
        reporter.error(f"生成失败: {e}")
        return None
    reporter.ok(f"已生成: {cfg.output}")
    return cfg.output
