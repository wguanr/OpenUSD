#!/usr/bin/env python3
"""
高性能批量化测试生成脚本。

测试内容：
1. 单体生成性能测试（不同规模的建筑）
2. PointInstancer vs 逐个创建的性能对比
3. SdfChangeBlock性能验证
4. 并行批量生成测试（multiprocessing）
5. 大规模场景压力测试
"""

import os
import sys
import time
import json
import gc
from typing import Dict, Any, List
from multiprocessing import Pool, cpu_count
from dataclasses import asdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pcg_core.engine import PCGEngine, BuildingConfig
from generators.building_generator import BuildingGenerator


# =============================================================================
# 测试工具
# =============================================================================

class BenchmarkResult:
    """基准测试结果。"""

    def __init__(self, name: str):
        self.name = name
        self.results: List[Dict[str, Any]] = []

    def add(self, label: str, data: Dict[str, Any]):
        data["label"] = label
        self.results.append(data)

    def summary(self) -> str:
        lines = [f"\n{'='*70}", f"  基准测试: {self.name}", f"{'='*70}"]
        for r in self.results:
            lines.append(f"\n  [{r['label']}]")
            for k, v in r.items():
                if k == "label":
                    continue
                if isinstance(v, float):
                    lines.append(f"    {k}: {v:.4f}")
                else:
                    lines.append(f"    {k}: {v}")
        lines.append(f"{'='*70}\n")
        return "\n".join(lines)


def _generate_single_building(args: tuple) -> Dict[str, Any]:
    """单个建筑生成函数（用于multiprocessing）。"""
    config_dict, output_path = args

    # 在子进程中重新创建引擎
    engine = PCGEngine()
    engine.register_generator("building", BuildingGenerator)

    config = BuildingConfig(**{
        k: tuple(v) if isinstance(v, list) else v
        for k, v in config_dict.items()
        if k in BuildingConfig.__dataclass_fields__
    })

    result = engine.run(config, "building", output_path=output_path)
    return result


# =============================================================================
# 测试1: 单体生成性能（不同规模）
# =============================================================================

def test_scaling_performance(output_dir: str) -> BenchmarkResult:
    """测试不同规模建筑的生成性能。"""
    bench = BenchmarkResult("单体生成性能 - 规模扩展测试")

    test_cases = [
        {"name": "小型(3层)", "floors": 3, "width": 20, "depth": 15},
        {"name": "中型(5层)", "floors": 5, "width": 30, "depth": 20},
        {"name": "大型(10层)", "floors": 10, "width": 40, "depth": 25},
        {"name": "高层(20层)", "floors": 20, "width": 50, "depth": 30},
        {"name": "超高层(50层)", "floors": 50, "width": 60, "depth": 35},
        {"name": "极限(100层)", "floors": 100, "width": 80, "depth": 40},
    ]

    engine = PCGEngine()
    engine.register_generator("building", BuildingGenerator)

    for tc in test_cases:
        config = BuildingConfig(
            building_name=f"Scale_{tc['floors']}F",
            num_floors=tc["floors"],
            building_width=tc["width"],
            building_depth=tc["depth"],
            roof_style="parapet",
            use_instancing=True,
        )

        output_path = os.path.join(output_dir, f"scale_{tc['floors']}f.usda")

        gc.collect()
        start = time.perf_counter()
        result = engine.run(config, "building", output_path=output_path)
        elapsed = time.perf_counter() - start

        bench.add(tc["name"], {
            "楼层数": tc["floors"],
            "尺寸(m)": f"{tc['width']}x{tc['depth']}",
            "总高度(m)": tc["floors"] * 3.5,
            "窗户数": result.get("num_windows", 0),
            "房间数": result.get("num_rooms", 0),
            "总Prim数": result.get("num_walls", 0) + result.get("num_floor_slabs", 0) + result.get("num_rooms", 0),
            "生成时间(s)": elapsed,
            "文件大小(KB)": round(result["file_size_bytes"] / 1024, 1),
            "窗户/秒": round(result.get("num_windows", 0) / max(elapsed, 0.001)),
        })

    return bench


# =============================================================================
# 测试2: PointInstancer vs 逐个创建
# =============================================================================

def test_instancing_performance(output_dir: str) -> BenchmarkResult:
    """对比PointInstancer和逐个创建的性能差异。"""
    bench = BenchmarkResult("PointInstancer vs 逐个创建 性能对比")

    engine = PCGEngine()
    engine.register_generator("building", BuildingGenerator)

    for floors in [5, 10, 20, 50]:
        # 使用PointInstancer
        config_inst = BuildingConfig(
            building_name=f"Instanced_{floors}F",
            num_floors=floors,
            building_width=40,
            building_depth=25,
            use_instancing=True,
        )

        output_inst = os.path.join(output_dir, f"instanced_{floors}f.usda")
        gc.collect()
        start = time.perf_counter()
        result_inst = engine.run(config_inst, "building", output_path=output_inst)
        time_inst = time.perf_counter() - start
        size_inst = result_inst["file_size_bytes"]

        # 不使用PointInstancer
        config_no_inst = BuildingConfig(
            building_name=f"NoInstanced_{floors}F",
            num_floors=floors,
            building_width=40,
            building_depth=25,
            use_instancing=False,
        )

        output_no_inst = os.path.join(output_dir, f"no_instanced_{floors}f.usda")
        gc.collect()
        start = time.perf_counter()
        result_no_inst = engine.run(config_no_inst, "building", output_path=output_no_inst)
        time_no_inst = time.perf_counter() - start
        size_no_inst = result_no_inst["file_size_bytes"]

        bench.add(f"{floors}层建筑", {
            "窗户数": result_inst.get("num_windows", 0),
            "PointInstancer时间(s)": time_inst,
            "逐个创建时间(s)": time_no_inst,
            "时间加速比": round(time_no_inst / max(time_inst, 0.001), 2),
            "PointInstancer文件(KB)": round(size_inst / 1024, 1),
            "逐个创建文件(KB)": round(size_no_inst / 1024, 1),
            "文件大小比": round(size_no_inst / max(size_inst, 1), 2),
        })

    return bench


# =============================================================================
# 测试3: 并行批量生成
# =============================================================================

def test_parallel_generation(output_dir: str) -> BenchmarkResult:
    """测试并行批量生成多个建筑的性能。"""
    bench = BenchmarkResult("并行批量生成测试")

    # 定义一批不同参数的建筑
    building_configs = []
    for i in range(20):
        floors = 3 + (i % 10) * 2  # 3-21层
        width = 20 + (i % 5) * 10  # 20-60m
        depth = 15 + (i % 4) * 5   # 15-30m

        config = BuildingConfig(
            building_name=f"BatchBuilding_{i:03d}",
            num_floors=floors,
            building_width=width,
            building_depth=depth,
            seed=42 + i,
            roof_style="parapet" if i % 2 == 0 else "flat",
            use_instancing=True,
        )
        output_path = os.path.join(output_dir, f"batch_{i:03d}.usda")
        building_configs.append((asdict(config), output_path))

    num_buildings = len(building_configs)

    # 串行生成
    gc.collect()
    start = time.perf_counter()
    serial_results = []
    for args in building_configs:
        r = _generate_single_building(args)
        serial_results.append(r)
    serial_time = time.perf_counter() - start

    total_serial_size = sum(r["file_size_bytes"] for r in serial_results)
    total_serial_windows = sum(r.get("num_windows", 0) for r in serial_results)

    bench.add(f"串行生成 {num_buildings}栋建筑", {
        "建筑数量": num_buildings,
        "总窗户数": total_serial_windows,
        "总时间(s)": serial_time,
        "平均每栋(s)": round(serial_time / num_buildings, 4),
        "总文件大小(MB)": round(total_serial_size / 1024 / 1024, 2),
        "吞吐量(栋/秒)": round(num_buildings / serial_time, 2),
    })

    # 并行生成（使用所有可用核心）
    num_workers = min(cpu_count(), 4)  # 限制最大4个worker

    gc.collect()
    start = time.perf_counter()
    with Pool(processes=num_workers) as pool:
        parallel_results = pool.map(_generate_single_building, building_configs)
    parallel_time = time.perf_counter() - start

    total_parallel_size = sum(r["file_size_bytes"] for r in parallel_results)

    bench.add(f"并行生成 {num_buildings}栋建筑 ({num_workers}进程)", {
        "建筑数量": num_buildings,
        "工作进程数": num_workers,
        "总时间(s)": parallel_time,
        "平均每栋(s)": round(parallel_time / num_buildings, 4),
        "总文件大小(MB)": round(total_parallel_size / 1024 / 1024, 2),
        "吞吐量(栋/秒)": round(num_buildings / parallel_time, 2),
        "并行加速比": round(serial_time / max(parallel_time, 0.001), 2),
    })

    return bench


# =============================================================================
# 测试4: 大规模场景压力测试
# =============================================================================

def test_stress(output_dir: str) -> BenchmarkResult:
    """大规模场景压力测试。"""
    bench = BenchmarkResult("大规模场景压力测试")

    engine = PCGEngine()
    engine.register_generator("building", BuildingGenerator)

    # 测试1: 超大单体建筑
    config = BuildingConfig(
        building_name="MegaTower",
        num_floors=200,
        building_width=100,
        building_depth=50,
        use_instancing=True,
        roof_style="parapet",
    )

    output_path = os.path.join(output_dir, "mega_tower_200f.usda")
    gc.collect()
    start = time.perf_counter()
    result = engine.run(config, "building", output_path=output_path)
    elapsed = time.perf_counter() - start

    bench.add("200层超高层建筑", {
        "楼层数": 200,
        "尺寸(m)": "100x50",
        "总高度(m)": 700,
        "窗户数": result.get("num_windows", 0),
        "房间数": result.get("num_rooms", 0),
        "生成时间(s)": elapsed,
        "文件大小(MB)": round(result["file_size_bytes"] / 1024 / 1024, 2),
    })

    # 测试2: 批量生成50栋中型建筑
    configs = []
    for i in range(50):
        c = BuildingConfig(
            building_name=f"StressBuilding_{i:03d}",
            num_floors=5 + i % 15,
            building_width=20 + (i % 5) * 10,
            building_depth=15 + (i % 4) * 5,
            seed=100 + i,
            use_instancing=True,
        )
        configs.append((asdict(c), os.path.join(output_dir, f"stress_{i:03d}.usda")))

    gc.collect()
    start = time.perf_counter()
    num_workers = min(cpu_count(), 4)
    with Pool(processes=num_workers) as pool:
        stress_results = pool.map(_generate_single_building, configs)
    stress_time = time.perf_counter() - start

    total_windows = sum(r.get("num_windows", 0) for r in stress_results)
    total_rooms = sum(r.get("num_rooms", 0) for r in stress_results)
    total_size = sum(r["file_size_bytes"] for r in stress_results)

    bench.add(f"批量生成50栋建筑 ({num_workers}进程)", {
        "建筑数量": 50,
        "总窗户数": total_windows,
        "总房间数": total_rooms,
        "总时间(s)": stress_time,
        "吞吐量(栋/秒)": round(50 / stress_time, 2),
        "总文件大小(MB)": round(total_size / 1024 / 1024, 2),
    })

    return bench


# =============================================================================
# 主测试入口
# =============================================================================

def run_all_benchmarks():
    """运行所有基准测试。"""
    output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "benchmarks")
    os.makedirs(output_dir, exist_ok=True)

    print("=" * 70)
    print("  USD-PCG 高性能批量化测试")
    print(f"  CPU核心数: {cpu_count()}")
    print(f"  输出目录: {output_dir}")
    print("=" * 70)

    all_results = []

    # 测试1: 规模扩展
    print("\n>>> 运行测试1: 单体生成性能 - 规模扩展...")
    r1 = test_scaling_performance(output_dir)
    print(r1.summary())
    all_results.append(r1)

    # 测试2: 实例化对比
    print("\n>>> 运行测试2: PointInstancer vs 逐个创建...")
    r2 = test_instancing_performance(output_dir)
    print(r2.summary())
    all_results.append(r2)

    # 测试3: 并行生成
    print("\n>>> 运行测试3: 并行批量生成...")
    r3 = test_parallel_generation(output_dir)
    print(r3.summary())
    all_results.append(r3)

    # 测试4: 压力测试
    print("\n>>> 运行测试4: 大规模场景压力测试...")
    r4 = test_stress(output_dir)
    print(r4.summary())
    all_results.append(r4)

    # 保存测试结果
    report_path = os.path.join(output_dir, "benchmark_report.txt")
    with open(report_path, 'w') as f:
        f.write("USD-PCG 高性能批量化测试报告\n")
        f.write(f"CPU核心数: {cpu_count()}\n")
        f.write(f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        for r in all_results:
            f.write(r.summary())

    print(f"\n测试报告已保存到: {report_path}")

    # 保存JSON格式结果
    json_results = {}
    for r in all_results:
        json_results[r.name] = r.results

    json_path = os.path.join(output_dir, "benchmark_results.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(json_results, f, indent=2, ensure_ascii=False)

    print(f"JSON结果已保存到: {json_path}")

    return all_results


if __name__ == "__main__":
    run_all_benchmarks()
