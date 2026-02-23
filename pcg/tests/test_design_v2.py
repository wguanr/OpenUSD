#!/usr/bin/env python3
"""
测试户型设计理念 v2：
1. 生成6种户型的平面图（标注动静分区、湿区、管井墙）
2. 生成多种建筑配置的3D渲染
3. 生成3BR随机变体对比图
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch
import numpy as np

from pcg_core.unit_plan_generator import UnitPlanGenerator, TEMPLATE_REGISTRY
from pcg_core.floor_plan import FloorPlanFactory, RoomType

# 分区颜色方案
ZONE_COLORS = {
    "dynamic":    "#FFD54F",   # 暖黄 - 动区
    "static":     "#81D4FA",   # 浅蓝 - 静区
    "wet":        "#A5D6A7",   # 浅绿 - 湿区
    "transition": "#E0E0E0",   # 灰色 - 过渡区
}

ZONE_LABELS = {
    "dynamic":    "动区 (客厅/餐厅)",
    "static":     "静区 (卧室/书房)",
    "wet":        "湿区 (厨房/卫生间)",
    "transition": "过渡区 (玄关/走廊)",
}

ROOM_TYPE_LABELS = {
    RoomType.LIVING: "客厅",
    RoomType.DINING: "餐厅",
    RoomType.MASTER_BED: "主卧",
    RoomType.BEDROOM: "次卧",
    RoomType.KITCHEN: "厨房",
    RoomType.BATHROOM: "卫生间",
    RoomType.BALCONY: "阳台",
    RoomType.CORRIDOR: "走廊",
    RoomType.STORAGE: "储物间",
    RoomType.ENTRANCE: "玄关",
    RoomType.STUDY: "书房",
    RoomType.WALK_IN_CLOSET: "衣帽间",
    RoomType.STAIRCASE: "楼梯间",
}


def draw_unit_plan(ax, plan, title="", show_labels=True):
    """绘制单个户型平面图，标注动静分区。"""
    ax.set_aspect("equal")
    ax.set_title(title, fontsize=10, fontweight="bold", pad=8)

    for room in plan.rooms:
        color = ZONE_COLORS.get(room.zone, "#FFFFFF")
        # 绘制房间矩形
        rect = FancyBboxPatch(
            (room.x, room.z), room.width, room.depth,
            boxstyle="round,pad=0.02",
            facecolor=color, edgecolor="#333333", linewidth=1.2,
            alpha=0.85,
        )
        ax.add_patch(rect)

        # 标注房间名称
        if show_labels:
            label = ROOM_TYPE_LABELS.get(room.room_type, room.name)
            fontsize = 7 if room.area < 5 else 8
            # 小房间缩短标签
            if room.width < 2.0 or room.depth < 2.0:
                label = label[:2]
                fontsize = 6

            ax.text(room.center_x, room.center_z, label,
                    ha="center", va="center", fontsize=fontsize,
                    color="#333333", fontweight="bold")

            # 标注尺寸
            dim_text = f"{room.width:.1f}×{room.depth:.1f}"
            ax.text(room.center_x, room.center_z - 0.5, dim_text,
                    ha="center", va="center", fontsize=5.5,
                    color="#666666")

        # 标注管井墙（红色虚线）
        if room.shares_pipe_wall:
            ax.plot([room.x, room.x], [room.z, room.z_end],
                    color="red", linewidth=1.5, linestyle="--", alpha=0.6)

        # 标注阳台（蓝色三角）
        if room.has_balcony:
            ax.annotate("▽", xy=(room.center_x, room.z_end),
                       fontsize=8, ha="center", va="bottom",
                       color="#1565C0")

        # 标注空调位（灰色方块）
        if room.has_ac_slot:
            ax.plot(room.x_end - 0.3, room.center_z, "s",
                    color="#757575", markersize=4)

    # 标注南北方向
    x_min = min(r.x for r in plan.rooms) - 0.5
    x_max = max(r.x_end for r in plan.rooms) + 0.5
    z_min = min(r.z for r in plan.rooms) - 0.5
    z_max = max(r.z_end for r in plan.rooms) + 0.5

    ax.annotate("南 (+Z)", xy=(x_min + (x_max - x_min) / 2, z_max),
               fontsize=7, ha="center", va="bottom", color="#D32F2F")
    ax.annotate("北 (-Z)", xy=(x_min + (x_max - x_min) / 2, z_min),
               fontsize=7, ha="center", va="top", color="#1565C0")

    ax.set_xlim(x_min, x_max)
    ax.set_ylim(z_min, z_max)
    ax.set_xlabel("X (面宽方向) / m", fontsize=7)
    ax.set_ylabel("Z (进深方向) / m", fontsize=7)
    ax.tick_params(labelsize=6)
    ax.grid(True, alpha=0.2)


def main():
    out_dir = "output/design_v2"
    os.makedirs(out_dir, exist_ok=True)

    # =========================================================
    # 1. 6种户型平面图（标注动静分区）
    # =========================================================
    print("=== 生成6种户型平面图 ===")
    fig, axes = plt.subplots(2, 3, figsize=(20, 14))
    fig.suptitle("户型平面设计 v2 — 动静分区 · 湿区集中 · 以客厅为核心",
                 fontsize=14, fontweight="bold", y=0.98)

    templates = list(TEMPLATE_REGISTRY.keys())
    for idx, tid in enumerate(templates):
        ax = axes[idx // 3][idx % 3]
        info = TEMPLATE_REGISTRY[tid]
        plan = UnitPlanGenerator.generate(tid, seed=42)
        title = f"{info.display_name} ({info.unit_type})\n{info.design_philosophy}"
        draw_unit_plan(ax, plan, title)

    # 添加图例
    legend_patches = [
        mpatches.Patch(color=ZONE_COLORS["dynamic"], label=ZONE_LABELS["dynamic"]),
        mpatches.Patch(color=ZONE_COLORS["static"], label=ZONE_LABELS["static"]),
        mpatches.Patch(color=ZONE_COLORS["wet"], label=ZONE_LABELS["wet"]),
        mpatches.Patch(color=ZONE_COLORS["transition"], label=ZONE_LABELS["transition"]),
    ]
    fig.legend(handles=legend_patches, loc="lower center", ncol=4,
              fontsize=10, frameon=True, fancybox=True)

    plt.tight_layout(rect=[0, 0.04, 1, 0.96])
    path1 = os.path.join(out_dir, "all_unit_plans_v2.png")
    fig.savefig(path1, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  保存: {path1}")

    # =========================================================
    # 2. 3BR三种变体对比
    # =========================================================
    print("\n=== 生成3BR变体对比 ===")
    fig, axes = plt.subplots(1, 3, figsize=(21, 7))
    fig.suptitle("舒适三居 (3BR) — 三种设计变体",
                 fontsize=13, fontweight="bold", y=0.98)

    variant_names = ["经典三室两厅两卫", "大客厅+北向次卧", "主卧套间"]
    # 用不同seed触发不同变体
    seeds_for_variants = []
    for s in range(1, 200):
        plan = UnitPlanGenerator.generate("3BR", seed=s)
        n_rooms = len(plan.rooms)
        has_closet = any(r.room_type == RoomType.WALK_IN_CLOSET for r in plan.rooms)
        has_dining = any(r.room_type == RoomType.DINING for r in plan.rooms)
        # 变体A: 有独立餐厅+无衣帽间 (经典)
        # 变体B: 无独立餐厅+无衣帽间 (大客厅)
        # 变体C: 有衣帽间 (主卧套间)
        if has_closet and len(seeds_for_variants) >= 2 and not any(
            sv[1] == "C" for sv in seeds_for_variants
        ):
            seeds_for_variants.append((s, "C"))
        elif has_dining and not has_closet and not any(
            sv[1] == "A" for sv in seeds_for_variants
        ):
            seeds_for_variants.append((s, "A"))
        elif not has_dining and not has_closet and not any(
            sv[1] == "B" for sv in seeds_for_variants
        ):
            seeds_for_variants.append((s, "B"))
        if len(seeds_for_variants) >= 3:
            break

    # 按A/B/C排序
    seeds_for_variants.sort(key=lambda x: x[1])
    for idx, (seed, variant) in enumerate(seeds_for_variants):
        ax = axes[idx]
        plan = UnitPlanGenerator.generate("3BR", seed=seed)
        vname = {"A": "变体A: 经典三室两厅两卫",
                 "B": "变体B: 大客厅+北向次卧",
                 "C": "变体C: 主卧套间"}[variant]
        draw_unit_plan(ax, plan, f"{vname}\n(seed={seed})")

    legend_patches = [
        mpatches.Patch(color=ZONE_COLORS["dynamic"], label=ZONE_LABELS["dynamic"]),
        mpatches.Patch(color=ZONE_COLORS["static"], label=ZONE_LABELS["static"]),
        mpatches.Patch(color=ZONE_COLORS["wet"], label=ZONE_LABELS["wet"]),
        mpatches.Patch(color=ZONE_COLORS["transition"], label=ZONE_LABELS["transition"]),
    ]
    fig.legend(handles=legend_patches, loc="lower center", ncol=4,
              fontsize=9, frameon=True)
    plt.tight_layout(rect=[0, 0.06, 1, 0.94])
    path2 = os.path.join(out_dir, "3br_variants_v2.png")
    fig.savefig(path2, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  保存: {path2}")

    # =========================================================
    # 3. 标准层平面布局（板楼+塔楼）
    # =========================================================
    print("\n=== 生成标准层平面布局 ===")
    fig, axes = plt.subplots(2, 2, figsize=(18, 14))
    fig.suptitle("标准层平面布局 — 对称排布",
                 fontsize=13, fontweight="bold", y=0.98)

    configs = [
        ("板楼 3BR×2 (轴对称)", "slab", ["3BR"], 2, 42),
        ("板楼 3BR+2BR (异型对称)", "slab", ["3BR", "2BR"], 2, 42),
        ("塔楼 3BR×4 (中心对称)", "tower", ["3BR"], 4, 42),
        ("塔楼 3BR+2BR×4 (双轴对称)", "tower", ["3BR", "2BR"], 4, 42),
    ]

    for idx, (title, btype, utypes, units, seed) in enumerate(configs):
        ax = axes[idx // 2][idx % 2]
        if btype == "slab":
            fp = FloorPlanFactory.create_slab_floor(utypes, units, seed=seed)
        else:
            fp = FloorPlanFactory.create_tower_floor(utypes, units, seed=seed)

        ax.set_aspect("equal")
        ax.set_title(title, fontsize=10, fontweight="bold")

        # 绘制所有户型的房间
        for pu in fp.placed_units:
            for room in pu.plan.rooms:
                color = ZONE_COLORS.get(room.zone, "#FFFFFF")
                rx = room.x + pu.offset_x
                rz = room.z + pu.offset_z
                rect = FancyBboxPatch(
                    (rx, rz), room.width, room.depth,
                    boxstyle="round,pad=0.01",
                    facecolor=color, edgecolor="#333333",
                    linewidth=0.8, alpha=0.8,
                )
                ax.add_patch(rect)
                label = ROOM_TYPE_LABELS.get(room.room_type, room.name)
                if room.width >= 1.5 and room.depth >= 1.5:
                    ax.text(rx + room.width / 2, rz + room.depth / 2,
                           label[:3], ha="center", va="center",
                           fontsize=5.5, color="#333")

        # 绘制核心筒
        core = fp.core
        cx, cz, cw, cd = core.x, core.z, core.width, core.depth
        core_rect = plt.Rectangle(
            (cx, cz), cw, cd,
            facecolor="#FFAB91", edgecolor="#BF360C",
            linewidth=1.5, alpha=0.7, linestyle="--",
        )
        ax.add_patch(core_rect)
        ax.text(cx + cw / 2, cz + cd / 2, "核心筒\n(电梯+楼梯)",
               ha="center", va="center", fontsize=6,
               color="#BF360C", fontweight="bold")

        # 绘制轮廓
        outline = fp.compute_outline()
        if outline:
            ox = [p[0] for p in outline] + [outline[0][0]]
            oz = [p[1] for p in outline] + [outline[0][1]]
            ax.plot(ox, oz, "b-", linewidth=1.5, alpha=0.5)

        # 绘制对称轴
        bounds = fp.compute_bounds()
        mid_x = (bounds[0] + bounds[2]) / 2
        mid_z = (bounds[1] + bounds[3]) / 2
        ax.axvline(x=mid_x, color="red", linewidth=0.8,
                  linestyle="--", alpha=0.4, label="对称轴")

        ax.set_xlim(bounds[0] - 1, bounds[2] + 1)
        ax.set_ylim(bounds[1] - 1, bounds[3] + 1)
        ax.set_xlabel("X / m", fontsize=7)
        ax.set_ylabel("Z / m", fontsize=7)
        ax.tick_params(labelsize=6)
        ax.grid(True, alpha=0.15)

    legend_patches = [
        mpatches.Patch(color=ZONE_COLORS["dynamic"], label="动区"),
        mpatches.Patch(color=ZONE_COLORS["static"], label="静区"),
        mpatches.Patch(color=ZONE_COLORS["wet"], label="湿区"),
        mpatches.Patch(color=ZONE_COLORS["transition"], label="过渡区"),
        mpatches.Patch(color="#FFAB91", label="核心筒"),
    ]
    fig.legend(handles=legend_patches, loc="lower center", ncol=5,
              fontsize=9, frameon=True)
    plt.tight_layout(rect=[0, 0.05, 1, 0.95])
    path3 = os.path.join(out_dir, "floor_plans_v2.png")
    fig.savefig(path3, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  保存: {path3}")

    # =========================================================
    # 4. 3D建筑渲染
    # =========================================================
    print("\n=== 生成3D建筑渲染 ===")
    from pcg_core.engine import ResidentialConfig
    from pcg_core.usd_bridge import UsdBridge
    from generators.residential_generator import ResidentialGenerator
    from tools.render_usd import render_panoramic_views

    render_dir = os.path.join(out_dir, "renders")
    os.makedirs(render_dir, exist_ok=True)

    building_configs = [
        ("Slab_6F_3BR", ResidentialConfig(
            building_type="slab", num_floors=6,
            unit_types=["3BR"], units_per_floor=2, seed=42,
        )),
        ("Slab_18F_3BR_2BR", ResidentialConfig(
            building_type="slab", num_floors=18,
            unit_types=["3BR", "2BR"], units_per_floor=2, seed=42,
        )),
        ("Tower_33F_3BR", ResidentialConfig(
            building_type="tower", num_floors=33,
            unit_types=["3BR"], units_per_floor=4, seed=42,
        )),
        ("Slab_18F_Commercial", ResidentialConfig(
            building_type="slab", num_floors=18,
            unit_types=["3BR", "2BR"], units_per_floor=2,
            has_ground_commercial=True, commercial_floors=2, seed=42,
        )),
    ]

    rendered_images = []
    for name, config in building_configs:
        print(f"\n  生成: {name}")
        usd_path = os.path.join(out_dir, f"{name}.usda")
        bridge = UsdBridge(usd_path)
        gen = ResidentialGenerator(bridge, config)
        gen.generate(f"/World/{name}")
        bridge.save()
        print(f"    USD: {usd_path}")

        views = render_panoramic_views(usd_path, render_dir, name)
        rendered_images.append((name, views))
        print(f"    渲染: {len(views)} 张")

    # 对比图
    print("\n=== 生成对比图 ===")
    n = len(rendered_images)
    fig, axes = plt.subplots(1, n, figsize=(6 * n, 6))
    if n == 1:
        axes = [axes]
    fig.suptitle("住宅建筑 v2 — 户型设计理念驱动",
                 fontsize=13, fontweight="bold")

    for idx, (name, views) in enumerate(rendered_images):
        ax = axes[idx]
        # 找透视图
        front_view = None
        for v in views:
            if "perspective_front" in v:
                front_view = v
                break
        if front_view is None and views:
            front_view = views[0]

        if front_view and os.path.exists(front_view):
            img = plt.imread(front_view)
            ax.imshow(img)
        ax.set_title(name.replace("_", " "), fontsize=9)
        ax.axis("off")

    plt.tight_layout()
    path4 = os.path.join(render_dir, "building_comparison_v2.png")
    fig.savefig(path4, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  保存: {path4}")

    print("\n=== 全部完成 ===")
    print(f"输出目录: {out_dir}")


if __name__ == "__main__":
    main()
