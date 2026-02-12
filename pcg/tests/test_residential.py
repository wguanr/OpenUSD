#!/usr/bin/env python3
"""
测试中国住宅小区商品房生成器。

生成4种典型住宅建筑形制：
  1. 6层板楼（一梯两户，三室一厅）- 多层住宅
  2. 18层板楼（一梯两户，三室+两室）- 小高层
  3. 33层塔楼（两梯四户）- 高层塔楼
  4. 18层底商板楼（一梯两户+底商）- 底商住宅
"""

import sys
import os
# 添加父目录(pcg/)到路径
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from pcg_core.engine import PCGEngine, ResidentialConfig
from generators.residential_generator import ResidentialGenerator
from tools.render_usd import render_panoramic_views

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from PIL import Image


def generate_residential(name, config_overrides, output_dir):
    """生成单栋住宅楼并返回USD文件路径。"""
    os.makedirs(output_dir, exist_ok=True)

    config = ResidentialConfig(
        building_name=name,
        seed=42,
        output_dir=output_dir,
    )

    for k, v in config_overrides.items():
        setattr(config, k, v)

    engine = PCGEngine()
    engine.register_generator("residential", ResidentialGenerator)

    output_path = os.path.join(output_dir, f"{name}.usda")
    result = engine.run(config, "residential", output_path=output_path)

    print(f"\n[{name}] 生成完成:")
    print(f"  文件: {result['output_path']}")
    print(f"  耗时: {result['total_time_seconds']:.3f}s")
    print(f"  文件大小: {result['file_size_bytes'] / 1024:.1f} KB")
    for k, v in result.items():
        if k not in ('output_path', 'total_time_seconds', 'file_size_bytes', 'generator_timings'):
            print(f"  {k}: {v}")

    return result['output_path']


def main():
    output_dir = "./output/residential"
    render_dir = "./output/residential/renders"
    os.makedirs(render_dir, exist_ok=True)

    styles = [
        {
            "name": "Slab_6F_2Unit",
            "label": "6层板楼\n一梯两户·三室一厅",
            "config": {
                "building_type": "slab",
                "num_floors": 6,
                "floor_height": 2.9,
                "building_depth": 12.0,
                "units_per_floor": 2,
                "unit_types": ["3BR", "3BR"],
                "core_width": 3.5,
                "balcony_type": "open",
                "roof_style": "pitched",
                "pitch_angle": 28.0,
                "has_ground_commercial": False,
            }
        },
        {
            "name": "Slab_18F_2Unit",
            "label": "18层小高层\n一梯两户·三室+两室",
            "config": {
                "building_type": "slab",
                "num_floors": 18,
                "floor_height": 2.9,
                "building_depth": 13.0,
                "units_per_floor": 2,
                "unit_types": ["3BR", "2BR"],
                "core_width": 4.0,
                "num_elevators": 1,
                "balcony_type": "enclosed",
                "roof_style": "flat",
                "parapet_height": 1.2,
                "has_ground_commercial": False,
            }
        },
        {
            "name": "Tower_33F_4Unit",
            "label": "33层高层塔楼\n两梯四户",
            "config": {
                "building_type": "tower",
                "num_floors": 33,
                "floor_height": 2.9,
                "building_depth": 18.0,
                "units_per_floor": 4,
                "unit_types": ["3BR", "2BR", "2BR", "3BR"],
                "core_width": 5.0,
                "num_elevators": 2,
                "balcony_type": "enclosed",
                "roof_style": "flat",
                "parapet_height": 1.5,
                "has_ground_commercial": False,
            }
        },
        {
            "name": "Slab_18F_Commercial",
            "label": "18层底商住宅\n一梯两户+底商",
            "config": {
                "building_type": "slab",
                "num_floors": 18,
                "floor_height": 2.9,
                "building_depth": 13.0,
                "units_per_floor": 2,
                "unit_types": ["3BR", "3BR"],
                "core_width": 4.0,
                "balcony_type": "enclosed",
                "roof_style": "flat",
                "parapet_height": 1.2,
                "has_ground_commercial": True,
                "commercial_floors": 2,
                "commercial_height": 4.0,
            }
        },
    ]

    # 生成所有建筑
    usd_files = []
    for style in styles:
        print(f"\n{'='*60}")
        print(f"生成: {style['label'].replace(chr(10), ' ')}")
        print(f"{'='*60}")
        usd_path = generate_residential(style["name"], style["config"], output_dir)
        usd_files.append((style, usd_path))

    # 渲染每栋建筑
    all_renders = []
    for style, usd_path in usd_files:
        print(f"\n渲染: {style['name']}...")
        renders = render_panoramic_views(usd_path, render_dir, f"res_{style['name']}")
        all_renders.append((style, renders))

    # 创建对比图
    print("\n创建对比图...")
    create_comparison(all_renders, render_dir)
    print(f"\n全部完成！渲染结果保存在: {render_dir}")


def create_comparison(all_renders, render_dir):
    """创建4种住宅形制的对比图。"""
    n = len(all_renders)
    fig, axes = plt.subplots(2, n, figsize=(7 * n, 14))

    fig.suptitle('Chinese Residential Building PCG - Style Comparison\n中国住宅小区商品房 PCG 形制对比',
                 fontsize=20, fontweight='bold', y=0.98)

    for col, (style, renders) in enumerate(all_renders):
        # 第一行：透视图
        persp_path = os.path.join(render_dir, f"res_{style['name']}_perspective_front.png")
        if os.path.exists(persp_path):
            img = Image.open(persp_path)
            axes[0, col].imshow(img)
        axes[0, col].set_title(f"{style['label']}\n(Perspective)", fontsize=11, fontweight='bold')
        axes[0, col].axis('off')

        # 第二行：鸟瞰图
        bird_path = os.path.join(render_dir, f"res_{style['name']}_bird_eye.png")
        if os.path.exists(bird_path):
            img = Image.open(bird_path)
            axes[1, col].imshow(img)
        axes[1, col].set_title(f"{style['label']}\n(Bird's Eye)", fontsize=11, fontweight='bold')
        axes[1, col].axis('off')

    plt.tight_layout(rect=[0, 0, 1, 0.93])
    path = os.path.join(render_dir, "residential_comparison.png")
    plt.savefig(path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()
    print(f"  对比图保存: {path}")


if __name__ == "__main__":
    main()
