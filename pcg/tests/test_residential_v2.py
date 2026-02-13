"""
测试住宅建筑生成器 v2（户型平面驱动）。

生成多种户型组合的住宅建筑，渲染全景截图。
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pcg_core.engine import ResidentialConfig
from pcg_core.usd_bridge import UsdBridge
from generators.residential_generator import ResidentialGenerator
from tools.render_usd import render_panoramic_views

OUTPUT_DIR = "output/residential_v2"
os.makedirs(f"{OUTPUT_DIR}/renders", exist_ok=True)


def render_comparison_chart(usd_files, render_dir):
    """生成对比图。"""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.image as mpimg
    import glob

    names = list(usd_files.keys())
    n = len(names)
    fig, axes = plt.subplots(1, n, figsize=(6 * n, 6))
    if n == 1:
        axes = [axes]

    for i, name in enumerate(names):
        # 找到该建筑的front透视图
        pattern = os.path.join(render_dir, f"{name}_perspective_front.png")
        files = glob.glob(pattern)
        if not files:
            pattern = os.path.join(render_dir, f"{name}_panoramic.png")
            files = glob.glob(pattern)
        if files:
            img = mpimg.imread(files[0])
            axes[i].imshow(img)
        axes[i].set_title(name.replace('_', ' '), fontsize=10)
        axes[i].axis('off')

    plt.tight_layout()
    out_path = os.path.join(render_dir, "residential_v2_comparison.png")
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Comparison saved: {out_path}")


def generate_building(name: str, config: ResidentialConfig) -> str:
    """生成一栋住宅建筑并返回USD文件路径。"""
    config.output_dir = OUTPUT_DIR
    bridge = UsdBridge()
    gen = ResidentialGenerator(bridge, config)
    stats = gen.generate()

    usd_path = os.path.join(OUTPUT_DIR, f"{name}.usda")
    bridge.save(usd_path)

    print(f"\n=== {name} ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print(f"  USD: {usd_path}")

    return usd_path


def main():
    configs = {
        # 1. 6层板楼：一梯两户，3BR+2BR
        "Slab_6F_3BR_2BR": ResidentialConfig(
            building_name="Slab_6F_3BR_2BR",
            building_type="slab",
            num_floors=6,
            floor_height=2.9,
            units_per_floor=2,
            unit_types=["3BR", "2BR"],
            core_width=4.0,
            num_elevators=1,
            balcony_type="open",
            roof_style="pitched",
            pitch_angle=25.0,
        ),

        # 2. 18层小高层：一梯两户，3BR+3BR
        "Slab_18F_3BR_3BR": ResidentialConfig(
            building_name="Slab_18F_3BR_3BR",
            building_type="slab",
            num_floors=18,
            floor_height=2.9,
            units_per_floor=2,
            unit_types=["3BR", "3BR"],
            core_width=4.0,
            num_elevators=1,
            balcony_type="enclosed",
            roof_style="flat",
        ),

        # 3. 33层高层：一梯四户，4BR+3BR+3BR+2BR
        "Tower_33F_4Unit": ResidentialConfig(
            building_name="Tower_33F_4Unit",
            building_type="tower",
            num_floors=33,
            floor_height=2.9,
            units_per_floor=4,
            unit_types=["4BR", "3BR", "3BR", "2BR"],
            core_width=6.0,
            core_depth=6.0,
            num_elevators=2,
            balcony_type="enclosed",
            roof_style="flat",
        ),

        # 4. 18层底商住宅：底商2层+住宅16层
        "Slab_18F_Commercial": ResidentialConfig(
            building_name="Slab_18F_Commercial",
            building_type="slab",
            num_floors=18,
            floor_height=2.9,
            units_per_floor=2,
            unit_types=["3BR", "2BR"],
            core_width=4.0,
            num_elevators=1,
            has_ground_commercial=True,
            commercial_floors=2,
            commercial_height=4.0,
            balcony_type="enclosed",
            roof_style="flat",
        ),

        # 5. 6层板楼：一梯两户，2BR+2BR（经济适用型）
        "Slab_6F_2BR_2BR": ResidentialConfig(
            building_name="Slab_6F_2BR_2BR",
            building_type="slab",
            num_floors=6,
            floor_height=2.8,
            units_per_floor=2,
            unit_types=["2BR", "2BR"],
            core_width=3.5,
            num_elevators=0,
            balcony_type="open",
            roof_style="pitched",
            pitch_angle=30.0,
        ),
    }

    usd_files = {}
    for name, cfg in configs.items():
        try:
            usd_path = generate_building(name, cfg)
            usd_files[name] = usd_path
        except Exception as e:
            print(f"\nERROR generating {name}: {e}")
            import traceback
            traceback.print_exc()

    # 渲染
    if usd_files:
        render_dir = f"{OUTPUT_DIR}/renders"

        for name, usd_path in usd_files.items():
            try:
                render_panoramic_views(usd_path, render_dir, prefix=name)
                print(f"  Rendered panoramic: {name}")
            except Exception as e:
                print(f"  Render error {name}: {e}")
                import traceback
                traceback.print_exc()

        # 对比图
        try:
            render_comparison_chart(usd_files, render_dir)
        except Exception as e:
            print(f"  Comparison render error: {e}")

    print("\n=== All done ===")


if __name__ == "__main__":
    main()
