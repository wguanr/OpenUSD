#!/usr/bin/env python3
"""
USD-PCG: 办公楼程序化生成 - 主入口。

用法:
    python main.py                          # 使用默认配置
    python main.py --config path/to/config.json
    python main.py --floors 10 --width 40 --depth 25
"""

import argparse
import json
import os
import sys
import time

# 确保模块路径正确
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pcg_core.engine import PCGEngine, BuildingConfig
from generators.building_generator import BuildingGenerator


def parse_args():
    parser = argparse.ArgumentParser(
        description="USD-PCG: 基于USD的高性能办公楼程序化生成系统"
    )
    parser.add_argument("--config", type=str, default=None,
                        help="JSON配置文件路径")
    parser.add_argument("--output", type=str, default=None,
                        help="输出USD文件路径")
    parser.add_argument("--floors", type=int, default=None,
                        help="楼层数")
    parser.add_argument("--width", type=float, default=None,
                        help="建筑宽度(米)")
    parser.add_argument("--depth", type=float, default=None,
                        help="建筑进深(米)")
    parser.add_argument("--name", type=str, default=None,
                        help="建筑名称")
    parser.add_argument("--no-interior", action="store_true",
                        help="不生成内部结构")
    parser.add_argument("--no-instancing", action="store_true",
                        help="不使用PointInstancer（用于性能对比）")
    parser.add_argument("--roof", type=str, choices=["flat", "parapet"],
                        default=None, help="屋顶样式")
    parser.add_argument("--format", type=str, choices=["usda", "usdc"],
                        default=None, help="输出格式")
    return parser.parse_args()


def main():
    args = parse_args()

    # 加载配置
    if args.config:
        with open(args.config, 'r') as f:
            config_data = json.load(f)
        config = BuildingConfig(**{k: tuple(v) if isinstance(v, list) else v
                                   for k, v in config_data.items()
                                   if k in BuildingConfig.__dataclass_fields__})
    else:
        config = BuildingConfig()

    # 命令行参数覆盖
    if args.floors is not None:
        config.num_floors = args.floors
    if args.width is not None:
        config.building_width = args.width
    if args.depth is not None:
        config.building_depth = args.depth
    if args.name is not None:
        config.building_name = args.name
    if args.no_interior:
        config.enable_interior = False
    if args.no_instancing:
        config.use_instancing = False
    if args.roof is not None:
        config.roof_style = args.roof
    if args.format is not None:
        config.output_format = args.format

    # 打印配置摘要
    print("=" * 60)
    print("  USD-PCG: 办公楼程序化生成系统")
    print("=" * 60)
    print(f"  建筑名称:     {config.building_name}")
    print(f"  楼层数:       {config.num_floors}")
    print(f"  建筑尺寸:     {config.building_width}m x {config.building_depth}m")
    print(f"  层高:         {config.floor_height}m")
    print(f"  总高度:       {config.num_floors * config.floor_height}m")
    print(f"  屋顶样式:     {config.roof_style}")
    print(f"  内部结构:     {'是' if config.enable_interior else '否'}")
    print(f"  PointInstancer: {'是' if config.use_instancing else '否'}")
    print(f"  输出格式:     {config.output_format}")
    print("=" * 60)

    # 创建引擎并注册生成器
    engine = PCGEngine()
    engine.register_generator("building", BuildingGenerator)

    # 执行生成
    print("\n开始生成...")
    start = time.perf_counter()

    result = engine.run(config, "building", output_path=args.output)

    total = time.perf_counter() - start

    # 打印结果
    print("\n" + "=" * 60)
    print("  生成完成!")
    print("=" * 60)
    print(f"  输出文件:     {result['output_path']}")
    print(f"  文件大小:     {result['file_size_bytes'] / 1024:.1f} KB")
    print(f"  总耗时:       {total:.4f}s")
    print()
    print("  生成统计:")
    for key, value in result.items():
        if key in ("output_path", "total_time_seconds", "generator_timings", "file_size_bytes"):
            continue
        print(f"    {key}: {value}")
    print()
    print("  各阶段耗时:")
    for stage_name, elapsed in result.get("generator_timings", {}).items():
        print(f"    {stage_name}: {elapsed:.4f}s")
    print("=" * 60)

    return result


if __name__ == "__main__":
    main()
