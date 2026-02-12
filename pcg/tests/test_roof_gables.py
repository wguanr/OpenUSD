#!/usr/bin/env python3
"""
测试屋顶山墙造型系统。

生成5种不同屋顶风格的办公楼，并渲染全景截图进行对比。
"""

import sys
import os
# 添加pcg根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pcg_core.engine import PCGEngine, BuildingConfig
from generators.building_generator import BuildingGenerator
from tools.render_usd import render_panoramic_views

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from PIL import Image


def generate_building(style_name, config_overrides, output_dir="./output"):
    """生成单栋建筑并返回USD文件路径。"""
    os.makedirs(output_dir, exist_ok=True)

    config = BuildingConfig(
        building_name=f"Building_{style_name}",
        num_floors=8,
        floor_height=3.5,
        building_width=30.0,
        building_depth=18.0,
        wall_thickness=0.3,
        footprint_type="rectangle",
        roof_style="flat",
        parapet_height=1.0,
        lobby_floors=1,
        lobby_height=5.0,
        seed=42,
        enable_interior=False,
        facade_styles={"default": "modern_glass"},
        output_dir=output_dir,
    )

    # 应用覆盖配置
    for k, v in config_overrides.items():
        setattr(config, k, v)

    engine = PCGEngine()
    engine.register_generator("building", BuildingGenerator)

    output_path = os.path.join(output_dir, f"{config.building_name}.usda")
    result = engine.run(config, "building", output_path=output_path)

    print(f"\n[{style_name}] 生成完成:")
    print(f"  文件: {result['output_path']}")
    print(f"  耗时: {result['total_time_seconds']:.3f}s")
    print(f"  文件大小: {result['file_size_bytes'] / 1024:.1f} KB")

    return result['output_path']


def main():
    output_dir = "./output/roof_gables"
    render_dir = "./output/roof_gables/renders"
    os.makedirs(render_dir, exist_ok=True)

    # 定义5种屋顶风格
    styles = [
        {
            "name": "parapet",
            "label": "Parapet (女儿墙)",
            "config": {
                "roof_style": "parapet",
                "parapet_height": 1.2,
            }
        },
        {
            "name": "pediment",
            "label": "Pediment (三角山墙)",
            "config": {
                "roof_style": "pediment",
                "parapet_height": 1.0,
                "gable_height": 3.0,
                "gable_width_ratio": 0.65,
                "gable_color": (0.55, 0.53, 0.50),
            }
        },
        {
            "name": "stepped",
            "label": "Stepped (阶梯山墙)",
            "config": {
                "roof_style": "stepped",
                "parapet_height": 1.0,
                "gable_height": 3.5,
                "gable_width_ratio": 0.7,
                "gable_steps": 5,
                "gable_color": (0.52, 0.50, 0.48),
            }
        },
        {
            "name": "crown",
            "label": "Crown (冠状山墙/Art Deco)",
            "config": {
                "roof_style": "crown",
                "parapet_height": 1.0,
                "gable_height": 4.0,
                "gable_width_ratio": 0.8,
                "gable_color": (0.58, 0.55, 0.50),
            }
        },
        {
            "name": "barrel",
            "label": "Barrel (弧形山墙)",
            "config": {
                "roof_style": "barrel",
                "parapet_height": 1.0,
                "gable_height": 2.5,
                "gable_width_ratio": 0.75,
                "gable_segments": 12,
                "gable_color": (0.50, 0.48, 0.46),
            }
        },
    ]

    # 生成所有建筑
    usd_files = []
    for style in styles:
        print(f"\n{'='*60}")
        print(f"生成: {style['label']}")
        print(f"{'='*60}")
        usd_path = generate_building(style["name"], style["config"], output_dir)
        usd_files.append((style, usd_path))

    # 渲染每栋建筑的全景截图
    all_renders = []
    for style, usd_path in usd_files:
        print(f"\n渲染: {style['label']}...")
        renders = render_panoramic_views(usd_path, render_dir, f"roof_{style['name']}")
        all_renders.append((style, renders))

    # 创建对比图：每种风格的透视图和鸟瞰图
    print("\n创建对比图...")
    create_comparison_figure(all_renders, render_dir)

    print(f"\n全部完成！渲染结果保存在: {render_dir}")


def create_comparison_figure(all_renders, render_dir):
    """创建5种屋顶风格的对比图。"""
    n = len(all_renders)
    fig, axes = plt.subplots(2, n, figsize=(6 * n, 12))

    fig.suptitle('Office Building Roof Gable Styles Comparison\n办公楼屋顶山墙造型对比',
                 fontsize=20, fontweight='bold', y=0.98)

    for col, (style, renders) in enumerate(all_renders):
        # 第一行：透视图（perspective_front）
        persp_img_path = os.path.join(render_dir, f"roof_{style['name']}_perspective_front.png")
        if os.path.exists(persp_img_path):
            img = Image.open(persp_img_path)
            axes[0, col].imshow(img)
        axes[0, col].set_title(f"{style['label']}\n(Perspective)", fontsize=12, fontweight='bold')
        axes[0, col].axis('off')

        # 第二行：鸟瞰图（bird_eye）
        bird_img_path = os.path.join(render_dir, f"roof_{style['name']}_bird_eye.png")
        if os.path.exists(bird_img_path):
            img = Image.open(bird_img_path)
            axes[1, col].imshow(img)
        axes[1, col].set_title(f"{style['label']}\n(Bird's Eye)", fontsize=12, fontweight='bold')
        axes[1, col].axis('off')

    plt.tight_layout(rect=[0, 0, 1, 0.94])
    comparison_path = os.path.join(render_dir, "roof_gables_comparison.png")
    plt.savefig(comparison_path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()
    print(f"  对比图保存: {comparison_path}")


if __name__ == "__main__":
    main()
