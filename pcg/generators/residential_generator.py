"""
Residential Generator v2: 户型平面驱动的中国住宅商品房程序化生成器。

核心架构变化（v1 → v2）：
  v1: 先定义规则矩形外壳 → 再在外壳上贴窗户/阳台
  v2: 先设计户型平面（房间级别）→ 户型拼合出不规则标准层轮廓
      → 逐层复制生成整栋建筑

生成流程：
  1. 根据配置创建 FloorPlan（标准层平面）
  2. 计算标准层外轮廓多边形（不规则）
  3. 逐层生成：
     a. 多边形楼板（create_polygon_slab）
     b. 沿轮廓边缘生成外墙段
     c. 根据房间类型自动决定窗户/阳台/空调位
  4. 生成核心筒、入口、屋顶等附属结构

坐标约定：
  - X轴: 建筑面宽方向（东西向）
  - Y轴: 高度方向（向上）
  - Z轴: 建筑进深方向（南北向，+Z=南，-Z=北）
  - 建筑质心在XZ平面的原点附近
"""

import math
import random
from typing import Dict, Any, List, Tuple, Optional
from dataclasses import dataclass, field
from pxr import Gf, Vt, Sdf, UsdGeom

from pcg_core.engine import GeneratorBase, ResidentialConfig
from pcg_core.usd_bridge import UsdBridge
from pcg_core.floor_plan import (
    Room, RoomType, Facing, WindowType,
    UnitPlan, UnitPlanPresets, CorePlan,
    FloorPlan, PlacedUnit, FloorPlanFactory,
    triangulate_polygon,
)
from pcg_core.unit_plan_generator import UnitPlanGenerator


# =============================================================================
# 轮廓边缘分析工具
# =============================================================================

@dataclass
class OutlineEdge:
    """轮廓上的一条边。"""
    p0: Tuple[float, float]     # 起点 (x, z)
    p1: Tuple[float, float]     # 终点 (x, z)
    direction: str              # "south"(+Z), "north"(-Z), "east"(+X), "west"(-X)
    length: float
    mid_x: float
    mid_z: float

    # 关联的房间信息（由分析填充）
    rooms: List[Room] = field(default_factory=list)


def analyze_outline_edges(outline: List[Tuple[float, float]],
                          rooms: List[Room]) -> List[OutlineEdge]:
    """
    分析轮廓的每条边，确定朝向和关联房间。

    Args:
        outline: 外轮廓顶点列表
        rooms: 所有世界坐标下的房间列表
    """
    edges = []
    n = len(outline)

    for i in range(n):
        p0 = outline[i]
        p1 = outline[(i + 1) % n]

        dx = p1[0] - p0[0]
        dz = p1[1] - p0[1]
        length = math.sqrt(dx * dx + dz * dz)

        if length < 0.01:
            continue

        mid_x = (p0[0] + p1[0]) / 2
        mid_z = (p0[1] + p1[1]) / 2

        # 判断边的朝向（基于法线方向）
        # 对于逆时针多边形，法线 = (dz, -dx) 归一化
        # 对于顺时针多边形，法线 = (-dz, dx) 归一化
        # shapely 返回的是逆时针还是顺时针取决于具体情况
        # 我们用边的方向来判断：
        if abs(dx) > abs(dz):
            # 水平边
            if abs(dx) < 0.01:
                continue
            # 需要判断法线方向（朝外）
            # 简单方法：看这条边在轮廓的哪一侧
            direction = _classify_horizontal_edge(p0, p1, outline)
        else:
            # 垂直边
            if abs(dz) < 0.01:
                continue
            direction = _classify_vertical_edge(p0, p1, outline)

        edge = OutlineEdge(
            p0=p0, p1=p1,
            direction=direction,
            length=length,
            mid_x=mid_x, mid_z=mid_z,
        )

        # 找出与这条边关联的房间
        edge.rooms = _find_rooms_on_edge(edge, rooms)
        edges.append(edge)

    return edges


def _classify_horizontal_edge(p0, p1, outline) -> str:
    """判断水平边是朝南还是朝北。"""
    z = p0[1]  # 水平边的Z坐标
    # 计算轮廓的Z范围
    all_z = [p[1] for p in outline]
    z_min, z_max = min(all_z), max(all_z)
    z_mid = (z_min + z_max) / 2

    if z > z_mid:
        return "south"  # 在轮廓的南侧（+Z）
    else:
        return "north"  # 在轮廓的北侧（-Z）


def _classify_vertical_edge(p0, p1, outline) -> str:
    """判断垂直边是朝东还是朝西。"""
    x = p0[0]
    all_x = [p[0] for p in outline]
    x_min, x_max = min(all_x), max(all_x)
    x_mid = (x_min + x_max) / 2

    if x > x_mid:
        return "east"
    else:
        return "west"


def _find_rooms_on_edge(edge: OutlineEdge, rooms: List[Room]) -> List[Room]:
    """找出与轮廓边关联的房间。"""
    result = []
    tol = 0.5  # 容差

    for room in rooms:
        if edge.direction == "south":
            # 南面边：找z_end接近edge.mid_z的房间
            if abs(room.z_end - edge.mid_z) < tol:
                # 检查X范围重叠
                edge_x_min = min(edge.p0[0], edge.p1[0])
                edge_x_max = max(edge.p0[0], edge.p1[0])
                if room.x < edge_x_max - tol and room.x_end > edge_x_min + tol:
                    result.append(room)
        elif edge.direction == "north":
            if abs(room.z - edge.mid_z) < tol:
                edge_x_min = min(edge.p0[0], edge.p1[0])
                edge_x_max = max(edge.p0[0], edge.p1[0])
                if room.x < edge_x_max - tol and room.x_end > edge_x_min + tol:
                    result.append(room)
        elif edge.direction == "east":
            if abs(room.x_end - edge.mid_x) < tol:
                edge_z_min = min(edge.p0[1], edge.p1[1])
                edge_z_max = max(edge.p0[1], edge.p1[1])
                if room.z < edge_z_max - tol and room.z_end > edge_z_min + tol:
                    result.append(room)
        elif edge.direction == "west":
            if abs(room.x - edge.mid_x) < tol:
                edge_z_min = min(edge.p0[1], edge.p1[1])
                edge_z_max = max(edge.p0[1], edge.p1[1])
                if room.z < edge_z_max - tol and room.z_end > edge_z_min + tol:
                    result.append(room)

    return result


# =============================================================================
# ResidentialGenerator v2
# =============================================================================

class ResidentialGenerator(GeneratorBase):
    """中国住宅小区商品房程序化生成器 v2（户型平面驱动）。"""

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

        # 第一步：生成标准层平面
        with self._time_it("floor_plan"):
            self._create_floor_plan()
            stats["building_width"] = round(self._floor_plan.building_width(), 1)
            stats["building_depth"] = round(self._floor_plan.building_depth(), 1)
            stats["outline_points"] = len(self._outline)

        # 第二步：创建材质
        with self._time_it("materials"):
            self._create_materials(root)

        # 第三步：生成楼板（多边形）
        with self._time_it("floor_slabs"):
            stats["num_floor_slabs"] = self._generate_floor_slabs(root)

        # 第四步：生成外墙（沿轮廓边缘）
        with self._time_it("walls"):
            wall_stats = self._generate_walls(root)
            stats.update(wall_stats)

        # 第五步：生成窗户
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

        # 第九步：入口门厅
        with self._time_it("entrance"):
            self._generate_entrance(root)

        # 第十步：屋顶
        with self._time_it("roof"):
            self._generate_roof(root)

        # 第十一步：光照
        with self._time_it("lighting"):
            self._create_lighting(root)

        return stats

    # =========================================================================
    # 标准层平面生成
    # =========================================================================

    def _create_floor_plan(self):
        """
        根据配置创建标准层平面。

        用户只需指定1~2种户型类型，FloorPlanFactory会自动展开为
        对称布局（板楼轴对称，塔楼中心对称）。
        """
        # 解析户型类型（1~2种即可，工厂会自动展开）
        if self.cfg.unit_types:
            unit_types = list(self.cfg.unit_types[:2])  # 最多取2种
        else:
            unit_types = ["3BR"]  # 默认3BR

        n_units = self.cfg.units_per_floor

        # 创建标准层平面（传递seed实现参数化变体）
        seed = getattr(self.cfg, 'seed', 42)
        if self.cfg.building_type == "tower":
            self._floor_plan = FloorPlanFactory.create_tower_floor(
                unit_types=unit_types,
                core_width=self.cfg.core_width,
                core_depth=self.cfg.core_depth,
                num_elevators=self.cfg.num_elevators,
                units_per_floor=n_units,
                seed=seed,
            )
        else:
            self._floor_plan = FloorPlanFactory.create_slab_floor(
                unit_types=unit_types,
                core_width=self.cfg.core_width,
                core_depth=self.cfg.core_depth,
                num_elevators=self.cfg.num_elevators,
                units_per_floor=n_units,
                seed=seed,
            )

        # 计算轮廓和三角化
        self._outline = self._floor_plan.compute_outline()
        self._triangles = triangulate_polygon(self._outline)
        self._bounds = self._floor_plan.compute_bounds()

        # 分析轮廓边缘
        all_rooms = self._floor_plan.all_world_rooms()
        self._edges = analyze_outline_edges(self._outline, all_rooms)

        # 计算住宅层数
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

        # 窗户位置收集器
        self._window_positions = []   # [(x, y, z, scale_x, scale_y, scale_z)]
        self._balcony_data = []       # [(x, y, z, width, depth)]
        self._ac_data = []            # [(x, y, z, direction)]

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
        self.bridge.create_material(f"{mat_root}/ACUnitMat",
                                    diffuse_color=self.cfg.ac_unit_color, roughness=0.8)
        if self.cfg.has_ground_commercial:
            self.bridge.create_material(f"{mat_root}/ShopMat",
                                        diffuse_color=self.cfg.shopfront_color, roughness=0.4)

    # =========================================================================
    # 楼板（多边形）
    # =========================================================================

    def _generate_floor_slabs(self, root: str) -> int:
        """使用多边形楼板生成不规则形状的楼板。"""
        slab_root = f"{root}/FloorSlabs"
        self.bridge.define_scope(slab_root)

        ft = self.cfg.floor_thickness
        count = 0

        # 底商层楼板（如果有，用包围盒矩形）
        if self.cfg.has_ground_commercial:
            x_min, z_min, x_max, z_max = self._bounds
            bw = x_max - x_min
            bd = z_max - z_min
            cx = (x_min + x_max) / 2
            cz = (z_min + z_max) / 2
            for i in range(self._commercial_floors):
                y = i * self._commercial_height
                self.bridge.create_box_mesh(
                    f"{slab_root}/CommSlab_{i}",
                    width=bw, height=ft, depth=bd,
                    translate=(cx, y + ft / 2, cz),
                    display_color=self.cfg.floor_color,
                )
                count += 1

        # 住宅层楼板（多边形）
        for i in range(self._residential_floors + 1):  # +1 for roof slab
            y = self._residential_start_y + i * self.cfg.floor_height
            self.bridge.create_polygon_slab(
                f"{slab_root}/ResSlab_{i}",
                vertices_xz=self._outline,
                triangles=self._triangles,
                thickness=ft,
                y_center=y + ft / 2,
                display_color=self.cfg.floor_color,
            )
            count += 1

        return count

    # =========================================================================
    # 外墙（沿轮廓边缘）
    # =========================================================================

    def _generate_walls(self, root: str) -> Dict[str, int]:
        """
        沿轮廓边缘逐层生成外墙。

        每条边根据关联房间的类型决定：
        - 南向房间（客厅/卧室）→ 大窗洞
        - 北向房间（厨卫）→ 小窗洞
        - 东西山墙 → 实墙或小窗
        """
        wall_root = f"{root}/Walls"
        self.bridge.define_scope(wall_root)

        wt = self.cfg.wall_thickness
        fh = self.cfg.floor_height
        ft = self.cfg.floor_thickness
        wall_h = fh - ft

        wall_count = 0

        for floor_i in range(self.cfg.num_floors):
            if floor_i < self._commercial_floors:
                continue

            res_floor_i = floor_i - self._commercial_floors
            y_base = self._residential_start_y + res_floor_i * fh + ft

            floor_root = f"{wall_root}/Floor_{floor_i}"
            self.bridge.define_scope(floor_root)

            for edge_i, edge in enumerate(self._edges):
                if edge.length < 0.1:
                    continue

                # 计算墙体的放置参数
                wall_width = edge.length
                edge_cx = edge.mid_x
                edge_cz = edge.mid_z

                # 根据边的朝向确定墙体放置
                if edge.direction in ("south", "north"):
                    # 水平墙（沿X方向）
                    holes = self._compute_wall_holes(edge, wall_h, wall_width)
                    z_offset = wt / 2 if edge.direction == "south" else -wt / 2

                    self.bridge.create_wall_mesh(
                        f"{floor_root}/Wall_{edge_i}",
                        width=wall_width, height=wall_h, thickness=wt,
                        holes=holes if holes else None,
                        translate=(edge_cx, y_base + wall_h / 2, edge_cz),
                        display_color=self.cfg.wall_color,
                    )

                    # 收集窗户位置
                    for hole in holes:
                        wx = edge_cx + hole["x"]
                        wy = y_base + hole["y"]
                        wz = edge_cz + (wt / 2 + 0.01 if edge.direction == "south" else -wt / 2 - 0.01)
                        self._window_positions.append((
                            wx, wy, wz,
                            hole["w"], hole["h"], 0.05
                        ))

                    # 收集阳台和空调位数据
                    self._collect_facade_elements(edge, y_base, wall_h)

                else:
                    # 垂直墙（沿Z方向）— 山墙
                    # 山墙一般是实墙
                    wall_depth = edge.length
                    x_offset = wt / 2 if edge.direction == "east" else -wt / 2

                    self.bridge.create_box_mesh(
                        f"{floor_root}/Wall_{edge_i}",
                        width=wt, height=wall_h, depth=wall_depth,
                        translate=(edge_cx, y_base + wall_h / 2, edge_cz),
                        display_color=self.cfg.wall_color,
                    )

                wall_count += 1

        # 底商层外墙
        if self.cfg.has_ground_commercial:
            comm_stats = self._generate_commercial_walls(root)
            wall_count += comm_stats

        return {"num_walls": wall_count}

    def _compute_wall_holes(self, edge: OutlineEdge, wall_h: float,
                            wall_width: float) -> List[Dict[str, float]]:
        """
        根据边关联的房间类型计算窗洞。

        南向房间 → 大窗（客厅落地窗/卧室标准窗）
        北向房间 → 小窗（厨卫窗）
        """
        holes = []
        sill_h = self.cfg.window_sill_height

        for room in edge.rooms:
            if room.window_type == WindowType.NONE:
                continue

            # 计算窗户在墙体局部坐标中的X位置
            # 墙体局部坐标：中心在(0,0)，X范围[-wall_width/2, wall_width/2]
            edge_x_min = min(edge.p0[0], edge.p1[0])

            if edge.direction in ("south", "north"):
                room_cx_on_edge = room.center_x - edge_x_min - wall_width / 2
            else:
                edge_z_min = min(edge.p0[1], edge.p1[1])
                room_cx_on_edge = room.center_z - edge_z_min - wall_width / 2

            # 根据窗户类型确定尺寸
            if room.window_type == WindowType.LARGE:
                win_w = min(self.cfg.south_window_width, room.width - 0.6)
                win_h = self.cfg.south_window_height
                win_y = sill_h + win_h / 2 - wall_h / 2
            elif room.window_type == WindowType.FLOOR_TO_CEILING:
                win_w = min(room.width - 0.8, 3.0)
                win_h = wall_h - 0.3
                win_y = 0.15
            elif room.window_type == WindowType.STANDARD:
                win_w = min(self.cfg.south_window_width * 0.85, room.width - 0.6)
                win_h = self.cfg.south_window_height * 0.9
                win_y = sill_h + win_h / 2 - wall_h / 2
            elif room.window_type == WindowType.SMALL:
                win_w = min(self.cfg.north_window_width, room.width - 0.4)
                win_h = self.cfg.north_window_height
                win_y = sill_h + win_h / 2 - wall_h / 2
            else:
                continue

            # 确保窗户不超出墙体范围
            half_wall = wall_width / 2
            if abs(room_cx_on_edge) + win_w / 2 > half_wall - 0.1:
                continue

            holes.append({
                "x": room_cx_on_edge,
                "y": win_y,
                "w": win_w,
                "h": win_h,
            })

        return holes

    def _collect_facade_elements(self, edge: OutlineEdge,
                                  y_base: float, wall_h: float):
        """收集阳台和空调机位数据。"""
        for room in edge.rooms:
            if room.has_balcony and edge.direction == "south":
                # 阳台：南向房间外挂
                bal_w = min(room.width - 0.2, 3.5)
                self._balcony_data.append((
                    room.center_x,
                    y_base,
                    room.z_end,  # 南面外侧
                    bal_w,
                    self.cfg.balcony_depth,
                ))

            if room.has_ac_slot:
                # 空调机位
                if edge.direction == "south":
                    ac_z = room.z_end + 0.01
                elif edge.direction == "north":
                    ac_z = room.z - 0.01
                else:
                    continue

                # 空调位放在房间的一侧
                ac_x = room.x_end - self.cfg.ac_unit_width / 2 - 0.2
                self._ac_data.append((
                    ac_x,
                    y_base + 0.3,  # 略高于楼板
                    ac_z,
                    edge.direction,
                ))

    def _generate_commercial_walls(self, root: str) -> int:
        """生成底商层外墙。"""
        comm_root = f"{root}/Commercial"
        self.bridge.define_scope(comm_root)

        x_min, z_min, x_max, z_max = self._bounds
        bw = x_max - x_min
        bd = z_max - z_min
        cx = (x_min + x_max) / 2
        cz = (z_min + z_max) / 2
        wt = self.cfg.wall_thickness
        count = 0

        for i in range(self._commercial_floors):
            ch = self.cfg.commercial_height
            ft = self.cfg.floor_thickness
            wall_h = ch - ft
            y_base = i * ch + ft

            floor_root = f"{comm_root}/Floor_{i}"
            self.bridge.define_scope(floor_root)

            # 南面（店面大玻璃）
            shop_holes = []
            num_shops = max(1, int(bw / 5.0))
            shop_w = (bw - 1.0) / num_shops
            for j in range(num_shops):
                shop_cx = -bw / 2 + 0.5 + j * shop_w + shop_w / 2
                shop_holes.append({
                    "x": shop_cx,
                    "y": 0.0,
                    "w": shop_w * 0.8,
                    "h": wall_h * 0.75,
                })

            self.bridge.create_wall_mesh(
                f"{floor_root}/SouthWall",
                width=bw, height=wall_h, thickness=wt,
                holes=shop_holes,
                translate=(cx, y_base + wall_h / 2, z_max),
                display_color=self.cfg.shopfront_color,
            )
            count += 1

            # 北面
            self.bridge.create_box_mesh(
                f"{floor_root}/NorthWall",
                width=bw, height=wall_h, depth=wt,
                translate=(cx, y_base + wall_h / 2, z_min),
                display_color=self.cfg.shopfront_color,
            )
            count += 1

            # 东西面
            for side, x_pos in [("East", x_max), ("West", x_min)]:
                self.bridge.create_box_mesh(
                    f"{floor_root}/{side}Wall",
                    width=wt, height=wall_h, depth=bd,
                    translate=(x_pos, y_base + wall_h / 2, cz),
                    display_color=self.cfg.shopfront_color,
                )
                count += 1

        return count

    # =========================================================================
    # 窗户
    # =========================================================================

    def _generate_windows(self, root: str) -> int:
        """使用PointInstancer生成所有窗户。"""
        if not self._window_positions:
            return 0

        win_root = f"{root}/Windows"
        self.bridge.define_scope(win_root)

        proto_path = f"{win_root}/Instancer/Prototypes/WinProto"
        self.bridge.create_box_mesh(
            proto_path,
            width=1.0, height=1.0, depth=1.0,
            display_color=self.cfg.window_color,
        )

        positions = [(wp[0], wp[1], wp[2]) for wp in self._window_positions]
        scales = [(wp[3], wp[4], wp[5]) for wp in self._window_positions]

        self.bridge.create_point_instancer(
            f"{win_root}/Instancer",
            prototype_paths=[proto_path],
            positions=positions,
            proto_indices=[0] * len(positions),
            scales=scales,
        )

        return len(positions)

    # =========================================================================
    # 阳台
    # =========================================================================

    def _generate_balconies(self, root: str) -> int:
        """生成南向阳台。"""
        if not self._balcony_data:
            return 0

        bal_root = f"{root}/Balconies"
        self.bridge.define_scope(bal_root)

        bd = self.cfg.balcony_depth
        rh = self.cfg.balcony_railing_height
        slab_t = 0.12
        railing_t = 0.08
        count = 0

        for i, (bx, by, bz, bw, b_depth) in enumerate(self._balcony_data):
            bal_path = f"{bal_root}/Bal_{i}"
            self.bridge.define_scope(bal_path)

            # 阳台底板
            self.bridge.create_box_mesh(
                f"{bal_path}/Slab",
                width=bw, height=slab_t, depth=b_depth,
                translate=(bx, by + slab_t / 2, bz + b_depth / 2),
                display_color=self.cfg.balcony_slab_color,
            )

            # 阳台栏杆/封闭玻璃
            if self.cfg.balcony_type == "enclosed":
                # 封闭阳台：前面玻璃
                self.bridge.create_box_mesh(
                    f"{bal_path}/FrontGlass",
                    width=bw, height=rh, depth=railing_t,
                    translate=(bx, by + slab_t + rh / 2, bz + b_depth),
                    display_color=self.cfg.balcony_glass_color,
                )
                # 两侧玻璃
                for side, sx in [("Left", bx - bw / 2), ("Right", bx + bw / 2)]:
                    self.bridge.create_box_mesh(
                        f"{bal_path}/{side}Glass",
                        width=railing_t, height=rh, depth=b_depth,
                        translate=(sx, by + slab_t + rh / 2, bz + b_depth / 2),
                        display_color=self.cfg.balcony_glass_color,
                    )
            else:
                # 开放阳台：栏杆
                self.bridge.create_box_mesh(
                    f"{bal_path}/FrontRailing",
                    width=bw, height=rh, depth=railing_t,
                    translate=(bx, by + slab_t + rh / 2, bz + b_depth),
                    display_color=self.cfg.wall_color,
                )

            count += 1

        return count

    # =========================================================================
    # 空调机位
    # =========================================================================

    def _generate_ac_units(self, root: str) -> int:
        """生成空调外机位。"""
        if not self._ac_data:
            return 0

        ac_root = f"{root}/ACUnits"
        self.bridge.define_scope(ac_root)

        aw = self.cfg.ac_unit_width
        ad = self.cfg.ac_unit_depth
        ah = self.cfg.ac_unit_height
        count = 0

        for i, (ax, ay, az, direction) in enumerate(self._ac_data):
            ac_path = f"{ac_root}/AC_{i}"
            self.bridge.define_scope(ac_path)

            if direction in ("south", "north"):
                z_sign = 1 if direction == "south" else -1
                # 底板
                self.bridge.create_box_mesh(
                    f"{ac_path}/Base",
                    width=aw, height=0.05, depth=ad,
                    translate=(ax, ay, az + z_sign * ad / 2),
                    display_color=self.cfg.ac_unit_color,
                )
                # 三面格栅
                self.bridge.create_box_mesh(
                    f"{ac_path}/Front",
                    width=aw, height=ah, depth=0.03,
                    translate=(ax, ay + ah / 2, az + z_sign * ad),
                    display_color=self.cfg.ac_unit_color,
                )
                for side, sx in [("Left", ax - aw / 2), ("Right", ax + aw / 2)]:
                    self.bridge.create_box_mesh(
                        f"{ac_path}/{side}",
                        width=0.03, height=ah, depth=ad,
                        translate=(sx, ay + ah / 2, az + z_sign * ad / 2),
                        display_color=self.cfg.ac_unit_color,
                    )

            count += 1

        return count

    # =========================================================================
    # 核心筒
    # =========================================================================

    def _generate_core(self, root: str):
        """生成核心筒（楼梯间+电梯间）。"""
        core = self._floor_plan.core
        if not core:
            return

        core_root = f"{root}/Core"
        self.bridge.define_scope(core_root)

        wt = self.cfg.wall_thickness
        fh = self.cfg.floor_height
        ft = self.cfg.floor_thickness
        wall_h = fh - ft

        for floor_i in range(self.cfg.num_floors):
            if floor_i < self._commercial_floors:
                continue

            res_floor_i = floor_i - self._commercial_floors
            y_base = self._residential_start_y + res_floor_i * fh + ft

            floor_root = f"{core_root}/Floor_{floor_i}"
            self.bridge.define_scope(floor_root)

            cx = core.center_x
            cz = core.center_z

            # 核心筒四面墙
            # 南面
            self.bridge.create_box_mesh(
                f"{floor_root}/SouthWall",
                width=core.width, height=wall_h, depth=wt,
                translate=(cx, y_base + wall_h / 2, core.z_end),
                display_color=self.cfg.wall_color,
            )
            # 北面
            self.bridge.create_box_mesh(
                f"{floor_root}/NorthWall",
                width=core.width, height=wall_h, depth=wt,
                translate=(cx, y_base + wall_h / 2, core.z),
                display_color=self.cfg.wall_color,
            )
            # 中间隔墙（电梯间/楼梯间分隔）
            self.bridge.create_box_mesh(
                f"{floor_root}/DividerWall",
                width=wt, height=wall_h, depth=core.depth - 2 * wt,
                translate=(cx, y_base + wall_h / 2, cz),
                display_color=self.cfg.wall_color,
            )

    # =========================================================================
    # 入口门厅
    # =========================================================================

    def _generate_entrance(self, root: str):
        """生成入口门厅。"""
        ent_root = f"{root}/Entrance"
        self.bridge.define_scope(ent_root)

        core = self._floor_plan.core
        if not core:
            return

        # 入口在核心筒的南面
        ew = self.cfg.entrance_width
        eh = self.cfg.entrance_height
        wt = self.cfg.wall_thickness

        ent_x = core.center_x
        ent_z = core.z_end + wt / 2

        # 门框
        frame_t = 0.15
        # 左柱
        self.bridge.create_box_mesh(
            f"{ent_root}/LeftPillar",
            width=frame_t, height=eh, depth=frame_t,
            translate=(ent_x - ew / 2 - frame_t / 2, eh / 2, ent_z),
            display_color=self.cfg.wall_color,
        )
        # 右柱
        self.bridge.create_box_mesh(
            f"{ent_root}/RightPillar",
            width=frame_t, height=eh, depth=frame_t,
            translate=(ent_x + ew / 2 + frame_t / 2, eh / 2, ent_z),
            display_color=self.cfg.wall_color,
        )
        # 横梁
        self.bridge.create_box_mesh(
            f"{ent_root}/Lintel",
            width=ew + 2 * frame_t, height=frame_t, depth=frame_t,
            translate=(ent_x, eh + frame_t / 2, ent_z),
            display_color=self.cfg.wall_color,
        )

        # 雨棚
        if self.cfg.has_entrance_canopy:
            cd = self.cfg.canopy_depth
            self.bridge.create_box_mesh(
                f"{ent_root}/Canopy",
                width=ew + 2.0, height=0.12, depth=cd,
                translate=(ent_x, eh + frame_t + 0.06, ent_z + cd / 2),
                display_color=self.cfg.roof_color,
            )

    # =========================================================================
    # 屋顶
    # =========================================================================

    def _generate_roof(self, root: str):
        """生成屋顶结构。"""
        roof_root = f"{root}/Roof"
        self.bridge.define_scope(roof_root)

        total_h = self._residential_start_y + self._residential_floors * self.cfg.floor_height
        x_min, z_min, x_max, z_max = self._bounds
        bw = x_max - x_min
        bd = z_max - z_min
        cx = (x_min + x_max) / 2
        cz = (z_min + z_max) / 2

        if self.cfg.roof_style == "pitched":
            # 坡屋顶（多层住宅常见）
            self._generate_pitched_roof(roof_root, total_h, cx, cz, bw, bd)
        else:
            # 平顶 + 女儿墙
            self._generate_flat_roof(roof_root, total_h, cx, cz, bw, bd)

    def _generate_flat_roof(self, roof_root: str, total_h: float,
                            cx: float, cz: float, bw: float, bd: float):
        """生成平顶+女儿墙。"""
        ph = self.cfg.parapet_height
        wt = self.cfg.wall_thickness

        # 女儿墙沿轮廓生成
        for i, edge in enumerate(self._edges):
            if edge.length < 0.1:
                continue

            if edge.direction in ("south", "north"):
                self.bridge.create_box_mesh(
                    f"{roof_root}/Parapet_{i}",
                    width=edge.length, height=ph, depth=wt,
                    translate=(edge.mid_x, total_h + ph / 2, edge.mid_z),
                    display_color=self.cfg.roof_color,
                )
            else:
                self.bridge.create_box_mesh(
                    f"{roof_root}/Parapet_{i}",
                    width=wt, height=ph, depth=edge.length,
                    translate=(edge.mid_x, total_h + ph / 2, edge.mid_z),
                    display_color=self.cfg.roof_color,
                )

    def _generate_pitched_roof(self, roof_root: str, total_h: float,
                                cx: float, cz: float, bw: float, bd: float):
        """生成坡屋顶（用多层递减宽度的方块近似）。"""
        angle = self.cfg.pitch_angle
        tan_a = math.tan(math.radians(angle))
        ridge_h = (bd / 2) * tan_a  # 屋脊高度
        num_layers = 12
        layer_h = ridge_h / num_layers

        roof_color = self.cfg.pitched_roof_color

        for i in range(num_layers):
            ratio = 1.0 - (i + 0.5) / num_layers
            layer_d = bd * ratio
            layer_y = total_h + i * layer_h

            if layer_d < 0.5:
                break

            self.bridge.create_box_mesh(
                f"{roof_root}/PitchLayer_{i}",
                width=bw + 0.5, height=layer_h, depth=layer_d,
                translate=(cx, layer_y + layer_h / 2, cz),
                display_color=roof_color,
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
        bw = self._floor_plan.building_width()
        bd = self._floor_plan.building_depth()
        max_dim = max(bw, bd)

        self.bridge.create_rect_light(
            f"{lights_root}/SunLight",
            width=max_dim * 2,
            height=max_dim * 2,
            intensity=1000.0,
            translate=(max_dim, total_h * 1.5, max_dim),
        )
