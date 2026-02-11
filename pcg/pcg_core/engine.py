"""
PCG Engine: 程序化内容生成引擎。

负责参数解析、规则执行和生成器调度。
"""

import json
import time
import os
from typing import Dict, Any, Optional, Type
from dataclasses import dataclass, field, asdict

from .usd_bridge import UsdBridge


@dataclass
class PCGConfig:
    """PCG生成配置的基类。"""
    seed: int = 42
    output_format: str = "usda"  # "usda" or "usdc"
    output_dir: str = "./output"

    @classmethod
    def from_json(cls, json_path: str) -> "PCGConfig":
        """从JSON文件加载配置。"""
        with open(json_path, 'r') as f:
            data = json.load(f)
        return cls(**data)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PCGConfig":
        """从字典创建配置。"""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典。"""
        return asdict(self)

    def to_json(self, filepath: str) -> None:
        """保存为JSON文件。"""
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        with open(filepath, 'w') as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)


@dataclass
class BuildingConfig(PCGConfig):
    """办公楼生成配置。"""
    # 建筑整体参数
    building_name: str = "OfficeBuilding"
    num_floors: int = 5
    floor_height: float = 3.5       # 每层高度(米)
    building_width: float = 30.0     # 建筑宽度(米) - X方向
    building_depth: float = 20.0     # 建筑进深(米) - Z方向

    # 外墙参数
    wall_thickness: float = 0.3      # 外墙厚度(米)
    wall_color: tuple = (0.85, 0.82, 0.78)  # 外墙颜色

    # 窗户参数
    window_width: float = 1.8       # 窗户宽度(米)
    window_height: float = 1.5      # 窗户高度(米)
    window_sill_height: float = 0.9  # 窗台高度(米)
    window_spacing: float = 3.0      # 窗户间距(米)
    window_color: tuple = (0.6, 0.75, 0.9)  # 窗户颜色(玻璃蓝)

    # 门参数
    door_width: float = 1.2         # 门宽度
    door_height: float = 2.4        # 门高度
    num_entrances: int = 1          # 入口数量

    # 楼板参数
    floor_thickness: float = 0.3    # 楼板厚度(米)
    floor_color: tuple = (0.7, 0.7, 0.72)

    # 屋顶参数
    roof_style: str = "flat"        # "flat" or "parapet"
    parapet_height: float = 1.0     # 女儿墙高度
    roof_color: tuple = (0.5, 0.5, 0.52)

    # 内部布局参数
    enable_interior: bool = True
    corridor_width: float = 2.0     # 走廊宽度
    room_min_width: float = 4.0     # 最小房间宽度
    room_max_width: float = 8.0     # 最大房间宽度
    interior_wall_thickness: float = 0.15

    # 性能参数
    use_instancing: bool = True     # 使用PointInstancer
    use_change_block: bool = True   # 使用SdfChangeBlock
    lod_level: int = 1              # LOD级别 (0=低, 1=中, 2=高)


class GeneratorBase:
    """生成器基类。"""

    def __init__(self, bridge: UsdBridge, config: PCGConfig):
        self.bridge = bridge
        self.config = config
        self._timings: Dict[str, float] = {}

    def generate(self, parent_path: str = "") -> Dict[str, Any]:
        """
        执行生成。子类必须实现此方法。

        Args:
            parent_path: 父Prim路径

        Returns:
            生成结果的元数据字典
        """
        raise NotImplementedError

    def _time_it(self, label: str):
        """返回一个计时上下文管理器。"""
        return _Timer(label, self._timings)

    def get_timings(self) -> Dict[str, float]:
        """获取各步骤的耗时统计。"""
        return self._timings.copy()


class _Timer:
    """简单的计时上下文管理器。"""

    def __init__(self, label: str, timings: Dict[str, float]):
        self.label = label
        self.timings = timings

    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, *args):
        elapsed = time.perf_counter() - self.start
        self.timings[self.label] = elapsed


class PCGEngine:
    """PCG引擎：协调配置解析和生成器调度。"""

    def __init__(self):
        self._generators: Dict[str, Type[GeneratorBase]] = {}

    def register_generator(self, name: str, generator_cls: Type[GeneratorBase]) -> None:
        """注册一个生成器类。"""
        self._generators[name] = generator_cls

    def run(self, config: PCGConfig, generator_name: str,
            output_path: Optional[str] = None) -> Dict[str, Any]:
        """
        运行PCG生成流程。

        Args:
            config: 生成配置
            generator_name: 要使用的生成器名称
            output_path: 输出文件路径

        Returns:
            包含生成结果元数据的字典
        """
        if generator_name not in self._generators:
            raise ValueError(f"Unknown generator: {generator_name}. "
                             f"Available: {list(self._generators.keys())}")

        # 确定输出路径
        if not output_path:
            os.makedirs(config.output_dir, exist_ok=True)
            ext = config.output_format
            output_path = os.path.join(
                config.output_dir,
                f"{getattr(config, 'building_name', 'pcg_output')}.{ext}"
            )

        # 创建USD Bridge
        bridge = UsdBridge(output_path)

        # 实例化生成器
        generator_cls = self._generators[generator_name]
        generator = generator_cls(bridge, config)

        # 执行生成
        start_time = time.perf_counter()
        result = generator.generate()
        total_time = time.perf_counter() - start_time

        # 保存
        saved_path = bridge.save()

        # 汇总结果
        result.update({
            "output_path": saved_path,
            "total_time_seconds": round(total_time, 4),
            "generator_timings": generator.get_timings(),
            "file_size_bytes": os.path.getsize(saved_path),
        })

        return result
