#!/usr/bin/env python3
"""
测试模块化墙体拼接系统：
  - 前墙: CurtainWall(12m) + DoorWall(3m) + CurtainWall(14.4m)
  - 右墙: WindowWall(19.4m)
  - 后墙: LouverWall(8m) + SolidWall(5.4m) + WindowWall(16m)
  - 左墙: MixedWall(19.4m)
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pcg_core.engine import BuildingConfig, PCGEngine
from pcg_core.wall_module import IWallSegment, WallLayout, WallEdge
from generators.building_generator import BuildingGenerator

# 导入所有墙段类型
import pcg_core.wall_segments  # noqa: F401


def test_mixed_facade():
    """测试混合立面：每面墙使用不同的墙段组合。"""
    config = BuildingConfig(
        building_name="MixedFacadeOffice",
        num_floors=5,
        floor_height=3.5,
        building_width=30.0,
        building_depth=20.0,
        wall_thickness=0.3,
        roof_style="parapet",
        parapet_height=1.0,
    )

    # 自定义墙体布局
    wt = config.wall_thickness
    fb_len = config.building_width - 2 * wt   # 29.4m
    lr_len = config.building_depth - 2 * wt   # 19.4m
    wall_h = config.floor_height - config.floor_thickness  # 3.2m

    # 定义每条边的墙段配置
    config.wall_layout = {
        "front": [
            {"type": "CurtainWall", "length": 12.0, "height": wall_h, "thickness": wt,
             "name": "front_curtain_L", "grid_cols": 8, "grid_rows": 3},
            {"type": "DoorWall", "length": 3.0, "height": wall_h, "thickness": wt,
             "name": "front_door", "door_width": 2.0, "door_height": 2.8},
            {"type": "CurtainWall", "length": fb_len - 12.0 - 3.0, "height": wall_h, "thickness": wt,
             "name": "front_curtain_R", "grid_cols": 10, "grid_rows": 3},
        ],
        "right": [
            {"type": "WindowWall", "length": lr_len, "height": wall_h, "thickness": wt,
             "name": "right_windows",
             "window_width": 1.8, "window_height": 1.5,
             "window_sill_height": 0.9, "window_spacing": 3.0},
        ],
        "back": [
            {"type": "LouverWall", "length": 8.0, "height": wall_h, "thickness": wt,
             "name": "back_louver", "louver_count": 15,
             "louver_start_height": 0.3, "louver_end_height": 2.8},
            {"type": "SolidWall", "length": 5.4, "height": wall_h, "thickness": wt,
             "name": "back_solid"},
            {"type": "WindowWall", "length": 16.0, "height": wall_h, "thickness": wt,
             "name": "back_windows",
             "window_width": 2.0, "window_height": 1.2,
             "window_sill_height": 1.0, "window_spacing": 3.5},
        ],
        "left": [
            {"type": "MixedWall", "length": lr_len, "height": wall_h, "thickness": wt,
             "name": "left_mixed",
             "split_height": 1.2, "window_width": 1.5,
             "window_height": 1.0, "window_spacing": 3.0},
        ],
    }

    engine = PCGEngine()
    engine.register_generator("building", BuildingGenerator)

    output_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "output", "mixed_facade_office.usda")
    result = engine.run(config, "building", output_path)

    print("=" * 60)
    print("  混合立面办公楼生成结果")
    print("=" * 60)
    for k, v in result.items():
        if k != "generator_timings":
            print(f"  {k}: {v}")
    print("\n  各阶段耗时:")
    for k, v in result.get("generator_timings", {}).items():
        print(f"    {k}: {v:.4f}s")
    print("=" * 60)

    return result


def test_all_solid():
    """测试全实墙建筑。"""
    config = BuildingConfig(
        building_name="SolidBuilding",
        num_floors=3,
        building_width=20.0,
        building_depth=15.0,
        wall_thickness=0.3,
        enable_interior=False,
    )

    wt = config.wall_thickness
    fb_len = config.building_width - 2 * wt
    lr_len = config.building_depth - 2 * wt
    wall_h = config.floor_height - config.floor_thickness

    config.wall_layout = {
        "front": [{"type": "SolidWall", "length": fb_len, "height": wall_h, "thickness": wt, "name": "front"}],
        "right": [{"type": "SolidWall", "length": lr_len, "height": wall_h, "thickness": wt, "name": "right"}],
        "back": [{"type": "SolidWall", "length": fb_len, "height": wall_h, "thickness": wt, "name": "back"}],
        "left": [{"type": "SolidWall", "length": lr_len, "height": wall_h, "thickness": wt, "name": "left"}],
    }

    engine = PCGEngine()
    engine.register_generator("building", BuildingGenerator)

    output_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "output", "solid_building.usda")
    result = engine.run(config, "building", output_path)

    print(f"\n全实墙建筑: {result['num_wall_segments']} segments, "
          f"{result['num_windows']} windows, {result['total_time_seconds']}s")

    return result


def test_all_curtain():
    """测试全幕墙建筑。"""
    config = BuildingConfig(
        building_name="CurtainWallTower",
        num_floors=8,
        building_width=25.0,
        building_depth=25.0,
        wall_thickness=0.2,
        enable_interior=False,
    )

    wt = config.wall_thickness
    fb_len = config.building_width - 2 * wt
    lr_len = config.building_depth - 2 * wt
    wall_h = config.floor_height - config.floor_thickness

    curtain_cfg = lambda name, length: {
        "type": "CurtainWall", "length": length, "height": wall_h, "thickness": wt,
        "name": name, "grid_cols": max(1, int(length / 1.2)), "grid_rows": 3,
    }

    config.wall_layout = {
        "front": [curtain_cfg("front", fb_len)],
        "right": [curtain_cfg("right", lr_len)],
        "back": [curtain_cfg("back", fb_len)],
        "left": [curtain_cfg("left", lr_len)],
    }

    engine = PCGEngine()
    engine.register_generator("building", BuildingGenerator)

    output_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "output", "curtain_wall_tower.usda")
    result = engine.run(config, "building", output_path)

    print(f"\n全幕墙大楼: {result['num_wall_segments']} segments, "
          f"{result['num_windows']} windows, {result['total_time_seconds']}s")

    return result


if __name__ == "__main__":
    print("=" * 60)
    print("  模块化墙体拼接系统测试")
    print("=" * 60)

    print("\n>>> 测试1: 混合立面办公楼")
    test_mixed_facade()

    print("\n>>> 测试2: 全实墙建筑")
    test_all_solid()

    print("\n>>> 测试3: 全幕墙大楼")
    test_all_curtain()

    print("\n所有测试完成!")
