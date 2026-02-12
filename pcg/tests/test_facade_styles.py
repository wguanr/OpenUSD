"""
测试分层外立面风格系统。

生成多种不同风格配置的建筑，验证：
  1. 不同楼层使用不同风格的墙段类型
  2. 区间模式和精确楼层模式都能正确工作
  3. 12种墙段类型都能正确生成
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pcg_core.engine import PCGEngine, BuildingConfig
from generators.building_generator import BuildingGenerator
import pcg_core.wall_segments  # noqa: F401


def run_building(config, output_path):
    """辅助函数：使用PCGEngine运行建筑生成。"""
    engine = PCGEngine()
    engine.register_generator("building", BuildingGenerator)
    return engine.run(config, "building", output_path=output_path)


def test_1_zone_mode():
    """测试1：区间模式 - 15层办公楼，4种区间风格"""
    config = BuildingConfig(
        building_name="ZoneStyle_15F",
        num_floors=15,
        building_width=30.0,
        building_depth=20.0,
        floor_height=4.0,
        seed=42,
        lobby_floors=2,
        lobby_height=8.0,
        randomize_walls=True,
        facade_styles={
            "lobby": "modern_glass",     # 大厅层：玻璃幕墙风格（由lobby系统处理）
            "low": "modern_mixed",       # 低区(3-7层)：现代混合
            "mid": "classical",          # 中区(8-11层)：古典
            "high": "minimalist",        # 高区(12-14层)：极简
            "top": "art_deco",           # 顶层(15层)：装饰艺术
        },
    )
    stats = run_building(config, f"output/ZoneStyle_15F.usda")
    print(f"\n=== Test 1: Zone Mode 15F ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    return stats


def test_2_floor_mode():
    """测试2：精确楼层模式 - 8层办公楼，每层不同风格"""
    config = BuildingConfig(
        building_name="FloorStyle_8F",
        num_floors=8,
        building_width=25.0,
        building_depth=18.0,
        floor_height=4.0,
        seed=123,
        lobby_floors=0,
        randomize_walls=True,
        facade_styles={
            "floor_0": "industrial",      # 1层：工业风
            "floor_1": "brutalist",       # 2层：粗野主义
            "floor_2": "classical",       # 3层：古典
            "floor_3": "modern_glass",    # 4层：玻璃幕墙
            "floor_4": "modern_mixed",    # 5层：现代混合
            "floor_5": "minimalist",      # 6层：极简
            "floor_6": "art_deco",        # 7层：装饰艺术
            "floor_7": "default",         # 8层：默认
        },
    )
    stats = run_building(config, f"output/FloorStyle_8F.usda")
    print(f"\n=== Test 2: Floor Mode 8F ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    return stats


def test_3_hex_mixed():
    """测试3：六边形建筑 + 区间模式"""
    config = BuildingConfig(
        building_name="HexMixed_10F",
        num_floors=10,
        building_width=20.0,
        building_depth=20.0,
        floor_height=3.5,
        footprint_type="hexagon",
        seed=77,
        lobby_floors=1,
        randomize_walls=True,
        facade_styles={
            "low": "modern_glass",
            "mid": "industrial",
            "high": "brutalist",
        },
    )
    stats = run_building(config, f"output/HexMixed_10F.usda")
    print(f"\n=== Test 3: Hex Mixed 10F ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    return stats


def test_4_all_12_types():
    """测试4：确保所有12种墙段类型都能被生成"""
    # 使用自定义权重确保所有类型都出现
    config = BuildingConfig(
        building_name="All12Types_5F",
        num_floors=5,
        building_width=60.0,  # 宽建筑，确保每层有足够多的墙段
        building_depth=40.0,
        floor_height=4.0,
        seed=999,
        lobby_floors=0,
        randomize_walls=True,
        facade_styles={
            # 使用自定义权重字符串，均匀分配所有12种类型
            "default": "SolidWall:10,WindowWall:10,DoorWall:10,CurtainWall:10,LouverWall:10,MixedWall:10,SpandrelWall:10,RibbonWindowWall:10,ColumnWall:10,ArchWall:10,BrickWall:10,PanelWall:10",
        },
    )
    stats = run_building(config, f"output/All12Types_5F.usda")
    print(f"\n=== Test 4: All 12 Types 5F ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")

    # 检查生成的USD文件中是否包含所有12种类型
    with open("output/All12Types_5F.usda", "r") as f:
        content = f.read()

    all_types = [
        "SolidWall", "WindowWall", "DoorWall", "CurtainWall",
        "LouverWall", "MixedWall", "SpandrelWall", "RibbonWindowWall",
        "ColumnWall", "ArchWall", "BrickWall", "PanelWall",
    ]
    found = []
    missing = []
    for t in all_types:
        if t in content:
            found.append(t)
        else:
            missing.append(t)

    print(f"\n  Found types ({len(found)}): {', '.join(found)}")
    if missing:
        print(f"  Missing types ({len(missing)}): {', '.join(missing)}")
    else:
        print(f"  ALL 12 types present!")

    return stats


if __name__ == "__main__":
    os.makedirs("output", exist_ok=True)
    test_1_zone_mode()
    test_2_floor_mode()
    test_3_hex_mixed()
    test_4_all_12_types()
    print("\n=== All facade style tests completed! ===")
