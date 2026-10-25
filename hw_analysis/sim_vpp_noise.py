# -*- coding: utf-8 -*-
"""模拟真实采集链，看 Vpp 读数到底会不会因为噪声而变。

为什么要做这个仿真
------------------
用户反馈"加噪声前后没什么区别"。与其继续解释，不如算一遍。

关键是**必须包含 8 位量化**。1 码 = 36.33 mV 这个数字很粗糙，
当信号本身只有几个码的时候，量化本身就是最大的噪声源。
之前的解释漏了这一点。

采集链按 RTL 实际参数：
    ADC 25 MSPS，8 位
    5 点中值滤波（ad_driver 之后）
    抽取 decim=1000 -> 50 kHz
    波形帧 1024 点
    Vpp = (max - min) * 36.33 mV
"""
import numpy as np

FS = 50000.0        # 抽取后采样率
N = 1024            # 波形帧点数
LSB = 36.33         # mV / 码（KN=37203 标定）
FC = 1000.0         # 信号频率
NPRE = 1000         # 抽取前的过采样倍数


def acquire(a_vpp, noise_mv, rng, fc=FC):
    """生成一帧 1024 点，返回 8 位码值数组（0~255，中点 128）。

    a_vpp   : 信号峰峰值 mV（模块输入端）
    noise_mv: 高斯噪声标准差 mV（加在模块输入端）
    """
    n_pre = N * NPRE
    t = np.arange(n_pre) / (FS * NPRE)

    sig = (a_vpp / 2.0) * np.sin(2 * np.pi * fc * t)
    x = sig + rng.normal(0.0, noise_mv, n_pre)

    # 量化到 8 位，中点 128（对应模块输入的 0V）
    code = np.round(x / LSB).astype(np.int32) + 128
    code = np.clip(code, 0, 255)

    # 5 点中值滤波（与 ad_driver 后级一致，取奇数窗口）
    # 用滑动窗口视图做，向量化的 np.median 比逐点循环快两个数量级
    # （逐点版本在 100 万点上跑 40 次要几分钟，实测跑不完）
    win = np.lib.stride_tricks.sliding_window_view(code, 5)
    med = np.median(win, axis=1)

    # 抽取
    out = med[::NPRE][:N]
    return out.astype(np.int32)


def measure_vpp(codes):
    return int(codes.max() - codes.min()) * LSB


def run(a_vpp, noise_mv, trials=40, seed=1):
    rng = np.random.default_rng(seed)
    vpps = np.array([measure_vpp(acquire(a_vpp, noise_mv, rng)) for _ in range(trials)])
    return vpps


def lockin_amp(a_vpp, noise_mv, rng, fc=FC, periods=32, fs_adc=25e6):
    """模拟 lockin_core：与同频正交参考相乘，整周期累加，返回幅度（Vpp 口径 mV）。

    和 RTL 一致：参考 NCO 跑 ADC 实际速率，累加整除周期数。
    """
    n = int(round(fs_adc / fc * periods))
    t = np.arange(n) / fs_adc

    sig = (a_vpp / 2.0) * np.sin(2 * np.pi * fc * t)
    x = sig + rng.normal(0.0, noise_mv, n)
    code = np.round(x / LSB) + 128          # 8 位量化

    # 参考表是 Q1.15：值域 ±32767，不是 ±1。
    # 一开始归一化成 ±1，结果 |IQ| 小了 32767 倍，算出来是 0 —— 
    # 和 demo 脚本那句 2*|IQ|/(FULL_REF*n) 对不上。
    ref_i = np.round(np.cos(2 * np.pi * fc * t) * 32767)
    ref_q = np.round(np.sin(2 * np.pi * fc * t) * 32767)
    i_acc = np.sum((code - 128) * ref_i)   # 与 RTL 一致：先减 128 去偏置
    q_acc = np.sum((code - 128) * ref_q)
    # 与 demo 脚本同一口径：幅度 = 2*|IQ|/(满量程*N) * 2 * LSB
    return 2.0 * np.hypot(i_acc, q_acc) / (32767.0 * n) * 2.0 * LSB


def compare(a_vpp, noise_mv, trials=30, seed=7):
    rng = np.random.default_rng(seed)
    vpp = np.array([measure_vpp(acquire(a_vpp, noise_mv, rng)) for _ in range(trials)])
    lk = np.array([lockin_amp(a_vpp, noise_mv, rng) for _ in range(trials)])
    return vpp, lk


def main():
    print("=" * 74)
    print("  Vpp 读数会因噪声而变吗 —— 按真实 8 位量化模拟")
    print("=" * 74)
    print()
    print("  1 码 = %.2f mV；1024 点 @50kHz；每个条件模拟 40 次" % LSB)
    print()

    cases = [
        ("麦克风 2m，无额外噪声", 225, 0),
        ("麦克风 2m + 轻度噪声", 225, 30),
        ("麦克风 2m + 中度噪声", 225, 60),
        ("麦克风 2m + 强噪声", 225, 120),
        ("麦克风 50cm，无噪声", 600, 0),
        ("麦克风 50cm + 中度噪声", 600, 60),
        ("麦克风 50cm + 强噪声", 600, 120),
        ("信号很弱 100mV + 强噪声", 100, 120),
    ]

    print("  %-26s %8s %8s %8s %8s %8s" %
          ("条件", "码数", "Vpp均值", "最小", "最大", "极差"))
    print("  " + "-" * 72)

    for name, a, nz in cases:
        v = run(a, nz)
        code = a / LSB
        print("  %-26s %7.1f %7.0f %8.0f %8.0f %8.0f" %
              (name, code, v.mean(), v.min(), v.max(), v.max() - v.min()))

    print()
    print("=" * 74)
    print("  结论")
    print("=" * 74)
    print()

    # 定量：信号 225mV 时，噪声从 0 到 120 的效果
    v0 = run(225, 0)
    v1 = run(225, 120)
    print("  信号 225mVpp（约 %.1f 码）：" % (225 / LSB))
    print("    无噪声：Vpp 读数 %.0f ~ %.0f mV，极差 %.0f" % (v0.min(), v0.max(), v0.max() - v0.min()))
    print("    强噪声：Vpp 读数 %.0f ~ %.0f mV，极差 %.0f" % (v1.min(), v1.max(), v1.max() - v1.min()))
    print("    均值变化：%.0f -> %.0f mV（%.1f 倍）" % (v0.mean(), v1.mean(), v1.mean() / v0.mean()))
    print()

    print("=" * 74)
    print("  加入锁相后：同一个信号的两种读数")
    print("=" * 74)
    print()
    print("  %-22s %-24s %-24s" % ("条件", "Vpp 读数（波动）", "锁相读数（波动）"))
    print("  " + "-" * 72)
    for name, a, nz in [("干净信号", 225, 0), ("轻度噪声", 225, 30),
                        ("中度噪声", 225, 60), ("强噪声", 225, 120),
                        ("极强噪声", 225, 200)]:
        v, l = compare(a, nz)
        print("  %-22s %5.0f ± %3.0f  (%3.0f%%)      %5.0f ± %4.1f  (%3.1f%%)"
              % (name, v.mean(), (v.max() - v.min()) / 2, (v.max() - v.min()) / 2 / v.mean() * 100,
                 l.mean(), (l.max() - l.min()) / 2, (l.max() - l.min()) / 2 / l.mean() * 100))
    print()
    print("  注意 Vpp 那列的波动百分比一直不大 —— 这是实测和仿真的共同结果。")
    print("  真正看得见的差别是均值的抬升：218 -> 583，而锁相一直是 225 附近。")
    print()


if __name__ == "__main__":
    main()
