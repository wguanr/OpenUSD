"""
测试户型生成模块：生成多种户型模板的住宅建筑并渲染全景截图+平面图。

测试内容：
1. 6种户型模板的平面布局可视化
2. 同一模板不同seed的变体对比
3. 不同面宽参数的变体对比
4. 完整的3D建筑生成+渲染
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np

from pcg_core.unit_plan_generator import UnitPlanGenerator, TEMPLATE_REGISTRY
from pcg_core.floor_plan import (
    FloorPlanFactory, RoomType, Facing, WindowType,
)
from pcg_core.engine import ResidentialConfig
from pcg_core.usd_bridge import UsdBridge
from generators.residential_generator import ResidentialGenerator
from tools.render_usd import render_panoramic_views


# =============================================================================
# 颜色映射
# =============================================================================

ROOM_COLORS = {
    RoomType.LIVING: '#FFE4B5',      # 客厅 - 暖黄
    RoomType.DINING: '#FFDAB9',      # 餐厅 - 桃色
    RoomType.MASTER_BED: '#B0E0E6',  # 主卧 - 淡蓝
    RoomType.BEDROOM: '#ADD8E6',     # 次卧 - 浅蓝
    RoomType.KITCHEN: '#98FB98',     # 厨房 - 浅绿
    RoomType.BATHROOM: '#DDA0DD',    # 卫生间 - 淡紫
    RoomType.BALCONY: '#F0E68C',     # 阳台 - 卡其
    RoomType.CORRIDOR: '#D3D3D3',    # 走廊 - 灰色
    RoomType.STORAGE: '#F5DEB3',     # 储物间 - 小麦色
}

ROOM_LABELS = {
    RoomType.LIVING: '客厅',
    RoomType.DINING: '餐厅',
    RoomType.MASTER_BED: '主卧',
    RoomType.BEDROOM: '次卧',
    RoomType.KITCHEN: '厨房',
    RoomType.BATHROOM: '卫',
    RoomType.BALCONY: '阳台',
    RoomType.CORRIDOR: '走廊',
    RoomType.STORAGE: '书房',
}


def draw_unit_plan(ax, plan, title="", offset_x=0, offset_z=0):
    """绘制单个户型平面图。"""
    for room in plan.rooms:
        color = ROOM_COLORS.get(room.room_type, '#FFFFFF')
        rect = patches.Rectangle(
            (room.x + offset_x, room.z + offset_z),
            room.width, room.depth,
            linewidth=1.0, edgecolor='#333333',
            facecolor=color, alpha=0.8,
        )
        ax.add_patch(rect)

        # 房间标签
        label = ROOM_LABELS.get(room.room_type, room.name)
        cx = room.x + room.width / 2 + offset_x
        cz = room.z + room.depth / 2 + offset_z
        fontsize = max(5, min(8, room.width * 1.5))
        ax.text(cx, cz, label, ha='center', va='center',
                fontsize=fontsize, color='#333333', fontweight='bold')

        # 尺寸标注
        dim_text = f"{room.width:.1f}×{room.depth:.1f}"
        ax.text(cx, cz - 0.4, dim_text, ha='center', va='center',
                fontsize=max(4, fontsize - 2), color='#666666')

        # 标记阳台/空调位
        if room.has_balcony:
            ax.text(room.x + offset_x + 0.2, room.z_end + offset_z - 0.3,
                    '☐', fontsize=5, color='green')
        if room.has_ac_slot:
            ax.text(room.x_end + offset_x - 0.5, room.z + offset_z + 0.2,
                    'AC', fontsize=4, color='red')

    # 绘制轮廓
    outline = plan.outline()
    if outline:
        xs = [p[0] + offset_x for p in outline] + [outline[0][0] + offset_x]
        zs = [p[1] + offset_z for p in outline] + [outline[0][1] + offset_z]
        ax.plot(xs, zs, 'r-', linewidth=2.0, alpha=0.8)

    ax.set_title(title, fontsize=10, fontweight='bold')
    ax.set_aspect('equal')
    ax.grid(True, alpha=0.3)


def draw_floor_plan(ax, floor_plan, title=""):
    """绘制完整标准层平面图。"""
    # 绘制每个户型的房间
    for pu in floor_plan.placed_units:
        for room in pu.world_rooms():
            color = ROOM_COLORS.get(room.room_type, '#FFFFFF')
            rect = patches.Rectangle(
                (room.x, room.z), room.width, room.depth,
                linewidth=0.8, edgecolor='#333333',
                facecolor=color, alpha=0.7,
            )
            ax.add_patch(rect)

            label = ROOM_LABELS.get(room.room_type, room.name)
            cx = room.x + room.width / 2
            cz = room.z + room.depth / 2
            fontsize = max(4, min(7, room.width * 1.2))
            ax.text(cx, cz, label, ha='center', va='center',
                    fontsize=fontsize, color='#333333')

    # 绘制核心筒
    core = floor_plan.core
    rect = patches.Rectangle(
        (core.x, core.z), core.width, core.depth,
        linewidth=1.5, edgecolor='#8B0000',
        facecolor='#FFB6C1', alpha=0.5,
    )
    ax.add_patch(rect)
    ax.text(core.center_x, core.center_z, '核心筒',
            ha='center', va='center', fontsize=7, color='#8B0000',
            fontweight='bold')

    # 绘制合并轮廓
    outline = floor_plan.compute_outline()
    if outline:
        xs = [p[0] for p in outline] + [outline[0][0]]
        zs = [p[1] for p in outline] + [outline[0][1]]
        ax.plot(xs, zs, 'r-', linewidth=2.5, alpha=0.9)

    ax.set_title(title, fontsize=10, fontweight='bold')
    ax.set_aspect('equal')
    ax.grid(True, alpha=0.3)

    # 标注方向
    bounds = floor_plan.compute_bounds()
    ax.text((bounds[0] + bounds[1]) / 2, bounds[3] + 0.8, '南 (+Z)',
            ha='center', fontsize=8, color='red')
    ax.text((bounds[0] + bounds[1]) / 2, bounds[2] - 0.8, '北 (-Z)',
            ha='center', fontsize=8, color='blue')


# =============================================================================
# 测试1：6种户型模板的平面布局
# =============================================================================

def test_all_templates():
    """绘制6种户型模板的平面图。"""
    print("=== Test 1: 6种户型模板 ===")

    templates = ["studio", "compact_1br", "standard_2br",
                 "comfort_3br", "luxury_4br", "loft_duplex"]

    fig, axes = plt.subplots(2, 3, figsize=(24, 16))
    fig.suptitle('户型模板平面图 (Unit Plan Templates)', fontsize=16, fontweight='bold')

    for idx, tid in enumerate(templates):
        ax = axes[idx // 3][idx % 3]
        info = TEMPLATE_REGISTRY[tid]
        plan = UnitPlanGenerator.generate(tid, seed=42)

        title = f"{info.display_name} ({tid})\n{plan.total_width:.1f}m × {plan.total_depth:.1f}m"
        draw_unit_plan(ax, plan, title)

        # 设置坐标范围
        margin = 1.0
        ax.set_xlim(-margin, plan.total_width + margin)
        ax.set_ylim(-margin, plan.total_depth + margin)

    plt.tight_layout()
    plt.savefig(output_dir + '/all_templates.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: all_templates.png")


# =============================================================================
# 测试2：同一模板不同seed的变体对比
# =============================================================================

def test_seed_variants():
    """同一模板（3BR）不同seed生成的变体对比。"""
    print("=== Test 2: 3BR变体对比 (6个seed) ===")

    fig, axes = plt.subplots(2, 3, figsize=(24, 16))
    fig.suptitle('舒适三居 (comfort_3br) 随机变体对比', fontsize=16, fontweight='bold')

    for idx, seed in enumerate([1, 2, 3, 4, 5, 6]):
        ax = axes[idx // 3][idx % 3]
        plan = UnitPlanGenerator.random("3BR", seed=seed)

        title = f"seed={seed}\n{plan.total_width:.1f}m × {plan.total_depth:.1f}m | {len(plan.rooms)} rooms"
        draw_unit_plan(ax, plan, title)

        margin = 1.0
        ax.set_xlim(-margin, plan.total_width + margin)
        ax.set_ylim(-margin, plan.total_depth + margin)

    plt.tight_layout()
    plt.savefig(output_dir + '/3br_variants.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: 3br_variants.png")


# =============================================================================
# 测试3：不同面宽参数的变体
# =============================================================================

def test_bay_width_variants():
    """同一模板不同面宽参数的对比。"""
    print("=== Test 3: 面宽参数变体对比 ===")

    fig, axes = plt.subplots(2, 3, figsize=(24, 16))
    fig.suptitle('面宽参数对户型布局的影响', fontsize=16, fontweight='bold')

    configs = [
        ("comfort_3br", 10.0, "3BR 紧凑型 (10m)"),
        ("comfort_3br", 12.0, "3BR 标准型 (12m)"),
        ("comfort_3br", 14.0, "3BR 宽敞型 (14m)"),
        ("standard_2br", 7.5, "2BR 紧凑型 (7.5m)"),
        ("standard_2br", 9.0, "2BR 标准型 (9m)"),
        ("standard_2br", 10.5, "2BR 宽敞型 (10.5m)"),
    ]

    for idx, (tid, bw, label) in enumerate(configs):
        ax = axes[idx // 3][idx % 3]
        plan = UnitPlanGenerator.generate(tid, bay_width=bw, seed=42)

        title = f"{label}\n{plan.total_width:.1f}m × {plan.total_depth:.1f}m"
        draw_unit_plan(ax, plan, title)

        margin = 1.0
        ax.set_xlim(-margin, plan.total_width + margin)
        ax.set_ylim(-margin, plan.total_depth + margin)

    plt.tight_layout()
    plt.savefig(output_dir + '/bay_width_variants.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: bay_width_variants.png")


# =============================================================================
# 测试4：标准层平面布局（板楼+塔楼）
# =============================================================================

def test_floor_plans():
    """测试不同户型组合的标准层平面布局。"""
    print("=== Test 4: 标准层平面布局 ===")

    fig, axes = plt.subplots(2, 3, figsize=(28, 18))
    fig.suptitle('标准层平面布局 (Floor Plans)', fontsize=16, fontweight='bold')

    configs = [
        ("slab", ["comfort_3br"], 2, "板楼 一梯两户 3BR对称"),
        ("slab", ["comfort_3br", "standard_2br"], 2, "板楼 一梯两户 3BR+2BR"),
        ("slab", ["standard_2br"], 4, "板楼 一梯四户 2BR"),
        ("tower", ["comfort_3br"], 4, "塔楼 两梯四户 3BR"),
        ("tower", ["comfort_3br", "standard_2br"], 4, "塔楼 两梯四户 3BR+2BR"),
        ("slab", ["compact_1br"], 2, "板楼 一梯两户 1BR"),
    ]

    for idx, (btype, utypes, n_units, label) in enumerate(configs):
        ax = axes[idx // 3][idx % 3]

        if btype == "tower":
            fp = FloorPlanFactory.create_tower_floor(utypes, seed=42, units_per_floor=n_units)
        else:
            fp = FloorPlanFactory.create_slab_floor(utypes, seed=42, units_per_floor=n_units)

        draw_floor_plan(ax, fp, label)

        bounds = fp.compute_bounds()
        margin = 2.0
        ax.set_xlim(bounds[0] - margin, bounds[1] + margin)
        ax.set_ylim(bounds[2] - margin, bounds[3] + margin)

    plt.tight_layout()
    plt.savefig(output_dir + '/floor_plans.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: floor_plans.png")


# =============================================================================
# 测试5：完整3D建筑生成+渲染
# =============================================================================

def test_3d_buildings():
    """生成多种配置的3D住宅建筑并渲染。"""
    print("=== Test 5: 3D建筑生成+渲染 ===")

    buildings = [
        ("Slab_6F_3BR", ResidentialConfig(
            building_type="slab",
            num_floors=6,
            unit_types=["comfort_3br"],
            units_per_floor=2,
            seed=42,
        )),
        ("Slab_18F_3BR_2BR", ResidentialConfig(
            building_type="slab",
            num_floors=18,
            unit_types=["comfort_3br", "standard_2br"],
            units_per_floor=2,
            seed=100,
        )),
        ("Tower_33F_3BR", ResidentialConfig(
            building_type="tower",
            num_floors=33,
            unit_types=["comfort_3br"],
            units_per_floor=4,
            seed=42,
        )),
        ("Slab_6F_2BR_seed1", ResidentialConfig(
            building_type="slab",
            num_floors=6,
            unit_types=["standard_2br"],
            units_per_floor=2,
            seed=1,
        )),
        ("Slab_6F_2BR_seed99", ResidentialConfig(
            building_type="slab",
            num_floors=6,
            unit_types=["standard_2br"],
            units_per_floor=2,
            seed=99,
        )),
    ]

    usd_dir = output_dir + '/usd'
    render_dir = output_dir + '/renders'
    os.makedirs(usd_dir, exist_ok=True)
    os.makedirs(render_dir, exist_ok=True)

    for name, cfg in buildings:
        print(f"  Generating {name}...")
        bridge = UsdBridge()
        gen = ResidentialGenerator(bridge, cfg)
        result = gen.generate(parent_path="/World")

        usd_path = os.path.join(usd_dir, f"{name}.usda")
        bridge.save(usd_path)
        print(f"    USD saved: {usd_path}")
        print(f"    Stats: {result.get('stats', {})}")

        # 渲染
        render_panoramic_views(usd_path, render_dir, prefix=name)
        print(f"    Renders saved to: {render_dir}/{name}_*.png")

    # 对比图
    print("  Creating comparison chart...")
    fig, axes = plt.subplots(1, len(buildings), figsize=(6 * len(buildings), 8))
    if len(buildings) == 1:
        axes = [axes]

    for idx, (name, cfg) in enumerate(buildings):
        img_path = os.path.join(render_dir, f"{name}_perspective_front.png")
        if os.path.exists(img_path):
            img = plt.imread(img_path)
            axes[idx].imshow(img)
            axes[idx].set_title(name.replace('_', ' '), fontsize=10, fontweight='bold')
        axes[idx].axis('off')

    plt.suptitle('住宅建筑3D对比 (Unit Plan Generator)', fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig(render_dir + '/building_comparison.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: building_comparison.png")


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              'output', 'unit_templates')
    os.makedirs(output_dir, exist_ok=True)

    test_all_templates()
    test_seed_variants()
    test_bay_width_variants()
    test_floor_plans()
    test_3d_buildings()

    print("\n=== All tests completed! ===")
    print(f"Output directory: {output_dir}")
