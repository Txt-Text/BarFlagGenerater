# barflag/presets.py
"""预设文件的扫描、解析与保存。

路径基准是 core.APP_DIR（程序根目录），不是当前工作目录——
否则双击启动时工作目录可能是桌面，一个预设都扫不到。
"""

from __future__ import annotations

import os
import re

from . import core, report

#: 纯字母开头的 token（颜色名，如 red）
_FIRST_ALPHA = re.compile(r'^[A-Za-z]+$')


def preset_dirs():
    """预设搜索目录：程序根目录 + 根目录下的 presets/。"""
    return (core.APP_DIR, os.path.join(core.APP_DIR, core.PRESET_DIR))


def ensure_preset_dir(reporter=None):
    """确保 presets/ 目录存在（保存预设时用）"""
    d = os.path.join(core.APP_DIR, core.PRESET_DIR)
    if not os.path.isdir(d):
        try:
            os.makedirs(d, exist_ok=True)
        except Exception as e:
            (reporter or report.NullReporter()).warn(
                f"无法创建 {core.PRESET_DIR}/ 目录: {e}")
    return d


def scan_presets():
    """
    扫描程序根目录与 presets/ 目录，返回预设文件绝对路径列表（去重、排序）。
    只挑 .flagpreset 扩展名的文件。
    """
    found = []
    for d in preset_dirs():
        if not os.path.isdir(d):
            continue
        try:
            for name in os.listdir(d):
                if name.lower().endswith(core.PRESET_EXT):
                    found.append(os.path.abspath(os.path.join(d, name)))
        except Exception:
            pass
    # 去重 + 排序，保证编号稳定
    return sorted(set(found))


def resolve_preset_arg(arg, presets):
    """
    把 --preset 的值解析成路径。
    先当路径；不存在再当编号（1-based）；再试按文件名匹配。
    """
    if os.path.isfile(arg):
        return os.path.abspath(arg)
    if arg.isdigit():
        idx = int(arg)
        if 1 <= idx <= len(presets):
            return presets[idx - 1]
        raise ValueError(f"预设编号超出范围: {arg}（共 {len(presets)} 个）")
    base = os.path.basename(arg).lower()
    for p in presets:
        if os.path.basename(p).lower() == base:
            return p
    raise ValueError(f"找不到预设文件: {arg!r}")


def _first_token(text):
    """取到第一个空白/冒号为止的片段。"""
    return re.split(r'[\s:：]', text, maxsplit=1)[0]


def _looks_like_strip(s):
    """
    粗略判断一行是不是色条（用于区分"色条行"和"真注释"）。
    - 以 # 开头：看 # 后到第一个空白/冒号为止的 token 是不是合法十六进制
    - 不以 # 开头：看第一个 token 是不是纯字母（颜色名）
    """
    s = s.strip()
    if not s:
        return False
    if s.startswith('#'):
        return core.is_valid_hex(_first_token(s[1:]))
    return bool(_FIRST_ALPHA.match(_first_token(s)))


def load_preset(path, reporter=None):
    """
    读取预设文件，返回 dict:
      {name, width, height, strips}

    strips 是 [(color, weight), ...]
    非法行会警告并跳过；完全没有色条则抛 ValueError。
    """
    reporter = reporter or report.NullReporter()
    preset = {
        'name': os.path.splitext(os.path.basename(path))[0],
        'width': None,
        'height': None,
        'strips': [],
    }
    in_strips = False
    with open(path, 'r', encoding='utf-8') as f:
        for lineno, rawline in enumerate(f, 1):
            line = rawline.rstrip('\n')
            stripped = line.strip()
            # 空行直接跳过
            if not stripped:
                continue
            # 色条段开始（只在还没进入时判断一次）
            if not in_strips and stripped.lower().startswith('strips'):
                in_strips = True
                continue
            # 色条段内：优先当色条解析；只有"看起来像注释"才跳过
            if in_strips:
                if stripped.startswith('#') and not _looks_like_strip(stripped):
                    continue
                try:
                    one = core.parse_strips(stripped)
                    preset['strips'].extend(one)
                except ValueError:
                    reporter.warn(
                        f"{os.path.basename(path)} 第 {lineno} 行跳过: {stripped!r}")
                continue
            # 非色条段：以 # 开头当注释跳过
            if stripped.startswith('#'):
                continue
            # 键值行
            if '=' not in line:
                reporter.warn(
                    f"{os.path.basename(path)} 第 {lineno} 行跳过: {stripped!r}")
                continue
            key, val = line.split('=', 1)
            key = key.strip().lower()
            if key == 'name':
                preset['name'] = val.strip()
            elif key == 'resolution':
                try:
                    w, h = core.parse_resolution(val.split('#')[0].strip())
                    preset['width'], preset['height'] = w, h
                except ValueError as e:
                    reporter.warn(f"预设分辨率非法，已忽略: {e}")
            elif key == 'width':
                try:
                    preset['width'] = int(val.split('#')[0].strip())
                except ValueError:
                    pass
            elif key == 'height':
                try:
                    preset['height'] = int(val.split('#')[0].strip())
                except ValueError:
                    pass
    if not preset['strips']:
        raise ValueError(f"{os.path.basename(path)} 里没有可用色条")
    return preset


def save_preset(path, name, width, height, strips):
    """写出预设文件（UTF-8，人读友好）"""
    lines = [
        "# 旗帜预设（可被文本编辑器编辑）",
        f"name = {name}",
        f"resolution = {width}x{height}",
        "",
        "# 色条：颜色 比例（比例可省略，默认 1.0）",
        "strips:",
    ]
    for color, w in strips:
        w_str = str(int(w)) if float(w).is_integer() else f"{w:g}"
        lines.append(f"    {color} {w_str}")
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


def preset_path_for(name, reporter=None):
    """按预设名算出保存路径（自动建 presets/ 目录）。"""
    d = ensure_preset_dir(reporter)
    return os.path.join(d, f"{core.safe_filename(name)}{core.PRESET_EXT}")
