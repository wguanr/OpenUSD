#!/usr/bin/env python3
"""
测试多边形底面建筑生成。

生成多种不同底面类型的建筑，验证多边形系统的正确性。
"""

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pcg_core.engine import PCGEngine, BuildingConfig
from generators.building_generator import BuildingGenerator


def test_building(name: str, config: BuildingConfig) -> dict:
    """测试一种建筑配置。"""
    engine = PCGEngine()
    engine.register_generator("building", BuildingGenerator)

    output_path = os.path.join(config.output_dir, f"{config.building_name}.usda")

    print(f"\n{'='*60}")
    print(f"  生成: {name}")
    print(f"  底面类型: {config.footprint_type}")
    print(f"  楼层数: {config.num_floors}")
    print(f"{'='*60}")

    start = time.perf_counter()
    result = engine.run(config, "building", output_path=output_path)
    elapsed = time.perf_counter() - start

    print(f"  ✓ 底面顶点数: {result.get('footprint_vertices', 'N/A')}")
    print(f"  ✓ 底面面积: {result.get('footprint_area_m2', 'N/A')} m²")
    print(f"  ✓ 包围盒: {result.get('bounding_box', 'N/A')}")
    print(f"  ✓ 墙段数: {result.get('num_wall_segments', 0)}")
    print(f"  ✓ 窗户数: {result.get('num_windows', 0)}")
    print(f"  ✓ 转角柱: {result.get('num_corner_columns', 0)}")
    print(f"  ✓ 楼板数: {result.get('num_floor_slabs', 0)}")
    print(f"  ✓ 耗时: {elapsed:.3f}s")
    print(f"  ✓ 文件: {result['output_path']}")
    print(f"  ✓ 大小: {result['file_size_bytes'] / 1024:.1f} KB")

    return result


def main():
    output_dir = "./output"
    os.makedirs(output_dir, exist_ok=True)

    results = {}

    # =========================================================================
    # 1. 矩形（回归测试）
    # =========================================================================
    cfg_rect = BuildingConfig(
        building_name="rect_office",
        num_floors=5,
        building_width=30.0,
        building_depth=20.0,
        footprint_type="rectangle",
        roof_style="parapet",
        output_dir=output_dir,
    )
    results["rectangle"] = test_building("矩形办公楼 (30x20m, 5层)", cfg_rect)

    # =========================================================================
    # 2. L形
    # =========================================================================
    cfg_l = BuildingConfig(
        building_name="l_shape_office",
        num_floors=4,
        building_width=30.0,
        building_depth=20.0,
        footprint_type="l_shape",
        footprint_params={"w1": 18.0, "d1": 20.0, "w2": 12.0, "d2": 10.0},
        roof_style="parapet",
        enable_interior=False,
        output_dir=output_dir,
    )
    results["l_shape"] = test_building("L形办公楼 (4层)", cfg_l)

    # =========================================================================
    # 3. T形
    # =========================================================================
    cfg_t = BuildingConfig(
        building_name="t_shape_office",
        num_floors=3,
        building_width=30.0,
        building_depth=20.0,
        footprint_type="t_shape",
        footprint_params={"w_main": 30.0, "d_main": 8.0, "w_stem": 12.0, "d_stem": 12.0},
        roof_style="parapet",
        enable_interior=False,
        output_dir=output_dir,
    )
    results["t_shape"] = test_building("T形办公楼 (3层)", cfg_t)

    # =========================================================================
    # 4. 六边形
    # =========================================================================
    cfg_hex = BuildingConfig(
        building_name="hexagon_tower",
        num_floors=6,
        building_width=20.0,
        building_depth=20.0,
        footprint_type="hexagon",
        footprint_params={"radius": 10.0},
        roof_style="parapet",
        enable_interior=False,
        output_dir=output_dir,
    )
    results["hexagon"] = test_building("六边形塔楼 (R=10m, 6层)", cfg_hex)

    # =========================================================================
    # 5. 八边形
    # =========================================================================
    cfg_oct = BuildingConfig(
        building_name="octagon_tower",
        num_floors=8,
        building_width=24.0,
        building_depth=24.0,
        footprint_type="octagon",
        footprint_params={"radius": 12.0},
        roof_style="parapet",
        enable_interior=False,
        output_dir=output_dir,
    )
    results["octagon"] = test_building("八边形塔楼 (R=12m, 8层)", cfg_oct)

    # =========================================================================
    # 汇总
    # =========================================================================
    print(f"\n{'='*60}")
    print(f"  全部测试完成！")
    print(f"{'='*60}")
    for name, r in results.items():
        print(f"  {name:12s}: {r.get('footprint_vertices', '?')}顶点, "
              f"{r.get('num_windows', 0)}窗, "
              f"{r.get('num_corner_columns', 0)}转角, "
              f"{r['total_time_seconds']:.3f}s")


if __name__ == "__main__":
    main()
