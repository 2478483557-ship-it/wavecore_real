# -*- coding: utf-8 -*-
"""裁掉全景照左侧 1/6 —— 那里有背景里的学院名与书院名。

为什么要单独一步
----------------
`fig_p7_full_setup_annotated.jpg` 是 `annotate_photo.py` 点选生成的，
每次重新点标注都会覆盖它。把裁切放在那个脚本里，重标一次就白裁了。
所以这里做成**独立的后处理**：读 annotated，写 final，可反复执行。

裁多少、为什么安全
------------------
裁掉左侧 1/6（1920 → 1600 px）。箭头与标签的像素差分显示，
所有标注新增像素都在 x 490~1265（占宽 26%~66%），
裁到 16.7% 完全碰不到它们。

裁后宽高比 1600:1440 = 1.111（原 1.333），文档里需同步收窄图片宽度。
"""
import os

from PIL import Image

FIG = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(FIG, "fig_p7_full_setup_annotated.jpg")
FALLBACK = os.path.join(FIG, "fig_p7_full_setup.jpg")
OUT = os.path.join(FIG, "fig_p7_full_setup_final.jpg")

CROP_FRAC = 1.0 / 6.0


def main():
    src = SRC if os.path.exists(SRC) else FALLBACK
    im = Image.open(src)
    w, h = im.size
    cut = int(round(w * CROP_FRAC))
    out = im.crop((cut, 0, w, h))
    out.save(OUT, quality=93, optimize=True)

    print("源文件 : %s" % os.path.basename(src))
    print("原尺寸 : %dx%d  (比例 %.3f)" % (w, h, w / h))
    print("裁掉左 : %d px (%.1f%%)" % (cut, cut * 100.0 / w))
    print("新尺寸 : %dx%d  (比例 %.3f)" % (out.size[0], out.size[1],
                                          out.size[0] / out.size[1]))
    print("输出   : %s" % os.path.basename(OUT))

    # 核对：标注是否完整保留
    print()
    print("标注安全检查：原图标注像素在 x 490~1265，裁切点 %d —— %s"
          % (cut, "未触及 ✓" if cut < 490 else "★可能切到标注"))


if __name__ == "__main__":
    main()
