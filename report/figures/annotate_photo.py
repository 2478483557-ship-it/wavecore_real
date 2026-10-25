# -*- coding: utf-8 -*-
"""在实物照片上点选 4 个位置，自动生成带箭头的标注版。

为什么需要手工点选
------------------
照片上的 AD/DA 接口没有可识别的丝印文字（OCR 只认出了 "LSB UART"），
所以无法自动定位。让模型猜坐标会画出指错地方的箭头 —— 比不标还糟。

用法（约 30 秒）
----------------
1. 双击 `annotate_photo.bat`（或 python annotate_photo.py）
2. 窗口右侧列出 4 个待标位置，**当前要标的那一项是红底**
3. 在照片上点一下，就把它标在点上，自动跳到下一项
4. 点错了按 `Backspace` 撤销上一个
5. 4 个都标完，按 `S` 保存，`Esc` 退出

输出
----
`report/figures/fig_p3_board_annotated.jpg`
技术文档构建时如果发现这个文件，会自动换用它。
"""
import os
import sys
import tkinter as tk
from tkinter import messagebox

from PIL import Image, ImageDraw, ImageFont, ImageTk

FIG_DIR = os.path.dirname(os.path.abspath(__file__))
# 改成全景照：主板 + AD/DA 模块 + 全部接线。
# 原来的 fig_p3_board.jpg 只拍了主板，看不到 AD/DA 模块和飞线。
SRC = os.path.join(FIG_DIR, "fig_p7_full_setup.jpg")
OUT = os.path.join(FIG_DIR, "fig_p7_full_setup_annotated.jpg")

# 顺序即标注顺序。anchor 决定标签往哪个方向摆（避免压住板子主体）
TASKS = [
    ("AD/DA 模块", "ATK_HS_AD_DA\nAD9280 采集 + AD9708 输出", "ul"),
    ("ADC 输入口", "AD 排针输入端\n（回环时接 DAC 输出）", "ll"),
    ("DAC 输出口", "DA 排针输出端\n（接回环飞线）", "ll"),
    ("串口 USB", "CH340 转 USB\n460800-8N1", "ur"),
    ("回环飞线", "DA → AD 那根短线", "lr"),
]

# PIL 用 RGB 元组，tkinter 只认十六进制字符串 —— 两套分开定义，
# 之前把元组传给 tk 的 fg= 直接抛 TclError: unknown color name "200 40 40"
ACCENT = (200, 40, 40)          # PIL 绘图用
ACCENT_HEX = "#c82828"          # tkinter 控件用
INK = (25, 25, 25)
WHITE = (255, 255, 255)


def load_font(size, bold=False):
    for p in (r"C:/Windows/Fonts/msyhbd.ttc" if bold else r"C:/Windows/Fonts/msyh.ttc",
              r"C:/Windows/Fonts/simhei.ttf"):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


class App:
    def __init__(self, root):
        self.root = root
        self.img = Image.open(SRC).convert("RGB")
        self.W, self.H = self.img.size
        self.points = []          # [(x_orig, y_orig)]

        # 缩放到屏幕上放得下
        self.scale = min(760 / self.H, 900 / self.W, 1.0)
        self.dw = int(self.W * self.scale)
        self.dh = int(self.H * self.scale)
        self.disp = self.img.resize((self.dw, self.dh), Image.LANCZOS)

        root.title("实物照片标注 —— 点 4 下即可")
        root.configure(bg="#f5f5f3")

        self.canvas = tk.Canvas(root, width=self.dw, height=self.dh,
                                highlightthickness=1, highlightbackground="#bbb",
                                cursor="crosshair")
        self.canvas.grid(row=0, column=0, padx=(12, 8), pady=12)
        self.tk_img = ImageTk.PhotoImage(self.disp)
        self.canvas.create_image(0, 0, anchor="nw", image=self.tk_img)
        self.canvas.bind("<Button-1>", self.on_click)

        side = tk.Frame(root, bg="#f5f5f3")
        side.grid(row=0, column=1, sticky="n", padx=(0, 14), pady=12)

        tk.Label(side, text="依次点击照片", bg="#f5f5f3",
                 font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", pady=(0, 8))

        self.rows = []
        for i, (name, desc, _a) in enumerate(TASKS):
            box = tk.Frame(side, bg="#ffffff", bd=1, relief="solid")
            box.pack(fill="x", pady=3)
            num = tk.Label(box, text="%d" % (i + 1), width=2,
                           font=("Microsoft YaHei UI", 11, "bold"))
            num.pack(side="left", padx=(6, 4))
            txt = tk.Label(box, text=name + "\n" + desc.replace("\n", " "),
                           justify="left", anchor="w",
                           font=("Microsoft YaHei UI", 9))
            txt.pack(side="left", fill="x", expand=True, padx=(0, 6), pady=4)
            self.rows.append((box, num, txt))

        tk.Label(side, text="", bg="#f5f5f3").pack(pady=6)
        tk.Button(side, text="撤销上一个 (Backspace)", width=26,
                  command=self.undo).pack(pady=2)
        tk.Button(side, text="保存 (S)", width=26,
                  command=self.save).pack(pady=2)
        tk.Button(side, text="退出 (Esc)", width=26,
                  command=root.destroy).pack(pady=2)

        tk.Label(side, text="提示：点错了就撤销，不用重来",
                 bg="#f5f5f3", fg="#777",
                 font=("Microsoft YaHei UI", 9)).pack(pady=(10, 0))

        root.bind("<BackSpace>", lambda e: self.undo())
        root.bind("<Escape>", lambda e: root.destroy())
        root.bind("<s>", lambda e: self.save())
        root.bind("<S>", lambda e: self.save())

        self.refresh()

    # ---------------- 状态高亮 ----------------
    def refresh(self):
        cur = len(self.points)
        for i, (box, num, txt) in enumerate(self.rows):
            if i < cur:
                box.configure(bg="#e8f5ee"); num.configure(bg="#e8f5ee", fg="#0a7a4a")
                txt.configure(bg="#e8f5ee", fg="#0a7a4a")
                num.configure(text="✓")
            elif i == cur:
                box.configure(bg="#fdecec"); num.configure(bg="#fdecec", fg=ACCENT_HEX)
                txt.configure(bg="#fdecec", fg=ACCENT_HEX)
                num.configure(text="%d" % (i + 1))
            else:
                box.configure(bg="#ffffff"); num.configure(bg="#ffffff", fg="#999")
                txt.configure(bg="#ffffff", fg="#666")
                num.configure(text="%d" % (i + 1))
        self.canvas.delete("mark")
        for i, (x, y) in enumerate(self.points):
            sx, sy = x * self.scale, y * self.scale
            self.canvas.create_oval(sx - 7, sy - 7, sx + 7, sy + 7,
                                    outline=ACCENT_HEX, width=3, tags="mark")
            self.canvas.create_text(sx + 12, sy - 12, text=str(i + 1), fill=ACCENT_HEX,
                                    font=("Microsoft YaHei UI", 12, "bold"), tags="mark")

    def on_click(self, ev):
        if len(self.points) >= len(TASKS):
            return
        x = int(ev.x / self.scale)
        y = int(ev.y / self.scale)
        self.points.append((x, y))
        self.refresh()
        if len(self.points) == len(TASKS):
            messagebox.showinfo("标好了", "4 个位置都标完了。\n按「保存」生成图片。")

    def undo(self):
        if self.points:
            self.points.pop()
            self.refresh()

    # ---------------- 画箭头并保存 ----------------
    def save(self):
        if len(self.points) < len(TASKS):
            messagebox.showwarning("还没标完", "还剩 %d 个位置没点。" % (len(TASKS) - len(self.points)))
            return

        img = self.img.copy()
        d = ImageDraw.Draw(img, "RGBA")
        s = self.W / 1500.0          # 按原图宽度归一，字号跟着图走
        f_lab = load_font(int(34 * s), bold=True)
        f_num = load_font(int(30 * s), bold=True)

        for i, ((name, desc, anchor), (x, y)) in enumerate(zip(TASKS, self.points), 1):
            # 标签框放在远离板子中心的一侧
            pad = int(18 * s)
            tw = d.textlength(name, font=f_lab)
            th = int(40 * s)
            bw, bh = tw + pad * 2, th + pad

            dx = -1 if anchor.endswith("l") else 1
            dy = -1 if anchor.startswith("u") else 1
            bx = x + dx * int(150 * s)
            by = y + dy * int(90 * s)

            # 不让框跑出画面
            bx = max(pad, min(self.W - bw - pad, bx))
            by = max(pad, min(self.H - bh - pad, by))

            # 箭头：从框的边缘指向坐标点
            ax = bx if dx > 0 else bx + bw
            ay = by + bh / 2
            d.line([(ax, ay), (x, y)], fill=ACCENT, width=int(5 * s))
            # 箭头头部
            import math
            ang = math.atan2(y - ay, x - ax)
            L = int(26 * s)
            for sgn in (+1, -1):
                d.line([(x, y),
                        (x - L * math.cos(ang - sgn * 0.45),
                         y - L * math.sin(ang - sgn * 0.45))],
                       fill=ACCENT, width=int(5 * s))
            # 端点圆
            r = int(9 * s)
            d.ellipse([x - r, y - r, x + r, y + r], fill=ACCENT,
                      outline=WHITE, width=int(3 * s))

            # 标签框
            d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=int(10 * s),
                                fill=(255, 255, 255, 240), outline=ACCENT,
                                width=int(3 * s))
            d.text((bx + pad, by + bh / 2), name, font=f_lab, fill=ACCENT, anchor="lm")
            # 序号角标
            d.ellipse([bx - int(16 * s), by - int(16 * s),
                       bx + int(18 * s), by + int(18 * s)],
                      fill=ACCENT)
            d.text((bx + int(1 * s), by + int(1 * s)), str(i), font=f_num,
                   fill=WHITE, anchor="mm")

        img.save(OUT, quality=92)
        messagebox.showinfo("已保存", "%s\n\n技术文档重建时会自动使用这张。" % OUT)
        print("已保存:", OUT)
        for i, ((name, _d, _a), (x, y)) in enumerate(zip(TASKS, self.points), 1):
            print("  %d %-10s (%d, %d)" % (i, name, x, y))


if __name__ == "__main__":
    if not os.path.exists(SRC):
        print("找不到 %s" % SRC)
        sys.exit(1)
    root = tk.Tk()
    App(root)
    root.mainloop()
