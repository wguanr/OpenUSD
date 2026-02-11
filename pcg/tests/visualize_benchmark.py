#!/usr/bin/env python3
"""生成基准测试的可视化图表。"""

import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import os

plt.rcParams['font.sans-serif'] = ['DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

output_dir = "/home/ubuntu/usd_pcg/output/benchmarks"

with open(os.path.join(output_dir, "benchmark_results.json"), 'r', encoding='utf-8') as f:
    data = json.load(f)

fig, axes = plt.subplots(2, 2, figsize=(18, 13))
fig.suptitle('USD-PCG High-Performance Benchmark Results', fontsize=18, fontweight='bold', y=0.98)

# =====================================================================
# Chart 1: Scaling Performance
# =====================================================================
ax1 = axes[0, 0]
scaling_data = data["单体生成性能 - 规模扩展测试"]
floors = [d["楼层数"] for d in scaling_data]
gen_times = [d["生成时间(s)"] for d in scaling_data]
file_sizes = [d["文件大小(KB)"] / 1024 for d in scaling_data]

color1 = '#2196F3'
color2 = '#FF9800'

ax1.bar(range(len(floors)), gen_times, color=color1, alpha=0.8, label='Gen Time (s)')
ax1.set_xlabel('Building Scale (Floors)', fontsize=11)
ax1.set_ylabel('Generation Time (s)', color=color1, fontsize=11)
ax1.set_xticks(range(len(floors)))
ax1.set_xticklabels([f'{f}F' for f in floors])
ax1.tick_params(axis='y', labelcolor=color1)

ax1_twin = ax1.twinx()
ax1_twin.plot(range(len(floors)), file_sizes, 'o-', color=color2, linewidth=2.5, markersize=8, label='File Size (MB)')
ax1_twin.set_ylabel('File Size (MB)', color=color2, fontsize=11)
ax1_twin.tick_params(axis='y', labelcolor=color2)

ax1.set_title('Scaling Performance', fontsize=13, fontweight='bold')
lines1, labels1 = ax1.get_legend_handles_labels()
lines2, labels2 = ax1_twin.get_legend_handles_labels()
ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left', fontsize=9)

# =====================================================================
# Chart 2: Throughput
# =====================================================================
ax2 = axes[0, 1]
throughput = [d["窗户/秒"] for d in scaling_data]
windows = [d["窗户数"] for d in scaling_data]

bars2 = ax2.bar(range(len(floors)), throughput, color='#4CAF50', alpha=0.8)
ax2.set_xlabel('Building Scale', fontsize=11)
ax2.set_ylabel('Windows Generated / sec', fontsize=11)
ax2.set_xticks(range(len(floors)))
ax2.set_xticklabels([f'{f}F\n{w}w' for f, w in zip(floors, windows)], fontsize=9)
ax2.set_title('Generation Throughput', fontsize=13, fontweight='bold')

for i, v in enumerate(throughput):
    ax2.text(i, v + 50, f'{v}', ha='center', fontweight='bold', fontsize=10)

# =====================================================================
# Chart 3: PointInstancer vs Individual
# =====================================================================
ax3 = axes[1, 0]
inst_data = data["PointInstancer vs 逐个创建 性能对比"]
inst_floors = [5, 10, 20, 50]
inst_times = [d["PointInstancer时间(s)"] for d in inst_data]
no_inst_times = [d["逐个创建时间(s)"] for d in inst_data]
speedups = [d["时间加速比"] for d in inst_data]
inst_sizes = [d["PointInstancer文件(KB)"] for d in inst_data]
no_inst_sizes = [d["逐个创建文件(KB)"] for d in inst_data]

x = np.arange(len(inst_floors))
width = 0.35

ax3.bar(x - width/2, inst_times, width, label='PointInstancer', color='#2196F3', alpha=0.8)
ax3.bar(x + width/2, no_inst_times, width, label='Individual', color='#f44336', alpha=0.8)

ax3.set_xlabel('Building Scale (Floors)', fontsize=11)
ax3.set_ylabel('Generation Time (s)', fontsize=11)
ax3.set_xticks(x)
ax3.set_xticklabels([f'{f}F' for f in inst_floors])
ax3.set_title('PointInstancer vs Individual Creation', fontsize=13, fontweight='bold')
ax3.legend(fontsize=10)

for i, sp in enumerate(speedups):
    max_h = max(inst_times[i], no_inst_times[i])
    ax3.text(i, max_h + 0.03, f'{sp}x', ha='center', fontsize=11, fontweight='bold', color='#4CAF50')

# =====================================================================
# Chart 4: Serial vs Parallel
# =====================================================================
ax4 = axes[1, 1]
parallel_data = data["并行批量生成测试"]

categories = ['Serial\n20 buildings', 'Parallel (4 proc)\n20 buildings']
throughputs_p = [parallel_data[0]["吞吐量(栋/秒)"], parallel_data[1]["吞吐量(栋/秒)"]]
times_p = [parallel_data[0]["总时间(s)"], parallel_data[1]["总时间(s)"]]

colors = ['#f44336', '#4CAF50']
bars4 = ax4.bar(categories, throughputs_p, color=colors, alpha=0.8, width=0.5)
ax4.set_ylabel('Throughput (Buildings/sec)', fontsize=11)
ax4.set_title('Serial vs Parallel Generation', fontsize=13, fontweight='bold')

for bar, t, tp in zip(bars4, times_p, throughputs_p):
    ax4.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
             f'{tp} bldg/s\n({t:.1f}s)', ha='center', fontweight='bold', fontsize=11)

speedup = parallel_data[1].get("并行加速比", 0)
ax4.annotate(f'Speedup: {speedup}x', xy=(0.5, 0.45), xycoords='axes fraction',
             ha='center', fontsize=16, fontweight='bold', color='#1565C0',
             bbox=dict(boxstyle='round,pad=0.3', facecolor='#E3F2FD', edgecolor='#1565C0'))

plt.subplots_adjust(top=0.93, bottom=0.08, hspace=0.35, wspace=0.35)
chart_path = os.path.join(output_dir, "benchmark_charts.png")
plt.savefig(chart_path, dpi=150, bbox_inches='tight')
print(f"Charts saved to: {chart_path}")

# =====================================================================
# Additional: Stress test summary chart
# =====================================================================
fig2, ax5 = plt.subplots(1, 1, figsize=(10, 6))
stress_data = data["大规模场景压力测试"]

labels_s = ['200F MegaTower\n(Single)', '50 Buildings\n(Parallel 4-proc)']
windows_s = [stress_data[0]["窗户数"], stress_data[1]["总窗户数"]]
times_s = [stress_data[0]["生成时间(s)"], stress_data[1]["总时间(s)"]]

x_s = np.arange(len(labels_s))
width_s = 0.35

bars_w = ax5.bar(x_s - width_s/2, windows_s, width_s, label='Total Windows', color='#FF9800', alpha=0.8)
ax5_twin = ax5.twinx()
bars_t = ax5_twin.bar(x_s + width_s/2, times_s, width_s, label='Time (s)', color='#9C27B0', alpha=0.8)

ax5.set_xlabel('Stress Test Scenario', fontsize=12)
ax5.set_ylabel('Total Windows Generated', color='#FF9800', fontsize=12)
ax5_twin.set_ylabel('Generation Time (s)', color='#9C27B0', fontsize=12)
ax5.set_xticks(x_s)
ax5.set_xticklabels(labels_s, fontsize=11)
ax5.set_title('Stress Test: Large-Scale Generation', fontsize=14, fontweight='bold')

for i, (w, t) in enumerate(zip(windows_s, times_s)):
    ax5.text(i - width_s/2, w + 200, f'{w:,}', ha='center', fontweight='bold', fontsize=11)
    ax5_twin.text(i + width_s/2, t + 0.1, f'{t:.1f}s', ha='center', fontweight='bold', fontsize=11, color='#9C27B0')

lines_a, labels_a = ax5.get_legend_handles_labels()
lines_b, labels_b = ax5_twin.get_legend_handles_labels()
ax5.legend(lines_a + lines_b, labels_a + labels_b, loc='upper left', fontsize=11)

stress_path = os.path.join(output_dir, "stress_test_chart.png")
plt.savefig(stress_path, dpi=150, bbox_inches='tight')
print(f"Stress chart saved to: {stress_path}")
