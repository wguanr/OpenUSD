"""
Wall Module System: 墙体模块化拼接系统。

核心抽象层，定义了墙段模块、连接器和拼接器的接口规范。
所有具体墙体类型（实墙、窗墙、门墙、幕墙等）都继承自 IWallSegment。

拼接坐标约定（墙段局部坐标系）：
  - X轴: 沿墙段长度方向（从 start 到 end）
  - Y轴: 沿墙段高度方向（向上）
  - Z轴: 沿墙段厚度方向（法线朝外为+Z，厚度向内为-Z）

  俯视图（一个墙段的局部坐标）:
      start                              end
        │                                  │
        │  ←── length ──→                  │
        │                                  │
    Z=0 ┌──────────────────────────────────┐  外表面
        │          Wall Body               │
   Z=-t └──────────────────────────────────┘  内表面
        │                                  │
      X=0                                X=length
"""

from __future__ import annotations
import math
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Any, Type
from pxr import Gf, Vt, UsdGeom

# 避免循环导入
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .usd_bridge import UsdBridge


# =============================================================================
# Connector: 连接器（模块的对接接口）
# =============================================================================

@dataclass
class Connector:
    """
    墙段模块的连接接口。

    每个墙段有两个连接器：start（左端）和 end（右端）。
    连接器定义了模块对接的几何参数。

    Attributes:
        local_position: 连接器在墙段局部坐标系中的位置
        normal: 连接面的法线方向（局部坐标系）
        width: 连接面宽度（= 墙体厚度）
        height: 连接面高度（= 墙体高度）
    """
    local_position: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    normal: Tuple[float, float, float] = (-1.0, 0.0, 0.0)
    width: float = 0.3    # = wall_thickness
    height: float = 3.2   # = wall_height


# =============================================================================
# WallSegmentResult: 墙段生成结果
# =============================================================================

@dataclass
class WallSegmentResult:
    """
    墙段生成后返回的结果数据。

    包含窗户位置（用于全局PointInstancer聚合）和统计信息。
    """
    window_positions: List[Tuple[float, float, float]] = field(default_factory=list)
    window_orientations: List[Tuple[float, float, float, float]] = field(default_factory=list)
    door_positions: List[Tuple[float, float, float]] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=dict)


# =============================================================================
# IWallSegment: 墙段模块抽象基类
# =============================================================================

class IWallSegment(ABC):
    """
    墙段模块的抽象基类。

    所有具体墙体类型（实墙、窗墙、门墙、幕墙等）都必须继承此类，
    并实现 generate_usd() 方法。

    每个墙段在自己的局部坐标系中生成几何体：
      - X: [0, length]  沿墙段长度
      - Y: [0, height]  沿墙段高度
      - Z: [0, -thickness]  厚度向内（外表面Z=0，内表面Z=-thickness）

    BuildingGenerator 负责通过 Xform 变换将墙段放置到正确的世界位置。
    """

    # 注册表：所有可用的墙段类型
    _registry: Dict[str, Type[IWallSegment]] = {}

    def __init__(self, length: float, height: float, thickness: float,
                 name: str = "segment", **kwargs):
        self.length = length
        self.height = height
        self.thickness = thickness
        self.name = name
        self.extra_params = kwargs

        # 自动创建连接器
        self.start_connector = Connector(
            local_position=(0.0, height / 2, -thickness / 2),
            normal=(-1.0, 0.0, 0.0),
            width=thickness,
            height=height,
        )
        self.end_connector = Connector(
            local_position=(length, height / 2, -thickness / 2),
            normal=(1.0, 0.0, 0.0),
            width=thickness,
            height=height,
        )

    @classmethod
    def register(cls, type_name: str):
        """装饰器：注册一个墙段类型到全局注册表。"""
        def decorator(subclass):
            cls._registry[type_name] = subclass
            subclass._type_name = type_name
            return subclass
        return decorator

    @classmethod
    def create(cls, type_name: str, **kwargs) -> IWallSegment:
        """工厂方法：根据类型名创建墙段实例。"""
        if type_name not in cls._registry:
            raise ValueError(
                f"Unknown wall segment type: '{type_name}'. "
                f"Available: {list(cls._registry.keys())}"
            )
        return cls._registry[type_name](**kwargs)

    @abstractmethod
    def generate_usd(self, bridge: UsdBridge, path: str) -> WallSegmentResult:
        """
        在给定的USD路径下生成该墙段的几何体。

        几何体在墙段局部坐标系中生成：
          - 外表面在 Z=0 平面
          - 内表面在 Z=-thickness 平面
          - 底面在 Y=0
          - 顶面在 Y=height
          - 左端面在 X=0
          - 右端面在 X=length

        Args:
            bridge: USD操作桥接层
            path: 该墙段的USD Prim路径

        Returns:
            WallSegmentResult 包含窗户位置等信息
        """
        pass

    def get_config_dict(self) -> Dict[str, Any]:
        """将此墙段的配置序列化为字典（用于JSON保存/加载）。"""
        d = {
            "type": getattr(self, '_type_name', self.__class__.__name__),
            "length": self.length,
            "height": self.height,
            "thickness": self.thickness,
            "name": self.name,
        }
        d.update(self.extra_params)
        return d


# =============================================================================
# IJoiner: 连接件抽象基类
# =============================================================================

class IJoiner(ABC):
    """
    连接件的抽象基类。

    连接件负责在两个墙段模块之间生成具象的几何连接体。
    最常见的连接件是90度转角柱。
    """

    @abstractmethod
    def generate_usd(self, bridge: UsdBridge, path: str,
                     position: Tuple[float, float, float],
                     height: float, thickness: float,
                     angle: float = 90.0,
                     display_color: Tuple[float, float, float] = (0.8, 0.77, 0.73)
                     ) -> None:
        """
        生成连接件的USD几何体。

        Args:
            bridge: USD操作桥接层
            path: USD Prim路径
            position: 连接件中心位置（世界坐标）
            height: 连接件高度
            thickness: 墙体厚度（决定连接件截面尺寸）
            angle: 两面墙之间的夹角（度）
            display_color: 显示颜色
        """
        pass


class CornerJoiner90(IJoiner):
    """
    90度转角连接件。

    生成一个 thickness x thickness 截面的实心柱体，
    用于填充两面正交墙体交接处的空隙。
    """

    def generate_usd(self, bridge: UsdBridge, path: str,
                     position: Tuple[float, float, float],
                     height: float, thickness: float,
                     angle: float = 90.0,
                     display_color: Tuple[float, float, float] = (0.8, 0.77, 0.73)
                     ) -> None:
        bridge.create_box_mesh(
            path,
            width=thickness,
            height=height,
            depth=thickness,
            translate=position,
            display_color=display_color
        )


class CornerJoinerGeneric(IJoiner):
    """
    通用角度转角连接件。

    支持任意角度的转角柱，通过四边形截面棱柱体实现。
    截面由 BuildingFootprint.corner_quad() 提供。
    """

    def generate_usd(self, bridge, path: str,
                     position: Tuple[float, float, float],
                     height: float, thickness: float,
                     angle: float = 90.0,
                     display_color: Tuple[float, float, float] = (0.8, 0.77, 0.73)
                     ) -> None:
        # 对于90度角，退化为简单box
        if abs(angle - 90.0) < 1.0:
            bridge.create_box_mesh(
                path,
                width=thickness,
                height=height,
                depth=thickness,
                translate=position,
                display_color=display_color
            )
        else:
            # 非90度角时，使用外部提供的quad截面
            # 这个方法会被 generate_usd_with_quad 覆盖
            bridge.create_box_mesh(
                path,
                width=thickness,
                height=height,
                depth=thickness,
                translate=position,
                display_color=display_color
            )

    def generate_usd_with_quad(self, bridge, path: str,
                                quad_xz: list,
                                y_bottom: float, y_top: float,
                                display_color: Tuple[float, float, float] = (0.8, 0.77, 0.73)
                                ) -> None:
        """
        使用精确的四边形截面生成转角柱。

        Args:
            bridge: USD操作桥接层
            path: USD Prim路径
            quad_xz: 四边形截面顶点 [(x,z), ...]
            y_bottom: 底部Y坐标
            y_top: 顶部Y坐标
            display_color: 显示颜色
        """
        bridge.create_prism_mesh(
            path,
            quad_xz=quad_xz,
            y_bottom=y_bottom,
            y_top=y_top,
            display_color=display_color
        )


class TJoiner(IJoiner):
    """
    T形连接件。

    用于一面墙与另一面墙的中间位置交接（如内墙与外墙的交接）。
    生成一个T形截面的柱体。
    """

    def generate_usd(self, bridge: UsdBridge, path: str,
                     position: Tuple[float, float, float],
                     height: float, thickness: float,
                     angle: float = 90.0,
                     display_color: Tuple[float, float, float] = (0.8, 0.77, 0.73)
                     ) -> None:
        # T形 = 一个横向条 + 一个纵向条
        xform = bridge.define_xform(path, translate=position)

        # 横向条（沿主墙方向）
        bridge.create_box_mesh(
            f"{path}/Cross",
            width=thickness * 3,
            height=height,
            depth=thickness,
            display_color=display_color
        )
        # 纵向条（垂直于主墙）
        bridge.create_box_mesh(
            f"{path}/Stem",
            width=thickness,
            height=height,
            depth=thickness * 2,
            translate=(0, 0, -thickness / 2),
            display_color=display_color
        )


# =============================================================================
# FacadeStyleRegistry: 外立面风格注册表
# =============================================================================

class FacadeStyleRegistry:
    """
    外立面风格注册表。

    管理多种预定义的建筑外立面风格，每种风格定义了一组墙段类型的权重分布。
    支持按楼层区间（大厅/低区/中区/高区/顶层）或按具体楼层指定风格。
    """

    # 预定义风格：{style_name: [(wall_type, weight), ...]}
    BUILTIN_STYLES: Dict[str, List[Tuple[str, int]]] = {
        "default": [
            ("WindowWall", 40), ("SolidWall", 20), ("CurtainWall", 15),
            ("LouverWall", 10), ("MixedWall", 10), ("DoorWall", 5),
        ],
        "modern_glass": [
            ("CurtainWall", 50), ("RibbonWindowWall", 20),
            ("PanelWall", 15), ("SolidWall", 15),
        ],
        "modern_mixed": [
            ("WindowWall", 30), ("CurtainWall", 20), ("PanelWall", 20),
            ("SpandrelWall", 15), ("SolidWall", 15),
        ],
        "classical": [
            ("ColumnWall", 30), ("ArchWall", 25), ("BrickWall", 20),
            ("WindowWall", 15), ("SolidWall", 10),
        ],
        "industrial": [
            ("PanelWall", 35), ("LouverWall", 25), ("SolidWall", 20),
            ("WindowWall", 15), ("DoorWall", 5),
        ],
        "minimalist": [
            ("SolidWall", 35), ("RibbonWindowWall", 30),
            ("WindowWall", 20), ("PanelWall", 15),
        ],
        "art_deco": [
            ("SpandrelWall", 30), ("ColumnWall", 25), ("PanelWall", 20),
            ("WindowWall", 15), ("SolidWall", 10),
        ],
        "brutalist": [
            ("SolidWall", 40), ("WindowWall", 25), ("LouverWall", 20),
            ("PanelWall", 15),
        ],
    }

    # 区间名称到楼层范围的默认映射
    DEFAULT_ZONE_RANGES = {
        "lobby": (0, 0),       # 大厅层（由lobby_floors控制）
        "low": (1, 5),         # 低区
        "mid": (6, 15),        # 中区
        "high": (16, 30),      # 高区
        "top": (31, 999),      # 顶层/冠部
    }

    @classmethod
    def get_style_weights(cls, style_name: str) -> List[Tuple[str, int]]:
        """获取指定风格的墙段类型权重列表。"""
        if style_name in cls.BUILTIN_STYLES:
            return cls.BUILTIN_STYLES[style_name]
        # 尝试解析自定义格式 "TypeA:30,TypeB:70"
        try:
            pairs = []
            for item in style_name.split(","):
                t, w = item.strip().split(":")
                pairs.append((t.strip(), int(w.strip())))
            return pairs
        except Exception:
            return cls.BUILTIN_STYLES["default"]

    @classmethod
    def resolve_style_for_floor(cls, floor_idx: int, facade_config: Optional[Dict[str, str]],
                                 lobby_floors: int = 0, num_floors: int = 10) -> str:
        """
        根据楼层索引和外立面配置，解析该层应使用的风格名称。

        支持两种配置格式：
          1. 区间模式: {"lobby": "modern_glass", "low": "modern_mixed", ...}
          2. 精确楼层模式: {"floor_0": "modern_glass", "floor_1": "classical", "default": "modern_mixed"}

        Args:
            floor_idx: 楼层索引（0-based）
            facade_config: 外立面配置字典
            lobby_floors: 大厅占几层
            num_floors: 总楼层数

        Returns:
            风格名称字符串
        """
        if not facade_config:
            return "default"

        # 1. 精确楼层模式
        floor_key = f"floor_{floor_idx}"
        if floor_key in facade_config:
            return facade_config[floor_key]

        # 2. 区间模式
        if floor_idx < lobby_floors and "lobby" in facade_config:
            return facade_config["lobby"]

        # 计算标准层索引（相对于大厅之上）
        std_floor = floor_idx - lobby_floors if lobby_floors > 0 else floor_idx
        total_std = num_floors - lobby_floors if lobby_floors > 0 else num_floors

        # 顶层（最后1-2层）
        if "top" in facade_config and std_floor >= total_std - 2 and total_std > 4:
            return facade_config["top"]

        # 高区
        if "high" in facade_config and std_floor >= total_std * 0.6:
            return facade_config["high"]

        # 中区
        if "mid" in facade_config and std_floor >= total_std * 0.3:
            return facade_config["mid"]

        # 低区
        if "low" in facade_config:
            return facade_config["low"]

        # 默认
        return facade_config.get("default", "default")

    @classmethod
    def register_style(cls, name: str, weights: List[Tuple[str, int]]) -> None:
        """注册自定义风格。"""
        cls.BUILTIN_STYLES[name] = weights


# =============================================================================
# WallEdge: 建筑的一条边
# =============================================================================

@dataclass
class WallEdge:
    """
    建筑外轮廓的一条边。

    定义了这条边的几何参数和墙段模块序列。

    Attributes:
        name: 边的名称（如 "front", "right", "back", "left"）
        start_point: 边的起点（世界坐标, XZ平面）
        end_point: 边的终点（世界坐标, XZ平面）
        segments: 沿这条边排列的墙段模块列表
    """
    name: str
    start_point: Tuple[float, float] = (0.0, 0.0)
    end_point: Tuple[float, float] = (0.0, 0.0)
    segments: List[IWallSegment] = field(default_factory=list)

    @property
    def edge_length(self) -> float:
        """计算这条边的总长度。"""
        dx = self.end_point[0] - self.start_point[0]
        dz = self.end_point[1] - self.start_point[1]
        return math.sqrt(dx * dx + dz * dz)

    @property
    def direction(self) -> Tuple[float, float]:
        """计算这条边的单位方向向量（XZ平面）。"""
        length = self.edge_length
        if length < 1e-6:
            return (1.0, 0.0)
        dx = self.end_point[0] - self.start_point[0]
        dz = self.end_point[1] - self.start_point[1]
        return (dx / length, dz / length)

    @property
    def outward_normal(self) -> Tuple[float, float]:
        """计算这条边的外法线方向（XZ平面，右手定则）。"""
        dx, dz = self.direction
        # 右手定则：direction × Y = outward normal
        return (dz, -dx)

    @property
    def total_segment_length(self) -> float:
        """所有墙段的总长度。"""
        return sum(s.length for s in self.segments)

    def heading_angle_deg(self) -> float:
        """这条边相对于+X轴的角度（度），用于Xform旋转。"""
        dx, dz = self.direction
        return math.degrees(math.atan2(-dz, dx))


# =============================================================================
# WallLayout: 建筑外壳的完整布局
# =============================================================================

@dataclass
class WallLayout:
    """
    建筑外壳的完整墙体布局。

    包含建筑外轮廓的所有边和它们上面的墙段模块序列。
    """
    edges: List[WallEdge] = field(default_factory=list)
    joiner: IJoiner = field(default_factory=CornerJoiner90)

    @classmethod
    def create_rectangular(cls, width: float, depth: float,
                           wall_thickness: float, wall_height: float,
                           edge_configs: Optional[Dict[str, List[Dict]]] = None,
                           default_segment_type: str = "WindowWall",
                           **default_segment_kwargs) -> WallLayout:
        """
        工厂方法：为矩形建筑创建墙体布局。

        Args:
            width: 建筑宽度(X方向)
            depth: 建筑深度(Z方向)
            wall_thickness: 墙体厚度
            wall_height: 墙体高度（单层净高）
            edge_configs: 每条边的墙段配置，如 {"front": [...], "right": [...]}
            default_segment_type: 默认墙段类型
            **default_segment_kwargs: 默认墙段的额外参数
        """
        wt = wall_thickness
        hw, hd = width / 2, depth / 2

        # 矩形建筑的四条边（逆时针，外法线朝外）
        # 注意：墙段长度要扣除转角柱的宽度
        edge_length_fb = width - 2 * wt   # 前后墙净长度
        edge_length_lr = depth - 2 * wt   # 左右墙净长度

        edge_defs = [
            # name, start(XZ), end(XZ), available_length
            ("front",  (-hw + wt, hd),  (hw - wt, hd),   edge_length_fb),
            ("right",  (hw, hd - wt),   (hw, -hd + wt),  edge_length_lr),
            ("back",   (hw - wt, -hd),  (-hw + wt, -hd), edge_length_fb),
            ("left",   (-hw, -hd + wt), (-hw, hd - wt),  edge_length_lr),
        ]

        edges = []
        for name, start, end, avail_len in edge_defs:
            segments = []

            if edge_configs and name in edge_configs:
                # 使用用户指定的墙段配置
                for seg_cfg in edge_configs[name]:
                    seg_type = seg_cfg.pop("type", default_segment_type)
                    seg_cfg.setdefault("height", wall_height)
                    seg_cfg.setdefault("thickness", wall_thickness)
                    segments.append(IWallSegment.create(seg_type, **seg_cfg))
            else:
                # 使用默认配置：整条边一个墙段
                kwargs = {
                    "length": avail_len,
                    "height": wall_height,
                    "thickness": wall_thickness,
                    "name": f"{name}_default",
                }
                kwargs.update(default_segment_kwargs)
                segments.append(IWallSegment.create(default_segment_type, **kwargs))

            edges.append(WallEdge(
                name=name,
                start_point=start,
                end_point=end,
                segments=segments,
            ))

        return cls(edges=edges)

    @classmethod
    def create_from_footprint(cls, footprint,
                              wall_thickness: float, wall_height: float,
                              edge_configs: Optional[Dict[int, List[Dict]]] = None,
                              default_segment_type: str = "WindowWall",
                              randomize: bool = False,
                              seed: int = 42,
                              style_name: str = "default",
                              **default_segment_kwargs) -> WallLayout:
        """
        工厂方法：从 BuildingFootprint 创建墙体布局。

        支持任意多边形底面，自动为每条边创建墙段。

        Args:
            footprint: BuildingFootprint 实例
            wall_thickness: 墙体厚度
            wall_height: 墙体高度（单层净高）
            edge_configs: 每条边的墙段配置，键为边索引 {0: [...], 1: [...]}
            default_segment_type: 默认墙段类型
            style_name: 外立面风格名称（用于随机填充时的墙段类型权重）
            **default_segment_kwargs: 默认墙段的额外参数
        """
        wt = wall_thickness
        edges = []

        for i in range(footprint.num_edges):
            # 计算这条边的净墙段长度（扣除两端转角柱）
            net_length = footprint.wall_edge_net_length(i, wt)

            # 计算墙段起点（扣除起始转角柱后的外轮廓点）
            start_pt = footprint.wall_edge_start_point(i, wt)

            # 计算墙段终点
            d = footprint.edge_direction(i)
            end_pt = (start_pt[0] + d[0] * net_length,
                      start_pt[1] + d[1] * net_length)

            edge_name = f"edge_{i}"
            segments = []

            if edge_configs and i in edge_configs:
                for seg_cfg in edge_configs[i]:
                    seg_cfg = dict(seg_cfg)  # 复制以避免修改原始数据
                    seg_type = seg_cfg.pop("type", default_segment_type)
                    seg_cfg.setdefault("height", wall_height)
                    seg_cfg.setdefault("thickness", wall_thickness)
                    segments.append(IWallSegment.create(seg_type, **seg_cfg))
            else:
                if net_length > 0.1:  # 边太短则跳过
                    if randomize:
                        segments = cls._random_fill_edge(
                            net_length, wall_height, wall_thickness,
                            edge_name, default_segment_kwargs,
                            seed=seed, edge_index=i,
                            style_name=style_name,
                        )
                    else:
                        kwargs = {
                            "length": net_length,
                            "height": wall_height,
                            "thickness": wall_thickness,
                            "name": f"{edge_name}_default",
                        }
                        kwargs.update(default_segment_kwargs)
                        segments.append(IWallSegment.create(default_segment_type, **kwargs))

            edges.append(WallEdge(
                name=edge_name,
                start_point=start_pt,
                end_point=end_pt,
                segments=segments,
            ))

        return cls(edges=edges, joiner=CornerJoinerGeneric())

    @classmethod
    def _random_fill_edge(cls, total_length: float, wall_height: float,
                          wall_thickness: float, edge_name: str,
                          default_kwargs: dict,
                          seed: int = 42, edge_index: int = 0,
                          style_name: str = "default",
                          ) -> List[IWallSegment]:
        """
        用随机规则填充一条边的墙段模块。

        策略：
          1. 将边分割为多个随机长度的墙段（每段 3~8m）
          2. 根据指定的外立面风格，按权重随机选择墙段类型
          3. 确保每条边至少有一个采光墙段
          4. 门墙需要足够的宽度
        """
        rng = random.Random(seed * 1000 + edge_index)

        # 从FacadeStyleRegistry获取当前风格的墙段类型权重
        wall_types_weights = FacadeStyleRegistry.get_style_weights(style_name)
        types = [t for t, _ in wall_types_weights]
        weights = [w for _, w in wall_types_weights]

        # 分割边为多个墙段
        min_seg_len = 3.0
        max_seg_len = 8.0

        segments = []
        remaining = total_length

        while remaining > 0.5:
            if remaining <= max_seg_len:
                seg_len = remaining
            else:
                seg_len = rng.uniform(min_seg_len, min(max_seg_len, remaining - min_seg_len))
                seg_len = round(seg_len, 2)

            # 随机选择墙段类型
            seg_type = rng.choices(types, weights=weights, k=1)[0]

            # 门墙需要足够的宽度
            if seg_type == "DoorWall" and seg_len < 2.5:
                seg_type = "SolidWall"

            # 构建参数
            kwargs = {
                "length": seg_len,
                "height": wall_height,
                "thickness": wall_thickness,
                "name": f"{edge_name}_seg{len(segments)}",
            }
            # 从默认参数中复制窗户相关参数
            for k in ["window_width", "window_height", "window_sill_height",
                      "window_spacing", "color"]:
                if k in default_kwargs:
                    kwargs[k] = default_kwargs[k]

            segments.append(IWallSegment.create(seg_type, **kwargs))
            remaining -= seg_len

        # 确保至少有一个窗墙或幕墙（采光保证）
        has_window = any(
            isinstance(s, IWallSegment) and
            getattr(s, '_type_name', '') in (
                'WindowWall', 'CurtainWall', 'MixedWall',
                'SpandrelWall', 'RibbonWindowWall', 'ColumnWall', 'ArchWall'
            )
            for s in segments
        )
        if not has_window and len(segments) > 0:
            # 把第一个墙段替换为窗墙
            old = segments[0]
            kwargs = {
                "length": old.length,
                "height": old.height,
                "thickness": old.thickness,
                "name": old.name,
            }
            for k in ["window_width", "window_height", "window_sill_height",
                      "window_spacing", "color"]:
                if k in default_kwargs:
                    kwargs[k] = default_kwargs[k]
            segments[0] = IWallSegment.create("WindowWall", **kwargs)

        return segments
