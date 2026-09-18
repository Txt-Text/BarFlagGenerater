# barflag/render.py
"""渲染层：把配置画成 SVG 或位图。

纯函数，不碰界面、不打印任何东西。Pillow 只在位图路径上按需导入。
"""

from __future__ import annotations


def gen_svg(width, height, strips, heights, path):
    """生成 SVG（纯文本拼接，零依赖）"""
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
    """用 Pillow 生成位图（PNG/JPG）。

    fmt 显式指定格式，避免扩展名缺失或大小写不一致时报错。
    """
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
