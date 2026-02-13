"""
Unit Plan Generator: 参数化户型平面生成模块。

提供多种户型模板，每种模板可根据面宽/进深参数和随机种子生成不同变体。
输出标准的 UnitPlan 对象，供 FloorPlanFactory 和 ResidentialGenerator 消费。

户型模板清单：
  - studio:       开间/公寓（约25~35㎡）
  - compact_1br:  紧凑一居（约40~55㎡）
  - standard_2br: 标准两居（约70~90㎡）
  - comfort_3br:  舒适三居（约100~130㎡）
  - luxury_4br:   豪华四居（约130~170㎡）
  - loft_duplex:  复式/LOFT（约50~80㎡，标记双层）

设计规范（遵循中国住宅设计常理）：
  - 南区（+Z）：客厅、主卧、次卧（采光面）
  - 北区（-Z）：厨房、卫生间、走廊
  - 面宽分配优先级：客厅 > 主卧 > 次卧 > 厨房 > 卫生间
  - 南区进深 > 北区进深
  - 走廊连接南北区
  - 阳台：客厅和主卧朝南面
  - 空调位：每个卧室配一个
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
        """
        在范围内采样一个值。

        Args:
            rng: 随机数生成器
            bias: 偏向系数 [-1, 1]，-1=最小值，0=中间值，1=最大值
        """
        center = (self.min_val + self.max_val) / 2
        half = (self.max_val - self.min_val) / 2
        # 高斯采样，截断到范围内
        val = center + bias * half + rng.gauss(0, half * 0.3)
        return max(self.min_val, min(self.max_val, round(val, 1)))

    def clamp(self, val: float) -> float:
        return max(self.min_val, min(self.max_val, round(val, 1)))


@dataclass
class TemplateInfo:
    """模板元信息。"""
    template_id: str
    display_name: str
    unit_type: str          # "1BR"/"2BR"/"3BR"/"4BR"/"studio"/"loft"
    num_bedrooms: int
    area_range: Tuple[float, float]     # 面积范围（㎡）
    bay_width: ParamRange               # 总面宽范围
    depth_south: ParamRange             # 南区进深范围
    depth_north: ParamRange             # 北区进深范围
    description: str = ""


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
    ),
}

# 简写映射：向后兼容 "1BR" → "compact_1br" 等
_SHORTHAND_MAP = {
    "studio": "studio",
    "1BR": "compact_1br",
    "2BR": "standard_2br",
    "3BR": "comfort_3br",
    "4BR": "luxury_4br",
    "loft": "loft_duplex",
}


# =============================================================================
# 布局规则引擎
# =============================================================================

class _LayoutEngine:
    """
    户型布局规则引擎。

    根据模板参数和随机种子，按照中国住宅设计规范生成房间布局。
    核心思路：先确定南北分区的尺寸，再按优先级在各区内分配房间面宽。
    """

    def __init__(self, rng: random.Random):
        self.rng = rng

    def _jitter(self, base: float, amplitude: float = 0.3) -> float:
        """给基础值添加微小随机抖动。"""
        return round(base + self.rng.uniform(-amplitude, amplitude), 1)

    def _make_room(self, room_type: RoomType, name: str, width: float,
                   depth: float, x: float, z: float,
                   facing: Facing = Facing.INTERIOR,
                   window_type: WindowType = WindowType.NONE,
                   has_balcony: bool = False,
                   has_ac_slot: bool = False) -> Room:
        """创建一个房间，确保尺寸合理。"""
        return Room(
            room_type=room_type,
            width=max(1.0, round(width, 1)),
            depth=max(1.0, round(depth, 1)),
            x=round(x, 1),
            z=round(z, 1),
            name=name,
            facing=facing,
            window_type=window_type,
            has_balcony=has_balcony,
            has_ac_slot=has_ac_slot,
        )

    # -----------------------------------------------------------------
    # Studio: 开间/公寓
    # -----------------------------------------------------------------
    def generate_studio(self, bay_w: float, sd: float, nd: float) -> UnitPlan:
        """
        开间/公寓布局：

        南(+Z)
        ┌──────────────┐
        │ 客厅/卧室     │  ← 南向（开放式）
        │ bay_w × sd   │
        ├──────┬───────┤
        │ 厨房  │ 卫生间 │  ← 北向
        └──────┴───────┘
        北(-Z)
        """
        kitchen_w = self._jitter(max(2.0, bay_w * 0.5), 0.2)
        bath_w = bay_w - kitchen_w

        rooms = [
            self._make_room(RoomType.LIVING, "LivingBed", bay_w, sd,
                            0, nd, Facing.SOUTH, WindowType.LARGE,
                            has_balcony=True),
            self._make_room(RoomType.KITCHEN, "Kitchen", kitchen_w, nd,
                            0, 0, Facing.NORTH, WindowType.SMALL),
            self._make_room(RoomType.BATHROOM, "Bathroom", bath_w, nd,
                            kitchen_w, 0, Facing.NORTH, WindowType.SMALL),
        ]

        plan = UnitPlan(unit_type="studio", rooms=rooms,
                        south_depth=sd, north_depth=nd)
        plan.compute_bounds()
        return plan

    # -----------------------------------------------------------------
    # Compact 1BR: 紧凑一居
    # -----------------------------------------------------------------
    def generate_compact_1br(self, bay_w: float, sd: float, nd: float) -> UnitPlan:
        """
        紧凑一居布局：

        南(+Z)
        ┌──────────────────┐
        │ 客厅     │ 主卧   │  ← 南向
        ├──────┬───┼────────┤
        │ 厨房  │走廊│ 卫生间 │  ← 北向
        └──────┴───┴────────┘
        北(-Z)

        面宽分配：客厅 ~55%, 主卧 ~45%
        """
        living_w = self._jitter(bay_w * 0.55, 0.3)
        master_w = bay_w - living_w

        # 北区
        kitchen_w = self._jitter(max(2.2, bay_w * 0.35), 0.2)
        bath_w = self._jitter(max(1.8, bay_w * 0.25), 0.2)
        corridor_w = bay_w - kitchen_w - bath_w

        rooms = [
            # 南区
            self._make_room(RoomType.LIVING, "Living", living_w, sd,
                            0, nd, Facing.SOUTH, WindowType.LARGE,
                            has_balcony=True),
            self._make_room(RoomType.MASTER_BED, "MasterBed", master_w, sd,
                            living_w, nd, Facing.SOUTH, WindowType.STANDARD,
                            has_ac_slot=True),
            # 北区
            self._make_room(RoomType.KITCHEN, "Kitchen", kitchen_w, nd,
                            0, 0, Facing.NORTH, WindowType.SMALL),
            self._make_room(RoomType.CORRIDOR, "Corridor", corridor_w, nd,
                            kitchen_w, 0, Facing.INTERIOR),
            self._make_room(RoomType.BATHROOM, "Bathroom", bath_w, nd,
                            kitchen_w + corridor_w, 0, Facing.NORTH,
                            WindowType.SMALL),
        ]

        plan = UnitPlan(unit_type="1BR", rooms=rooms,
                        south_depth=sd, north_depth=nd)
        plan.compute_bounds()
        return plan

    # -----------------------------------------------------------------
    # Standard 2BR: 标准两居
    # -----------------------------------------------------------------
    def generate_standard_2br(self, bay_w: float, sd: float, nd: float) -> UnitPlan:
        """
        标准两居布局（多种变体）：

        变体A（次卧朝南）：
        南(+Z)
        ┌──────────────────────┐
        │ 客厅     │ 主卧  │次卧│  ← 南向
        ├──────┬───┼───────┤   │
        │ 厨房  │走廊│ 卫A   │   │  ← 北向
        └──────┴───┴───────┴───┘

        变体B（次卧朝北，经典南北通透）：
        南(+Z)
        ┌──────────────────────┐
        │ 客厅     │ 主卧      │  ← 南向
        ├──────┬───┼─────┬─────┤
        │ 厨房  │走廊│ 卫A │ 次卧 │  ← 北向
        └──────┴───┴─────┴─────┘
        """
        variant = self.rng.choice(["A", "B"])

        if variant == "A":
            return self._gen_2br_variant_a(bay_w, sd, nd)
        else:
            return self._gen_2br_variant_b(bay_w, sd, nd)

    def _gen_2br_variant_a(self, bay_w: float, sd: float, nd: float) -> UnitPlan:
        """2BR变体A：次卧朝南，南面三开间。"""
        # 面宽分配：客厅 ~40%, 主卧 ~35%, 次卧 ~25%
        living_w = self._jitter(bay_w * 0.40, 0.3)
        master_w = self._jitter(bay_w * 0.35, 0.2)
        bed2_w = bay_w - living_w - master_w

        # 次卧进深可能与南区不同，形成凹凸
        bed2_d = self._jitter(sd, 0.3)

        # 北区
        kitchen_w = self._jitter(max(2.2, living_w * 0.65), 0.2)
        corridor_w = self._jitter(max(1.2, 1.5), 0.1)
        bath_w = living_w + master_w - kitchen_w - corridor_w

        rooms = [
            # 南区
            self._make_room(RoomType.LIVING, "Living", living_w, sd,
                            0, nd, Facing.SOUTH, WindowType.LARGE,
                            has_balcony=True),
            self._make_room(RoomType.MASTER_BED, "MasterBed", master_w, sd,
                            living_w, nd, Facing.SOUTH, WindowType.STANDARD,
                            has_balcony=True, has_ac_slot=True),
            self._make_room(RoomType.BEDROOM, "BedroomA", bed2_w, bed2_d,
                            living_w + master_w, nd + (sd - bed2_d),
                            Facing.SOUTH, WindowType.STANDARD, has_ac_slot=True),
            # 北区
            self._make_room(RoomType.KITCHEN, "Kitchen", kitchen_w, nd,
                            0, 0, Facing.NORTH, WindowType.SMALL),
            self._make_room(RoomType.CORRIDOR, "Corridor", corridor_w, nd,
                            kitchen_w, 0, Facing.INTERIOR),
            self._make_room(RoomType.BATHROOM, "BathA", bath_w, nd,
                            kitchen_w + corridor_w, 0, Facing.NORTH,
                            WindowType.SMALL),
        ]

        plan = UnitPlan(unit_type="2BR", rooms=rooms,
                        south_depth=sd, north_depth=nd)
        plan.compute_bounds()
        return plan

    def _gen_2br_variant_b(self, bay_w: float, sd: float, nd: float) -> UnitPlan:
        """2BR变体B：次卧朝北，经典南北通透。"""
        # 面宽分配：客厅 ~50%, 主卧 ~50%（南面两开间）
        living_w = self._jitter(bay_w * 0.52, 0.3)
        master_w = bay_w - living_w

        # 北区：厨房+走廊+卫+次卧
        kitchen_w = self._jitter(max(2.2, bay_w * 0.28), 0.2)
        corridor_w = self._jitter(max(1.2, 1.4), 0.1)
        bath_w = self._jitter(max(1.8, 2.0), 0.1)
        bed2_w = bay_w - kitchen_w - corridor_w - bath_w
        # 次卧进深可能比北区深
        bed2_d = self._jitter(max(nd, nd + 0.5), 0.3)

        rooms = [
            # 南区
            self._make_room(RoomType.LIVING, "Living", living_w, sd,
                            0, nd, Facing.SOUTH, WindowType.LARGE,
                            has_balcony=True),
            self._make_room(RoomType.MASTER_BED, "MasterBed", master_w, sd,
                            living_w, nd, Facing.SOUTH, WindowType.STANDARD,
                            has_balcony=True, has_ac_slot=True),
            # 北区
            self._make_room(RoomType.KITCHEN, "Kitchen", kitchen_w, nd,
                            0, 0, Facing.NORTH, WindowType.SMALL),
            self._make_room(RoomType.CORRIDOR, "Corridor", corridor_w, nd,
                            kitchen_w, 0, Facing.INTERIOR),
            self._make_room(RoomType.BATHROOM, "BathA", bath_w, nd,
                            kitchen_w + corridor_w, 0, Facing.NORTH,
                            WindowType.SMALL),
            self._make_room(RoomType.BEDROOM, "BedroomA", bed2_w, bed2_d,
                            kitchen_w + corridor_w + bath_w, 0,
                            Facing.NORTH, WindowType.STANDARD, has_ac_slot=True),
        ]

        plan = UnitPlan(unit_type="2BR", rooms=rooms,
                        south_depth=sd, north_depth=nd)
        plan.compute_bounds()
        return plan

    # -----------------------------------------------------------------
    # Comfort 3BR: 舒适三居
    # -----------------------------------------------------------------
    def generate_comfort_3br(self, bay_w: float, sd: float, nd: float) -> UnitPlan:
        """
        舒适三居布局（多种变体）：

        变体A（经典三室两厅）：
        南(+Z)
        ┌────────────────────────────────┐
        │ 主卧     │ 客厅      │ 次卧A  │  ← 南向
        ├─────┬────┼──────┬────┼────────┤
        │ 卫A │走廊 │ 餐厅  │厨房│ 次卧B  │  ← 北向
        └─────┴────┴──────┴────┴────────┘

        变体B（大客厅+两次卧朝北）：
        南(+Z)
        ┌──────────────────────────┐
        │ 主卧     │ 客厅         │  ← 南向（大面宽客厅）
        ├─────┬────┼────┬────┬────┤
        │ 卫A │走廊 │厨房│次卧A│次卧B│  ← 北向
        └─────┴────┴────┴────┴────┘

        变体C（主卧套间）：
        南(+Z)
        ┌──────────────────────────────┐
        │ 主卧+卫B  │ 客厅     │ 次卧A │  ← 南向
        ├─────┬─────┼────┬─────┼──────┤
        │ 卫A │走廊  │餐厅│ 厨房 │ 次卧B │  ← 北向
        └─────┴─────┴────┴─────┴──────┘
        """
        variant = self.rng.choice(["A", "B", "C"])

        if variant == "A":
            return self._gen_3br_variant_a(bay_w, sd, nd)
        elif variant == "B":
            return self._gen_3br_variant_b(bay_w, sd, nd)
        else:
            return self._gen_3br_variant_c(bay_w, sd, nd)

    def _gen_3br_variant_a(self, bay_w: float, sd: float, nd: float) -> UnitPlan:
        """3BR变体A：经典三室两厅，南面三开间。"""
        # 南面宽分配：主卧 ~30%, 客厅 ~42%, 次卧A ~28%
        master_w = self._jitter(bay_w * 0.30, 0.3)
        living_w = self._jitter(bay_w * 0.42, 0.3)
        bed_a_w = bay_w - master_w - living_w

        # 次卧A进深可能与南区不同
        bed_a_d = self._jitter(sd - 0.5, 0.3)

        # 北区
        bath_a_w = self._jitter(2.0, 0.2)
        corridor_w = self._jitter(1.5, 0.2)
        dining_w = self._jitter(max(1.5, living_w * 0.35), 0.2)
        kitchen_w = self._jitter(max(2.5, living_w * 0.65), 0.2)
        bed_b_w = bay_w - bath_a_w - corridor_w - dining_w - kitchen_w

        # 次卧B进深可能比北区深
        bed_b_d = self._jitter(nd + 0.3, 0.3)

        rooms = [
            # 南区
            self._make_room(RoomType.MASTER_BED, "MasterBed", master_w, sd,
                            0, nd, Facing.SOUTH, WindowType.STANDARD,
                            has_balcony=True, has_ac_slot=True),
            self._make_room(RoomType.LIVING, "Living", living_w, sd,
                            master_w, nd, Facing.SOUTH, WindowType.LARGE,
                            has_balcony=True),
            self._make_room(RoomType.BEDROOM, "BedroomA", bed_a_w, bed_a_d,
                            master_w + living_w, nd + (sd - bed_a_d),
                            Facing.SOUTH, WindowType.STANDARD, has_ac_slot=True),
            # 北区
            self._make_room(RoomType.BATHROOM, "BathA", bath_a_w, nd,
                            0, 0, Facing.NORTH, WindowType.SMALL),
            self._make_room(RoomType.CORRIDOR, "Corridor", corridor_w, nd,
                            bath_a_w, 0, Facing.INTERIOR),
            self._make_room(RoomType.DINING, "Dining", dining_w, nd,
                            bath_a_w + corridor_w, 0, Facing.INTERIOR),
            self._make_room(RoomType.KITCHEN, "Kitchen", kitchen_w, nd,
                            bath_a_w + corridor_w + dining_w, 0,
                            Facing.NORTH, WindowType.SMALL),
            self._make_room(RoomType.BEDROOM, "BedroomB", bed_b_w, bed_b_d,
                            bath_a_w + corridor_w + dining_w + kitchen_w, 0,
                            Facing.NORTH, WindowType.STANDARD, has_ac_slot=True),
            # 主卫（南区内侧）
            self._make_room(RoomType.BATHROOM, "BathB", bath_a_w, 2.0,
                            0, nd - 0.2 + sd - 2.0,
                            Facing.INTERIOR, WindowType.NONE),
        ]

        plan = UnitPlan(unit_type="3BR", rooms=rooms,
                        south_depth=sd, north_depth=nd)
        plan.compute_bounds()
        return plan

    def _gen_3br_variant_b(self, bay_w: float, sd: float, nd: float) -> UnitPlan:
        """3BR变体B：大客厅+两次卧朝北。"""
        # 南面两开间：主卧 ~35%, 客厅 ~65%
        master_w = self._jitter(bay_w * 0.32, 0.3)
        living_w = bay_w - master_w

        # 北区：卫A+走廊+厨房+次卧A+次卧B
        bath_a_w = self._jitter(2.0, 0.2)
        corridor_w = self._jitter(1.3, 0.1)
        kitchen_w = self._jitter(max(2.5, bay_w * 0.22), 0.2)
        remaining = bay_w - bath_a_w - corridor_w - kitchen_w
        bed_a_w = self._jitter(remaining * 0.5, 0.2)
        bed_b_w = remaining - bed_a_w

        rooms = [
            # 南区
            self._make_room(RoomType.MASTER_BED, "MasterBed", master_w, sd,
                            0, nd, Facing.SOUTH, WindowType.STANDARD,
                            has_balcony=True, has_ac_slot=True),
            self._make_room(RoomType.LIVING, "Living", living_w, sd,
                            master_w, nd, Facing.SOUTH, WindowType.LARGE,
                            has_balcony=True),
            # 北区
            self._make_room(RoomType.BATHROOM, "BathA", bath_a_w, nd,
                            0, 0, Facing.NORTH, WindowType.SMALL),
            self._make_room(RoomType.CORRIDOR, "Corridor", corridor_w, nd,
                            bath_a_w, 0, Facing.INTERIOR),
            self._make_room(RoomType.KITCHEN, "Kitchen", kitchen_w, nd,
                            bath_a_w + corridor_w, 0,
                            Facing.NORTH, WindowType.SMALL),
            self._make_room(RoomType.BEDROOM, "BedroomA", bed_a_w, nd,
                            bath_a_w + corridor_w + kitchen_w, 0,
                            Facing.NORTH, WindowType.STANDARD, has_ac_slot=True),
            self._make_room(RoomType.BEDROOM, "BedroomB", bed_b_w, nd,
                            bath_a_w + corridor_w + kitchen_w + bed_a_w, 0,
                            Facing.NORTH, WindowType.STANDARD, has_ac_slot=True),
        ]

        plan = UnitPlan(unit_type="3BR", rooms=rooms,
                        south_depth=sd, north_depth=nd)
        plan.compute_bounds()
        return plan

    def _gen_3br_variant_c(self, bay_w: float, sd: float, nd: float) -> UnitPlan:
        """3BR变体C：主卧套间（主卧+主卫一体）。"""
        # 南面三开间：主卧套间 ~38%, 客厅 ~38%, 次卧A ~24%
        master_suite_w = self._jitter(bay_w * 0.38, 0.3)
        living_w = self._jitter(bay_w * 0.38, 0.3)
        bed_a_w = bay_w - master_suite_w - living_w

        # 主卧套间内部分割：主卧 + 主卫
        master_bath_w = self._jitter(2.0, 0.2)
        master_bed_w = master_suite_w - master_bath_w

        # 北区
        bath_a_w = self._jitter(2.0, 0.2)
        corridor_w = self._jitter(1.4, 0.1)
        dining_w = self._jitter(1.5, 0.2)
        kitchen_w = self._jitter(max(2.5, bay_w * 0.2), 0.2)
        bed_b_w = bay_w - bath_a_w - corridor_w - dining_w - kitchen_w

        rooms = [
            # 南区 - 主卧套间
            self._make_room(RoomType.MASTER_BED, "MasterBed", master_bed_w, sd,
                            0, nd, Facing.SOUTH, WindowType.STANDARD,
                            has_balcony=True, has_ac_slot=True),
            self._make_room(RoomType.BATHROOM, "BathB", master_bath_w,
                            min(2.5, sd * 0.55),
                            master_bed_w, nd, Facing.INTERIOR, WindowType.NONE),
            # 南区 - 客厅 + 次卧A
            self._make_room(RoomType.LIVING, "Living", living_w, sd,
                            master_suite_w, nd, Facing.SOUTH, WindowType.LARGE,
                            has_balcony=True),
            self._make_room(RoomType.BEDROOM, "BedroomA", bed_a_w, sd,
                            master_suite_w + living_w, nd,
                            Facing.SOUTH, WindowType.STANDARD, has_ac_slot=True),
            # 北区
            self._make_room(RoomType.BATHROOM, "BathA", bath_a_w, nd,
                            0, 0, Facing.NORTH, WindowType.SMALL),
            self._make_room(RoomType.CORRIDOR, "Corridor", corridor_w, nd,
                            bath_a_w, 0, Facing.INTERIOR),
            self._make_room(RoomType.DINING, "Dining", dining_w, nd,
                            bath_a_w + corridor_w, 0, Facing.INTERIOR),
            self._make_room(RoomType.KITCHEN, "Kitchen", kitchen_w, nd,
                            bath_a_w + corridor_w + dining_w, 0,
                            Facing.NORTH, WindowType.SMALL),
            self._make_room(RoomType.BEDROOM, "BedroomB", bed_b_w, nd,
                            bath_a_w + corridor_w + dining_w + kitchen_w, 0,
                            Facing.NORTH, WindowType.STANDARD, has_ac_slot=True),
        ]

        plan = UnitPlan(unit_type="3BR", rooms=rooms,
                        south_depth=sd, north_depth=nd)
        plan.compute_bounds()
        return plan

    # -----------------------------------------------------------------
    # Luxury 4BR: 豪华四居
    # -----------------------------------------------------------------
    def generate_luxury_4br(self, bay_w: float, sd: float, nd: float) -> UnitPlan:
        """
        豪华四居布局（多种变体）：

        变体A（经典四室两厅）：
        南(+Z)
        ┌──────────────────────────────────────┐
        │ 主卧     │ 客厅      │ 次卧A │ 次卧B │  ← 南向
        ├─────┬────┼──────┬────┼───────┼───────┤
        │ 卫A │走廊 │ 餐厅  │厨房│ 次卧C  │ 卫B  │  ← 北向
        └─────┴────┴──────┴────┴───────┴───────┘

        变体B（主卧套间+书房）：
        南(+Z)
        ┌──────────────────────────────────────┐
        │ 主卧+卫B │ 客厅      │ 次卧A │ 书房  │  ← 南向
        ├─────┬────┼──────┬────┼───────┼───────┤
        │ 卫A │走廊 │ 餐厅  │厨房│ 次卧B  │ 次卧C │  ← 北向
        └─────┴────┴──────┴────┴───────┴───────┘
        """
        variant = self.rng.choice(["A", "B"])

        if variant == "A":
            return self._gen_4br_variant_a(bay_w, sd, nd)
        else:
            return self._gen_4br_variant_b(bay_w, sd, nd)

    def _gen_4br_variant_a(self, bay_w: float, sd: float, nd: float) -> UnitPlan:
        """4BR变体A：经典四室两厅。"""
        # 南面四开间
        master_w = self._jitter(bay_w * 0.26, 0.3)
        living_w = self._jitter(bay_w * 0.34, 0.3)
        bed_a_w = self._jitter(bay_w * 0.20, 0.2)
        bed_b_w = bay_w - master_w - living_w - bed_a_w

        # 北区
        bath_a_w = self._jitter(2.2, 0.2)
        corridor_w = self._jitter(1.5, 0.2)
        dining_w = self._jitter(1.8, 0.2)
        kitchen_w = self._jitter(max(2.5, bay_w * 0.18), 0.2)
        bath_b_w = self._jitter(2.2, 0.2)
        bed_c_w = bay_w - bath_a_w - corridor_w - dining_w - kitchen_w - bath_b_w

        rooms = [
            # 南区
            self._make_room(RoomType.MASTER_BED, "MasterBed", master_w, sd,
                            0, nd, Facing.SOUTH, WindowType.STANDARD,
                            has_balcony=True, has_ac_slot=True),
            self._make_room(RoomType.LIVING, "Living", living_w, sd,
                            master_w, nd, Facing.SOUTH, WindowType.LARGE,
                            has_balcony=True),
            self._make_room(RoomType.BEDROOM, "BedroomA", bed_a_w, sd,
                            master_w + living_w, nd, Facing.SOUTH,
                            WindowType.STANDARD, has_ac_slot=True),
            self._make_room(RoomType.BEDROOM, "BedroomB", bed_b_w, sd,
                            master_w + living_w + bed_a_w, nd, Facing.SOUTH,
                            WindowType.STANDARD, has_ac_slot=True),
            # 北区
            self._make_room(RoomType.BATHROOM, "BathA", bath_a_w, nd,
                            0, 0, Facing.NORTH, WindowType.SMALL),
            self._make_room(RoomType.CORRIDOR, "Corridor", corridor_w, nd,
                            bath_a_w, 0, Facing.INTERIOR),
            self._make_room(RoomType.DINING, "Dining", dining_w, nd,
                            bath_a_w + corridor_w, 0, Facing.INTERIOR),
            self._make_room(RoomType.KITCHEN, "Kitchen", kitchen_w, nd,
                            bath_a_w + corridor_w + dining_w, 0,
                            Facing.NORTH, WindowType.SMALL),
            self._make_room(RoomType.BEDROOM, "BedroomC", bed_c_w, nd,
                            bath_a_w + corridor_w + dining_w + kitchen_w, 0,
                            Facing.NORTH, WindowType.STANDARD, has_ac_slot=True),
            self._make_room(RoomType.BATHROOM, "BathB", bath_b_w, nd,
                            bay_w - bath_b_w, 0, Facing.NORTH, WindowType.SMALL),
        ]

        plan = UnitPlan(unit_type="4BR", rooms=rooms,
                        south_depth=sd, north_depth=nd)
        plan.compute_bounds()
        return plan

    def _gen_4br_variant_b(self, bay_w: float, sd: float, nd: float) -> UnitPlan:
        """4BR变体B：主卧套间+书房。"""
        # 南面四开间：主卧套间 ~30%, 客厅 ~34%, 次卧A ~20%, 书房 ~16%
        master_suite_w = self._jitter(bay_w * 0.30, 0.3)
        living_w = self._jitter(bay_w * 0.34, 0.3)
        bed_a_w = self._jitter(bay_w * 0.20, 0.2)
        study_w = bay_w - master_suite_w - living_w - bed_a_w

        # 主卧套间内部
        master_bath_w = self._jitter(2.0, 0.2)
        master_bed_w = master_suite_w - master_bath_w

        # 北区
        bath_a_w = self._jitter(2.0, 0.2)
        corridor_w = self._jitter(1.4, 0.1)
        dining_w = self._jitter(1.5, 0.2)
        kitchen_w = self._jitter(max(2.5, bay_w * 0.18), 0.2)
        remaining_n = bay_w - bath_a_w - corridor_w - dining_w - kitchen_w
        bed_b_w = self._jitter(remaining_n * 0.5, 0.2)
        bed_c_w = remaining_n - bed_b_w

        rooms = [
            # 南区 - 主卧套间
            self._make_room(RoomType.MASTER_BED, "MasterBed", master_bed_w, sd,
                            0, nd, Facing.SOUTH, WindowType.STANDARD,
                            has_balcony=True, has_ac_slot=True),
            self._make_room(RoomType.BATHROOM, "BathB", master_bath_w,
                            min(2.5, sd * 0.55),
                            master_bed_w, nd, Facing.INTERIOR),
            # 南区 - 客厅 + 次卧A + 书房
            self._make_room(RoomType.LIVING, "Living", living_w, sd,
                            master_suite_w, nd, Facing.SOUTH, WindowType.LARGE,
                            has_balcony=True),
            self._make_room(RoomType.BEDROOM, "BedroomA", bed_a_w, sd,
                            master_suite_w + living_w, nd, Facing.SOUTH,
                            WindowType.STANDARD, has_ac_slot=True),
            self._make_room(RoomType.STORAGE, "Study", study_w, sd,
                            master_suite_w + living_w + bed_a_w, nd,
                            Facing.SOUTH, WindowType.STANDARD),
            # 北区
            self._make_room(RoomType.BATHROOM, "BathA", bath_a_w, nd,
                            0, 0, Facing.NORTH, WindowType.SMALL),
            self._make_room(RoomType.CORRIDOR, "Corridor", corridor_w, nd,
                            bath_a_w, 0, Facing.INTERIOR),
            self._make_room(RoomType.DINING, "Dining", dining_w, nd,
                            bath_a_w + corridor_w, 0, Facing.INTERIOR),
            self._make_room(RoomType.KITCHEN, "Kitchen", kitchen_w, nd,
                            bath_a_w + corridor_w + dining_w, 0,
                            Facing.NORTH, WindowType.SMALL),
            self._make_room(RoomType.BEDROOM, "BedroomB", bed_b_w, nd,
                            bath_a_w + corridor_w + dining_w + kitchen_w, 0,
                            Facing.NORTH, WindowType.STANDARD, has_ac_slot=True),
            self._make_room(RoomType.BEDROOM, "BedroomC", bed_c_w, nd,
                            bath_a_w + corridor_w + dining_w + kitchen_w + bed_b_w, 0,
                            Facing.NORTH, WindowType.STANDARD, has_ac_slot=True),
        ]

        plan = UnitPlan(unit_type="4BR", rooms=rooms,
                        south_depth=sd, north_depth=nd)
        plan.compute_bounds()
        return plan

    # -----------------------------------------------------------------
    # Loft Duplex: 复式/LOFT
    # -----------------------------------------------------------------
    def generate_loft_duplex(self, bay_w: float, sd: float, nd: float) -> UnitPlan:
        """
        复式/LOFT布局（标记为双层，实际生成单层平面）：

        下层平面：
        南(+Z)
        ┌──────────────────┐
        │ 客厅（挑高）     │  ← 南向
        ├──────┬───────────┤
        │ 厨房  │ 卫生间    │  ← 北向
        └──────┴───────────┘

        上层标记为 is_duplex=True，由建筑生成器处理。
        """
        living_w = bay_w
        kitchen_w = self._jitter(max(2.5, bay_w * 0.5), 0.2)
        bath_w = bay_w - kitchen_w

        rooms = [
            # 下层南区 - 挑高客厅
            self._make_room(RoomType.LIVING, "Living", living_w, sd,
                            0, nd, Facing.SOUTH, WindowType.FLOOR_TO_CEILING,
                            has_balcony=True),
            # 下层北区
            self._make_room(RoomType.KITCHEN, "Kitchen", kitchen_w, nd,
                            0, 0, Facing.NORTH, WindowType.SMALL),
            self._make_room(RoomType.BATHROOM, "Bathroom", bath_w, nd,
                            kitchen_w, 0, Facing.NORTH, WindowType.SMALL),
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
    户型平面生成器。

    提供多种户型模板，每种模板可根据面宽/进深参数和随机种子生成不同变体。
    替代原有的 UnitPlanPresets 硬编码预设系统。

    使用方式：
        # 使用默认参数
        plan = UnitPlanGenerator.generate("comfort_3br")

        # 指定面宽和随机种子
        plan = UnitPlanGenerator.generate("comfort_3br", bay_width=13.0, seed=42)

        # 使用简写（向后兼容）
        plan = UnitPlanGenerator.generate("3BR", seed=123)

        # 完全随机
        plan = UnitPlanGenerator.random("3BR", seed=456)
    """

    # 模板ID → 生成方法名的映射
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
        """将模板ID或简写解析为标准模板ID。"""
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
        """
        根据模板和参数生成户型平面。

        Args:
            template: 模板ID（如 "comfort_3br"）或简写（如 "3BR"）
            bay_width: 总面宽（米），0=使用模板默认值
            depth_south: 南区进深，0=使用模板默认值
            depth_north: 北区进深，0=使用模板默认值
            seed: 随机种子，0=使用随机种子

        Returns:
            UnitPlan 对象
        """
        tid = UnitPlanGenerator._resolve_template(template)
        info = TEMPLATE_REGISTRY[tid]
        rng = random.Random(seed if seed != 0 else None)

        # 确定参数值
        bw = info.bay_width.clamp(bay_width) if bay_width > 0 else info.bay_width.default
        sd = info.depth_south.clamp(depth_south) if depth_south > 0 else info.depth_south.default
        nd = info.depth_north.clamp(depth_north) if depth_north > 0 else info.depth_north.default

        # 调用对应的生成方法
        engine = _LayoutEngine(rng)
        gen_method = getattr(engine, UnitPlanGenerator._GENERATORS[tid])
        return gen_method(bw, sd, nd)

    @staticmethod
    def random(
        unit_type: str,
        seed: int = 0,
    ) -> UnitPlan:
        """
        根据户型类型随机选择参数生成。

        面宽和进深在模板允许范围内随机采样。

        Args:
            unit_type: 户型类型或模板ID
            seed: 随机种子

        Returns:
            UnitPlan 对象
        """
        tid = UnitPlanGenerator._resolve_template(unit_type)
        info = TEMPLATE_REGISTRY[tid]
        rng = random.Random(seed if seed != 0 else None)

        # 在范围内随机采样参数
        bw = info.bay_width.sample(rng)
        sd = info.depth_south.sample(rng)
        nd = info.depth_north.sample(rng)

        engine = _LayoutEngine(rng)
        gen_method = getattr(engine, UnitPlanGenerator._GENERATORS[tid])
        return gen_method(bw, sd, nd)

    @staticmethod
    def list_templates() -> Dict[str, TemplateInfo]:
        """列出所有可用模板及其参数范围。"""
        return dict(TEMPLATE_REGISTRY)

    @staticmethod
    def template_info(template: str) -> TemplateInfo:
        """获取指定模板的元信息。"""
        tid = UnitPlanGenerator._resolve_template(template)
        return TEMPLATE_REGISTRY[tid]
