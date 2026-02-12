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

    # 底面轮廓类型
    footprint_type: str = "rectangle"  # "rectangle", "l_shape", "t_shape", "hexagon", "custom"
    footprint_params: dict = None      # 底面轮廓参数（根据类型不同）
    custom_vertices: list = None       # 自定义多边形顶点 [(x,z), ...]

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
    roof_style: str = "flat"        # "flat", "parapet", "pediment", "stepped", "crown", "barrel"
    parapet_height: float = 1.0     # 女儿墙高度
    roof_color: tuple = (0.5, 0.5, 0.52)

    # 山墙造型参数
    gable_height: float = 2.5       # 山墙高度(米)
    gable_width_ratio: float = 0.6  # 山墙宽度占边长比例(0.3~1.0)
    gable_edges: list = None        # 哪些边有山墙(默认None=自动选择最长的两条对边)
    gable_color: tuple = None       # 山墙颜色(默认None=与roof_color相同)
    gable_steps: int = 4            # 阶梯山墙的台阶数(stepped样式)
    gable_segments: int = 10        # 弧形山墙的分段数(barrel样式)

    # 内部布局参数
    enable_interior: bool = True
    corridor_width: float = 2.0     # 走廊宽度
    room_min_width: float = 4.0     # 最小房间宽度
    room_max_width: float = 8.0     # 最大房间宽度
    interior_wall_thickness: float = 0.15

    # 大厅层参数
    lobby_floors: int = 1           # 大厅占几层（1=单层大厅, 2=双层通高大厅, 0=无大厅）
    lobby_height: float = 0.0       # 大厅总高度(米)，0=自动计算(lobby_floors * floor_height)
    lobby_wall_type: str = "CurtainWall"  # 大厅外墙默认类型
    lobby_has_entrance: bool = True  # 大厅是否有入口门
    lobby_entrance_edges: list = None  # 哪些边有入口（默认[0]即前墙）
    lobby_color: tuple = (0.88, 0.86, 0.82)  # 大厅墙体颜色（略浅于标准层）

    # 墙体随机化
    randomize_walls: bool = True    # 是否随机拼接墙体模块

    # 分层外立面风格
    facade_styles: dict = None      # 分层风格配置
    # 格式一（区间模式）: {"lobby": "modern_glass", "low": "modern_mixed", "mid": "modern_glass", "high": "minimalist", "top": "classical"}
    # 格式二（精确楼层）: {"floor_0": "modern_glass", "floor_1": "classical", "default": "modern_mixed"}
    # 可用风格: default, modern_glass, modern_mixed, classical, industrial, minimalist, art_deco, brutalist

    # 性能参数
    use_instancing: bool = True     # 使用PointInstancer
    use_change_block: bool = True   # 使用SdfChangeBlock
    lod_level: int = 1              # LOD级别 (0=低, 1=中, 2=高)


# =============================================================================
# 户型单元配置
# =============================================================================

@dataclass
class UnitConfig:
    """单个户型单元的配置。"""
    unit_type: str = "3BR"           # "1BR"/"2BR"/"3BR"/"4BR" (几室)
    unit_width: float = 0.0          # 户型面宽(米)，0=自动计算
    num_bedrooms: int = 3            # 卧室数
    num_living_rooms: int = 1        # 客厅数
    has_balcony: bool = True         # 是否有南向阳台
    balcony_bays: int = 2            # 阳台占几个开间
    num_ac_units: int = 3            # 空调机位数

    @staticmethod
    def preset(unit_type: str) -> "UnitConfig":
        """根据户型类型返回预设配置。"""
        presets = {
            "1BR": UnitConfig(unit_type="1BR", unit_width=8.0,  num_bedrooms=1, num_living_rooms=1, balcony_bays=1, num_ac_units=2),
            "2BR": UnitConfig(unit_type="2BR", unit_width=10.0, num_bedrooms=2, num_living_rooms=1, balcony_bays=2, num_ac_units=3),
            "3BR": UnitConfig(unit_type="3BR", unit_width=12.0, num_bedrooms=3, num_living_rooms=1, balcony_bays=2, num_ac_units=4),
            "4BR": UnitConfig(unit_type="4BR", unit_width=14.0, num_bedrooms=4, num_living_rooms=2, balcony_bays=3, num_ac_units=5),
        }
        return presets.get(unit_type, presets["3BR"])


@dataclass
class ResidentialConfig(PCGConfig):
    """
    中国住宅小区商品房生成配置。

    核心概念：
      - 板楼(slab): 南北朝向的长条形建筑，一梯两户为主，南北通透
      - 塔楼(tower): 近正方形平面，一梯多户（4-6户），中央核心筒
      - 户型单元(unit): 以"几室几厅"为基本单位的重复模块
      - 核心筒(core): 楼梯间+电梯间的公共交通区域
    """
    # ── 建筑整体参数 ──
    building_name: str = "ResidentialBuilding"
    building_type: str = "slab"      # "slab"(板楼) / "tower"(塔楼)
    num_floors: int = 18             # 总层数
    floor_height: float = 2.9        # 标准层高(米)
    building_depth: float = 13.0     # 建筑进深(米) - 南北方向

    # ── 户型配置 ──
    units_per_floor: int = 2         # 每层户数
    unit_types: list = None          # 每户的户型类型列表, 如 ["3BR", "2BR"]
    # 如果为None，自动根据units_per_floor生成默认配置

    # ── 核心筒参数 ──
    core_width: float = 4.0          # 核心筒面宽(米)
    core_depth: float = 0.0          # 核心筒进深(米)，0=与建筑进深相同
    num_elevators: int = 1           # 电梯数量
    staircase_width: float = 2.6     # 楼梯间宽度

    # ── 外墙参数 ──
    wall_thickness: float = 0.25     # 外墙厚度
    wall_color: tuple = (0.88, 0.85, 0.78)   # 外墙颜色（暖白色）
    accent_color: tuple = (0.55, 0.45, 0.35)  # 点缀色（深棕色线条）
    floor_line_color: tuple = (0.6, 0.58, 0.55)  # 楼层分隔线颜色

    # ── 窗户参数 ──
    south_window_width: float = 2.0   # 南向窗宽(客厅/卧室)
    south_window_height: float = 1.8  # 南向窗高
    north_window_width: float = 1.2   # 北向窗宽(厨房/卫生间)
    north_window_height: float = 1.0  # 北向窗高
    window_sill_height: float = 0.9   # 窗台高度
    window_color: tuple = (0.55, 0.7, 0.85)  # 窗户颜色(浅蓝玻璃)

    # ── 阳台参数 ──
    balcony_depth: float = 1.5       # 阳台进深(米)
    balcony_railing_height: float = 1.1  # 阳台栏杆高度
    balcony_type: str = "enclosed"   # "open"(开放) / "enclosed"(封闭)
    balcony_glass_color: tuple = (0.65, 0.78, 0.88)  # 封闭阳台玻璃颜色
    balcony_slab_color: tuple = (0.75, 0.73, 0.70)   # 阳台板颜色

    # ── 空调机位参数 ──
    ac_unit_width: float = 0.9       # 空调机位宽度
    ac_unit_depth: float = 0.45      # 空调机位深度(外挑)
    ac_unit_height: float = 0.6      # 空调机位高度
    ac_unit_color: tuple = (0.7, 0.68, 0.65)  # 空调机位颜色(灰色格栅)

    # ── 底商参数 ──
    has_ground_commercial: bool = False  # 是否有底商
    commercial_floors: int = 1       # 底商层数
    commercial_height: float = 4.0   # 底商层高(米)
    shopfront_color: tuple = (0.3, 0.3, 0.32)  # 店面颜色(深色)

    # ── 入口参数 ──
    entrance_width: float = 3.0      # 入口门宽
    entrance_height: float = 3.0     # 入口门高
    has_entrance_canopy: bool = True  # 是否有入口雨棚
    canopy_depth: float = 2.0        # 雨棚出挑深度

    # ── 屋顶参数 ──
    roof_style: str = "flat"         # "flat"(平顶) / "pitched"(坡屋顶)
    parapet_height: float = 1.2      # 女儿墙高度
    roof_color: tuple = (0.5, 0.48, 0.45)
    pitch_angle: float = 25.0        # 坡屋顶角度(度)
    pitched_roof_color: tuple = (0.45, 0.25, 0.15)  # 坡屋顶颜色(红棕色)

    # ── 楼板参数 ──
    floor_thickness: float = 0.2     # 楼板厚度
    floor_color: tuple = (0.7, 0.7, 0.72)

    # ── 性能参数 ──
    use_instancing: bool = True


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
