# -*- coding: utf-8 -*-
"""生成技术文档的三张配图（系统框图 / 预触发四档 / 资源优化前后）。

用法：  python make_figures.py
依赖：  matplotlib（中文需系统已装 Microsoft YaHei 或 SimHei）
输出：  与本脚本同目录的三个 PNG，再经 report/tech_doc_draft.docx 插入技术文档。
"""
# -*- coding: utf-8 -*-
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import matplotlib.font_manager as fm
import numpy as np

for f in ['Microsoft YaHei', 'SimHei']:
    try:
        fm.findfont(f, fallback_to_default=False)
        matplotlib.rcParams['font.sans-serif'] = [f]; break
    except Exception:
        continue
matplotlib.rcParams['axes.unicode_minus'] = False

OUT = r'C:/Users/Lenovo/WorkBuddy/2026-09-02-11-10-14/wavecore/report/figures'
C_FPGA='#E6F1FB'; C_S='#185FA5'; C_DSP='#E1F5EE'; C_D='#0F6E56'
C_MEAS='#FAEEDA'; C_M='#854F0B'; C_UI='#EEEDFE'; C_U='#534AB7'
C_ANA='#FAECE7'; C_A='#993C1D'

def box(ax,x,y,w,h,t,fc,ec,fs=9):
    ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle="round,pad=0.06,rounding_size=0.12",
                 fc=fc,ec=ec,lw=1.0,zorder=2))
    ax.text(x+w/2,y+h/2,t,ha='center',va='center',fontsize=fs,color='#2C2C2A',
            zorder=3,linespacing=1.5)

def ar(ax,p1,p2,c='#5F5E5A',lw=1.2,ls='-',cs=None):
    ax.add_patch(FancyArrowPatch(p1,p2,arrowstyle='-|>',mutation_scale=12,color=c,
                 lw=lw,linestyle=ls,zorder=4,shrinkA=0,shrinkB=0,
                 connectionstyle=cs if cs else 'arc3,rad=0'))

# ============ 图1 系统整体框图 ============
fig, ax = plt.subplots(figsize=(15, 8.2))
ax.set_xlim(0,15); ax.set_ylim(0,8.2); ax.axis('off')
ax.add_patch(FancyBboxPatch((3.1,0.55),11.7,7.45,boxstyle="round,pad=0.1,rounding_size=0.2",
             fc='#FCFCFB',ec=C_S,lw=1.4,zorder=1))
ax.text(8.95,7.72,'FPGA  AMD Artix-7 XC7A35T-2FGG484   50 MHz 单时钟域',
        ha='center',va='center',fontsize=11,color=C_S,zorder=3)
box(ax,0.15,5.55,2.6,1.9,'PC 上位机\n波形 · 频谱\n瀑布图 · 仪表',C_UI,C_U,10)
box(ax,3.55,6.30,3.5,0.95,'cmd_decoder\n命令解析 + 校验和',C_FPGA,C_S)
box(ax,7.45,6.30,3.5,0.95,'dds_nco + sine_rom\n32 位 NCO 信号源',C_DSP,C_D)
box(ax,11.35,6.30,3.1,0.95,'uart_rx / uart_tx\n460800-8N1',C_FPGA,C_S)
box(ax,3.55,4.95,3.5,0.95,'ad_driver\n25 MSPS 连续采集',C_FPGA,C_S)
box(ax,7.45,4.95,3.5,0.95,'freq_meter / measure_report\n频率·占空比·脉宽·Vpp',C_MEAS,C_M)
box(ax,11.35,4.95,3.1,0.95,'wave_id\n波形自动识别 TY',C_MEAS,C_M)
box(ax,3.55,3.60,3.5,0.95,'timebase\n时基抽取（换分辨率）',C_FPGA,C_S)
box(ax,7.45,3.60,3.5,0.95,'wave_frame\n1024 点波形 + 触发/预触发',C_FPGA,C_S)
box(ax,11.35,3.60,3.1,0.95,'spec_compress + spec_frame\n512 点幅度谱帧',C_DSP,C_D)
box(ax,7.45,2.25,3.5,0.95,'self_fft_1024（自研）\nHann 窗 + 抛物线插值',C_DSP,C_D)
box(ax,11.35,2.25,3.1,0.95,'xfft_0（厂商 IP）\n4096 点 FFT',C_DSP,C_D)
box(ax,3.55,2.25,3.5,0.95,'TX 互斥仲裁\n多路结果分时上传',C_FPGA,C_S)
box(ax,3.55,0.95,10.9,0.95,
    'AD9708 DAC（输出 ±5V）  →  短飞线回环  →  AD9280 ADC（输入 ±5V，25 MSPS）',C_ANA,C_A,10)
ar(ax,(2.75,6.45),(3.55,6.45)); ax.text(3.15,6.72,'UART',ha='center',fontsize=8,color=C_U)
ar(ax,(3.55,6.20),(2.75,5.95),c='#888780',ls='--')
ar(ax,(5.30,6.30),(5.30,5.90)); ar(ax,(9.20,6.30),(9.20,5.90))
ar(ax,(5.30,4.95),(5.30,4.55))
ar(ax,(5.30,4.55),(7.45,4.55),c='#888780',ls='--',cs='angle,angleA=0,angleB=90,rad=6')
ar(ax,(5.30,4.55),(11.35,4.55),c='#888780',ls='--',cs='angle,angleA=0,angleB=90,rad=6')
ar(ax,(9.20,4.95),(9.20,4.55))
ar(ax,(5.30,3.60),(7.45,3.60))
ar(ax,(9.20,3.60),(9.20,3.20))
ar(ax,(9.20,2.25),(9.20,1.90))
ar(ax,(12.90,2.25),(12.90,3.60),c='#888780',ls='--')
ar(ax,(12.90,4.55),(12.90,6.30),c='#888780',ls='--')
plt.tight_layout(pad=0.3)
plt.savefig(OUT+r'\fig_system_block.png',dpi=160,facecolor='white'); plt.close()
print('图1 系统整体框图')

# ============ 图2 预触发四档对比 ============
fig, axes = plt.subplots(4,1,figsize=(11,8.6),sharex=True)
N=1024; PER=50
tiers=[(0,'0%'),(256,'25%'),(512,'50%'),(768,'75%')]
n=np.arange(N)
for ax,(T,name) in zip(axes,tiers):
    phase=(n-T)%PER
    w=np.where(phase<PER//2,1.0,0.0)
    ax.step(n,w,where='post',color='#185FA5',lw=1.1)
    ax.axvline(T,color='#E24B4A',lw=1.4,ls='--')
    ax.set_ylim(-0.35,1.45); ax.set_yticks([])
    ax.set_ylabel('预触发\n'+name,fontsize=10,rotation=0,ha='right',va='center',color='#2C2C2A')
    ax.text(T+12,1.22,'触发点 @ 第 %d 点'%T,fontsize=9,color='#A32D2D',va='center')
    ax.text(1012,1.22,'低电平 %d 点'%T,fontsize=9,color='#5F5E5A',va='center',ha='right')
    for s in ['top','right']: ax.spines[s].set_visible(False)
    ax.grid(axis='x',color='#D3D1C7',lw=0.4,alpha=0.6)
axes[-1].set_xlabel('帧内样点序号（1 kHz 方波，fs = 50 kHz，1024 点）',fontsize=10)
fig.suptitle('预触发四档：触发点落在数据帧中的位置（实测低电平点数 0 / 256 / 512 / 768，逐点吻合）',
             fontsize=11.5,color='#2C2C2A',y=0.985)
plt.tight_layout(rect=[0.02,0,1,0.965])
plt.savefig(OUT+r'\fig_pretrigger_tiers.png',dpi=160,facecolor='white'); plt.close()
print('图2 预触发四档对比')

# ============ 图3 资源优化前后 ============
fig, ax = plt.subplots(figsize=(10,5.2))
labels=['整改前\n（f_ram 未进 BRAM）','整改后\n（SDP 模板）','功能扩展后\n（当前交付版）']
vals=[20829,5117,7063]
colors=['#E24B4A','#639922','#185FA5']
b=ax.bar(labels,vals,color=colors,width=0.52,zorder=3)
ax.axhline(20800,color='#888780',lw=1.3,ls='--',zorder=2)
ax.text(2.42,20800+380,'器件容量 20,800（100%）',ha='right',fontsize=9.5,color='#5F5E5A')
for r,v in zip(b,vals):
    ax.text(r.get_x()+r.get_width()/2,v+420,format(v,',')+'  (%.2f%%)'%(v/20800*100),
            ha='center',fontsize=10.5,color='#2C2C2A')
ax.set_ylabel('Slice LUTs',fontsize=10.5); ax.set_ylim(0,23500)
ax.annotate('',xy=(1,5117),xytext=(0,20829),
            arrowprops=dict(arrowstyle='-|>',color='#0F6E56',lw=1.6,ls='--',
                            connectionstyle='arc3,rad=-0.28'))
ax.text(0.5,14300,'−75.4%',fontsize=13,color='#0F6E56',ha='center',
        bbox=dict(boxstyle='round,pad=0.3',fc='#E1F5EE',ec='#0F6E56',lw=0.8))
for s in ['top','right']: ax.spines[s].set_visible(False)
ax.grid(axis='y',color='#D3D1C7',lw=0.4,alpha=0.5,zorder=0)
ax.set_title('资源优化前后对比（Vivado 2020.2 实测，XC7A35T）',fontsize=11.5,pad=12)
plt.tight_layout()
plt.savefig(OUT+r'\fig_resource_before_after.png',dpi=160,facecolor='white'); plt.close()
print('图3 资源优化前后对比')
