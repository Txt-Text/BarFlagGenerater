# barflag/cli.py
"""命令行前端：argparse + 交互式问答。

这里只做"收集输入 / 展示输出"，业务规则全部来自 core / presets / deps。
旧版 BarFlagGenerator.py 的行为在这里被完整保留。
"""

from __future__ import annotations

import argparse
import os
import sys

from . import core, deps, presets, report


# ============================ 参数 ============================


def build_parser():
    """构造 argparse 解析器"""
    p = argparse.ArgumentParser(
        prog="BarFlagGenerator.py",
        description="横条旗帜生成器（图形 / 交互 / 命令行 三种模式）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  图形界面: python BarFlagGenerator.py            （无参数即进 GUI）\n"
            "  文本交互: python BarFlagGenerator.py --cli\n"
            "  命令行:   python BarFlagGenerator.py -r 900x600 "
            "-s \"#FF0000 1,#FFFFFF 1.5\" -f svg -o flag.svg\n"
            "  用预设:   python BarFlagGenerator.py -p 2 -o out.png\n"
            "  看预设:   python BarFlagGenerator.py --list-presets\n"
            "\n提示: 只要带了任何参数就以命令行方式运行；\n"
            "      Windows CMD 下 -s 里的 # 和空格建议用双引号包起来，\n"
            "      PowerShell 可能需写成 -s '#FF0000 1,#FFFFFF 1.5'"
        ),
    )
    p.add_argument('--gui', action='store_true',
                   help='强制进入图形界面（等价于无参数运行）')
    p.add_argument('--cli', action='store_true',
                   help='使用命令行/文本交互模式（无参数时默认是图形界面）')
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


# ============================ 交互辅助 ============================


def _stdin_line(prompt):
    """读一行输入。

    stdin 不可用时（管道已关闭、没有终端、CI 环境）input() 会抛 EOFError，
    这里统一转成 None，交给调用方体面收场，而不是崩成"意外错误"。
    """
    try:
        return input(prompt)
    except (EOFError, OSError):
        return None


def _warn_no_stdin(rep=None):
    (rep or report.ConsoleReporter()).warn(
        "标准输入不可用，无法进行交互询问。"
        "非交互环境请加上 -y，或用参数把分辨率、色带、格式都给全。")


def ask_yes(prompt, auto_yes=False):
    """询问 Y/N。auto_yes=True 时（-y 模式）一律返回 True"""
    if auto_yes:
        print(f"{prompt} [Y/N]: Y  (自动)")
        return True
    line = _stdin_line(f"{prompt} [Y/N]: ")
    if line is None:
        _warn_no_stdin()
        return False          # 当作"否"，让流程继续往下走
    return line.strip().lower() in ('y', 'yes', '是')


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
    rep = report.ConsoleReporter()
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
            line = _stdin_line(f"{prompt}\n> ")
            if line is None:
                _warn_no_stdin(rep)
                return False, None
            raw = line.strip()
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
                    rep.error(str(value))
                elif not on_fail(value):
                    return False, None
        except Exception as e:
            if on_fail is None:
                rep.error(str(e))
            elif not on_fail(e):
                return False, None

        attempt += 1
        if retries is not None and attempt >= retries:
            rep.error(f"重试超过 {retries} 次，放弃。")
            return False, None


# ============================ 主流程 ============================


def show_banner():
    print(report.gray("=" * 80))
    print()
    print("横条旗帜生成器 v2.0")
    print()
    print("此工具可以生成以纯色横条构成的旗帜。如部分国旗、Pride旗等。")
    print("本工具支持自定义分辨率、色彩颜色、色带宽度比例、图片类型等，并允许保存与加载预设。")
    print("by Txt-Text")
    print()
    print(report.gray("=" * 80))
    print()


def list_presets(rep, show_header=True):
    """列出预设，返回路径列表。"""
    found = presets.scan_presets()
    if show_header:
        if found:
            rep.info(f"已扫描 {core.APP_DIR} 与 {core.PRESET_DIR}/ 目录，"
                     f"发现 {len(found)} 个预设文件：")
            for i, p in enumerate(found, 1):
                print(f"    {i}：{os.path.basename(p)}")
        else:
            rep.info(f"已扫描 {core.APP_DIR} 与 {core.PRESET_DIR}/ 目录，未发现预设文件。")
    return found


def _pick_preset(rep, presets_found):
    """交互式挑一个预设，返回 preset_data 或 None。"""
    if presets_found:
        rep.info(f"已扫描 {core.APP_DIR} 与 {core.PRESET_DIR}/ 目录，"
                 f"发现 {len(presets_found)} 个预设文件：")
        for i, p in enumerate(presets_found, 1):
            print(f"    {i}：{os.path.basename(p)}")
    else:
        rep.info(f"已扫描 {core.APP_DIR} 与 {core.PRESET_DIR}/ 目录，未发现预设文件。")
        return None

    ok, sel = ask(
        "请键入数字以选择列表中的预设，或直接输入预设路径。若不需要请回车跳过：",
        validator=lambda s: (True, s),
        default="", auto_yes=False)
    if not ok or not sel:
        if ok:
            rep.info("已跳过预设，进入手动输入。")
        return None

    try:
        path = presets.resolve_preset_arg(sel, presets_found)
        data = presets.load_preset(path, rep)
    except Exception as e:
        rep.error(f"加载预设失败: {e}")
        return None

    rep.ok(f"已加载预设：{os.path.basename(path)}")
    if not ask_yes("使用该预设生成?", auto_yes=False):
        rep.info("已放弃该预设，转入手动输入。")
        return None
    return data


def run(argv=None):
    """命令行主流程。返回进程退出码。"""
    report.enable_ansi()
    rep = report.ConsoleReporter(show_progress=True)
    show_banner()

    parser = build_parser()
    args = parser.parse_args(argv)

    auto_yes = args.yes

    # ---- 0. --list-presets: 列完就退出 ----
    if args.list_presets:
        list_presets(rep, show_header=True)
        return 0

    # ---- 1. 扫描预设（一次，供后续使用） ----
    found = presets.scan_presets()

    # ---- 2. 确定数据来源：预设 / 命令行 / 交互 ----
    preset_data = None

    if args.preset:
        # 2a. 命令行明确给了 --preset
        try:
            path = presets.resolve_preset_arg(args.preset, found)
            preset_data = presets.load_preset(path, rep)
            rep.ok(f"已加载预设：{os.path.basename(path)}")
        except Exception as e:
            rep.error(f"加载预设失败: {e}")
            return 1
    elif not auto_yes:
        # 2b. 没给 --preset，且非 -y 模式 → 交互询问
        preset_data = _pick_preset(rep, found)

    # ---- 3. 汇总分辨率、色带（优先级: 命令行 > 预设 > 交互） ----
    width = height = None
    strips = None

    if args.resolution:
        try:
            width, height = core.parse_resolution(args.resolution)
            if preset_data and (preset_data['width'] or preset_data['height']):
                rep.info(f"命令行覆盖分辨率: "
                         f"{preset_data['width']}x{preset_data['height']} "
                         f"→ {width}x{height}")
        except ValueError as e:
            rep.error(f"分辨率参数错误: {e}")
            return 1
    elif preset_data and preset_data['width'] and preset_data['height']:
        width, height = preset_data['width'], preset_data['height']

    if args.strips:
        try:
            strips = core.parse_strips(args.strips)
            if preset_data and preset_data['strips']:
                rep.info(f"命令行覆盖色带: 使用 {len(strips)} 条新色带")
        except ValueError as e:
            rep.error(f"色带参数错误: {e}")
            return 1
    elif preset_data and preset_data['strips']:
        strips = preset_data['strips']

    # 缺的进交互补
    if (width is None or height is None) or strips is None:
        if auto_yes:
            rep.error("错误：-y 模式下缺少必要参数（--resolution / --strips 或 --preset）")
            return 1
        rep.info("--- 新建旗帜 ---")
        if width is None or height is None:
            rep.info("分辨率格式：宽x高，例如 900x600")
            ok, wh = ask(
                "输入分辨率：",
                validator=lambda s: (True, core.parse_resolution(s)),
                on_success=lambda v: (rep.ok(f"分辨率 = {v[0]}x{v[1]}"), True)[1],
                default=None, auto_yes=False)
            if not ok:
                return 1
            width, height = wh
        if strips is None:
            rep.info("色带格式：颜色 比例，逗号分隔，比例可省略（默认 1.0）")
            rep.info("例：#FF0000 1.0, #FFFFFF 1.5, #0000FF 1.0")
            ok, strips = ask(
                "输入色带列表：",
                validator=lambda s: (True, core.parse_strips(s)),
                default=None, auto_yes=False)
            if not ok:
                return 1

    # ---- 4. 格式 ----
    fmt = core.normalize_format(args.fmt)
    if not fmt:
        if auto_yes:
            fmt = core.DEFAULT_FORMAT
            rep.info(f"未指定格式，使用默认: {fmt}")
        else:
            rep.info("可选格式：svg / png / jpg")
            ok, fmt = ask(
                "输入输出格式：",
                validator=lambda s: (s in ('svg', 'png', 'jpg', 'jpeg'), s),
                default=core.DEFAULT_FORMAT, auto_yes=False)
            if not ok:
                return 1
            fmt = core.normalize_format(fmt)

    # ---- 5. 输出文件名 ----
    if args.output:
        out = args.output
    elif auto_yes:
        out = f"flag.{fmt}"
    else:
        rep.info("留空则自动命名")
        ok, out = ask(
            "输入输出文件名：",
            validator=lambda s: (True, s),
            default=f"flag.{fmt}", auto_yes=False)
        if not ok:
            return 1

    # 统一补扩展名 / 校正格式
    out, fmt = core.finalize_output(out, fmt)

    # ---- 6. 同名冲突处理：-w 强制覆盖 / 交互询问 / 非交互自动改名 ----
    overwrite = False
    if os.path.exists(out):
        if args.overwrite:
            overwrite = True          # 覆盖提示由 core.generate 统一输出
        elif auto_yes:
            overwrite = False         # core.generate 会自动改名
        else:
            if ask_yes(f"{out} 已存在，是否覆盖?", auto_yes=False):
                overwrite = True
            else:
                rep.info("已选择改名，稍后自动生成不冲突的文件名。")

    # ---- 7. 生成 ----
    cfg = core.FlagConfig(width=width, height=height, strips=strips,
                          fmt=fmt, output=out)
    produced = core.generate(cfg, rep, overwrite=overwrite)
    if not produced:
        return 1

    # ---- 8. 保存预设 ----
    save_req = args.save_preset
    if save_req is None:
        if auto_yes:
            return 0
        if not ask_yes("是否保存为预设?", auto_yes=False):
            return 0
        ok, name = ask(
            "输入预设名称（留空用\"未命名\"）：",
            validator=lambda s: (True, s),
            default="未命名", auto_yes=False)
        if not ok:
            return 0
    else:
        if save_req is True:
            name = os.path.splitext(os.path.basename(produced))[0]
        else:
            name = str(save_req)

    try:
        path = presets.preset_path_for(name, rep)
        presets.save_preset(path, name, width, height, strips)
        rep.ok(f"预设已保存: {path}")
    except Exception as e:
        rep.error(f"保存预设失败: {e}")
    return 0


def main(argv=None):
    """CLI 入口（供 BarFlagGenerator.py 调用）。"""
    try:
        return run(argv)
    except KeyboardInterrupt:
        print()
        return 130
    except Exception as e:
        report.ConsoleReporter().error(f"意外错误: {type(e).__name__}: {e}")
        return 1
