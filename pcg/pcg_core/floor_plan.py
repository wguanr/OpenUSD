"""
Floor Plan System: 户型平面驱动的住宅建筑布局系统。

数据模型层级：
  Room → UnitPlan → FloorPlan

核心思路：
  先设计每个户型的房间级平面布局，再将多个户型+核心筒拼合为标准层，
  由标准层的不规则轮廓决定整栋建筑的体块形态。

坐标约定（户型局部坐标）：
  - X轴: 面宽方向（东西向）
  - Z轴: 进深方向（+Z=南，-Z=北）
  - 原点: 户型西南角（左下角）
"""

from __future__ import annotations
import math
import copy
from typing import List, Tuple, Optional, Dict
from dataclasses import dataclass, field
from enum import Enum

try:
    from shapely.geometry import Polygon as ShapelyPolygon, MultiPolygon
    from shapely.ops import unary_union
    HAS_SHAPELY = True
except ImportError:
    HAS_SHAPELY = False

# 延迟导入，避免循环依赖
_unit_plan_generator = None

def _get_unit_plan_generator():
    """延迟导入 UnitPlanGenerator，避免循环依赖。"""
    global _unit_plan_generator
    if _unit_plan_generator is None:
        from pcg_core.unit_plan_generator import UnitPlanGenerator
        _unit_plan_generator = UnitPlanGenerator
    return _unit_plan_generator


# =============================================================================
# 枚举类型
# =============================================================================

class RoomType(Enum):
    """房间类型。"""
    LIVING = "living"           # 客厅
    DINING = "dining"           # 餐厅
    MASTER_BED = "master_bed"   # 主卧
    BEDROOM = "bedroom"         # 次卧
    KITCHEN = "kitchen"         # 厨房
    BATHROOM = "bathroom"       # 卫生间
    BALCONY = "balcony"         # 阳台（外挂）
    CORRIDOR = "corridor"       # 走廊/过道
    STORAGE = "storage"         # 储物间
    ENTRANCE = "entrance"       # 玄关
    STUDY = "study"             # 书房
    WALK_IN_CLOSET = "closet"   # 衣帽间
    STAIRCASE = "staircase"     # 楼梯间


class Zone(Enum):
    """动静分区标记。"""
    DYNAMIC = "dynamic"         # 动区：客厅、餐厅、厨房、玄关
    STATIC = "static"           # 静区：卧室、书房、儿童房
    WET = "wet"                 # 湿区：厨房、卫生间
    TRANSITION = "transition"   # 过渡区：走廊、玄关


class Facing(Enum):
    """朝向。"""
    SOUTH = "south"   # +Z
    NORTH = "north"   # -Z
    EAST = "east"     # +X
    WEST = "west"     # -X
    INTERIOR = "interior"  # 内部（无外墙）


class WindowType(Enum):
    """窗户类型。"""
    NONE = "none"
    SMALL = "small"             # 小窗（厨卫）
    STANDARD = "standard"       # 标准窗（卧室）
    LARGE = "large"             # 大窗（客厅）
    FLOOR_TO_CEILING = "ftc"    # 落地窗


# =============================================================================
# Room: 单个房间
# =============================================================================

@dataclass
class Room:
    """
    单个房间的平面定义。

    坐标相对于所属户型(UnitPlan)的局部坐标系。
    原点在户型的西南角（x_min, z_min处）。
    """
    room_type: RoomType
    width: float            # X方向面宽（米）
    depth: float            # Z方向进深（米）
    x: float                # 房间左下角X（相对户型原点）
    z: float                # 房间左下角Z（相对户型原点）
    name: str = ""          # 房间名称（用于USD路径）

    # 朝向与立面属性（由布局规则自动设置）
    facing: Facing = Facing.INTERIOR
    window_type: WindowType = WindowType.NONE
    has_balcony: bool = False
    has_ac_slot: bool = False

    # 设计属性
    zone: str = "transition"    # 动静分区: dynamic/static/wet/transition
    is_suite_part: bool = False # 是否属于套间（主卧套间内的主卫/衣帽间）
    shares_pipe_wall: bool = False  # 是否共享管井墙

    @property
    def x_end(self) -> float:
        return self.x + self.width

    @property
    def z_end(self) -> float:
        return self.z + self.depth

    @property
    def center_x(self) -> float:
        return self.x + self.width / 2

    @property
    def center_z(self) -> float:
        return self.z + self.depth / 2

    @property
    def area(self) -> float:
        return self.width * self.depth

    def corners(self) -> List[Tuple[float, float]]:
        """返回房间四个角点 [(x,z), ...] 逆时针。"""
        return [
            (self.x, self.z),
            (self.x_end, self.z),
            (self.x_end, self.z_end),
            (self.x, self.z_end),
        ]

    def south_edge(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        """南边缘（+Z面）。"""
        return ((self.x, self.z_end), (self.x_end, self.z_end))

    def north_edge(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        """北边缘（-Z面）。"""
        return ((self.x, self.z), (self.x_end, self.z))


# =============================================================================
# UnitPlan: 户型平面
# =============================================================================

@dataclass
class UnitPlan:
    """
    单个户型的完整平面布局。

    包含所有房间的位置和尺寸，以及户型的外轮廓多边形。
    """
    unit_type: str                  # "1BR"/"2BR"/"3BR"/"4BR"
    rooms: List[Room] = field(default_factory=list)
    total_width: float = 0.0       # 户型总面宽（自动计算）
    total_depth: float = 0.0       # 户型最大进深（自动计算）
    south_depth: float = 0.0       # 南区进深（客厅/卧室区）
    north_depth: float = 0.0       # 北区进深（厨卫区）

    def compute_bounds(self):
        """根据房间列表计算总面宽和总进深。"""
        if not self.rooms:
            return
        x_min = min(r.x for r in self.rooms)
        x_max = max(r.x_end for r in self.rooms)
        z_min = min(r.z for r in self.rooms)
        z_max = max(r.z_end for r in self.rooms)
        self.total_width = x_max - x_min
        self.total_depth = z_max - z_min

    def outline(self) -> List[Tuple[float, float]]:
        """
        计算户型外轮廓多边形。

        通过合并所有房间的矩形区域，生成不规则的外轮廓。
        使用扫描线法：按Z方向分层，每层取X方向的最小/最大值。
        """
        if not self.rooms:
            return []

        # 收集所有Z方向的分界线
        z_lines = set()
        for r in self.rooms:
            z_lines.add(r.z)
            z_lines.add(r.z_end)
        z_sorted = sorted(z_lines)

        # 对每个Z区间，计算X方向的覆盖范围
        slices = []  # [(z_bot, z_top, x_min, x_max), ...]
        for i in range(len(z_sorted) - 1):
            z_bot = z_sorted[i]
            z_top = z_sorted[i + 1]
            z_mid = (z_bot + z_top) / 2

            # 找出在此Z区间内的所有房间
            x_min = float('inf')
            x_max = float('-inf')
            for r in self.rooms:
                if r.z <= z_mid < r.z_end:
                    x_min = min(x_min, r.x)
                    x_max = max(x_max, r.x_end)

            if x_min < x_max:
                slices.append((z_bot, z_top, x_min, x_max))

        if not slices:
            return []

        # 从slices生成外轮廓多边形（逆时针）
        # 先沿南面（+Z）从左到右，再沿北面（-Z）从右到左
        outline_pts = []

        # 右侧轮廓（从南到北，沿X_max边）
        right_pts = []
        for z_bot, z_top, x_min, x_max in reversed(slices):
            right_pts.append((x_max, z_top))
            right_pts.append((x_max, z_bot))

        # 左侧轮廓（从北到南，沿X_min边）
        left_pts = []
        for z_bot, z_top, x_min, x_max in slices:
            left_pts.append((x_min, z_bot))
            left_pts.append((x_min, z_top))

        # 合并并去除重复/共线点
        raw = right_pts + left_pts
        outline_pts = _simplify_polygon(raw)

        return outline_pts

    def mirror_x(self, axis_x: float = 0.0) -> "UnitPlan":
        """
        沿X轴镜像户型（用于板楼左右对称布局）。

        镜像时同时翻转东西朝向，使镜像后的户型立面元素正确。

        Args:
            axis_x: 镜像轴的X坐标
        """
        mirrored = copy.deepcopy(self)
        for room in mirrored.rooms:
            # 镜像X坐标: new_x = 2*axis_x - (x + width)
            new_x = 2 * axis_x - room.x_end
            room.x = new_x
            # 翻转东西朝向
            if room.facing == Facing.EAST:
                room.facing = Facing.WEST
            elif room.facing == Facing.WEST:
                room.facing = Facing.EAST
        mirrored.compute_bounds()
        return mirrored

    def mirror_z(self, axis_z: float = 0.0) -> "UnitPlan":
        """
        沿Z轴镜像户型（用于塔楼南北对称布局）。

        镜像时同时翻转南北朝向。

        Args:
            axis_z: 镜像轴的Z坐标
        """
        mirrored = copy.deepcopy(self)
        for room in mirrored.rooms:
            # 镜像Z坐标: new_z = 2*axis_z - (z + depth)
            new_z = 2 * axis_z - room.z_end
            room.z = new_z
            # 翻转南北朝向
            if room.facing == Facing.SOUTH:
                room.facing = Facing.NORTH
            elif room.facing == Facing.NORTH:
                room.facing = Facing.SOUTH
            # 翻转阳台（南变北后不再有阳台，北变南后可能有）
            # 保持has_balcony不变，由立面生成器根据朝向决定
        mirrored.compute_bounds()
        return mirrored

    def translate(self, dx: float, dz: float) -> "UnitPlan":
        """平移户型。"""
        moved = copy.deepcopy(self)
        for room in moved.rooms:
            room.x += dx
            room.z += dz
        moved.compute_bounds()
        return moved

    def south_rooms(self) -> List[Room]:
        """获取所有朝南的房间。"""
        return [r for r in self.rooms if r.facing == Facing.SOUTH]

    def north_rooms(self) -> List[Room]:
        """获取所有朝北的房间。"""
        return [r for r in self.rooms if r.facing == Facing.NORTH]


# =============================================================================
# CorePlan: 核心筒平面
# =============================================================================

@dataclass
class CorePlan:
    """
    核心筒（楼梯间+电梯间）的平面定义。
    """
    width: float = 4.0          # X方向面宽
    depth: float = 6.0          # Z方向进深
    x: float = 0.0              # 左下角X
    z: float = 0.0              # 左下角Z
    num_elevators: int = 1
    staircase_width: float = 2.6

    @property
    def x_end(self) -> float:
        return self.x + self.width

    @property
    def z_end(self) -> float:
        return self.z + self.depth

    @property
    def center_x(self) -> float:
        return self.x + self.width / 2

    @property
    def center_z(self) -> float:
        return self.z + self.depth / 2

    def corners(self) -> List[Tuple[float, float]]:
        return [
            (self.x, self.z),
            (self.x_end, self.z),
            (self.x_end, self.z_end),
            (self.x, self.z_end),
        ]


# =============================================================================
# FloorPlan: 标准层平面
# =============================================================================

@dataclass
class PlacedUnit:
    """放置在标准层中的户型实例。"""
    plan: UnitPlan
    offset_x: float = 0.0      # 世界坐标X偏移
    offset_z: float = 0.0      # 世界坐标Z偏移
    mirrored: bool = False      # 是否X轴镜像
    index: int = 0              # 在楼层中的序号

    def world_rooms(self) -> List[Room]:
        """返回世界坐标下的房间列表。"""
        rooms = []
        for r in self.plan.rooms:
            wr = copy.deepcopy(r)
            wr.x += self.offset_x
            wr.z += self.offset_z
            rooms.append(wr)
        return rooms

    def world_outline(self) -> List[Tuple[float, float]]:
        """返回世界坐标下的户型轮廓。"""
        outline = self.plan.outline()
        return [(x + self.offset_x, z + self.offset_z) for x, z in outline]


@dataclass
class FloorPlan:
    """
    标准层完整平面。

    包含所有户型实例和核心筒，以及整层的合并轮廓。
    """
    placed_units: List[PlacedUnit] = field(default_factory=list)
    core: Optional[CorePlan] = None
    building_type: str = "slab"  # "slab" / "tower"

    def all_world_rooms(self) -> List[Room]:
        """获取所有户型的世界坐标房间列表。"""
        rooms = []
        for pu in self.placed_units:
            rooms.extend(pu.world_rooms())
        return rooms

    def compute_outline(self) -> List[Tuple[float, float]]:
        """
        计算整层的合并外轮廓。

        将所有户型轮廓和核心筒合并为一个外轮廓多边形。
        使用 shapely 做可靠的多边形 union。
        """
        # 收集所有矩形区域
        rects = []
        for pu in self.placed_units:
            for r in pu.world_rooms():
                rects.append((r.x, r.z, r.x_end, r.z_end))
        if self.core:
            rects.append((self.core.x, self.core.z, self.core.x_end, self.core.z_end))

        if not rects:
            return []

        if HAS_SHAPELY:
            return _union_rects_shapely(rects)
        else:
            return _union_rects_scanline(rects)

    def compute_bounds(self) -> Tuple[float, float, float, float]:
        """返回 (x_min, z_min, x_max, z_max)。"""
        outline = self.compute_outline()
        if not outline:
            return (0, 0, 0, 0)
        xs = [p[0] for p in outline]
        zs = [p[1] for p in outline]
        return (min(xs), min(zs), max(xs), max(zs))

    def building_width(self) -> float:
        x_min, _, x_max, _ = self.compute_bounds()
        return x_max - x_min

    def building_depth(self) -> float:
        _, z_min, _, z_max = self.compute_bounds()
        return z_max - z_min


# =============================================================================
# 户型预设生成器
# =============================================================================

class UnitPlanPresets:
    """
    中国住宅户型平面预设生成器。

    每种户型遵循中国住宅设计常理：
    - 客厅、主卧朝南（+Z面），有阳台
    - 厨房、卫生间朝北（-Z面）
    - 南北通透
    - 卧室为标准矩形
    - 户型不一定是规则矩形（南北区进深可能不同）
    """

    @staticmethod
    def create_1br() -> UnitPlan:
        """
        一室一厅户型（约45㎡）。

        平面布局：
        南(+Z)
        ┌─────────────────┐
        │ 客厅    │ 主卧   │  ← 南向
        │ 4.0×4.0 │3.6×3.8 │
        ├─────────┼────────┤
        │ 厨房    │ 卫生间  │  ← 北向
        │ 2.5×2.8 │2.0×2.8 │
        └─────────────────┘
        北(-Z)
        """
        south_d = 4.0   # 南区进深
        north_d = 2.8   # 北区进深
        total_d = south_d + north_d

        rooms = [
            # 南区（朝南）
            Room(RoomType.LIVING, width=4.0, depth=south_d, x=0, z=north_d,
                 name="Living", facing=Facing.SOUTH,
                 window_type=WindowType.LARGE, has_balcony=True),
            Room(RoomType.MASTER_BED, width=3.6, depth=3.8, x=4.0, z=north_d,
                 name="MasterBed", facing=Facing.SOUTH,
                 window_type=WindowType.STANDARD, has_balcony=False, has_ac_slot=True),
            # 北区（朝北）
            Room(RoomType.KITCHEN, width=2.5, depth=north_d, x=0, z=0,
                 name="Kitchen", facing=Facing.NORTH,
                 window_type=WindowType.SMALL, has_ac_slot=False),
            Room(RoomType.BATHROOM, width=2.0, depth=north_d, x=2.5, z=0,
                 name="Bathroom", facing=Facing.NORTH,
                 window_type=WindowType.SMALL),
            # 走廊（连接南北）
            Room(RoomType.CORRIDOR, width=3.1, depth=north_d, x=4.5, z=0,
                 name="Corridor", facing=Facing.NORTH,
                 window_type=WindowType.NONE),
        ]

        plan = UnitPlan(unit_type="1BR", rooms=rooms,
                        south_depth=south_d, north_depth=north_d)
        plan.compute_bounds()
        return plan

    @staticmethod
    def create_2br() -> UnitPlan:
        """
        两室一厅户型（约75㎡）。

        平面布局：
        南(+Z)
        ┌──────────────────────┐
        │ 客厅     │ 主卧      │  ← 南向
        │ 4.5×4.2  │ 3.8×3.8   │
        ├──────────┼───────────┤
        │ 厨房     │ 卫  │ 次卧  │  ← 北向
        │ 2.8×3.0  │2.0  │3.5×3.5│
        │          │×2.5 │       │
        └──────────────────────┘
        北(-Z)

        注意：次卧(3.5m深) > 厨卫(3.0m深)，形成南面凹口。
        """
        south_d = 4.2   # 南区进深（客厅/主卧）
        north_d = 3.0   # 北区进深（厨房/卫生间）
        bed2_d = 3.5    # 次卧进深（比北区深，形成凹口）

        rooms = [
            # 南区
            Room(RoomType.LIVING, width=4.5, depth=south_d, x=0, z=north_d,
                 name="Living", facing=Facing.SOUTH,
                 window_type=WindowType.LARGE, has_balcony=True),
            Room(RoomType.MASTER_BED, width=3.8, depth=3.8, x=4.5, z=north_d,
                 name="MasterBed", facing=Facing.SOUTH,
                 window_type=WindowType.STANDARD, has_balcony=True, has_ac_slot=True),
            # 北区
            Room(RoomType.KITCHEN, width=2.8, depth=north_d, x=0, z=0,
                 name="Kitchen", facing=Facing.NORTH,
                 window_type=WindowType.SMALL),
            Room(RoomType.BATHROOM, width=2.0, depth=2.5, x=2.8, z=0,
                 name="Bathroom", facing=Facing.NORTH,
                 window_type=WindowType.SMALL),
            # 次卧（北向，比厨卫深，南面凸出）
            Room(RoomType.BEDROOM, width=3.5, depth=bed2_d, x=4.8, z=0,
                 name="Bedroom2", facing=Facing.NORTH,
                 window_type=WindowType.STANDARD, has_ac_slot=True),
            # 走廊
            Room(RoomType.CORRIDOR, width=1.7, depth=north_d, x=2.8, z=0.0,
                 name="Corridor", facing=Facing.INTERIOR,
                 window_type=WindowType.NONE),
        ]

        plan = UnitPlan(unit_type="2BR", rooms=rooms,
                        south_depth=south_d, north_depth=north_d)
        plan.compute_bounds()
        return plan

    @staticmethod
    def create_3br() -> UnitPlan:
        """
        三室一厅户型（约110㎡）。

        平面布局：
        南(+Z)
        ┌─────────────────────────────────┐
        │ 主卧      │ 客厅       │ 次卧A  │  ← 南向
        │ 3.9×4.0   │ 5.0×4.5    │3.5×3.5 │
        ├───────────┼────────────┤        │
        │ 卫A │走廊  │ 餐厅+厨房  │ 次卧A  │
        │2.0  │1.2   │ 3.5×3.2   │(续)    │
        │×2.5 │×3.2  │           ├────────┤
        │     │      │           │ 卫B    │  ← 北向
        │     │      │           │2.2×2.0 │
        └─────────────────────────────────┘
        北(-Z)

        特征：主卧+客厅+次卧A朝南，厨房+卫生间朝北。
        次卧A从南延伸到北（南北通透），形成东侧凸出。
        """
        south_d = 4.5   # 南区进深
        north_d = 3.2   # 北区进深
        total_d = south_d + north_d

        rooms = [
            # 南区
            Room(RoomType.MASTER_BED, width=3.9, depth=4.0, x=0, z=north_d,
                 name="MasterBed", facing=Facing.SOUTH,
                 window_type=WindowType.STANDARD, has_balcony=True, has_ac_slot=True),
            Room(RoomType.LIVING, width=5.0, depth=south_d, x=3.9, z=north_d,
                 name="Living", facing=Facing.SOUTH,
                 window_type=WindowType.LARGE, has_balcony=True),
            Room(RoomType.BEDROOM, width=3.5, depth=3.5, x=8.9, z=north_d + (south_d - 3.5),
                 name="BedroomA", facing=Facing.SOUTH,
                 window_type=WindowType.STANDARD, has_ac_slot=True),
            # 北区
            Room(RoomType.BATHROOM, width=2.0, depth=2.5, x=0, z=0,
                 name="BathA", facing=Facing.NORTH,
                 window_type=WindowType.SMALL),
            Room(RoomType.CORRIDOR, width=1.9, depth=north_d, x=2.0, z=0,
                 name="Corridor", facing=Facing.INTERIOR,
                 window_type=WindowType.NONE),
            Room(RoomType.KITCHEN, width=3.5, depth=north_d, x=3.9, z=0,
                 name="Kitchen", facing=Facing.NORTH,
                 window_type=WindowType.SMALL),
            Room(RoomType.DINING, width=1.5, depth=north_d, x=7.4, z=0,
                 name="Dining", facing=Facing.INTERIOR,
                 window_type=WindowType.NONE),
            # 次卧B（北向）
            Room(RoomType.BEDROOM, width=3.5, depth=3.5, x=8.9, z=0,
                 name="BedroomB", facing=Facing.NORTH,
                 window_type=WindowType.STANDARD, has_ac_slot=True),
            # 卫生间B
            Room(RoomType.BATHROOM, width=2.2, depth=2.0, x=0, z=2.5,
                 name="BathB", facing=Facing.INTERIOR,
                 window_type=WindowType.NONE),
        ]

        plan = UnitPlan(unit_type="3BR", rooms=rooms,
                        south_depth=south_d, north_depth=north_d)
        plan.compute_bounds()
        return plan

    @staticmethod
    def create_4br() -> UnitPlan:
        """
        四室两厅户型（约140㎡）。

        平面布局：
        南(+Z)
        ┌──────────────────────────────────────────┐
        │ 主卧      │ 客厅       │ 次卧A  │ 次卧B  │  ← 南向
        │ 4.2×4.2   │ 5.5×4.8    │3.5×3.5 │3.3×3.5 │
        ├───────────┼────────────┼────────┼────────┤
        │ 卫A │走廊  │ 餐厅+厨房  │ 次卧C  │ 卫B    │  ← 北向
        │2.2  │1.5   │ 4.0×3.5   │3.5×3.5 │2.3×2.8 │
        │×2.8 │×3.5  │           │        │        │
        └──────────────────────────────────────────┘
        北(-Z)
        """
        south_d = 4.8
        north_d = 3.5

        rooms = [
            # 南区
            Room(RoomType.MASTER_BED, width=4.2, depth=4.2, x=0, z=north_d,
                 name="MasterBed", facing=Facing.SOUTH,
                 window_type=WindowType.STANDARD, has_balcony=True, has_ac_slot=True),
            Room(RoomType.LIVING, width=5.5, depth=south_d, x=4.2, z=north_d,
                 name="Living", facing=Facing.SOUTH,
                 window_type=WindowType.LARGE, has_balcony=True),
            Room(RoomType.BEDROOM, width=3.5, depth=3.5, x=9.7, z=north_d + (south_d - 3.5),
                 name="BedroomA", facing=Facing.SOUTH,
                 window_type=WindowType.STANDARD, has_ac_slot=True),
            Room(RoomType.BEDROOM, width=3.3, depth=3.5, x=13.2, z=north_d + (south_d - 3.5),
                 name="BedroomB", facing=Facing.SOUTH,
                 window_type=WindowType.STANDARD, has_ac_slot=True),
            # 北区
            Room(RoomType.BATHROOM, width=2.2, depth=2.8, x=0, z=0,
                 name="BathA", facing=Facing.NORTH,
                 window_type=WindowType.SMALL),
            Room(RoomType.CORRIDOR, width=2.0, depth=north_d, x=2.2, z=0,
                 name="Corridor", facing=Facing.INTERIOR,
                 window_type=WindowType.NONE),
            Room(RoomType.KITCHEN, width=4.0, depth=north_d, x=4.2, z=0,
                 name="Kitchen", facing=Facing.NORTH,
                 window_type=WindowType.SMALL),
            Room(RoomType.DINING, width=1.5, depth=north_d, x=8.2, z=0,
                 name="Dining", facing=Facing.INTERIOR,
                 window_type=WindowType.NONE),
            Room(RoomType.BEDROOM, width=3.5, depth=3.5, x=9.7, z=0,
                 name="BedroomC", facing=Facing.NORTH,
                 window_type=WindowType.STANDARD, has_ac_slot=True),
            Room(RoomType.BATHROOM, width=2.3, depth=2.8, x=13.2, z=0,
                 name="BathB", facing=Facing.NORTH,
                 window_type=WindowType.SMALL),
            # 走廊补充
            Room(RoomType.CORRIDOR, width=0.7, depth=north_d, x=15.5, z=0,
                 name="Corridor2", facing=Facing.INTERIOR,
                 window_type=WindowType.NONE),
        ]

        plan = UnitPlan(unit_type="4BR", rooms=rooms,
                        south_depth=south_d, north_depth=north_d)
        plan.compute_bounds()
        return plan

    @classmethod
    def create(cls, unit_type: str) -> UnitPlan:
        """根据户型类型创建预设平面。"""
        creators = {
            "1BR": cls.create_1br,
            "2BR": cls.create_2br,
            "3BR": cls.create_3br,
            "4BR": cls.create_4br,
        }
        creator = creators.get(unit_type)
        if not creator:
            raise ValueError(f"Unknown unit type: {unit_type}. Available: {list(creators.keys())}")
        return creator()


# =============================================================================
# FloorPlan 工厂
# =============================================================================

class FloorPlanFactory:
    """
    标准层平面工厂。

    根据建筑类型和户型配置，自动拼合标准层平面。
    支持1~2种户型，通过镜像实现围绕核心筒的轴对称或中心对称排布。

    板楼对称规则：
      - 用户指定1~2种户型，工厂自动展开为左右对称布局
      - ["3BR"] → 左3BR镜像 | 核心筒 | 右3BR （完美轴对称）
      - ["3BR","2BR"] → 左3BR镜像 | 核心筒 | 右2BR镜像
        （两种户型各自关于核心筒中轴对称排布）

    塔楼对称规则：
      - 核心筒居中，户型围绕四面分布
      - ["3BR"] → 南北各放一对3BR镜像（中心对称）
      - ["3BR","2BR"] → 南面2×3BR + 北面2×2BR（中心对称）
    """

    @staticmethod
    def _expand_unit_types(unit_types: List[str], n_units: int) -> List[str]:
        """
        将1~2种户型展开为n_units个户型的列表。

        规则：
        - 1种户型 → 全部相同
        - 2种户型 → 交替分配
        """
        if len(unit_types) == 0:
            return ["3BR"] * n_units
        elif len(unit_types) == 1:
            return unit_types * n_units
        else:
            # 2种户型：交替分配
            result = []
            for i in range(n_units):
                result.append(unit_types[i % len(unit_types)])
            return result

    @staticmethod
    def create_slab_floor(
        unit_types: List[str],
        core_width: float = 4.0,
        core_depth: float = 0.0,
        num_elevators: int = 1,
        units_per_floor: int = 2,
        seed: int = 0,
    ) -> FloorPlan:
        """
        创建板楼标准层平面（轴对称布局）。

        板楼一梯N户布局规则：
        - 核心筒在中央，左右各放 N/2 户
        - 左侧户型 = 右侧户型的X轴镜像（关于核心筒中轴对称）
        - 同种户型镜像后完美对称，异种户型各自对称排布

        对于一梯两户（最常见）：
          左户型(镜像) | 核心筒 | 右户型
          两户关于核心筒中轴线对称

        Args:
            unit_types: 1~2种户型类型，如 ["3BR"] 或 ["3BR", "2BR"]
            core_width: 核心筒面宽
            core_depth: 核心筒进深（0=自动取最大户型进深）
            num_elevators: 电梯数量
            units_per_floor: 每层户数（默认2）
        """
        # 展开户型列表
        n = units_per_floor
        expanded = FloorPlanFactory._expand_unit_types(unit_types, n)

        # 创建所有户型平面（使用 UnitPlanGenerator 参数化生成）
        UPG = _get_unit_plan_generator()
        plans = [UPG.generate(ut, seed=seed + i) for i, ut in enumerate(expanded)]

        # 核心筒进深：取所有户型的最大进深
        max_depth = max(p.total_depth for p in plans)
        if core_depth <= 0:
            core_depth = max_depth

        # 分左右两组：左侧取前半，右侧取后半
        right_count = n // 2
        left_count = n - right_count
        # 右侧户型（原始方向）
        right_plans = plans[:right_count]
        # 左侧户型 = 右侧户型的镜像（实现对称）
        # 如果只有1种户型，左右完全对称
        # 如果有2种户型，左右各自对称
        left_plans = plans[right_count:]

        # 计算总面宽
        left_width = sum(p.total_width for p in left_plans)
        right_width = sum(p.total_width for p in right_plans)
        total_width = left_width + core_width + right_width

        # 居中：建筑中心在X=0
        half_w = total_width / 2

        placed_units = []
        idx = 0

        # 放置左侧户型（X轴镜像，使入户门朝核心筒）
        x_cursor = -half_w
        for plan in left_plans:
            # 镜像户型：关于户型自身中心线镜像
            mirrored = plan.mirror_x(axis_x=plan.total_width / 2)
            # Z方向居中对齐（与最大进深对齐）
            dz = (max_depth - plan.total_depth) / 2
            placed = PlacedUnit(
                plan=mirrored,
                offset_x=x_cursor,
                offset_z=dz,
                mirrored=True,
                index=idx,
            )
            placed_units.append(placed)
            x_cursor += plan.total_width
            idx += 1

        # 核心筒（居中）
        core_z = (max_depth - core_depth) / 2
        core = CorePlan(
            width=core_width,
            depth=core_depth,
            x=x_cursor,
            z=core_z,
            num_elevators=num_elevators,
        )
        x_cursor += core_width

        # 放置右侧户型（原始方向）
        for plan in right_plans:
            dz = (max_depth - plan.total_depth) / 2
            placed = PlacedUnit(
                plan=plan,
                offset_x=x_cursor,
                offset_z=dz,
                mirrored=False,
                index=idx,
            )
            placed_units.append(placed)
            x_cursor += plan.total_width
            idx += 1

        floor_plan = FloorPlan(
            placed_units=placed_units,
            core=core,
            building_type="slab",
        )
        return floor_plan

    @staticmethod
    def create_tower_floor(
        unit_types: List[str],
        core_width: float = 6.0,
        core_depth: float = 6.0,
        num_elevators: int = 2,
        units_per_floor: int = 4,
        seed: int = 0,
    ) -> FloorPlan:
        """
        创建塔楼标准层平面（中心对称布局）。

        塔楼布局：核心筒居中，户型围绕南北两面分布，形成近正方形平面。

        布局结构（俯视图）：
          南(+Z)
          ┌──────────────────────┐
          │ 南左(镜像) │ 南右    │  ← 南面户型
          ├────────┬───┴────────┤
          │        │ 核心筒     │
          ├────────┴───┬────────┤
          │ 北左(镜像) │ 北右    │  ← 北面户型（Z轴镜像）
          └──────────────────────┘
          北(-Z)

        对称性：
        - 南面左右户型关于核心筒X轴对称
        - 北面户型 = 南面户型的Z轴镜像（中心对称）
        - 整体形成围绕核心筒的中心对称布局

        Args:
            unit_types: 1~2种户型类型
            core_width: 核心筒面宽
            core_depth: 核心筒进深
            num_elevators: 电梯数量
            units_per_floor: 每层户数（默认4）
        """
        n = units_per_floor
        if n < 4:
            n = 4  # 塔楼最少4户

        # 展开户型：南面和北面各放一半
        south_count = n // 2
        north_count = n - south_count

        # 南面户型
        if len(unit_types) == 1:
            south_types = [unit_types[0]] * south_count
            north_types = [unit_types[0]] * north_count
        elif len(unit_types) >= 2:
            # 第一种户型放南面，第二种放北面
            south_types = [unit_types[0]] * south_count
            north_types = [unit_types[1]] * north_count
        else:
            south_types = ["3BR"] * south_count
            north_types = ["3BR"] * north_count

        UPG = _get_unit_plan_generator()
        south_plans = [UPG.generate(ut, seed=seed + i) for i, ut in enumerate(south_types)]
        north_plans = [UPG.generate(ut, seed=seed + south_count + i) for i, ut in enumerate(north_types)]

        # 计算尺寸
        south_max_depth = max(p.total_depth for p in south_plans)
        north_max_depth = max(p.total_depth for p in north_plans)

        # 南面户型面宽
        south_right_count = south_count // 2
        south_left_count = south_count - south_right_count
        south_right_plans = south_plans[:south_right_count]
        south_left_plans = south_plans[south_right_count:]
        south_width = sum(p.total_width for p in south_left_plans) + \
                      core_width + \
                      sum(p.total_width for p in south_right_plans)

        # 北面户型面宽
        north_right_count = north_count // 2
        north_left_count = north_count - north_right_count
        north_right_plans = north_plans[:north_right_count]
        north_left_plans = north_plans[north_right_count:]
        north_width = sum(p.total_width for p in north_left_plans) + \
                      core_width + \
                      sum(p.total_width for p in north_right_plans)

        # 总面宽取最大值
        max_width = max(south_width, north_width)
        total_depth = south_max_depth + core_depth + north_max_depth

        # 居中
        half_w = max_width / 2

        placed_units = []
        idx = 0

        # === 南面户型（+Z侧，正常朝向）===
        south_z_base = core_depth + north_max_depth  # 南面户型的Z起点
        south_total_w = sum(p.total_width for p in south_left_plans) + \
                        core_width + \
                        sum(p.total_width for p in south_right_plans)
        south_half = south_total_w / 2

        # 南面左侧（镜像）
        x_cursor = -south_half
        for plan in south_left_plans:
            mirrored = plan.mirror_x(axis_x=plan.total_width / 2)
            dz_offset = south_z_base + (south_max_depth - plan.total_depth) / 2
            placed = PlacedUnit(
                plan=mirrored,
                offset_x=x_cursor,
                offset_z=dz_offset,
                mirrored=True,
                index=idx,
            )
            placed_units.append(placed)
            x_cursor += plan.total_width
            idx += 1

        # 跳过核心筒宽度
        x_cursor += core_width

        # 南面右侧
        for plan in south_right_plans:
            dz_offset = south_z_base + (south_max_depth - plan.total_depth) / 2
            placed = PlacedUnit(
                plan=plan,
                offset_x=x_cursor,
                offset_z=dz_offset,
                mirrored=False,
                index=idx,
            )
            placed_units.append(placed)
            x_cursor += plan.total_width
            idx += 1

        # === 北面户型（-Z侧，Z轴镜像）===
        # 北面户型需要Z轴镜像：南北朝向翻转
        north_total_w = sum(p.total_width for p in north_left_plans) + \
                        core_width + \
                        sum(p.total_width for p in north_right_plans)
        north_half = north_total_w / 2

        # 北面左侧（X镜像 + Z镜像）
        x_cursor = -north_half
        for plan in north_left_plans:
            # 先Z轴镜像（翻转南北朝向）
            z_mirrored = plan.mirror_z(axis_z=plan.total_depth / 2)
            # 再X轴镜像（左右对称）
            xz_mirrored = z_mirrored.mirror_x(axis_x=z_mirrored.total_width / 2)
            dz_offset = (north_max_depth - plan.total_depth) / 2
            placed = PlacedUnit(
                plan=xz_mirrored,
                offset_x=x_cursor,
                offset_z=dz_offset,
                mirrored=True,
                index=idx,
            )
            placed_units.append(placed)
            x_cursor += plan.total_width
            idx += 1

        # 跳过核心筒宽度
        x_cursor += core_width

        # 北面右侧（仅Z镜像）
        for plan in north_right_plans:
            z_mirrored = plan.mirror_z(axis_z=plan.total_depth / 2)
            dz_offset = (north_max_depth - plan.total_depth) / 2
            placed = PlacedUnit(
                plan=z_mirrored,
                offset_x=x_cursor,
                offset_z=dz_offset,
                mirrored=False,
                index=idx,
            )
            placed_units.append(placed)
            x_cursor += plan.total_width
            idx += 1

        # 核心筒（居中）
        core_x = -core_width / 2
        core_z = north_max_depth
        core = CorePlan(
            width=core_width,
            depth=core_depth,
            x=core_x,
            z=core_z,
            num_elevators=num_elevators,
        )

        floor_plan = FloorPlan(
            placed_units=placed_units,
            core=core,
            building_type="tower",
        )
        return floor_plan


# =============================================================================
# 辅助函数
# =============================================================================

def _merge_ranges(ranges: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """合并重叠的一维区间。"""
    if not ranges:
        return []
    sorted_ranges = sorted(ranges, key=lambda r: r[0])
    merged = [sorted_ranges[0]]
    for start, end in sorted_ranges[1:]:
        if start <= merged[-1][1] + 1e-6:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _simplify_polygon(pts: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """
    简化多边形：去除重复点和共线中间点。
    """
    if len(pts) < 3:
        return pts

    # 去除连续重复点
    deduped = [pts[0]]
    for p in pts[1:]:
        if abs(p[0] - deduped[-1][0]) > 1e-6 or abs(p[1] - deduped[-1][1]) > 1e-6:
            deduped.append(p)
    # 检查首尾
    if len(deduped) > 1 and abs(deduped[0][0] - deduped[-1][0]) < 1e-6 and abs(deduped[0][1] - deduped[-1][1]) < 1e-6:
        deduped.pop()

    if len(deduped) < 3:
        return deduped

    # 去除共线中间点
    result = []
    n = len(deduped)
    for i in range(n):
        p0 = deduped[(i - 1) % n]
        p1 = deduped[i]
        p2 = deduped[(i + 1) % n]

        # 检查是否共线
        dx1 = p1[0] - p0[0]
        dz1 = p1[1] - p0[1]
        dx2 = p2[0] - p1[0]
        dz2 = p2[1] - p1[1]
        cross = dx1 * dz2 - dz1 * dx2

        if abs(cross) > 1e-6:
            result.append(p1)

    return result if len(result) >= 3 else deduped


def _union_rects_shapely(rects: List[Tuple[float, float, float, float]]) -> List[Tuple[float, float]]:
    """
    使用 shapely 合并多个矩形为一个外轮廓多边形。

    如果合并结果是 MultiPolygon（多个不连通区域），
    会用微小连接矩形桥接各部分，确保输出单一多边形。

    Args:
        rects: [(x_min, z_min, x_max, z_max), ...]
    Returns:
        外轮廓顶点列表 [(x, z), ...]
    """
    polygons = []
    for x_min, z_min, x_max, z_max in rects:
        poly = ShapelyPolygon([
            (x_min, z_min), (x_max, z_min), (x_max, z_max), (x_min, z_max)
        ])
        if poly.is_valid and poly.area > 1e-6:
            polygons.append(poly)

    if not polygons:
        return []

    merged = unary_union(polygons)

    # 处理 MultiPolygon：用微小连接矩形桥接各部分
    if isinstance(merged, MultiPolygon):
        geoms = list(merged.geoms)
        # 尝试用微小缓冲区合并（边缘接触的多边形）
        buffered = merged.buffer(0.01).buffer(-0.01)
        if isinstance(buffered, MultiPolygon):
            # 仍然不连通，用 convex hull 包裹所有部分
            # 但这会丢失凹形细节，所以我们用连接桥的方式
            # 找到所有部分的包围盒，用包围盒中心线作为桥接矩形
            all_parts = list(buffered.geoms)
            # 按质心X坐标排序
            all_parts.sort(key=lambda g: g.centroid.x)
            bridge_polys = []
            for i in range(len(all_parts) - 1):
                b1 = all_parts[i].bounds   # (minx, miny, maxx, maxy)
                b2 = all_parts[i + 1].bounds
                # 创建连接桥：从第i个的右边到第i+1个的左边
                bridge_x_min = b1[2] - 0.1  # 小量重叠确保连通
                bridge_x_max = b2[0] + 0.1
                # Z范围取两个部分的重叠区域
                z_overlap_min = max(b1[1], b2[1])
                z_overlap_max = min(b1[3], b2[3])
                if z_overlap_max > z_overlap_min:
                    # 有Z重叠，用重叠区域中心作为桥
                    bridge_z_mid = (z_overlap_min + z_overlap_max) / 2
                    bridge_z_half = max(0.5, (z_overlap_max - z_overlap_min) / 4)
                else:
                    # 无Z重叠，用两个部分的Z中心
                    bridge_z_mid = (b1[1] + b1[3] + b2[1] + b2[3]) / 4
                    bridge_z_half = 0.5
                bridge = ShapelyPolygon([
                    (bridge_x_min, bridge_z_mid - bridge_z_half),
                    (bridge_x_max, bridge_z_mid - bridge_z_half),
                    (bridge_x_max, bridge_z_mid + bridge_z_half),
                    (bridge_x_min, bridge_z_mid + bridge_z_half),
                ])
                bridge_polys.append(bridge)
            # 重新合并
            all_geoms = list(buffered.geoms) + bridge_polys
            merged = unary_union(all_geoms)
            if isinstance(merged, MultiPolygon):
                # 最后手段：取最大的
                merged = max(merged.geoms, key=lambda g: g.area)
        else:
            merged = buffered

    # 简化轮廓：去除buffer操作引入的微小弧线段
    # tolerance=0.05m 足以去除微小抖动，保留建筑级别的轮廓细节
    simplified = merged.simplify(0.05, preserve_topology=True)
    if simplified.is_empty or simplified.area < 1e-6:
        simplified = merged

    coords = list(simplified.exterior.coords)
    # shapely 返回的是闭合多边形（首尾相同），去掉最后一个重复点
    if len(coords) > 1 and coords[0] == coords[-1]:
        coords = coords[:-1]

    return [(round(x, 6), round(z, 6)) for x, z in coords]


def _union_rects_scanline(rects: List[Tuple[float, float, float, float]]) -> List[Tuple[float, float]]:
    """
    备用的扫描线法合并矩形（无shapely时使用）。
    简化实现：取所有矩形的包围盒。
    """
    if not rects:
        return []
    x_min = min(r[0] for r in rects)
    z_min = min(r[1] for r in rects)
    x_max = max(r[2] for r in rects)
    z_max = max(r[3] for r in rects)
    return [(x_min, z_min), (x_max, z_min), (x_max, z_max), (x_min, z_max)]


def triangulate_polygon(vertices: List[Tuple[float, float]]) -> List[Tuple[int, int, int]]:
    """
    对凹多边形进行三角化。

    使用 shapely 的约束 Delaunay 三角化，能正确处理凹多边形。
    """
    n = len(vertices)
    if n < 3:
        return []

    if HAS_SHAPELY:
        from shapely.geometry import Polygon as SPoly
        from shapely import get_coordinates
        import numpy as np

        poly = SPoly(vertices)
        if not poly.is_valid:
            poly = poly.buffer(0)

        # 使用 shapely 的 triangulate
        from shapely.ops import triangulate as shapely_triangulate
        tris_geom = shapely_triangulate(poly)

        # 筛选在多边形内部的三角形
        result = []
        verts_arr = np.array(vertices, dtype=float)

        for tri in tris_geom:
            centroid = tri.centroid
            if poly.contains(centroid):
                # 将三角形顶点映射回原始顶点索引
                tri_coords = list(tri.exterior.coords)[:-1]
                indices = []
                for tc in tri_coords:
                    # 找最近的原始顶点
                    dists = np.sqrt((verts_arr[:, 0] - tc[0])**2 + (verts_arr[:, 1] - tc[1])**2)
                    idx = int(np.argmin(dists))
                    indices.append(idx)
                if len(set(indices)) == 3:  # 确保三个不同的顶点
                    result.append(tuple(indices))

        if result:
            return result

    # 回退：简单扇形三角化
    triangles = []
    for i in range(1, n - 1):
        triangles.append((0, i, i + 1))
    return triangles
