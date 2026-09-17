# BarFlagGenerater.py
# 依赖: pip install pillow  (仅 PNG/JPG 需要，缺失时会自动尝试安装)
#
# 用法:
#   交互模式:  python BarFlagGenerater.py
#   命令行模式: python BarFlagGenerater.py -r 900x600 -s "#FF0000 1,#FFFFFF 1.5" -f svg -o flag.svg
#
# 日志约定：
#   [-]  失败  红色
#   <!>  警告  黄色
#   [+]  成功  绿色
#   [*]  普通  白色
#
# 在 Windows 上如果颜色没生效，程序会自动尝试开启 ANSI 支持；
# 若仍不行可手动: pip install colorama

import argparse
import importlib
import os
import re
import subprocess
import sys

# ============================ 常量 ============================

PRESET_EXT = ".flagpreset"      # 预设文件扩展名
PRESET_DIR = "presets"          # 预设子目录（会自动创建）
DEFAULT_FORMAT = "png"          # 非交互时的默认格式

# ============================ 彩色日志 ============================

_RESET  = "\033[0m"
_RED    = "\033[31m"
_YELLOW = "\033[33m"
_GREEN  = "\033[32m"
_WHITE  = "\033[37m"
_GRAY       = "\033[90m"          # 亮黑，通常显示为浅灰
_RESET      = "\033[0m"

def _enable_ansi():
    """
    让 Windows 终端也能显示 ANSI 颜色。
    优先用 colorama（如果装了），否则用 os.system("") 的兼容黑科技。
    失败也不影响程序运行，只是没颜色。
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

_enable_ansi()

def _log(prefix, color, msg):
    """统一日志出口；整行着色"""
    print(f"{color}{prefix} {msg}{_RESET}")

def log_error(msg):
    """失败 —— 红色 [-]"""
    _log("[-]", _RED, msg)

def log_warn(msg):
    """警告 —— 黄色 <!>"""
    _log("<!>", _YELLOW, msg)

def log_ok(msg):
    """成功 —— 绿色 [+]"""
    _log("[+]", _GREEN, msg)

def log_info(msg):
    """普通信息 —— 白色 [*]"""
    _log("[*]", _WHITE, msg)

# ============================ 基础解析 ============================

def parse_resolution(text):
    """
    解析分辨率字符串，返回 (宽, 高)。
    接受: '900x600' / '900X600' / '900 x 600' / '900 × 600'（交互模式宽松）
    非法则抛 ValueError。
    """
    m = re.match(r'^\s*(\d+)\s*[xX×]\s*(\d+)\s*$', text)
    if not m:
        raise ValueError(f"分辨率格式不对: {text!r}（应形如 900x600）")
    w, h = int(m.group(1)), int(m.group(2))
    if w <= 0 or h <= 0:
        raise ValueError("分辨率必须为正数")
    return w, h

# 合法颜色：3/4/6/8 位十六进制，或字母颜色名（red、blue 等）
_HEX_LENS = (3, 4, 6, 8)
_HEX_RE = re.compile(
    r'^(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{4}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$'
)

def _is_valid_hex(hexpart):
    """长度是 3/4/6/8 且全是十六进制字符"""
    return len(hexpart) in _HEX_LENS and bool(_HEX_RE.match(hexpart))

def parse_strips(text):
    """
    解析色带列表，返回 [(color, weight), ...]。
    接受: '#FF0000 1.0, #FFFFFF 1.5' / 'FF0000 1,FFFFFF' / 逗号或换行分隔。
    颜色可带/不带 #，自动补 #。
    比例可省略，默认 1.0。
    颜色必须为合法的 3/4/6/8 位十六进制，或字母颜色名。
    """
    strips = []
    # 先按逗号或换行切分
    for item in re.split(r'[,\n]', text):
        item = item.strip()
        if not item:
            continue
        # 颜色（3/4/6/8 位十六进制 或 字母颜色名）+ 可选数字（空格/冒号分隔）
        m = re.match(
            r'^(#?(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{4}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})'
            r'|[A-Za-z]+)\s*[:：\s]?\s*(\d+(?:\.\d+)?)?$',
            item)
        if not m:
            raise ValueError(
                f"无法解析这条色带: {item!r}"
                f"（颜色应为 3/4/6/8 位十六进制或颜色名）"
            )
        color = m.group(1)
        # 十六进制没带 # 就补上；纯字母（如 red）保持原样
        if not color.startswith('#') and not color.isalpha():
            color = '#' + color
        # 二次校验：防 5/7 位等非法长度漏进来
        if color.startswith('#'):
            hexpart = color[1:]
            if not _is_valid_hex(hexpart):
                raise ValueError(
                    f"颜色不是合法的 3/4/6/8 位十六进制: {item!r}"
                )
        weight = float(m.group(2)) if m.group(2) else 1.0
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

# ============================ 依赖检测 ============================

def ensure_pillow():
    """
    确保 Pillow 可用；缺就自动 pip 安装。
    返回 True 表示可用，False 表示装不上。
    """
    try:
        import PIL  # noqa: F401
        return True
    except ModuleNotFoundError:
        pass

    log_warn("检测到缺少 Pillow，正在自动安装…")
    # 用 sys.executable 保证装到当前运行的 Python，避免多版本装串
    base = [sys.executable, "-m", "pip", "install", "pillow"]
    for cmd in (base, base + ["--user"]):
        try:
            subprocess.check_call(cmd)
            importlib.invalidate_caches()
            import PIL  # noqa: F401
            log_ok("Pillow 安装成功")
            return True
        except Exception as e:
            log_error(f"这种方式安装失败：{e}")
    log_error("自动安装失败，请手动运行：python -m pip install pillow")
    return False

# ============================ 预设读写 ============================

def _ensure_preset_dir():
    """确保 presets/ 目录存在（保存预设时用）"""
    if not os.path.isdir(PRESET_DIR):
        try:
            os.makedirs(PRESET_DIR, exist_ok=True)
        except Exception as e:
            log_warn(f"无法创建 {PRESET_DIR}/ 目录: {e}")

def scan_presets():
    """
    扫描本目录与 presets/ 目录，返回预设文件路径列表（去重、排序）。
    只挑 .flagpreset 扩展名的文件。
    """
    found = []
    for d in (".", PRESET_DIR):
        if not os.path.isdir(d):
            continue
        try:
            for name in os.listdir(d):
                if name.lower().endswith(PRESET_EXT):
                    found.append(os.path.join(d, name))
        except Exception:
            pass
    # 去重 + 排序，保证编号稳定
    return sorted(set(found))

def list_presets(show_header=True):
    """
    列出预设，返回列表。show_header 控制是否打印"已扫描…"那行。
    """
    presets = scan_presets()
    if show_header:
        if presets:
            log_info(f"已扫描本目录与 {PRESET_DIR}/ 目录，发现 {len(presets)} 个预设文件：")
            for i, p in enumerate(presets, 1):
                print(f"    {i}：{os.path.basename(p)}")
        else:
            log_info(f"已扫描本目录与 {PRESET_DIR}/ 目录，未发现预设文件。")
    return presets

def load_preset(path):
    """
    读取预设文件，返回 dict:
      {name, width, height, strips}
    strips 是 [(color, weight), ...]
    非法行会警告并跳过；完全没有色带则抛 ValueError。
    """
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
            # 空行 / 整行注释
            if not stripped or stripped.startswith('#'):
                continue
            # 色带段开始
            if stripped.lower().startswith('strips'):
                in_strips = True
                continue
            # 色带行
            if in_strips:
                try:
                    one = parse_strips(stripped)
                    preset['strips'].extend(one)
                except ValueError:
                    log_warn(f"{os.path.basename(path)} 第 {lineno} 行跳过: {stripped!r}")
                continue
            # 键值行
            if '=' not in line:
                log_warn(f"{os.path.basename(path)} 第 {lineno} 行跳过: {stripped!r}")
                continue
            key, val = line.split('=', 1)
            key = key.strip().lower()
            # name 保留原样；其他去掉行内注释（# 之后）
            if key == 'name':
                preset['name'] = val.strip()
            elif key == 'resolution':
                try:
                    w, h = parse_resolution(val.split('#')[0].strip())
                    preset['width'], preset['height'] = w, h
                except ValueError as e:
                    log_warn(f"预设分辨率非法，已忽略: {e}")
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
        raise ValueError(f"{os.path.basename(path)} 中无可用色带")
    return preset

def save_preset(path, name, width, height, strips):
    """写预设文件（UTF-8，人类可读）"""
    lines = [
        "# 旗帜预设",
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

# ============================ 图片生成 ============================

def gen_svg(width, height, strips, heights, path):
    """生成 SVG（纯文本拼接）"""
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
    ]
    y = 0.0
    for (color, _), h in zip(strips, heights):
        parts.append(
            f'<rect x="0" y="{y:.4f}" width="{width}" '
            f'height="{h:.4f}" fill="{color}"/>'
        )
        y += h
    parts.append('</svg>')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(parts))

def gen_raster(width, height, strips, heights, path, fmt=None):
    """用 Pillow 生成位图（PNG/JPG），fmt 显式指定格式避免扩展名缺失报错"""
    from PIL import Image, ImageDraw
    img = Image.new('RGB', (width, height))
    d = ImageDraw.Draw(img)
    y = 0.0
    for (color, _), h in zip(strips, heights):
        d.rectangle([0, round(y), width, round(y + h)], fill=color)
        y += h
    save_kwargs = {}
    if fmt:
        save_kwargs["format"] = "JPEG" if fmt in ("jpg", "jpeg") else fmt.upper()
    img.save(path, **save_kwargs)

# ============================ 交互辅助 ============================

def ask_yes(prompt, auto_yes=False):
    """询问 Y/N。auto_yes=True 时（-y 模式）一律返回 True"""
    if auto_yes:
        print(f"{prompt} [Y/N]: Y  (自动)")
        return True
    ans = input(f"{prompt} [Y/N]: ").strip().lower()
    return ans in ('y', 'yes', '是')

def ask(prompt, validator, on_fail=None, on_success=None,
        default=None, auto_yes=False, retries=None):
    """
    循环提示输入，直到成功。统一用"提示行 + \\n> "两行风格。

    参数:
      prompt     : 提示文字
      validator  : 成功条件。接收原始字符串，返回
                     - bool                        → ok，value 取原字符串
                     - (ok: bool, value_or_reason) → ok + 值 / 失败原因
                   抛异常视作失败。
      on_fail    : 失败时调用，接收异常或失败原因。
                   返回 True 继续重试，False 放弃。
                   默认: 打印 log_error(原因) 并继续。
      on_success : 成功时调用，接收 value。
                   返回 True 接受，False 视作不满意、重来。
                   默认: 直接接受。
      default    : 空输入时的默认值。返回时走同一套 validator。
      auto_yes   : -y 模式。有 default 直接用；无 default 直接放弃。
      retries    : 最大重试次数，None 表示无限。

    返回 (ok, value)。ok=False 表示用户放弃或重试超限。
    """
    attempt = 0

    while True:
        # -y 模式：不提示，有默认直接吃默认
        if auto_yes:
            if default is None:
                print(f"{prompt}  (自动放弃，无默认值)")
                return False, None
            raw = default
            print(f"{prompt}: {raw}  (自动)")
        else:
            raw = input(f"{prompt}\n> ").strip()
            if not raw and default is not None:
                raw = default

        # ---- 校验 ----
        try:
            res = validator(raw)
            if isinstance(res, tuple):
                ok, value = res
            else:
                ok, value = bool(res), raw
            if ok:
                # 成功回调
                if on_success is None or on_success(value):
                    return True, value
                # on_success 返回 False → 不满意，重来
            else:
                # 失败原因走 on_fail
                if on_fail is None:
                    log_error(str(value))
                elif not on_fail(value):
                    return False, None
        except Exception as e:
            if on_fail is None:
                log_error(str(e))
            elif not on_fail(e):
                return False, None

        attempt += 1
        if retries is not None and attempt >= retries:
            log_error(f"重试超过 {retries} 次，放弃。")
            return False, None

# ============================ 主流程 ============================

def build_parser():
    """构造 argparse 解析器"""
    p = argparse.ArgumentParser(
        prog="BarFlagGenerater.py",
        description="横条旗帜生成器（交互 / 命令行双模式）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  全交互:  python BarFlagGenerater.py\n"
            "  命令行:  python BarFlagGenerater.py -r 900x600 "
            "-s \"#FF0000 1,#FFFFFF 1.5\" -f svg -o flag.svg\n"
            "  用预设:  python BarFlagGenerater.py -p 2 -o out.png\n"
            "  看预设:  python BarFlagGenerater.py --list-presets\n"
            "\n提示: Windows CMD 下 -s 里的 # 和空格建议用双引号包起来；\n"
            "      PowerShell 可能需写成 -s '#FF0000 1,#FFFFFF 1.5'"
        ),
    )
    p.add_argument('-p', '--preset', metavar='PATH',
                   help='加载预设（支持编号或路径）')
    p.add_argument('-r', '--resolution', metavar='WxH',
                   help='分辨率，如 900x600')
    p.add_argument('-s', '--strips', metavar='LIST',
                   help='色带列表，如 "#FF0000 1.0,#FFFFFF 1.5"')
    p.add_argument('-f', '--format', dest='fmt', metavar='FMT',
                   choices=['svg', 'png', 'jpg', 'jpeg'],
                   help='输出格式: svg / png / jpg')
    p.add_argument('-o', '--output', metavar='FILE',
                   help='输出文件名')
    p.add_argument('--save-preset', nargs='?', const=True, default=None,
                   metavar='NAME', help='生成后保存为预设（可给名称）')
    p.add_argument('--list-presets', action='store_true',
                   help='只列出可用预设并退出')
    p.add_argument('-y', '--yes', action='store_true',
                   help='所有询问自动回答 yes')
    p.add_argument('-w', '--overwrite', action='store_true',
                   help='同名文件直接覆盖（默认：交互询问 / 非交互自动改名）')
    return p

def resolve_preset_arg(arg, presets):
    """
    把 --preset 的值解析成路径。
    先当路径；不存在再当编号（1-based）在 presets 列表里找。
    """
    if os.path.isfile(arg):
        return arg
    if arg.isdigit():
        idx = int(arg)
        if 1 <= idx <= len(presets):
            return presets[idx - 1]
        raise ValueError(f"预设编号超出范围: {arg}（共 {len(presets)} 个）")
    raise ValueError(f"找不到预设文件: {arg!r}")

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

def main():
    print(f"{_GRAY}", end = "")
    print(f"================================================================================")
    print(f"")
    print(f"横条旗帜生成器 v1.0")
    print(f"")
    print(f"此工具可以生成以纯色横条构成的旗帜。如部分国旗、Pride旗等。")
    print(f"本工具支持自定义分辨率、色彩颜色、色带宽度比例、图片类型等，并允许保存与加载预设。")
    print(f"by Txt-Text")
    print(f"")
    print(f"================================================================================")
    print(f"{_RESET}", end = "")
    print(f"")
    log_info("本工具的非 SVG 图片相关功能需要本机安装 pillow 包。若缺失，本工具将在需要时自动安装。\n\n")

    parser = build_parser()
    args = parser.parse_args()

    auto_yes = args.yes

    # ---- 0. --list-presets: 列完就退出 ----
    if args.list_presets:
        list_presets(show_header=True)
        return

    # ---- 1. 扫描预设（一次，供后续使用） ----
    presets = scan_presets()

    # ---- 2. 确定数据来源：预设 / 命令行 / 交互 ----
    preset_data = None   # 加载的预设 dict

    # 2a. 命令行明确给了 --preset
    if args.preset:
        try:
            path = resolve_preset_arg(args.preset, presets)
            preset_data = load_preset(path)
            log_ok(f"已加载预设：{os.path.basename(path)}")
        except Exception as e:
            log_error(f"加载预设失败: {e}")
            return
    # 2b. 没给 --preset，且非 -y 模式 → 交互询问
    elif not auto_yes:
        # 无论有无预设，都先输出扫描结果
        if presets:
            log_info(f"已扫描本目录与 {PRESET_DIR}/ 目录，发现 {len(presets)} 个预设文件：")
            for i, p in enumerate(presets, 1):
                print(f"    {i}：{os.path.basename(p)}")
        else:
            log_info(f"已扫描本目录与 {PRESET_DIR}/ 目录，未发现预设文件。")

        # 只有存在预设时才让用户选；一次输入解决"编号 / 路径 / 跳过"
        if presets:
            ok, sel = ask(
                "请键入数字以选择列表中的预设，或直接输入预设路径。若不需要请回车跳过：",
                validator=lambda s: (True, s),
                default="", auto_yes=False)
            if not ok:
                return
            if sel:
                try:
                    path = resolve_preset_arg(sel, presets)
                    preset_data = load_preset(path)
                    log_ok(f"已加载预设：{os.path.basename(path)}")
                    # 确认使用
                    if not ask_yes("使用该预设生成?", auto_yes=False):
                        log_info("已放弃该预设，转入手动输入。")
                        preset_data = None
                except Exception as e:
                    log_error(f"加载预设失败: {e}")
                    return
            else:
                log_info("已跳过预设，进入手动输入。")

    # ---- 3. 汇总分辨率、色带（优先级: 命令行 > 预设 > 交互） ----
    width = height = None
    strips = None

    # 分辨率
    if args.resolution:
        try:
            width, height = parse_resolution(args.resolution)
            if preset_data and (preset_data['width'] or preset_data['height']):
                log_info(f"命令行覆盖分辨率: "
                         f"{preset_data['width']}x{preset_data['height']} "
                         f"→ {width}x{height}")
        except ValueError as e:
            log_error(f"分辨率参数错误: {e}")
            return
    elif preset_data and preset_data['width'] and preset_data['height']:
        width, height = preset_data['width'], preset_data['height']

    # 色带
    if args.strips:
        try:
            strips = parse_strips(args.strips)
            if preset_data and preset_data['strips']:
                log_info(f"命令行覆盖色条: 使用 {len(strips)} 条新色带")
        except ValueError as e:
            log_error(f"色带参数错误: {e}")
            return
    elif preset_data and preset_data['strips']:
        strips = preset_data['strips']

    # 缺的进交互补
    if (width is None or height is None) or strips is None:
        if auto_yes:
            log_error("错误：-y 模式下缺少必要参数（--resolution / --strips 或 --preset）")
            return
        log_info("--- 新建旗帜 ---")
        if width is None or height is None:
            log_info("分辨率格式：宽x高，例如 900x600")
            ok, wh = ask(
                "输入分辨率：",
                validator=lambda s: (True, parse_resolution(s)),
                on_success=lambda v: (log_ok(f"分辨率 = {v[0]}x{v[1]}"), True)[1],
                default=None, auto_yes=False)
            if not ok:
                return
            width, height = wh
        if strips is None:
            log_info("色带格式：颜色 比例，逗号分隔，比例可省略（默认 1.0）")
            log_info("例：#FF0000 1.0, #FFFFFF 1.5, #0000FF 1.0")
            ok, strips = ask(
                "输入色带列表：",
                validator=lambda s: (True, parse_strips(s)),
                default=None, auto_yes=False)
            if not ok:
                return

    # 打印概览
    total_w = sum(w for _, w in strips)
    log_info(f"共 {len(strips)} 条色带，比例总和 = {total_w:g}")
    pcts = [f"{w/total_w*100:.2f}%" for _, w in strips]
    log_info("各条占比: " + " / ".join(pcts))

    heights = resolve_heights(strips, height)

    # ---- 4. 格式与输出名 ----
    fmt = args.fmt.lower() if args.fmt else None
    if fmt is None:
        if auto_yes:
            fmt = DEFAULT_FORMAT
            log_info(f"未指定格式，使用默认: {fmt}")
        else:
            log_info("可选格式：svg / png / jpg")
            ok, fmt = ask(
                "输入输出格式：",
                validator=lambda s: (s in ('svg', 'png', 'jpg', 'jpeg'),
                                     s),
                default=DEFAULT_FORMAT, auto_yes=False)
            if not ok:
                return
    canon = 'jpg' if fmt in ('jpg', 'jpeg') else fmt

    # ---- 4b. 输出文件名（统一处理扩展名 + 同名冲突） ----
    # 来源优先级：命令行 --output > 交互输入 > 自动命名
    if args.output:
        out = args.output
    elif auto_yes:
        out = f"flag.{canon}"
    else:
        log_info("留空则自动命名")
        ok, out = ask(
            "输入输出文件名：",
            validator=lambda s: (True, s),
            default=f"flag.{canon}", auto_yes=False)
        if not ok:
            return

    # 统一补扩展名 / 校正格式（无论名字从哪来都走这一步）
    root, ext = os.path.splitext(out)
    if not ext:
        out = f"{out}.{canon}"
        log_warn(f"文件名不包含扩展名，已自动补齐为: {out}")
    else:
        real = ext.lstrip('.').lower()
        if real in ('jpg', 'jpeg', 'png', 'svg'):
            fmt = 'jpg' if real in ('jpg', 'jpeg') else real

    # 同名冲突处理：-w 强制覆盖 / 交互询问 / 非交互自动改名
    if os.path.exists(out):
        if args.overwrite:
            log_warn(f"文件已存在，--overwrite 强制覆盖: {out}")
        elif auto_yes:
            new_out = unique_path(out)
            log_warn(f"文件已存在，自动改名: {out} → {new_out}")
            out = new_out
        else:
            if ask_yes(f"{out} 已存在，是否覆盖?", auto_yes=False):
                log_warn(f"已选择覆盖: {out}")
            else:
                new_out = unique_path(out)
                log_warn(f"已自动改名: {out} → {new_out}")
                out = new_out

    # ---- 5. 生成图片 ----
    if fmt == 'svg':
        gen_svg(width, height, strips, heights, out)
    elif fmt in ('png', 'jpg', 'jpeg'):
        if not ensure_pillow():
            log_error("缺少 Pillow，无法生成位图；可改用 svg，或先手动安装")
            return
        gen_raster(width, height, strips, heights, out, fmt=fmt)
    else:
        log_error(f"不支持的格式: {fmt!r}")
        return

    log_ok(f"已生成: {out}")

    # ---- 6. 保存预设 ----
    save_req = args.save_preset
    if save_req is None:
        # 命令行没要求 → 非 -y 时交互询问
        if auto_yes:
            return
        if not ask_yes("是否保存为预设?", auto_yes=False):
            return
        ok, name = ask(
            "输入预设名称（留空用\"未命名\"）：",
            validator=lambda s: (True, s),
            default="未命名", auto_yes=False)
        if not ok:
            return
    else:
        # 命令行给了 --save-preset
        if save_req is True:
            # 不带值 → 用输出文件名当预设名
            name = os.path.splitext(os.path.basename(out))[0]
        else:
            name = str(save_req)

    _ensure_preset_dir()
    # 名称清洗：去掉路径分隔符，防越界
    safe_name = re.sub(r'[\\/:*?"<>|]', '_', name) or "未命名"
    preset_path = os.path.join(PRESET_DIR, f"{safe_name}{PRESET_EXT}")
    try:
        save_preset(preset_path, name, width, height, strips)
        log_ok(f"预设已保存: {preset_path}")
    except Exception as e:
        log_error(f"保存预设失败: {e}")

if __name__ == '__main__':
    main()