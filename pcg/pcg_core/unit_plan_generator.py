"""
Unit Plan Generator: 参数化户型平面生成模块（v2 — 设计理念驱动）。

每种户型模板遵循不同的建筑设计哲学：
  - studio:       极致效率 — 开放式布局，湿区紧凑集中
  - compact_1br:  功能完整的最小住宅 — 动静分区，湿区集中
  - standard_2br: 经典南北通透 — 餐客一体/横厅，动静分离
  - comfort_3br:  全功能家庭住宅 — 客厅为核心，三段式分区
  - luxury_4br:   尊享空间 — 双套间，独立餐厅，三翼布局
  - loft_duplex:  立体生活 — 上下层彻底动静分离

核心设计原则：
  1. 动静分区：动区(客厅/餐厅/厨房/玄关) vs 静区(卧室/书房)
  2. 湿区集中：厨房+卫生间紧邻，共享管井墙
  3. 以客厅为核心：所有卧室围绕客厅布置
  4. 南北通透：南向采光(客厅/主卧)，北向通风(厨卫)
"""

from __future__ import annotations
import random
import math
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, field

from pcg_core.floor_plan import (
    Room, RoomType, Facing, WindowType, UnitPlan,
)


# =============================================================================
# 模板参数范围定义
# =============================================================================

@dataclass
class ParamRange:
    """参数的允许范围。"""
    min_val: float
    max_val: float
    default: float

    def sample(self, rng: random.Random, bias: float = 0.0) -> float:
        center = (self.min_val + self.max_val) / 2
        half = (self.max_val - self.min_val) / 2
        val = center + bias * half + rng.gauss(0, half * 0.3)
        return max(self.min_val, min(self.max_val, round(val, 1)))

    def clamp(self, val: float) -> float:
        return max(self.min_val, min(self.max_val, round(val, 1)))


@dataclass
class TemplateInfo:
    """模板元信息。"""
    template_id: str
    display_name: str
    unit_type: str
    num_bedrooms: int
    area_range: Tuple[float, float]
    bay_width: ParamRange
    depth_south: ParamRange
    depth_north: ParamRange
    description: str = ""
    design_philosophy: str = ""


# =============================================================================
# 模板注册表
# =============================================================================

TEMPLATE_REGISTRY: Dict[str, TemplateInfo] = {
    "studio": TemplateInfo(
        template_id="studio",
        display_name="开间/公寓",
        unit_type="studio",
        num_bedrooms=0,
        area_range=(25, 40),
        bay_width=ParamRange(4.0, 6.5, 5.0),
        depth_south=ParamRange(3.0, 4.0, 3.5),
        depth_north=ParamRange(2.0, 2.8, 2.4),
        description="无独立卧室，客厅兼卧室，适合单身公寓",
        design_philosophy="极致效率：开放式布局，湿区紧凑集中",
    ),
    "compact_1br": TemplateInfo(
        template_id="compact_1br",
        display_name="紧凑一居",
        unit_type="1BR",
        num_bedrooms=1,
        area_range=(40, 60),
        bay_width=ParamRange(6.0, 8.5, 7.6),
        depth_south=ParamRange(3.5, 4.5, 4.0),
        depth_north=ParamRange(2.5, 3.2, 2.8),
        description="一室一厅一卫，南北通透",
        design_philosophy="功能完整的最小住宅：明确动静分区，湿区集中",
    ),
    "standard_2br": TemplateInfo(
        template_id="standard_2br",
        display_name="标准两居",
        unit_type="2BR",
        num_bedrooms=2,
        area_range=(65, 95),
        bay_width=ParamRange(7.5, 10.5, 8.3),
        depth_south=ParamRange(3.8, 4.8, 4.2),
        depth_north=ParamRange(2.8, 3.5, 3.0),
        description="两室一厅一卫，主卧+客厅朝南",
        design_philosophy="经典南北通透：餐客一体/横厅，动静分离",
    ),
    "comfort_3br": TemplateInfo(
        template_id="comfort_3br",
        display_name="舒适三居",
        unit_type="3BR",
        num_bedrooms=3,
        area_range=(95, 135),
        bay_width=ParamRange(10.0, 14.5, 12.4),
        depth_south=ParamRange(4.0, 5.2, 4.5),
        depth_north=ParamRange(2.8, 3.8, 3.2),
        description="三室两厅两卫，南北通透，主卧套间",
        design_philosophy="全功能家庭住宅：客厅为核心，两翼静区，严格动静分区",
    ),
    "luxury_4br": TemplateInfo(
        template_id="luxury_4br",
        display_name="豪华四居",
        unit_type="4BR",
        num_bedrooms=4,
        area_range=(130, 180),
        bay_width=ParamRange(13.0, 18.0, 16.5),
        depth_south=ParamRange(4.2, 5.5, 4.8),
        depth_north=ParamRange(3.0, 4.0, 3.5),
        description="四室两厅两卫，独立餐厅，双阳台",
        design_philosophy="尊享空间：三翼布局，双套间，独立餐厅",
    ),
    "loft_duplex": TemplateInfo(
        template_id="loft_duplex",
        display_name="复式/LOFT",
        unit_type="loft",
        num_bedrooms=1,
        area_range=(45, 80),
        bay_width=ParamRange(5.5, 8.0, 6.5),
        depth_south=ParamRange(4.0, 5.5, 4.8),
        depth_north=ParamRange(2.5, 3.5, 3.0),
        description="上下两层，下层客厅+厨卫，上层卧室",
        design_philosophy="立体生活：上下层彻底动静分离，挑高客厅",
    ),
}

# 简写映射
_SHORTHAND_MAP = {
    "studio": "studio",
    "1BR": "compact_1br",
    "2BR": "standard_2br",
    "3BR": "comfort_3br",
    "4BR": "luxury_4br",
    "loft": "loft_duplex",
}


# =============================================================================
# 布局规则引擎 v2 — 设计理念驱动
# =============================================================================

class _LayoutEngine:
    """
    户型布局规则引擎 v2。

    每种户型模板遵循不同的建筑设计哲学，通过分区规则和房间优先级
    实现符合真实住宅设计常理的平面布局。
    """

    def __init__(self, rng: random.Random):
        self.rng = rng

    def _j(self, base: float, amp: float = 0.3) -> float:
        """给基础值添加微小随机抖动。"""
        return round(base + self.rng.uniform(-amp, amp), 1)

    def _room(self, room_type: RoomType, name: str, w: float, d: float,
              x: float, z: float,
              facing: Facing = Facing.INTERIOR,
              window: WindowType = WindowType.NONE,
              balcony: bool = False, ac: bool = False,
              zone: str = "transition",
              suite: bool = False, pipe: bool = False) -> Room:
        """创建房间，确保尺寸合理。"""
        return Room(
            room_type=room_type,
            width=max(1.0, round(w, 2)),
            depth=max(1.0, round(d, 2)),
            x=round(x, 2),
            z=round(z, 2),
            name=name,
            facing=facing,
            window_type=window,
            has_balcony=balcony,
            has_ac_slot=ac,
            zone=zone,
            is_suite_part=suite,
            shares_pipe_wall=pipe,
        )

    # =================================================================
    # Studio: 极致效率
    # =================================================================
    def generate_studio(self, bw: float, sd: float, nd: float) -> UnitPlan:
        """
        开间/公寓 — 极致效率设计。

        设计理念：
        - 开放式一体空间，无隔墙，通过家具软分区
        - 厨卫紧邻共享管井墙，最小化管道长度
        - 厨房半开放式（吧台隔断），节省空间

        平面：
        南(+Z)
        ┌──────────────────┐
        │                  │
        │  客厅/卧室/餐厅   │  ← 全南向采光
        │  (开放式一体)     │
        │                  │
        ├────────┬─────────┤
        │ 厨房    │ 卫生间   │  ← 湿区集中，共享管井墙
        └────────┴─────────┘
        北(-Z)
        """
        # 湿区集中：厨房和卫生间紧邻，共享管井墙
        # 厨房稍大（需要操作台面），卫生间紧凑
        kitchen_w = self._j(max(2.2, bw * 0.55), 0.2)
        bath_w = round(bw - kitchen_w, 2)

        rooms = [
            # 南区：开放式客厅/卧室/餐厅一体（动区+静区合一）
            self._room(RoomType.LIVING, "LivingBed", bw, sd,
                       0, nd, Facing.SOUTH, WindowType.LARGE,
                       balcony=True, zone="dynamic"),
            # 北区湿区：厨房+卫生间紧邻，共享管井墙
            self._room(RoomType.KITCHEN, "Kitchen", kitchen_w, nd,
                       0, 0, Facing.NORTH, WindowType.SMALL,
                       zone="wet", pipe=True),
            self._room(RoomType.BATHROOM, "Bathroom", bath_w, nd,
                       kitchen_w, 0, Facing.NORTH, WindowType.SMALL,
                       zone="wet", pipe=True),
        ]

        plan = UnitPlan(unit_type="studio", rooms=rooms,
                        south_depth=sd, north_depth=nd)
        plan.compute_bounds()
        return plan

    # =================================================================
    # Compact 1BR: 功能完整的最小住宅
    # =================================================================
    def generate_compact_1br(self, bw: float, sd: float, nd: float) -> UnitPlan:
        """
        紧凑一居 — 功能完整的最小住宅。

        设计理念：
        - 明确动静分区：客厅(动)在左，主卧(静)在右
        - 湿区集中：厨房+卫生间在北侧紧邻，共享管井墙
        - 玄关缓冲：入户有玄关/走廊过渡，不直对客厅
        - 动线分离：入户→玄关→客厅(动线) / 玄关→主卧(静线)

        平面：
        南(+Z)
        ┌──────────┬─────────┐
        │          │         │
        │  客厅     │  主卧    │  ← 动区 | 静区
        │  (动区)   │ (静区)   │
        │          │         │
        ├────┬─────┼─────────┤
        │厨房│玄关  │ 卫生间   │  ← 湿区|过渡|湿区
        │    │     │         │     厨+卫共享管井
        └────┴─────┴─────────┘
        北(-Z)
        """
        # 南区面宽分配：客厅 ~55%, 主卧 ~45%
        living_w = self._j(bw * 0.55, 0.3)
        master_w = round(bw - living_w, 2)

        # 北区：厨房 | 玄关/走廊 | 卫生间
        # 湿区集中原则：厨房在最左，卫生间在最右，中间是玄关过渡
        kitchen_w = self._j(max(2.0, bw * 0.32), 0.2)
        bath_w = self._j(max(1.8, bw * 0.28), 0.2)
        entrance_w = round(bw - kitchen_w - bath_w, 2)

        rooms = [
            # 南区：动区(客厅) + 静区(主卧)
            self._room(RoomType.LIVING, "Living", living_w, sd,
                       0, nd, Facing.SOUTH, WindowType.LARGE,
                       balcony=True, zone="dynamic"),
            self._room(RoomType.MASTER_BED, "MasterBed", master_w, sd,
                       living_w, nd, Facing.SOUTH, WindowType.STANDARD,
                       ac=True, zone="static"),
            # 北区：湿区(厨房) + 过渡区(玄关) + 湿区(卫生间)
            self._room(RoomType.KITCHEN, "Kitchen", kitchen_w, nd,
                       0, 0, Facing.NORTH, WindowType.SMALL,
                       zone="wet", pipe=True),
            self._room(RoomType.ENTRANCE, "Entrance", entrance_w, nd,
                       kitchen_w, 0, Facing.INTERIOR,
                       zone="transition"),
            self._room(RoomType.BATHROOM, "Bathroom", bath_w, nd,
                       kitchen_w + entrance_w, 0, Facing.NORTH,
                       WindowType.SMALL, zone="wet", pipe=True),
        ]

        plan = UnitPlan(unit_type="1BR", rooms=rooms,
                        south_depth=sd, north_depth=nd)
        plan.compute_bounds()
        return plan

    # =================================================================
    # Standard 2BR: 经典南北通透
    # =================================================================
    def generate_standard_2br(self, bw: float, sd: float, nd: float) -> UnitPlan:
        """标准两居 — 两种变体随机选择。"""
        variant = self.rng.choice(["A", "B"])
        if variant == "A":
            return self._gen_2br_classic(bw, sd, nd)
        else:
            return self._gen_2br_horizontal_hall(bw, sd, nd)

    def _gen_2br_classic(self, bw: float, sd: float, nd: float) -> UnitPlan:
        """
        2BR变体A：经典南北通透。

        设计理念：
        - 纵向动静分区：左侧=动区(客厅+餐厅+厨房)，右侧=静区(主卧+次卧)
        - 客厅+餐厅一体，增大空间感
        - 湿区集中：厨房+公卫在北侧紧邻
        - 次卧朝北，与公卫相邻（方便使用）

        平面：
        南(+Z)
        ┌──────────┬──────────┐
        │          │          │
        │  客厅     │  主卧    │  ← 动区 | 静区
        │  +餐厅   │          │
        │          │          │
        ├────┬─────┼────┬─────┤
        │厨房│玄关  │公卫 │次卧  │  ← 湿区|过渡|湿区|静区
        └────┴─────┴────┴─────┘
        北(-Z)
        """
        # 南区：客厅(含餐厅) ~52%, 主卧 ~48%
        living_w = self._j(bw * 0.52, 0.3)
        master_w = round(bw - living_w, 2)

        # 北区：厨房 | 玄关 | 公卫 | 次卧
        # 湿区集中：厨房和公卫靠近（中间隔玄关，但管井在同一侧）
        kitchen_w = self._j(max(2.2, bw * 0.28), 0.2)
        entrance_w = self._j(max(1.2, bw * 0.14), 0.1)
        bath_w = self._j(max(1.8, bw * 0.18), 0.1)
        bed2_w = round(bw - kitchen_w - entrance_w - bath_w, 2)

        # 次卧进深可能比北区稍深（形成凹凸轮廓）
        bed2_d = self._j(max(nd, nd + 0.5), 0.3)

        rooms = [
            # 南区：动区(客厅+餐厅) + 静区(主卧)
            self._room(RoomType.LIVING, "Living", living_w, sd,
                       0, nd, Facing.SOUTH, WindowType.LARGE,
                       balcony=True, zone="dynamic"),
            self._room(RoomType.MASTER_BED, "MasterBed", master_w, sd,
                       living_w, nd, Facing.SOUTH, WindowType.STANDARD,
                       balcony=True, ac=True, zone="static"),
            # 北区
            self._room(RoomType.KITCHEN, "Kitchen", kitchen_w, nd,
                       0, 0, Facing.NORTH, WindowType.SMALL,
                       zone="wet", pipe=True),
            self._room(RoomType.ENTRANCE, "Entrance", entrance_w, nd,
                       kitchen_w, 0, Facing.INTERIOR,
                       zone="transition"),
            self._room(RoomType.BATHROOM, "BathPub", bath_w, nd,
                       kitchen_w + entrance_w, 0, Facing.NORTH,
                       WindowType.SMALL, zone="wet", pipe=True),
            self._room(RoomType.BEDROOM, "BedroomA", bed2_w, bed2_d,
                       kitchen_w + entrance_w + bath_w, 0,
                       Facing.NORTH, WindowType.STANDARD,
                       ac=True, zone="static"),
        ]

        plan = UnitPlan(unit_type="2BR", rooms=rooms,
                        south_depth=sd, north_depth=nd)
        plan.compute_bounds()
        return plan

    def _gen_2br_horizontal_hall(self, bw: float, sd: float, nd: float) -> UnitPlan:
        """
        2BR变体B：横厅设计。

        设计理念：
        - 横向动静分区：南面=大面宽横厅(动区)，北面=卧室+厨卫(静区+湿区)
        - 横厅超大采光面，空间感极强
        - 北面按功能聚合：主卧(静) | 厨+餐(湿+动) | 公卫(湿) | 次卧(静)
        - 厨卫在中间集中，两侧卧室安静

        平面：
        南(+Z)
        ┌─────────────────────────┐
        │                         │
        │  客厅（横厅，大面宽）     │  ← 动区核心
        │                         │
        ├──────┬──────┬─────┬─────┤
        │ 主卧  │厨房+餐│ 公卫 │次卧 │  ← 静|湿+动|湿|静
        └──────┴──────┴─────┴─────┘
        北(-Z)
        """
        # 南区：整面宽横厅
        living_d = self._j(sd, 0.2)

        # 北区：主卧 | 厨+餐 | 公卫 | 次卧
        master_w = self._j(max(3.0, bw * 0.28), 0.2)
        bed2_w = self._j(max(2.8, bw * 0.24), 0.2)
        bath_w = self._j(max(1.8, 2.0), 0.1)
        kitchen_w = round(bw - master_w - bed2_w - bath_w, 2)

        rooms = [
            # 南区：横厅（动区核心）
            self._room(RoomType.LIVING, "Living", bw, living_d,
                       0, nd, Facing.SOUTH, WindowType.LARGE,
                       balcony=True, zone="dynamic"),
            # 北区：静区(主卧) | 湿区(厨+餐) | 湿区(公卫) | 静区(次卧)
            self._room(RoomType.MASTER_BED, "MasterBed", master_w, nd,
                       0, 0, Facing.NORTH, WindowType.STANDARD,
                       ac=True, zone="static"),
            self._room(RoomType.KITCHEN, "KitchenDining", kitchen_w, nd,
                       master_w, 0, Facing.NORTH, WindowType.SMALL,
                       zone="wet", pipe=True),
            self._room(RoomType.BATHROOM, "BathPub", bath_w, nd,
                       master_w + kitchen_w, 0, Facing.NORTH,
                       WindowType.SMALL, zone="wet", pipe=True),
            self._room(RoomType.BEDROOM, "BedroomA", bed2_w, nd,
                       master_w + kitchen_w + bath_w, 0,
                       Facing.NORTH, WindowType.STANDARD,
                       ac=True, zone="static"),
        ]

        plan = UnitPlan(unit_type="2BR", rooms=rooms,
                        south_depth=sd, north_depth=nd)
        plan.compute_bounds()
        return plan

    # =================================================================
    # Comfort 3BR: 全功能家庭住宅
    # =================================================================
    def generate_comfort_3br(self, bw: float, sd: float, nd: float) -> UnitPlan:
        """舒适三居 — 三种变体随机选择。"""
        variant = self.rng.choice(["A", "B", "C"])
        if variant == "A":
            return self._gen_3br_classic(bw, sd, nd)
        elif variant == "B":
            return self._gen_3br_wide_living(bw, sd, nd)
        else:
            return self._gen_3br_master_suite(bw, sd, nd)

    def _gen_3br_classic(self, bw: float, sd: float, nd: float) -> UnitPlan:
        """
        3BR变体A：经典三室两厅两卫。

        设计理念：
        - 三段式动静分区：左翼(主卧套间=极静) | 中央(客厅+餐厅=动) | 右翼(次卧群=静)
        - 客厅是家庭中心：从客厅可达所有卧室
        - 主卧套间独立：主卧+主卫，最大限度保证私密性
        - 湿区集中：公卫+厨房在北侧中央，共享管井
        - 餐厨一体：餐厅和厨房相邻，完整烹饪-用餐动线

        平面：
        南(+Z)
        ┌────────┬──────────┬────────┐
        │ 主卧    │  客厅     │ 次卧A  │  ← 静(左翼)|动(中央)|静(右翼)
        │ (极静)  │  (动区)   │ (静区) │
        ├──┬─────┼────┬─────┼────────┤
        │主│玄关  │餐厅 │ 厨房 │ 次卧B  │  ← 湿|过渡|动|湿|静
        │卫│/走廊 │    │+公卫 │        │     厨+公卫共享管井
        └──┴─────┴────┴─────┴────────┘
        北(-Z)
        """
        # 南区三段：主卧 ~28%, 客厅 ~42%, 次卧A ~30%
        master_w = self._j(bw * 0.28, 0.3)
        living_w = self._j(bw * 0.42, 0.3)
        bed_a_w = round(bw - master_w - living_w, 2)

        # 次卧A进深可能略小（形成凹凸）
        bed_a_d = self._j(sd - 0.3, 0.3)

        # 北区：主卫 | 玄关/走廊 | 餐厅 | 厨房+公卫 | 次卧B
        # 湿区集中：厨房和公卫紧邻，共享管井墙
        master_bath_w = self._j(2.0, 0.2)
        entrance_w = self._j(max(1.3, master_w - master_bath_w), 0.1)
        # 调整主卫宽度使其与主卧对齐
        master_bath_w = round(master_w - entrance_w, 2)

        dining_w = self._j(max(2.0, living_w * 0.45), 0.2)
        # 厨房+公卫共享区域
        kitchen_bath_w = round(living_w - dining_w, 2)
        kitchen_w = self._j(max(2.0, kitchen_bath_w * 0.6), 0.1)
        pub_bath_w = round(kitchen_bath_w - kitchen_w, 2)
        if pub_bath_w < 1.5:
            kitchen_w = round(kitchen_bath_w - 1.5, 2)
            pub_bath_w = 1.5

        bed_b_w = round(bw - master_bath_w - entrance_w - dining_w
                        - kitchen_w - pub_bath_w, 2)

        # 次卧B进深可能比北区深
        bed_b_d = self._j(nd + 0.3, 0.3)

        rooms = [
            # === 南区 ===
            # 左翼：主卧（极静区）
            self._room(RoomType.MASTER_BED, "MasterBed", master_w, sd,
                       0, nd, Facing.SOUTH, WindowType.STANDARD,
                       balcony=True, ac=True, zone="static"),
            # 中央：客厅（动区核心）
            self._room(RoomType.LIVING, "Living", living_w, sd,
                       master_w, nd, Facing.SOUTH, WindowType.LARGE,
                       balcony=True, zone="dynamic"),
            # 右翼：次卧A（静区）
            self._room(RoomType.BEDROOM, "BedroomA", bed_a_w, bed_a_d,
                       master_w + living_w, nd + (sd - bed_a_d),
                       Facing.SOUTH, WindowType.STANDARD,
                       ac=True, zone="static"),

            # === 北区 ===
            # 主卫（主卧套间，湿区）
            self._room(RoomType.BATHROOM, "BathMaster", master_bath_w, nd,
                       0, 0, Facing.NORTH, WindowType.SMALL,
                       zone="wet", suite=True, pipe=True),
            # 玄关/走廊（过渡区）
            self._room(RoomType.ENTRANCE, "Entrance", entrance_w, nd,
                       master_bath_w, 0, Facing.INTERIOR,
                       zone="transition"),
            # 餐厅（动区）
            self._room(RoomType.DINING, "Dining", dining_w, nd,
                       master_w, 0, Facing.INTERIOR,
                       zone="dynamic"),
            # 厨房（湿区，与公卫共享管井）
            self._room(RoomType.KITCHEN, "Kitchen", kitchen_w, nd,
                       master_w + dining_w, 0, Facing.NORTH,
                       WindowType.SMALL, zone="wet", pipe=True),
            # 公卫（湿区，与厨房共享管井）
            self._room(RoomType.BATHROOM, "BathPub", pub_bath_w, nd,
                       master_w + dining_w + kitchen_w, 0,
                       Facing.NORTH, WindowType.SMALL,
                       zone="wet", pipe=True),
            # 次卧B（静区）
            self._room(RoomType.BEDROOM, "BedroomB", bed_b_w, bed_b_d,
                       master_w + dining_w + kitchen_w + pub_bath_w, 0,
                       Facing.NORTH, WindowType.STANDARD,
                       ac=True, zone="static"),
        ]

        plan = UnitPlan(unit_type="3BR", rooms=rooms,
                        south_depth=sd, north_depth=nd)
        plan.compute_bounds()
        return plan

    def _gen_3br_wide_living(self, bw: float, sd: float, nd: float) -> UnitPlan:
        """
        3BR变体B：大客厅+两次卧朝北。

        设计理念：
        - 南面只有主卧+大客厅，最大化客厅采光面
        - 两个次卧放在北面，与公卫相邻
        - 厨卫在北面中央集中
        - 动静分区：南面=动区(客厅)+极静(主卧)，北面=湿区(中)+静区(两翼)

        平面：
        南(+Z)
        ┌────────┬─────────────────┐
        │        │                 │
        │ 主卧    │  客厅（大面宽）  │  ← 静(左) | 动(右)
        │        │                 │
        ├──┬─────┼────┬─────┬─────┤
        │主│玄关  │厨房│ 公卫 │次卧A │  ← 湿|过渡|湿集中|静
        │卫│     │+餐 │     │+次卧B│
        └──┴─────┴────┴─────┴─────┘
        北(-Z)
        """
        # 南区：主卧 ~32%, 客厅 ~68%
        master_w = self._j(bw * 0.32, 0.3)
        living_w = round(bw - master_w, 2)

        # 北区：主卫 | 玄关 | 厨+餐 | 公卫 | 次卧A+次卧B
        master_bath_w = self._j(2.0, 0.2)
        entrance_w = round(master_w - master_bath_w, 2)
        if entrance_w < 1.0:
            master_bath_w = round(master_w - 1.2, 2)
            entrance_w = 1.2

        kitchen_w = self._j(max(2.5, bw * 0.22), 0.2)
        pub_bath_w = self._j(max(1.8, 2.0), 0.1)
        remaining = round(bw - master_bath_w - entrance_w
                          - kitchen_w - pub_bath_w, 2)
        bed_a_w = self._j(remaining * 0.5, 0.2)
        bed_b_w = round(remaining - bed_a_w, 2)

        rooms = [
            # 南区
            self._room(RoomType.MASTER_BED, "MasterBed", master_w, sd,
                       0, nd, Facing.SOUTH, WindowType.STANDARD,
                       balcony=True, ac=True, zone="static"),
            self._room(RoomType.LIVING, "Living", living_w, sd,
                       master_w, nd, Facing.SOUTH, WindowType.LARGE,
                       balcony=True, zone="dynamic"),
            # 北区
            self._room(RoomType.BATHROOM, "BathMaster", master_bath_w, nd,
                       0, 0, Facing.NORTH, WindowType.SMALL,
                       zone="wet", suite=True, pipe=True),
            self._room(RoomType.ENTRANCE, "Entrance", entrance_w, nd,
                       master_bath_w, 0, Facing.INTERIOR,
                       zone="transition"),
            self._room(RoomType.KITCHEN, "KitchenDining", kitchen_w, nd,
                       master_w, 0, Facing.NORTH, WindowType.SMALL,
                       zone="wet", pipe=True),
            self._room(RoomType.BATHROOM, "BathPub", pub_bath_w, nd,
                       master_w + kitchen_w, 0, Facing.NORTH,
                       WindowType.SMALL, zone="wet", pipe=True),
            self._room(RoomType.BEDROOM, "BedroomA", bed_a_w, nd,
                       master_w + kitchen_w + pub_bath_w, 0,
                       Facing.NORTH, WindowType.STANDARD,
                       ac=True, zone="static"),
            self._room(RoomType.BEDROOM, "BedroomB", bed_b_w, nd,
                       master_w + kitchen_w + pub_bath_w + bed_a_w, 0,
                       Facing.NORTH, WindowType.STANDARD,
                       ac=True, zone="static"),
        ]

        plan = UnitPlan(unit_type="3BR", rooms=rooms,
                        south_depth=sd, north_depth=nd)
        plan.compute_bounds()
        return plan

    def _gen_3br_master_suite(self, bw: float, sd: float, nd: float) -> UnitPlan:
        """
        3BR变体C：主卧套间（主卧+主卫+衣帽间）。

        设计理念：
        - 主卧套间：主卧+主卫+衣帽间一体，极致私密
        - 三段式：主卧翼(极静) | 客厅(动) | 次卧翼(静)
        - 主卫在主卧内侧（不占南向窗位）
        - 衣帽间连接主卧和主卫

        平面：
        南(+Z)
        ┌────────────┬──────────┬────────┐
        │ 主卧        │  客厅     │ 次卧A  │
        │ ┌──┬──┐    │          │        │
        │ │衣│主│    │          │        │
        │ │帽│卫│    │          │        │
        ├─┴──┴──┴────┼────┬─────┼────────┤
        │  玄关/走廊   │餐厅 │厨+卫 │ 次卧B  │
        └────────────┴────┴─────┴────────┘
        北(-Z)
        """
        # 南区三段
        master_suite_w = self._j(bw * 0.36, 0.3)
        living_w = self._j(bw * 0.38, 0.3)
        bed_a_w = round(bw - master_suite_w - living_w, 2)

        # 主卧套间内部：主卧占大部分，主卫+衣帽间在内侧
        closet_w = self._j(1.5, 0.1)
        master_bath_w = self._j(2.0, 0.2)
        # 主卫和衣帽间在主卧南区的内侧（占用部分进深）
        suite_inner_d = self._j(2.2, 0.2)

        # 北区
        entrance_w = self._j(max(1.5, master_suite_w * 0.5), 0.2)
        dining_w = self._j(max(2.0, living_w * 0.45), 0.2)
        kitchen_w = self._j(max(2.0, bw * 0.16), 0.1)
        pub_bath_w = self._j(max(1.5, 1.8), 0.1)
        bed_b_w = round(bw - entrance_w - dining_w - kitchen_w
                        - pub_bath_w, 2)

        # 调整玄关宽度
        if entrance_w + dining_w > master_suite_w + living_w * 0.5:
            entrance_w = round(master_suite_w, 2)

        bed_b_w = round(bw - entrance_w - dining_w - kitchen_w
                        - pub_bath_w, 2)
        bed_b_d = self._j(nd + 0.3, 0.3)

        rooms = [
            # 南区 - 主卧套间
            self._room(RoomType.MASTER_BED, "MasterBed", master_suite_w, sd,
                       0, nd, Facing.SOUTH, WindowType.STANDARD,
                       balcony=True, ac=True, zone="static"),
            # 主卫（套间内，内侧）
            self._room(RoomType.BATHROOM, "BathMaster", master_bath_w,
                       suite_inner_d,
                       0, nd + sd - suite_inner_d,
                       Facing.INTERIOR, zone="wet",
                       suite=True, pipe=True),
            # 衣帽间（套间内）
            self._room(RoomType.WALK_IN_CLOSET, "Closet", closet_w,
                       suite_inner_d,
                       master_bath_w, nd + sd - suite_inner_d,
                       Facing.INTERIOR, zone="static", suite=True),
            # 南区 - 客厅 + 次卧A
            self._room(RoomType.LIVING, "Living", living_w, sd,
                       master_suite_w, nd, Facing.SOUTH, WindowType.LARGE,
                       balcony=True, zone="dynamic"),
            self._room(RoomType.BEDROOM, "BedroomA", bed_a_w, sd,
                       master_suite_w + living_w, nd,
                       Facing.SOUTH, WindowType.STANDARD,
                       ac=True, zone="static"),
            # 北区
            self._room(RoomType.ENTRANCE, "Entrance", entrance_w, nd,
                       0, 0, Facing.INTERIOR, zone="transition"),
            self._room(RoomType.DINING, "Dining", dining_w, nd,
                       entrance_w, 0, Facing.INTERIOR, zone="dynamic"),
            self._room(RoomType.KITCHEN, "Kitchen", kitchen_w, nd,
                       entrance_w + dining_w, 0, Facing.NORTH,
                       WindowType.SMALL, zone="wet", pipe=True),
            self._room(RoomType.BATHROOM, "BathPub", pub_bath_w, nd,
                       entrance_w + dining_w + kitchen_w, 0,
                       Facing.NORTH, WindowType.SMALL,
                       zone="wet", pipe=True),
            self._room(RoomType.BEDROOM, "BedroomB", bed_b_w, bed_b_d,
                       entrance_w + dining_w + kitchen_w + pub_bath_w, 0,
                       Facing.NORTH, WindowType.STANDARD,
                       ac=True, zone="static"),
        ]

        plan = UnitPlan(unit_type="3BR", rooms=rooms,
                        south_depth=sd, north_depth=nd)
        plan.compute_bounds()
        return plan

    # =================================================================
    # Luxury 4BR: 尊享空间
    # =================================================================
    def generate_luxury_4br(self, bw: float, sd: float, nd: float) -> UnitPlan:
        """豪华四居 — 两种变体随机选择。"""
        variant = self.rng.choice(["A", "B"])
        if variant == "A":
            return self._gen_4br_classic(bw, sd, nd)
        else:
            return self._gen_4br_study(bw, sd, nd)

    def _gen_4br_classic(self, bw: float, sd: float, nd: float) -> UnitPlan:
        """
        4BR变体A：经典四室两厅两卫。

        设计理念：
        - 三翼布局：主卧翼(极静) | 公共翼(动) | 次卧翼(静)
        - 独立餐厅：不与客厅合并，有独立空间
        - 双卫标配：主卫(套间)+公卫(走廊旁)
        - 湿区集中：厨房+公卫在北侧中央紧邻
        - 双阳台：客厅阳台+主卧阳台

        平面：
        南(+Z)
        ┌────────┬──────────┬────────┬───────┐
        │ 主卧    │  客厅     │ 次卧A  │次卧B  │
        │ (极静)  │  (动区)   │ (静区) │(静区) │
        ├──┬─────┼────┬─────┼────────┼───────┤
        │主│玄关  │餐厅 │厨房  │ 公卫   │次卧C  │
        │卫│/走廊 │(动) │(湿)  │ (湿)   │(静)  │
        └──┴─────┴────┴─────┴────────┴───────┘
        北(-Z)
        """
        # 南区四段
        master_w = self._j(bw * 0.25, 0.3)
        living_w = self._j(bw * 0.32, 0.3)
        bed_a_w = self._j(bw * 0.22, 0.2)
        bed_b_w = round(bw - master_w - living_w - bed_a_w, 2)

        # 北区
        master_bath_w = self._j(2.2, 0.2)
        entrance_w = round(master_w - master_bath_w, 2)
        if entrance_w < 1.2:
            master_bath_w = round(master_w - 1.2, 2)
            entrance_w = 1.2

        dining_w = self._j(max(2.2, living_w * 0.45), 0.2)
        kitchen_w = self._j(max(2.5, bw * 0.16), 0.2)
        pub_bath_w = self._j(max(1.8, 2.0), 0.1)
        bed_c_w = round(bw - master_bath_w - entrance_w - dining_w
                        - kitchen_w - pub_bath_w, 2)

        rooms = [
            # 南区
            self._room(RoomType.MASTER_BED, "MasterBed", master_w, sd,
                       0, nd, Facing.SOUTH, WindowType.STANDARD,
                       balcony=True, ac=True, zone="static"),
            self._room(RoomType.LIVING, "Living", living_w, sd,
                       master_w, nd, Facing.SOUTH, WindowType.LARGE,
                       balcony=True, zone="dynamic"),
            self._room(RoomType.BEDROOM, "BedroomA", bed_a_w, sd,
                       master_w + living_w, nd, Facing.SOUTH,
                       WindowType.STANDARD, ac=True, zone="static"),
            self._room(RoomType.BEDROOM, "BedroomB", bed_b_w, sd,
                       master_w + living_w + bed_a_w, nd,
                       Facing.SOUTH, WindowType.STANDARD,
                       ac=True, zone="static"),
            # 北区
            self._room(RoomType.BATHROOM, "BathMaster", master_bath_w, nd,
                       0, 0, Facing.NORTH, WindowType.SMALL,
                       zone="wet", suite=True, pipe=True),
            self._room(RoomType.ENTRANCE, "Entrance", entrance_w, nd,
                       master_bath_w, 0, Facing.INTERIOR,
                       zone="transition"),
            self._room(RoomType.DINING, "Dining", dining_w, nd,
                       master_w, 0, Facing.INTERIOR,
                       zone="dynamic"),
            self._room(RoomType.KITCHEN, "Kitchen", kitchen_w, nd,
                       master_w + dining_w, 0, Facing.NORTH,
                       WindowType.SMALL, zone="wet", pipe=True),
            self._room(RoomType.BATHROOM, "BathPub", pub_bath_w, nd,
                       master_w + dining_w + kitchen_w, 0,
                       Facing.NORTH, WindowType.SMALL,
                       zone="wet", pipe=True),
            self._room(RoomType.BEDROOM, "BedroomC", bed_c_w, nd,
                       master_w + dining_w + kitchen_w + pub_bath_w, 0,
                       Facing.NORTH, WindowType.STANDARD,
                       ac=True, zone="static"),
        ]

        plan = UnitPlan(unit_type="4BR", rooms=rooms,
                        south_depth=sd, north_depth=nd)
        plan.compute_bounds()
        return plan

    def _gen_4br_study(self, bw: float, sd: float, nd: float) -> UnitPlan:
        """
        4BR变体B：主卧套间+书房。

        设计理念：
        - 主卧套间：主卧+主卫+衣帽间，极致私密
        - 书房朝南：安静采光好，适合工作学习
        - 三段式：主卧翼(极静) | 公共翼(动) | 书房+次卧翼(静)
        - 北面三个次卧+厨卫集中

        平面：
        南(+Z)
        ┌──────────┬──────────┬────────┬──────┐
        │ 主卧套间  │  客厅     │ 次卧A  │ 书房 │
        │ ┌──┬──┐  │  (动区)   │ (静区) │(静区)│
        │ │衣│主│  │          │        │      │
        │ │帽│卫│  │          │        │      │
        ├─┴──┴──┴──┼────┬─────┼────────┼──────┤
        │  玄关/走廊 │餐厅 │厨+卫 │ 次卧B  │次卧C │
        └──────────┴────┴─────┴────────┴──────┘
        北(-Z)
        """
        # 南区
        master_suite_w = self._j(bw * 0.28, 0.3)
        living_w = self._j(bw * 0.32, 0.3)
        bed_a_w = self._j(bw * 0.22, 0.2)
        study_w = round(bw - master_suite_w - living_w - bed_a_w, 2)

        # 主卧套间内部
        closet_w = self._j(1.5, 0.1)
        master_bath_w = self._j(2.0, 0.2)
        suite_inner_d = self._j(2.2, 0.2)

        # 北区
        entrance_w = self._j(max(1.5, master_suite_w * 0.6), 0.2)
        dining_w = self._j(max(2.0, living_w * 0.45), 0.2)
        kitchen_w = self._j(max(2.0, bw * 0.14), 0.1)
        pub_bath_w = self._j(max(1.5, 1.8), 0.1)
        remaining_n = round(bw - entrance_w - dining_w - kitchen_w
                            - pub_bath_w, 2)
        bed_b_w = self._j(remaining_n * 0.5, 0.2)
        bed_c_w = round(remaining_n - bed_b_w, 2)

        rooms = [
            # 南区 - 主卧套间
            self._room(RoomType.MASTER_BED, "MasterBed", master_suite_w, sd,
                       0, nd, Facing.SOUTH, WindowType.STANDARD,
                       balcony=True, ac=True, zone="static"),
            self._room(RoomType.BATHROOM, "BathMaster", master_bath_w,
                       suite_inner_d,
                       0, nd + sd - suite_inner_d,
                       Facing.INTERIOR, zone="wet",
                       suite=True, pipe=True),
            self._room(RoomType.WALK_IN_CLOSET, "Closet", closet_w,
                       suite_inner_d,
                       master_bath_w, nd + sd - suite_inner_d,
                       Facing.INTERIOR, zone="static", suite=True),
            # 南区 - 客厅 + 次卧A + 书房
            self._room(RoomType.LIVING, "Living", living_w, sd,
                       master_suite_w, nd, Facing.SOUTH, WindowType.LARGE,
                       balcony=True, zone="dynamic"),
            self._room(RoomType.BEDROOM, "BedroomA", bed_a_w, sd,
                       master_suite_w + living_w, nd,
                       Facing.SOUTH, WindowType.STANDARD,
                       ac=True, zone="static"),
            self._room(RoomType.STUDY, "Study", study_w, sd,
                       master_suite_w + living_w + bed_a_w, nd,
                       Facing.SOUTH, WindowType.STANDARD,
                       zone="static"),
            # 北区
            self._room(RoomType.ENTRANCE, "Entrance", entrance_w, nd,
                       0, 0, Facing.INTERIOR, zone="transition"),
            self._room(RoomType.DINING, "Dining", dining_w, nd,
                       entrance_w, 0, Facing.INTERIOR, zone="dynamic"),
            self._room(RoomType.KITCHEN, "Kitchen", kitchen_w, nd,
                       entrance_w + dining_w, 0, Facing.NORTH,
                       WindowType.SMALL, zone="wet", pipe=True),
            self._room(RoomType.BATHROOM, "BathPub", pub_bath_w, nd,
                       entrance_w + dining_w + kitchen_w, 0,
                       Facing.NORTH, WindowType.SMALL,
                       zone="wet", pipe=True),
            self._room(RoomType.BEDROOM, "BedroomB", bed_b_w, nd,
                       entrance_w + dining_w + kitchen_w + pub_bath_w, 0,
                       Facing.NORTH, WindowType.STANDARD,
                       ac=True, zone="static"),
            self._room(RoomType.BEDROOM, "BedroomC", bed_c_w, nd,
                       entrance_w + dining_w + kitchen_w + pub_bath_w
                       + bed_b_w, 0,
                       Facing.NORTH, WindowType.STANDARD,
                       ac=True, zone="static"),
        ]

        plan = UnitPlan(unit_type="4BR", rooms=rooms,
                        south_depth=sd, north_depth=nd)
        plan.compute_bounds()
        return plan

    # =================================================================
    # Loft Duplex: 立体生活
    # =================================================================
    def generate_loft_duplex(self, bw: float, sd: float, nd: float) -> UnitPlan:
        """
        复式/LOFT — 立体生活。

        设计理念：
        - 上下层彻底动静分离：下层=全动区，上层=全静区
        - 下层：挑高客厅+餐厅(动) + 厨卫集中(湿)
        - 上层：卧室+书房(静)，由建筑生成器处理
        - 湿区全部在下层北侧：厨房+卫生间紧邻
        - 楼梯间在北侧，连接上下层

        下层平面：
        南(+Z)
        ┌─────────────────┐
        │                  │
        │  客厅（挑高）     │  ← 动区核心
        │  +餐厅           │
        │                  │
        ├────────┬────┬────┤
        │ 厨房    │卫生│楼梯│  ← 湿区集中 + 交通
        │        │间  │间  │
        └────────┴────┴────┘
        北(-Z)
        """
        # 南区：挑高客厅+餐厅
        living_d = sd

        # 北区：厨房 | 卫生间 | 楼梯间
        # 湿区集中：厨房和卫生间紧邻
        kitchen_w = self._j(max(2.5, bw * 0.45), 0.2)
        bath_w = self._j(max(1.8, bw * 0.25), 0.1)
        stair_w = round(bw - kitchen_w - bath_w, 2)

        rooms = [
            # 南区：客厅+餐厅（动区，挑高）
            self._room(RoomType.LIVING, "Living", bw, living_d,
                       0, nd, Facing.SOUTH, WindowType.FLOOR_TO_CEILING,
                       balcony=True, zone="dynamic"),
            # 北区：湿区集中
            self._room(RoomType.KITCHEN, "Kitchen", kitchen_w, nd,
                       0, 0, Facing.NORTH, WindowType.SMALL,
                       zone="wet", pipe=True),
            self._room(RoomType.BATHROOM, "Bathroom", bath_w, nd,
                       kitchen_w, 0, Facing.NORTH, WindowType.SMALL,
                       zone="wet", pipe=True),
            self._room(RoomType.STAIRCASE, "Staircase", stair_w, nd,
                       kitchen_w + bath_w, 0, Facing.INTERIOR,
                       zone="transition"),
        ]

        plan = UnitPlan(unit_type="loft", rooms=rooms,
                        south_depth=sd, north_depth=nd)
        plan.compute_bounds()
        return plan


# =============================================================================
# 主入口：UnitPlanGenerator
# =============================================================================

class UnitPlanGenerator:
    """
    户型平面生成器 v2（设计理念驱动）。

    每种户型模板遵循不同的建筑设计哲学：
    - studio:       极致效率
    - compact_1br:  功能完整的最小住宅
    - standard_2br: 经典南北通透
    - comfort_3br:  全功能家庭住宅
    - luxury_4br:   尊享空间
    - loft_duplex:  立体生活

    使用方式：
        plan = UnitPlanGenerator.generate("comfort_3br")
        plan = UnitPlanGenerator.generate("3BR", seed=42)
        plan = UnitPlanGenerator.random("3BR", seed=456)
    """

    _GENERATORS = {
        "studio": "generate_studio",
        "compact_1br": "generate_compact_1br",
        "standard_2br": "generate_standard_2br",
        "comfort_3br": "generate_comfort_3br",
        "luxury_4br": "generate_luxury_4br",
        "loft_duplex": "generate_loft_duplex",
    }

    @staticmethod
    def _resolve_template(template: str) -> str:
        if template in TEMPLATE_REGISTRY:
            return template
        if template in _SHORTHAND_MAP:
            return _SHORTHAND_MAP[template]
        raise ValueError(
            f"Unknown template: '{template}'. "
            f"Available: {list(TEMPLATE_REGISTRY.keys())} "
            f"or shorthands: {list(_SHORTHAND_MAP.keys())}"
        )

    @staticmethod
    def generate(
        template: str,
        bay_width: float = 0,
        depth_south: float = 0,
        depth_north: float = 0,
        seed: int = 0,
    ) -> UnitPlan:
        tid = UnitPlanGenerator._resolve_template(template)
        info = TEMPLATE_REGISTRY[tid]
        rng = random.Random(seed if seed != 0 else None)

        bw = info.bay_width.clamp(bay_width) if bay_width > 0 else info.bay_width.default
        sd = info.depth_south.clamp(depth_south) if depth_south > 0 else info.depth_south.default
        nd = info.depth_north.clamp(depth_north) if depth_north > 0 else info.depth_north.default

        engine = _LayoutEngine(rng)
        gen_method = getattr(engine, UnitPlanGenerator._GENERATORS[tid])
        return gen_method(bw, sd, nd)

    @staticmethod
    def random(
        unit_type: str,
        seed: int = 0,
    ) -> UnitPlan:
        tid = UnitPlanGenerator._resolve_template(unit_type)
        info = TEMPLATE_REGISTRY[tid]
        rng = random.Random(seed if seed != 0 else None)

        bw = info.bay_width.sample(rng)
        sd = info.depth_south.sample(rng)
        nd = info.depth_north.sample(rng)

        engine = _LayoutEngine(rng)
        gen_method = getattr(engine, UnitPlanGenerator._GENERATORS[tid])
        return gen_method(bw, sd, nd)

    @staticmethod
    def list_templates() -> Dict[str, TemplateInfo]:
        return dict(TEMPLATE_REGISTRY)

    @staticmethod
    def template_info(template: str) -> TemplateInfo:
        tid = UnitPlanGenerator._resolve_template(template)
        return TEMPLATE_REGISTRY[tid]
