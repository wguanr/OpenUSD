"""
测试住宅建筑对称布局优化效果。

测试场景：
1. 板楼·同户型对称: ["3BR"] → 完美轴对称
2. 板楼·异户型对称: ["3BR","2BR"] → 各自对称
3. 塔楼·同户型中心对称: ["3BR"] → 4户围绕核心筒
4. 塔楼·异户型中心对称: ["3BR","2BR"] → 南3BR+北2BR
"""

import sys
import os
import glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.image as mpimg

from pcg_core.engine import ResidentialConfig
from pcg_core.usd_bridge import UsdBridge
from pcg_core.floor_plan import FloorPlanFactory, UnitPlanPresets
from generators.residential_generator import ResidentialGenerator
from tools.render_usd import render_panoramic_views

OUTPUT_DIR = "output/symmetric"
os.makedirs(f"{OUTPUT_DIR}/renders", exist_ok=True)


def visualize_floor_plans():
    """可视化各种标准层平面，验证对称性。"""
    fig, axes = plt.subplots(2, 2, figsize=(20, 16))
    fig.suptitle('Floor Plan Symmetry Comparison', fontsize=16, fontweight='bold')

    configs = [
        ("Slab: 1×3BR (Symmetric)", "slab",
         FloorPlanFactory.create_slab_floor(["3BR"], core_width=4.0, units_per_floor=2)),
        ("Slab: 3BR+2BR", "slab",
         FloorPlanFactory.create_slab_floor(["3BR", "2BR"], core_width=4.0, units_per_floor=2)),
        ("Tower: 1×3BR (4 units)", "tower",
         FloorPlanFactory.create_tower_floor(["3BR"], core_width=6.0, core_depth=6.0, units_per_floor=4)),
        ("Tower: 3BR+2BR (4 units)", "tower",
         FloorPlanFactory.create_tower_floor(["3BR", "2BR"], core_width=6.0, core_depth=6.0, units_per_floor=4)),
    ]

    colors_by_facing = {
        'south': '#FFD700',   # 金色=南
        'north': '#4169E1',   # 蓝色=北
        'east': '#FF6347',    # 红色=东
        'west': '#32CD32',    # 绿色=西
        'interior': '#D3D3D3', # 灰色=内部
    }

    for idx, (title, btype, fp) in enumerate(configs):
        ax = axes[idx // 2][idx % 2]
        ax.set_title(title, fontsize=13, fontweight='bold')
        ax.set_aspect('equal')
        ax.grid(True, alpha=0.3)

        # 绘制每个户型的房间
        for pu in fp.placed_units:
            for room in pu.world_rooms():
                color = colors_by_facing.get(room.facing.value, '#D3D3D3')
                rect = plt.Rectangle(
                    (room.x, room.z), room.width, room.depth,
                    linewidth=1, edgecolor='black', facecolor=color, alpha=0.5
                )
                ax.add_patch(rect)
                # 房间名称
                cx = room.x + room.width / 2
                cz = room.z + room.depth / 2
                label = room.name
                if room.has_balcony:
                    label += "\n🏠"
                ax.text(cx, cz, label, ha='center', va='center', fontsize=6)

        # 绘制核心筒
        if fp.core:
            rect = plt.Rectangle(
                (fp.core.x, fp.core.z), fp.core.width, fp.core.depth,
                linewidth=2, edgecolor='red', facecolor='#FF9999', alpha=0.6
            )
            ax.add_patch(rect)
            ax.text(fp.core.center_x, fp.core.center_z, "CORE",
                    ha='center', va='center', fontsize=9, fontweight='bold', color='red')

        # 绘制合并轮廓
        outline = fp.compute_outline()
        if outline:
            ox = [p[0] for p in outline] + [outline[0][0]]
            oz = [p[1] for p in outline] + [outline[0][1]]
            ax.plot(ox, oz, 'k-', linewidth=2.5, label='Outline')

        # 绘制对称轴
        bounds = fp.compute_bounds()
        x_mid = (bounds[0] + bounds[2]) / 2
        z_mid = (bounds[1] + bounds[3]) / 2
        ax.axvline(x=x_mid, color='red', linestyle='--', alpha=0.5, label='X-axis')
        if btype == "tower":
            ax.axhline(y=z_mid, color='blue', linestyle='--', alpha=0.5, label='Z-axis')

        ax.set_xlabel('X (m)')
        ax.set_ylabel('Z (m)')
        ax.legend(loc='upper right', fontsize=8)

        # 自动调整范围
        margin = 2
        ax.set_xlim(bounds[0] - margin, bounds[2] + margin)
        ax.set_ylim(bounds[1] - margin, bounds[3] + margin)

    plt.tight_layout()
    out_path = f"{OUTPUT_DIR}/renders/floor_plan_symmetry.png"
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Floor plan visualization saved: {out_path}")


def generate_building(name, config):
    """生成一栋建筑并返回USD路径。"""
    config.output_dir = OUTPUT_DIR
    bridge = UsdBridge()
    gen = ResidentialGenerator(bridge, config)
    stats = gen.generate()

    usd_path = os.path.join(OUTPUT_DIR, f"{name}.usda")
    bridge.save(usd_path)

    print(f"\n=== {name} ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    return usd_path


def main():
    # 第一步：可视化标准层平面
    print("=== Visualizing floor plans ===")
    visualize_floor_plans()

    # 第二步：生成3D建筑
    configs = {
        # 1. 板楼·同户型完美对称
        "Slab_3BR_Sym": ResidentialConfig(
            building_name="Slab_3BR_Sym",
            building_type="slab",
            num_floors=6,
            floor_height=2.9,
            units_per_floor=2,
            unit_types=["3BR"],
            core_width=4.0,
            balcony_type="open",
            roof_style="pitched",
        ),
        # 2. 板楼·异户型对称
        "Slab_3BR_2BR": ResidentialConfig(
            building_name="Slab_3BR_2BR",
            building_type="slab",
            num_floors=18,
            floor_height=2.9,
            units_per_floor=2,
            unit_types=["3BR", "2BR"],
            core_width=4.0,
            balcony_type="enclosed",
            roof_style="flat",
        ),
        # 3. 塔楼·同户型中心对称
        "Tower_3BR_Sym": ResidentialConfig(
            building_name="Tower_3BR_Sym",
            building_type="tower",
            num_floors=33,
            floor_height=2.9,
            units_per_floor=4,
            unit_types=["3BR"],
            core_width=6.0,
            core_depth=6.0,
            num_elevators=2,
            balcony_type="enclosed",
            roof_style="flat",
        ),
        # 4. 塔楼·异户型中心对称
        "Tower_3BR_2BR": ResidentialConfig(
            building_name="Tower_3BR_2BR",
            building_type="tower",
            num_floors=25,
            floor_height=2.9,
            units_per_floor=4,
            unit_types=["3BR", "2BR"],
            core_width=6.0,
            core_depth=6.0,
            num_elevators=2,
            balcony_type="enclosed",
            roof_style="flat",
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

    # 第三步：渲染
    if usd_files:
        render_dir = f"{OUTPUT_DIR}/renders"
        for name, usd_path in usd_files.items():
            try:
                render_panoramic_views(usd_path, render_dir, prefix=name)
                print(f"  Rendered: {name}")
            except Exception as e:
                print(f"  Render error {name}: {e}")
                import traceback
                traceback.print_exc()

        # 对比图
        names = list(usd_files.keys())
        n = len(names)
        fig, axes = plt.subplots(1, n, figsize=(6 * n, 6))
        if n == 1:
            axes = [axes]
        for i, name in enumerate(names):
            pattern = os.path.join(render_dir, f"{name}_perspective_front.png")
            files = glob.glob(pattern)
            if files:
                img = mpimg.imread(files[0])
                axes[i].imshow(img)
            axes[i].set_title(name.replace('_', ' '), fontsize=10)
            axes[i].axis('off')
        plt.tight_layout()
        out_path = os.path.join(render_dir, "symmetric_comparison.png")
        plt.savefig(out_path, dpi=150, bbox_inches='tight')
        plt.close()
        print(f"  Comparison saved: {out_path}")

    print("\n=== All done ===")


if __name__ == "__main__":
    main()
