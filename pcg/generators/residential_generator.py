"""
Residential Generator: 中国住宅小区商品房程序化生成器。

核心架构：
  以"户型单元"为最小重复模块，通过"一梯N户"的楼层平面布局，
  逐层堆叠生成整栋住宅楼。

建筑形制：
  板楼(slab): 南北朝向的长条形建筑
    - 南立面: 客厅大窗 + 卧室窗 + 阳台 + 空调机位
    - 北立面: 厨房窗 + 卫生间窗 + 空调机位
    - 东西山墙: 实墙或少量窗
    - 中央: 核心筒(楼梯间+电梯间)

  塔楼(tower): 近正方形平面
    - 四面均有窗户和阳台
    - 中央核心筒较大

坐标约定：
  - X轴: 建筑面宽方向（东西向）
  - Y轴: 高度方向（向上）
  - Z轴: 建筑进深方向（南北向，+Z=南，-Z=北）
  - 建筑质心在原点
  - 南立面 = +Z面，北立面 = -Z面
"""

import math
import random
from typing import Dict, Any, List, Tuple, Optional
from dataclasses import dataclass, field
from pxr import Gf, Vt, Sdf, UsdGeom

from pcg_core.engine import GeneratorBase, ResidentialConfig, UnitConfig
from pcg_core.usd_bridge import UsdBridge


# =============================================================================
# 户型单元运行时数据
# =============================================================================

@dataclass
class UnitLayout:
    """单个户型单元在楼层中的布局信息。"""
    index: int                  # 户型在楼层中的序号(0-based)
    config: UnitConfig          # 户型配置
    x_start: float              # 户型左边界X坐标
    x_end: float                # 户型右边界X坐标
    width: float                # 户型面宽

    # 南立面窗户布局（局部X坐标列表）
    south_windows: List[Tuple[float, float]] = field(default_factory=list)  # [(cx, width), ...]
    # 北立面窗户布局
    north_windows: List[Tuple[float, float]] = field(default_factory=list)
    # 阳台区域
    balcony_x_start: float = 0.0
    balcony_x_end: float = 0.0
    # 空调机位位置（局部X坐标列表）
    ac_positions: List[float] = field(default_factory=list)


class ResidentialGenerator(GeneratorBase):
    """中国住宅小区商品房程序化生成器。"""

    def __init__(self, bridge: UsdBridge, config: ResidentialConfig):
        super().__init__(bridge, config)
        self.cfg: ResidentialConfig = config
        random.seed(config.seed)

    def generate(self, parent_path: str = "") -> Dict[str, Any]:
        """执行完整的住宅楼生成流程。"""
        root = f"{parent_path}/{self.cfg.building_name}"
        self.bridge.define_xform(root)

        stats = {
            "building_name": self.cfg.building_name,
            "building_type": self.cfg.building_type,
            "num_floors": self.cfg.num_floors,
            "units_per_floor": self.cfg.units_per_floor,
        }

        # 第一步：解析户型配置，计算建筑总面宽
        with self._time_it("layout"):
            self._resolve_layout()
            stats["building_width"] = round(self._building_width, 1)
            stats["building_depth"] = round(self._building_depth, 1)
            stats["total_units"] = self.cfg.units_per_floor * self._residential_floors

        # 第二步：创建材质
        with self._time_it("materials"):
            self._create_materials(root)

        # 第三步：生成楼板
        with self._time_it("floor_slabs"):
            stats["num_floor_slabs"] = self._generate_floor_slabs(root)

        # 第四步：生成外墙壳体（每层）
        with self._time_it("walls"):
            wall_stats = self._generate_walls(root)
            stats.update(wall_stats)

        # 第五步：生成窗户（PointInstancer）
        with self._time_it("windows"):
            stats["num_windows"] = self._generate_windows(root)

        # 第六步：生成阳台
        with self._time_it("balconies"):
            stats["num_balconies"] = self._generate_balconies(root)

        # 第七步：生成空调机位
        with self._time_it("ac_units"):
            stats["num_ac_units"] = self._generate_ac_units(root)

        # 第八步：生成核心筒
        with self._time_it("core"):
            self._generate_core(root)

        # 第九步：底商（如果有）
        if self.cfg.has_ground_commercial:
            with self._time_it("commercial"):
                self._generate_commercial(root)

        # 第十步：入口门厅
        with self._time_it("entrance"):
            self._generate_entrance(root)

        # 第十一步：屋顶
        with self._time_it("roof"):
            self._generate_roof(root)

        # 第十二步：楼层分隔线装饰
        with self._time_it("floor_lines"):
            self._generate_floor_lines(root)

        # 第十三步：光照
        with self._time_it("lighting"):
            self._create_lighting(root)

        return stats

    # =========================================================================
    # 布局计算
    # =========================================================================

    def _resolve_layout(self):
        """
        解析户型配置，计算建筑总面宽和每户的布局位置。

        板楼布局（从西到东）：
          [户型A] [核心筒] [户型B]
          南立面朝+Z方向

        塔楼布局：
          核心筒在中央，户型单元围绕四面分布
        """
        n_units = self.cfg.units_per_floor

        # 解析户型配置
        if self.cfg.unit_types:
            unit_types = self.cfg.unit_types[:n_units]
            while len(unit_types) < n_units:
                unit_types.append(unit_types[-1])
        else:
            # 默认配置
            if n_units <= 2:
                unit_types = ["3BR"] * n_units
            elif n_units <= 4:
                unit_types = ["3BR", "2BR"] * (n_units // 2)
                if n_units % 2:
                    unit_types.append("2BR")
            else:
                unit_types = ["2BR"] * n_units

        self._unit_configs = [UnitConfig.preset(ut) for ut in unit_types]

        # 计算每户面宽
        unit_widths = [uc.unit_width for uc in self._unit_configs]
        total_unit_width = sum(unit_widths)

        # 核心筒宽度
        core_w = self.cfg.core_width
        self._core_width = core_w
        self._core_depth = self.cfg.core_depth if self.cfg.core_depth > 0 else self.cfg.building_depth

        # 建筑总面宽
        self._building_width = total_unit_width + core_w
        self._building_depth = self.cfg.building_depth

        # 计算每户的X坐标位置
        half_w = self._building_width / 2

        if self.cfg.building_type == "slab":
            # 板楼：左侧户型 + 核心筒 + 右侧户型
            self._unit_layouts = []

            if n_units == 1:
                # 一梯一户：核心筒在一侧
                uc = self._unit_configs[0]
                x_start = -half_w
                x_end = x_start + uc.unit_width
                layout = UnitLayout(index=0, config=uc,
                                    x_start=x_start, x_end=x_end,
                                    width=uc.unit_width)
                self._unit_layouts.append(layout)
                self._core_x_start = x_end
                self._core_x_end = x_end + core_w

            elif n_units == 2:
                # 一梯两户：经典板楼布局
                # [户型A] [核心筒] [户型B]
                uc_left = self._unit_configs[0]
                uc_right = self._unit_configs[1]

                x = -half_w
                layout_left = UnitLayout(index=0, config=uc_left,
                                         x_start=x, x_end=x + uc_left.unit_width,
                                         width=uc_left.unit_width)
                self._unit_layouts.append(layout_left)
                x += uc_left.unit_width

                self._core_x_start = x
                self._core_x_end = x + core_w
                x += core_w

                layout_right = UnitLayout(index=1, config=uc_right,
                                          x_start=x, x_end=x + uc_right.unit_width,
                                          width=uc_right.unit_width)
                self._unit_layouts.append(layout_right)

            else:
                # 一梯多户：核心筒在中央
                # [户型A] [户型B] [核心筒] [户型C] [户型D]
                left_count = n_units // 2
                right_count = n_units - left_count

                x = -half_w
                for i in range(left_count):
                    uc = self._unit_configs[i]
                    layout = UnitLayout(index=i, config=uc,
                                        x_start=x, x_end=x + uc.unit_width,
                                        width=uc.unit_width)
                    self._unit_layouts.append(layout)
                    x += uc.unit_width

                self._core_x_start = x
                self._core_x_end = x + core_w
                x += core_w

                for i in range(left_count, n_units):
                    uc = self._unit_configs[i]
                    layout = UnitLayout(index=i, config=uc,
                                        x_start=x, x_end=x + uc.unit_width,
                                        width=uc.unit_width)
                    self._unit_layouts.append(layout)
                    x += uc.unit_width

        else:
            # 塔楼：简化为类似板楼但更宽的进深
            self._unit_layouts = []
            x = -half_w
            left_count = n_units // 2
            for i in range(left_count):
                uc = self._unit_configs[i]
                layout = UnitLayout(index=i, config=uc,
                                    x_start=x, x_end=x + uc.unit_width,
                                    width=uc.unit_width)
                self._unit_layouts.append(layout)
                x += uc.unit_width

            self._core_x_start = x
            self._core_x_end = x + core_w
            x += core_w

            for i in range(left_count, n_units):
                uc = self._unit_configs[i]
                layout = UnitLayout(index=i, config=uc,
                                    x_start=x, x_end=x + uc.unit_width,
                                    width=uc.unit_width)
                self._unit_layouts.append(layout)
                x += uc.unit_width

        # 为每户计算窗户和阳台布局
        for layout in self._unit_layouts:
            self._compute_unit_facade(layout)

        # 计算住宅层数（扣除底商层）
        if self.cfg.has_ground_commercial:
            self._commercial_floors = self.cfg.commercial_floors
            self._commercial_height = self.cfg.commercial_height
            self._residential_floors = self.cfg.num_floors - self._commercial_floors
            self._residential_start_y = self._commercial_floors * self._commercial_height
        else:
            self._commercial_floors = 0
            self._commercial_height = 0
            self._residential_floors = self.cfg.num_floors
            self._residential_start_y = 0.0

        # 全局窗户收集器
        self._south_win_positions = []
        self._south_win_orientations = []
        self._north_win_positions = []
        self._north_win_orientations = []
        self._south_win_scales = []
        self._north_win_scales = []

    def _compute_unit_facade(self, layout: UnitLayout):
        """
        计算单个户型单元的立面元素布局。

        南立面（+Z面）窗户排布：
          - 客厅大窗（居中或偏左）
          - 卧室窗（每间一个）
          - 阳台区域

        北立面（-Z面）窗户排布：
          - 厨房窗
          - 卫生间窗
        """
        uc = layout.config
        w = layout.width
        margin = 0.8  # 窗户距户型边界的最小间距

        # ── 南立面窗户 ──
        south_wins = []
        # 可用宽度
        usable_w = w - 2 * margin
        sw = self.cfg.south_window_width

        # 客厅大窗（占据阳台区域）
        n_bays = uc.num_living_rooms + uc.num_bedrooms
        bay_width = usable_w / max(n_bays, 1)

        # 阳台区域（客厅对应的开间）
        balcony_bays = min(uc.balcony_bays, uc.num_living_rooms + 1)
        layout.balcony_x_start = layout.x_start + margin
        layout.balcony_x_end = layout.x_start + margin + balcony_bays * bay_width

        # 每个开间一个窗
        for i in range(n_bays):
            cx = margin + (i + 0.5) * bay_width
            win_w = min(sw, bay_width - 0.4)
            south_wins.append((cx, win_w))

        layout.south_windows = south_wins

        # ── 北立面窗户 ──
        north_wins = []
        nw = self.cfg.north_window_width
        # 厨房窗 + 卫生间窗（各一个，较小）
        n_north = 1 + 1  # 厨房 + 卫生间
        north_bay_w = usable_w / max(n_north + uc.num_bedrooms - 1, 2)

        for i in range(min(n_north, 3)):
            cx = margin + (i + 0.5) * north_bay_w
            north_wins.append((cx, nw))

        # 北向卧室窗（如果有北向卧室）
        if uc.num_bedrooms >= 3:
            for i in range(uc.num_bedrooms - 2):
                cx = margin + (n_north + i + 0.5) * north_bay_w
                north_wins.append((cx, min(self.cfg.south_window_width * 0.8, north_bay_w - 0.4)))

        layout.north_windows = north_wins

        # ── 空调机位位置 ──
        ac_positions = []
        n_ac = uc.num_ac_units
        ac_spacing = usable_w / (n_ac + 1)
        for i in range(n_ac):
            ac_positions.append(margin + (i + 1) * ac_spacing)
        layout.ac_positions = ac_positions

    # =========================================================================
    # 材质
    # =========================================================================

    def _create_materials(self, root: str):
        """创建所有材质。"""
        mat_root = f"{root}/Materials"
        self.bridge.define_scope(mat_root)

        self.bridge.create_material(f"{mat_root}/WallMat",
                                    diffuse_color=self.cfg.wall_color, roughness=0.7)
        self.bridge.create_material(f"{mat_root}/WindowMat",
                                    diffuse_color=self.cfg.window_color, roughness=0.1,
                                    metallic=0.3, opacity=0.7)
        self.bridge.create_material(f"{mat_root}/FloorMat",
                                    diffuse_color=self.cfg.floor_color, roughness=0.6)
        self.bridge.create_material(f"{mat_root}/RoofMat",
                                    diffuse_color=self.cfg.roof_color, roughness=0.8)
        self.bridge.create_material(f"{mat_root}/BalconySlabMat",
                                    diffuse_color=self.cfg.balcony_slab_color, roughness=0.6)
        self.bridge.create_material(f"{mat_root}/BalconyGlassMat",
                                    diffuse_color=self.cfg.balcony_glass_color, roughness=0.1,
                                    opacity=0.5)
        self.bridge.create_material(f"{mat_root}/AccentMat",
                                    diffuse_color=self.cfg.accent_color, roughness=0.6)
        self.bridge.create_material(f"{mat_root}/ACUnitMat",
                                    diffuse_color=self.cfg.ac_unit_color, roughness=0.8)
        self.bridge.create_material(f"{mat_root}/FloorLineMat",
                                    diffuse_color=self.cfg.floor_line_color, roughness=0.5)
        if self.cfg.has_ground_commercial:
            self.bridge.create_material(f"{mat_root}/ShopMat",
                                        diffuse_color=self.cfg.shopfront_color, roughness=0.4)
        if self.cfg.roof_style == "pitched":
            self.bridge.create_material(f"{mat_root}/PitchedRoofMat",
                                        diffuse_color=self.cfg.pitched_roof_color, roughness=0.7)

    # =========================================================================
    # 楼板
    # =========================================================================

    def _generate_floor_slabs(self, root: str) -> int:
        """生成所有楼板。"""
        slab_root = f"{root}/FloorSlabs"
        self.bridge.define_scope(slab_root)

        half_w = self._building_width / 2
        half_d = self._building_depth / 2
        ft = self.cfg.floor_thickness
        count = 0

        # 底商层楼板
        for i in range(self._commercial_floors):
            y = i * self.cfg.commercial_height
            self.bridge.create_box_mesh(
                f"{slab_root}/CommSlab_{i}",
                width=self._building_width, height=ft, depth=self._building_depth,
                translate=(0, y + ft / 2, 0),
                display_color=self.cfg.floor_color,
            )
            count += 1

        # 住宅层楼板
        for i in range(self._residential_floors + 1):  # +1 for roof slab
            y = self._residential_start_y + i * self.cfg.floor_height
            self.bridge.create_box_mesh(
                f"{slab_root}/ResSlab_{i}",
                width=self._building_width, height=ft, depth=self._building_depth,
                translate=(0, y + ft / 2, 0),
                display_color=self.cfg.floor_color,
            )
            count += 1

        return count

    # =========================================================================
    # 外墙
    # =========================================================================

    def _generate_walls(self, root: str) -> Dict[str, int]:
        """
        生成所有外墙。

        板楼外墙结构：
          - 南墙(+Z): 窗户墙（带开口）
          - 北墙(-Z): 窗户墙（较小开口）
          - 东墙(+X): 山墙（实墙为主）
          - 西墙(-X): 山墙（实墙为主）
        """
        wall_root = f"{root}/Walls"
        self.bridge.define_scope(wall_root)

        half_w = self._building_width / 2
        half_d = self._building_depth / 2
        wt = self.cfg.wall_thickness
        fh = self.cfg.floor_height
        ft = self.cfg.floor_thickness
        wall_h = fh - ft  # 净墙高

        wall_count = 0

        # 逐层生成
        for floor_i in range(self.cfg.num_floors):
            if floor_i < self._commercial_floors:
                # 底商层：单独处理
                continue

            res_floor_i = floor_i - self._commercial_floors
            y_base = self._residential_start_y + res_floor_i * fh + ft

            floor_root = f"{wall_root}/Floor_{floor_i}"
            self.bridge.define_scope(floor_root)

            # ── 南墙 (+Z面) ──
            south_holes = self._collect_south_holes(wall_h)
            self.bridge.create_wall_mesh(
                f"{floor_root}/SouthWall",
                width=self._building_width, height=wall_h, thickness=wt,
                holes=south_holes,
                translate=(0, y_base + wall_h / 2, half_d - wt / 2),
                display_color=self.cfg.wall_color,
            )
            wall_count += 1

            # 收集南向窗户位置（世界坐标）
            for hole in south_holes:
                wx = hole["x"]
                wy = y_base + hole["y"]
                wz = half_d
                self._south_win_positions.append((wx, wy, wz))
                self._south_win_orientations.append((1, 0, 0, 0))
                self._south_win_scales.append((hole["w"], hole["h"], 0.05))

            # ── 北墙 (-Z面) ──
            north_holes = self._collect_north_holes(wall_h)
            self.bridge.create_wall_mesh(
                f"{floor_root}/NorthWall",
                width=self._building_width, height=wall_h, thickness=wt,
                holes=north_holes,
                translate=(0, y_base + wall_h / 2, -half_d + wt / 2),
                display_color=self.cfg.wall_color,
            )
            wall_count += 1

            # 收集北向窗户位置
            for hole in north_holes:
                wx = hole["x"]
                wy = y_base + hole["y"]
                wz = -half_d
                self._north_win_positions.append((wx, wy, wz))
                # 北面窗户旋转180度
                self._north_win_orientations.append((0, 0, 1, 0))
                self._north_win_scales.append((hole["w"], hole["h"], 0.05))

            # ── 东山墙 (+X面) ──
            # depth 减去南北外墙厚度，避免转角穿模
            gable_depth = self._building_depth - 2 * wt
            self.bridge.create_box_mesh(
                f"{floor_root}/EastWall",
                width=wt, height=wall_h, depth=gable_depth,
                translate=(half_w - wt / 2, y_base + wall_h / 2, 0),
                display_color=self.cfg.wall_color,
            )
            wall_count += 1

            # ── 西山墙 (-X面) ──
            self.bridge.create_box_mesh(
                f"{floor_root}/WestWall",
                width=wt, height=wall_h, depth=gable_depth,
                translate=(-half_w + wt / 2, y_base + wall_h / 2, 0),
                display_color=self.cfg.wall_color,
            )
            wall_count += 1

        return {"num_wall_panels": wall_count}

    def _collect_south_holes(self, wall_h: float) -> List[Dict]:
        """收集南立面所有窗户开口。"""
        holes = []
        sill = self.cfg.window_sill_height
        wh = self.cfg.south_window_height
        # 窗户中心Y（相对于墙体中心）
        win_cy = sill + wh / 2 - wall_h / 2

        for layout in self._unit_layouts:
            for cx_local, win_w in layout.south_windows:
                # 转换为建筑坐标（相对于墙体中心X=0）
                cx_world = layout.x_start + cx_local
                holes.append({"x": cx_world, "y": win_cy, "w": win_w, "h": wh})

        return holes

    def _collect_north_holes(self, wall_h: float) -> List[Dict]:
        """收集北立面所有窗户开口。"""
        holes = []
        sill = self.cfg.window_sill_height
        wh = self.cfg.north_window_height
        win_cy = sill + wh / 2 - wall_h / 2

        for layout in self._unit_layouts:
            for cx_local, win_w in layout.north_windows:
                cx_world = layout.x_start + cx_local
                holes.append({"x": cx_world, "y": win_cy, "w": win_w, "h": wh})

        return holes

    # =========================================================================
    # 窗户（PointInstancer）
    # =========================================================================

    def _generate_windows(self, root: str) -> int:
        """使用PointInstancer生成所有窗户。"""
        win_root = f"{root}/Windows"
        self.bridge.define_scope(win_root)

        total = 0

        # 南向窗户
        if self._south_win_positions:
            # 创建窗户原型
            proto_path = f"{win_root}/SouthInstancer/Prototypes/WinProto"
            self.bridge.create_box_mesh(
                proto_path,
                width=1.0, height=1.0, depth=1.0,
                display_color=self.cfg.window_color,
            )
            self.bridge.create_point_instancer(
                f"{win_root}/SouthInstancer",
                prototype_paths=[proto_path],
                positions=self._south_win_positions,
                proto_indices=[0] * len(self._south_win_positions),
                orientations=self._south_win_orientations,
                scales=self._south_win_scales,
            )
            total += len(self._south_win_positions)

        # 北向窗户
        if self._north_win_positions:
            proto_path = f"{win_root}/NorthInstancer/Prototypes/WinProto"
            self.bridge.create_box_mesh(
                proto_path,
                width=1.0, height=1.0, depth=1.0,
                display_color=self.cfg.window_color,
            )
            self.bridge.create_point_instancer(
                f"{win_root}/NorthInstancer",
                prototype_paths=[proto_path],
                positions=self._north_win_positions,
                proto_indices=[0] * len(self._north_win_positions),
                orientations=self._north_win_orientations,
                scales=self._north_win_scales,
            )
            total += len(self._north_win_positions)

        return total

    # =========================================================================
    # 阳台
    # =========================================================================

    def _generate_balconies(self, root: str) -> int:
        """
        生成南向阳台。

        阳台结构：
          - 阳台底板（从南墙外挑出）
          - 阳台栏杆/封闭玻璃（三面围合）
        """
        bal_root = f"{root}/Balconies"
        self.bridge.define_scope(bal_root)

        half_d = self._building_depth / 2
        fh = self.cfg.floor_height
        ft = self.cfg.floor_thickness
        bd = self.cfg.balcony_depth
        rh = self.cfg.balcony_railing_height
        slab_t = 0.12  # 阳台板厚度
        railing_t = 0.08  # 栏杆/玻璃厚度
        count = 0

        for floor_i in range(self.cfg.num_floors):
            if floor_i < self._commercial_floors:
                continue

            res_floor_i = floor_i - self._commercial_floors
            y_base = self._residential_start_y + res_floor_i * fh + ft

            for layout in self._unit_layouts:
                if not layout.config.has_balcony:
                    continue

                bal_w = layout.balcony_x_end - layout.balcony_x_start
                if bal_w < 1.0:
                    continue

                bal_cx = (layout.balcony_x_start + layout.balcony_x_end) / 2
                bal_cz = half_d + bd / 2  # 阳台中心Z

                bal_path = f"{bal_root}/F{floor_i}_U{layout.index}"
                self.bridge.define_xform(bal_path)

                # 阳台底板
                self.bridge.create_box_mesh(
                    f"{bal_path}/Slab",
                    width=bal_w, height=slab_t, depth=bd,
                    translate=(bal_cx, y_base + slab_t / 2, bal_cz),
                    display_color=self.cfg.balcony_slab_color,
                )

                if self.cfg.balcony_type == "enclosed":
                    # 封闭阳台：三面玻璃
                    glass_color = self.cfg.balcony_glass_color
                    wall_h_bal = fh - ft - slab_t

                    # 前面玻璃
                    self.bridge.create_box_mesh(
                        f"{bal_path}/FrontGlass",
                        width=bal_w, height=wall_h_bal, depth=railing_t,
                        translate=(bal_cx, y_base + slab_t + wall_h_bal / 2,
                                   half_d + bd - railing_t / 2),
                        display_color=glass_color,
                    )
                    # 左侧玻璃
                    self.bridge.create_box_mesh(
                        f"{bal_path}/LeftGlass",
                        width=railing_t, height=wall_h_bal, depth=bd,
                        translate=(layout.balcony_x_start + railing_t / 2,
                                   y_base + slab_t + wall_h_bal / 2, bal_cz),
                        display_color=glass_color,
                    )
                    # 右侧玻璃
                    self.bridge.create_box_mesh(
                        f"{bal_path}/RightGlass",
                        width=railing_t, height=wall_h_bal, depth=bd,
                        translate=(layout.balcony_x_end - railing_t / 2,
                                   y_base + slab_t + wall_h_bal / 2, bal_cz),
                        display_color=glass_color,
                    )
                else:
                    # 开放阳台：三面栏杆
                    rail_color = self.cfg.accent_color

                    # 前面栏杆
                    self.bridge.create_box_mesh(
                        f"{bal_path}/FrontRail",
                        width=bal_w, height=rh, depth=railing_t,
                        translate=(bal_cx, y_base + slab_t + rh / 2,
                                   half_d + bd - railing_t / 2),
                        display_color=rail_color,
                    )
                    # 左侧栏杆
                    self.bridge.create_box_mesh(
                        f"{bal_path}/LeftRail",
                        width=railing_t, height=rh, depth=bd,
                        translate=(layout.balcony_x_start + railing_t / 2,
                                   y_base + slab_t + rh / 2, bal_cz),
                        display_color=rail_color,
                    )
                    # 右侧栏杆
                    self.bridge.create_box_mesh(
                        f"{bal_path}/RightRail",
                        width=railing_t, height=rh, depth=bd,
                        translate=(layout.balcony_x_end - railing_t / 2,
                                   y_base + slab_t + rh / 2, bal_cz),
                        display_color=rail_color,
                    )

                count += 1

        return count

    # =========================================================================
    # 空调机位
    # =========================================================================

    def _generate_ac_units(self, root: str) -> int:
        """
        生成空调外机位。

        空调机位结构：从北墙外挑出的小平台+格栅围挡。
        """
        ac_root = f"{root}/ACUnits"
        self.bridge.define_scope(ac_root)

        half_d = self._building_depth / 2
        fh = self.cfg.floor_height
        ft = self.cfg.floor_thickness
        ac_w = self.cfg.ac_unit_width
        ac_d = self.cfg.ac_unit_depth
        ac_h = self.cfg.ac_unit_height
        slab_t = 0.08
        count = 0

        for floor_i in range(self.cfg.num_floors):
            if floor_i < self._commercial_floors:
                continue

            res_floor_i = floor_i - self._commercial_floors
            y_base = self._residential_start_y + res_floor_i * fh + ft

            for layout in self._unit_layouts:
                for j, ac_x_local in enumerate(layout.ac_positions):
                    ac_cx = layout.x_start + ac_x_local
                    ac_cz = -half_d - ac_d / 2  # 北墙外侧

                    ac_path = f"{ac_root}/F{floor_i}_U{layout.index}_AC{j}"

                    # 空调机位底板
                    self.bridge.create_box_mesh(
                        f"{ac_path}_Slab",
                        width=ac_w, height=slab_t, depth=ac_d,
                        translate=(ac_cx, y_base + slab_t / 2, ac_cz),
                        display_color=self.cfg.ac_unit_color,
                    )

                    # 空调机位格栅围挡（前面+两侧）
                    grill_t = 0.04
                    # 前面
                    self.bridge.create_box_mesh(
                        f"{ac_path}_Front",
                        width=ac_w, height=ac_h, depth=grill_t,
                        translate=(ac_cx, y_base + slab_t + ac_h / 2,
                                   -half_d - ac_d + grill_t / 2),
                        display_color=self.cfg.ac_unit_color,
                    )
                    # 左侧
                    self.bridge.create_box_mesh(
                        f"{ac_path}_Left",
                        width=grill_t, height=ac_h, depth=ac_d,
                        translate=(ac_cx - ac_w / 2 + grill_t / 2,
                                   y_base + slab_t + ac_h / 2, ac_cz),
                        display_color=self.cfg.ac_unit_color,
                    )
                    # 右侧
                    self.bridge.create_box_mesh(
                        f"{ac_path}_Right",
                        width=grill_t, height=ac_h, depth=ac_d,
                        translate=(ac_cx + ac_w / 2 - grill_t / 2,
                                   y_base + slab_t + ac_h / 2, ac_cz),
                        display_color=self.cfg.ac_unit_color,
                    )

                    count += 1

        return count

    # =========================================================================
    # 核心筒
    # =========================================================================

    def _generate_core(self, root: str):
        """
        生成核心筒（楼梯间+电梯间）。

        核心筒是贯穿所有楼层的实心区域，用不同颜色标识。
        """
        core_root = f"{root}/Core"
        self.bridge.define_scope(core_root)

        core_cx = (self._core_x_start + self._core_x_end) / 2
        core_w = self._core_x_end - self._core_x_start
        core_d = self._core_depth
        wt = self.cfg.wall_thickness
        fh = self.cfg.floor_height
        ft = self.cfg.floor_thickness

        # 核心筒内墙（南北向隔墙）
        total_h = self.cfg.num_floors * fh
        if self.cfg.has_ground_commercial:
            total_h = self._commercial_floors * self._commercial_height + \
                      self._residential_floors * fh

        # 核心筒西墙
        self.bridge.create_box_mesh(
            f"{core_root}/WestWall",
            width=wt, height=total_h, depth=core_d - 2 * wt,
            translate=(self._core_x_start + wt / 2, total_h / 2, 0),
            display_color=self.cfg.wall_color,
        )

        # 核心筒东墙
        self.bridge.create_box_mesh(
            f"{core_root}/EastWall",
            width=wt, height=total_h, depth=core_d - 2 * wt,
            translate=(self._core_x_end - wt / 2, total_h / 2, 0),
            display_color=self.cfg.wall_color,
        )

    # =========================================================================
    # 底商
    # =========================================================================

    def _generate_commercial(self, root: str):
        """
        生成底商层。

        底商特征：
          - 更高的层高（3.5-4.5m）
          - 大面积玻璃幕墙/卷帘门
          - 深色店面框架
        """
        comm_root = f"{root}/Commercial"
        self.bridge.define_scope(comm_root)

        half_w = self._building_width / 2
        half_d = self._building_depth / 2
        wt = self.cfg.wall_thickness
        ch = self.cfg.commercial_height
        ft = self.cfg.floor_thickness

        for floor_i in range(self._commercial_floors):
            y_base = floor_i * ch + ft
            wall_h = ch - ft

            floor_path = f"{comm_root}/Floor_{floor_i}"
            self.bridge.define_scope(floor_path)

            # 南面店铺（大开间玻璃幕墙）
            n_shops = max(2, int(self._building_width / 6.0))
            shop_w = self._building_width / n_shops

            for i in range(n_shops):
                shop_cx = -half_w + (i + 0.5) * shop_w
                # 店面框架（深色）
                self.bridge.create_box_mesh(
                    f"{floor_path}/ShopFrame_S_{i}",
                    width=shop_w, height=wall_h, depth=wt,
                    translate=(shop_cx, y_base + wall_h / 2, half_d - wt / 2),
                    display_color=self.cfg.shopfront_color,
                )
                # 玻璃门窗（占店面80%宽度，90%高度）
                glass_w = shop_w * 0.8
                glass_h = wall_h * 0.85
                self.bridge.create_box_mesh(
                    f"{floor_path}/ShopGlass_S_{i}",
                    width=glass_w, height=glass_h, depth=0.03,
                    translate=(shop_cx, y_base + glass_h / 2 + 0.1,
                               half_d + 0.01),
                    display_color=(0.5, 0.65, 0.75),
                )

            # 北面（实墙+小窗）
            self.bridge.create_box_mesh(
                f"{floor_path}/NorthWall",
                width=self._building_width, height=wall_h, depth=wt,
                translate=(0, y_base + wall_h / 2, -half_d + wt / 2),
                display_color=self.cfg.shopfront_color,
            )

            # 东西山墙（depth减去南北外墙厚度，避免转角穿模）
            comm_gable_depth = self._building_depth - 2 * wt
            self.bridge.create_box_mesh(
                f"{floor_path}/EastWall",
                width=wt, height=wall_h, depth=comm_gable_depth,
                translate=(half_w - wt / 2, y_base + wall_h / 2, 0),
                display_color=self.cfg.shopfront_color,
            )
            self.bridge.create_box_mesh(
                f"{floor_path}/WestWall",
                width=wt, height=wall_h, depth=comm_gable_depth,
                translate=(-half_w + wt / 2, y_base + wall_h / 2, 0),
                display_color=self.cfg.shopfront_color,
            )

    # =========================================================================
    # 入口门厅
    # =========================================================================

    def _generate_entrance(self, root: str):
        """
        生成入口门厅。

        入口位于核心筒对应的南墙位置，包含：
          - 入口门洞
          - 雨棚（如果配置）
        """
        ent_root = f"{root}/Entrance"
        self.bridge.define_scope(ent_root)

        half_d = self._building_depth / 2
        ent_w = self.cfg.entrance_width
        ent_h = self.cfg.entrance_height
        core_cx = (self._core_x_start + self._core_x_end) / 2

        # 入口门框（深色）
        frame_t = 0.15
        # 左框
        self.bridge.create_box_mesh(
            f"{ent_root}/FrameLeft",
            width=frame_t, height=ent_h, depth=self.cfg.wall_thickness + 0.1,
            translate=(core_cx - ent_w / 2 - frame_t / 2, ent_h / 2,
                       half_d),
            display_color=self.cfg.accent_color,
        )
        # 右框
        self.bridge.create_box_mesh(
            f"{ent_root}/FrameRight",
            width=frame_t, height=ent_h, depth=self.cfg.wall_thickness + 0.1,
            translate=(core_cx + ent_w / 2 + frame_t / 2, ent_h / 2,
                       half_d),
            display_color=self.cfg.accent_color,
        )
        # 上框
        self.bridge.create_box_mesh(
            f"{ent_root}/FrameTop",
            width=ent_w + 2 * frame_t, height=frame_t, depth=self.cfg.wall_thickness + 0.1,
            translate=(core_cx, ent_h + frame_t / 2, half_d),
            display_color=self.cfg.accent_color,
        )

        # 入口玻璃门
        self.bridge.create_box_mesh(
            f"{ent_root}/GlassDoor",
            width=ent_w, height=ent_h * 0.95, depth=0.04,
            translate=(core_cx, ent_h * 0.95 / 2, half_d + 0.02),
            display_color=(0.5, 0.65, 0.78),
        )

        # 雨棚
        if self.cfg.has_entrance_canopy:
            canopy_d = self.cfg.canopy_depth
            canopy_w = ent_w + 1.0
            canopy_t = 0.12
            self.bridge.create_box_mesh(
                f"{ent_root}/Canopy",
                width=canopy_w, height=canopy_t, depth=canopy_d,
                translate=(core_cx, ent_h + frame_t + canopy_t / 2,
                           half_d + canopy_d / 2),
                display_color=self.cfg.accent_color,
            )

    # =========================================================================
    # 屋顶
    # =========================================================================

    def _generate_roof(self, root: str):
        """
        生成屋顶。

        支持两种样式：
          - flat: 平顶 + 女儿墙
          - pitched: 坡屋顶（双坡）
        """
        roof_root = f"{root}/Roof"
        self.bridge.define_scope(roof_root)

        half_w = self._building_width / 2
        half_d = self._building_depth / 2
        total_h = self._residential_start_y + self._residential_floors * self.cfg.floor_height
        wt = self.cfg.wall_thickness
        ph = self.cfg.parapet_height

        if self.cfg.roof_style == "flat":
            # 平顶 + 女儿墙
            # 南墙女儿墙
            self.bridge.create_box_mesh(
                f"{roof_root}/ParapetSouth",
                width=self._building_width, height=ph, depth=wt,
                translate=(0, total_h + ph / 2, half_d - wt / 2),
                display_color=self.cfg.roof_color,
            )
            # 北墙女儿墙
            self.bridge.create_box_mesh(
                f"{roof_root}/ParapetNorth",
                width=self._building_width, height=ph, depth=wt,
                translate=(0, total_h + ph / 2, -half_d + wt / 2),
                display_color=self.cfg.roof_color,
            )
            # 东墙女儿墙（depth减去南北女儿墙厚度，避免转角穿模）
            parapet_gable_depth = self._building_depth - 2 * wt
            self.bridge.create_box_mesh(
                f"{roof_root}/ParapetEast",
                width=wt, height=ph, depth=parapet_gable_depth,
                translate=(half_w - wt / 2, total_h + ph / 2, 0),
                display_color=self.cfg.roof_color,
            )
            # 西墙女儿墙
            self.bridge.create_box_mesh(
                f"{roof_root}/ParapetWest",
                width=wt, height=ph, depth=parapet_gable_depth,
                translate=(-half_w + wt / 2, total_h + ph / 2, 0),
                display_color=self.cfg.roof_color,
            )

        elif self.cfg.roof_style == "pitched":
            # 坡屋顶（双坡，沿X轴方向的脊线）
            angle = math.radians(self.cfg.pitch_angle)
            ridge_h = half_d * math.tan(angle)  # 屋脊高度

            # 用多段方块近似坡面
            n_seg = 10
            seg_d = self._building_depth / n_seg

            for i in range(n_seg):
                # 从南到北
                z_center = half_d - (i + 0.5) * seg_d
                # 距离中心线的距离
                dist_from_center = abs(z_center)
                # 坡面高度
                seg_y = total_h + ridge_h * (1.0 - dist_from_center / half_d)
                # 坡面倾斜（简化为水平方块）
                seg_h = 0.15

                self.bridge.create_box_mesh(
                    f"{roof_root}/PitchSeg_{i}",
                    width=self._building_width + 0.6,  # 出挑
                    height=seg_h,
                    depth=seg_d * 1.02,
                    translate=(0, seg_y, z_center),
                    display_color=self.cfg.pitched_roof_color,
                )

            # 屋脊装饰线
            self.bridge.create_box_mesh(
                f"{roof_root}/Ridge",
                width=self._building_width + 0.8, height=0.2, depth=0.3,
                translate=(0, total_h + ridge_h + 0.1, 0),
                display_color=self.cfg.accent_color,
            )

            # 东西两侧山花（三角形近似）
            n_tri = 8
            for side_name, x_pos in [("East", half_w), ("West", -half_w)]:
                for j in range(n_tri):
                    ratio = 1.0 - (j + 0.5) / n_tri
                    layer_d = self._building_depth * ratio
                    layer_y = total_h + ridge_h * (j + 0.5) / n_tri
                    layer_h = ridge_h / n_tri

                    self.bridge.create_box_mesh(
                        f"{roof_root}/Gable{side_name}_{j}",
                        width=wt, height=layer_h, depth=layer_d,
                        translate=(x_pos, layer_y + layer_h / 2, 0),
                        display_color=self.cfg.wall_color,
                    )

    # =========================================================================
    # 楼层分隔线
    # =========================================================================

    def _generate_floor_lines(self, root: str):
        """
        生成楼层分隔线装饰。

        在每层楼板位置的外墙上添加水平线条装饰。
        """
        line_root = f"{root}/FloorLines"
        self.bridge.define_scope(line_root)

        half_w = self._building_width / 2
        half_d = self._building_depth / 2
        line_h = 0.06  # 线条高度
        line_d = 0.03  # 线条出挑深度

        for floor_i in range(1, self.cfg.num_floors):
            if floor_i <= self._commercial_floors:
                continue

            res_floor_i = floor_i - self._commercial_floors
            y = self._residential_start_y + res_floor_i * self.cfg.floor_height

            # 南面线条
            self.bridge.create_box_mesh(
                f"{line_root}/South_{floor_i}",
                width=self._building_width + 0.02, height=line_h, depth=line_d,
                translate=(0, y, half_d + line_d / 2),
                display_color=self.cfg.floor_line_color,
            )
            # 北面线条
            self.bridge.create_box_mesh(
                f"{line_root}/North_{floor_i}",
                width=self._building_width + 0.02, height=line_h, depth=line_d,
                translate=(0, y, -half_d - line_d / 2),
                display_color=self.cfg.floor_line_color,
            )

    # =========================================================================
    # 光照
    # =========================================================================

    def _create_lighting(self, root: str):
        """创建场景光照。"""
        lights_root = f"{root}/Lights"
        self.bridge.define_scope(lights_root)
        self.bridge.create_dome_light(f"{lights_root}/DomeLight", intensity=0.5)

        total_h = self._residential_start_y + self._residential_floors * self.cfg.floor_height
        max_dim = max(self._building_width, self._building_depth)

        self.bridge.create_rect_light(
            f"{lights_root}/SunLight",
            width=max_dim * 2,
            height=max_dim * 2,
            intensity=1000.0,
            translate=(max_dim, total_h * 1.5, max_dim),
        )
