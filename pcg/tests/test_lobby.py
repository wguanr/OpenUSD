"""
测试大厅层功能：单层大厅、双层通高大厅。
"""
import sys
sys.path.insert(0, "/home/ubuntu/usd_pcg")

from pcg_core.engine import PCGEngine, BuildingConfig
from generators.building_generator import BuildingGenerator

engine = PCGEngine()
engine.register_generator("building", BuildingGenerator)

# ============================================================
# 测试1: 单层大厅（lobby_floors=1）
# ============================================================
print("=" * 60)
print("TEST 1: 单层大厅办公楼 (8层, 矩形)")
print("=" * 60)

cfg1 = BuildingConfig(
    building_name="SingleLobby_8F",
    num_floors=8,
    floor_height=3.5,
    building_width=30.0,
    building_depth=20.0,
    footprint_type="rectangle",
    lobby_floors=1,          # 单层大厅
    lobby_height=0,          # 自动计算 = 1 * 3.5 = 3.5m
    lobby_wall_type="CurtainWall",
    lobby_has_entrance=True,
    lobby_entrance_edges=[0],  # 前墙有入口
    lobby_color=(0.88, 0.86, 0.82),
    randomize_walls=True,
    roof_style="parapet",
    seed=42,
    output_dir="./output",
)

result1 = engine.run(cfg1, "building")
print(f"  Output: {result1['output_path']}")
print(f"  Time: {result1['total_time_seconds']}s")
print(f"  Segments: {result1.get('num_wall_segments', 'N/A')}")
print(f"  Windows: {result1.get('num_windows', 'N/A')}")
print(f"  Lobby floors: {result1.get('lobby_floors', 'N/A')}")

# ============================================================
# 测试2: 双层通高大厅（lobby_floors=2）
# ============================================================
print()
print("=" * 60)
print("TEST 2: 双层通高大厅办公楼 (10层, 矩形)")
print("=" * 60)

cfg2 = BuildingConfig(
    building_name="DoubleLobby_10F",
    num_floors=10,
    floor_height=3.5,
    building_width=35.0,
    building_depth=22.0,
    footprint_type="rectangle",
    lobby_floors=2,          # 双层通高大厅
    lobby_height=8.0,        # 自定义大厅高度 8m（大于 2*3.5=7m）
    lobby_wall_type="CurtainWall",
    lobby_has_entrance=True,
    lobby_entrance_edges=[0],
    lobby_color=(0.90, 0.88, 0.84),
    randomize_walls=True,
    roof_style="parapet",
    seed=123,
    output_dir="./output",
)

result2 = engine.run(cfg2, "building")
print(f"  Output: {result2['output_path']}")
print(f"  Time: {result2['total_time_seconds']}s")
print(f"  Segments: {result2.get('num_wall_segments', 'N/A')}")
print(f"  Windows: {result2.get('num_windows', 'N/A')}")
print(f"  Lobby floors: {result2.get('lobby_floors', 'N/A')}")

# ============================================================
# 测试3: 双层通高大厅 + 六边形底面
# ============================================================
print()
print("=" * 60)
print("TEST 3: 双层通高大厅 + 六边形塔楼 (8层)")
print("=" * 60)

cfg3 = BuildingConfig(
    building_name="HexLobby_8F",
    num_floors=8,
    floor_height=3.5,
    building_width=20.0,
    building_depth=20.0,
    footprint_type="hexagon",
    lobby_floors=2,
    lobby_height=7.5,
    lobby_wall_type="CurtainWall",
    lobby_has_entrance=True,
    lobby_entrance_edges=[0],
    lobby_color=(0.90, 0.88, 0.84),
    randomize_walls=True,
    roof_style="parapet",
    seed=456,
    output_dir="./output",
)

result3 = engine.run(cfg3, "building")
print(f"  Output: {result3['output_path']}")
print(f"  Time: {result3['total_time_seconds']}s")
print(f"  Segments: {result3.get('num_wall_segments', 'N/A')}")
print(f"  Windows: {result3.get('num_windows', 'N/A')}")
print(f"  Lobby floors: {result3.get('lobby_floors', 'N/A')}")

# ============================================================
# 测试4: 无大厅（回归测试）
# ============================================================
print()
print("=" * 60)
print("TEST 4: 无大厅办公楼 (5层, 回归测试)")
print("=" * 60)

cfg4 = BuildingConfig(
    building_name="NoLobby_5F",
    num_floors=5,
    floor_height=3.5,
    building_width=30.0,
    building_depth=20.0,
    footprint_type="rectangle",
    lobby_floors=0,          # 无大厅
    randomize_walls=True,
    roof_style="flat",
    seed=42,
    output_dir="./output",
)

result4 = engine.run(cfg4, "building")
print(f"  Output: {result4['output_path']}")
print(f"  Time: {result4['total_time_seconds']}s")
print(f"  Segments: {result4.get('num_wall_segments', 'N/A')}")
print(f"  Windows: {result4.get('num_windows', 'N/A')}")
print(f"  Lobby floors: {result4.get('lobby_floors', 'N/A')}")

print()
print("ALL TESTS COMPLETED!")
