"""
Building Generator v3: 模块化墙体拼接版。

核心架构变更：
  v2: 硬编码四面墙 → 每面墙是一整块Mesh
  v3: 模块化拼接   → 每面墙由多个可替换的WallSegment组成

建筑外壳生成流程：
  1. 创建 WallLayout（定义四条边和每条边上的墙段序列）
  2. 沿每条边遍历墙段，通过 Xform 变换将局部坐标映射到世界坐标
  3. 在每条边的两端放置 CornerJoiner（转角柱）
  4. 收集所有墙段返回的窗户位置，用全局 PointInstancer 生成窗户

坐标约定（与v2一致）：
  - 建筑中心在原点
  - X轴: 建筑宽度方向
  - Y轴: 高度方向（向上）
  - Z轴: 建筑深度方向
  - 外墙外表面对齐建筑外轮廓

墙段局部坐标系：
  - X: [0, length]  沿墙段长度
  - Y: [0, height]  沿墙段高度
  - Z: [0, -thickness]  厚度向内
"""

import math
import random
from typing import Dict, Any, List, Tuple, Optional
from pxr import Gf, Vt, Sdf, UsdGeom

from pcg_core.engine import GeneratorBase, BuildingConfig
from pcg_core.usd_bridge import UsdBridge
from pcg_core.wall_module import (
    IWallSegment, WallSegmentResult, WallLayout, WallEdge,
    CornerJoiner90, IJoiner
)
# 导入所有墙段类型以触发注册
import pcg_core.wall_segments  # noqa: F401


class BuildingGenerator(GeneratorBase):
    """办公楼程序化生成器（v3 - 模块化墙体拼接版）。"""

    def __init__(self, bridge: UsdBridge, config: BuildingConfig):
        super().__init__(bridge, config)
        self.cfg: BuildingConfig = config
        random.seed(config.seed)

    def generate(self, parent_path: str = "") -> Dict[str, Any]:
        """执行完整的办公楼生成流程。"""
        root = f"{parent_path}/{self.cfg.building_name}"
        self.bridge.define_xform(root)

        stats = {
            "building_name": self.cfg.building_name,
            "num_floors": self.cfg.num_floors,
            "dimensions": f"{self.cfg.building_width}x{self.cfg.building_depth}x"
                          f"{self.cfg.num_floors * self.cfg.floor_height}m",
        }

        # 预计算关键尺寸
        self._precompute_dimensions()

        with self._time_it("materials"):
            self._create_materials(root)

        with self._time_it("floor_slabs"):
            stats["num_floor_slabs"] = self._generate_floor_slabs(root)

        with self._time_it("corner_columns"):
            stats["num_corner_columns"] = self._generate_corner_columns(root)

        with self._time_it("modular_walls"):
            wall_stats = self._generate_modular_walls(root)
            stats.update(wall_stats)

        with self._time_it("windows"):
            stats["num_windows"] = self._generate_windows_from_layout(root)

        if self.cfg.enable_interior:
            with self._time_it("interior"):
                stats.update(self._generate_interior(root))

        with self._time_it("roof"):
            self._generate_roof(root)

        with self._time_it("lighting"):
            self._create_lighting(root)

        return stats

    # =========================================================================
    # 预计算
    # =========================================================================

    def _precompute_dimensions(self):
        """预计算所有关键尺寸。"""
        W = self.cfg.building_width
        D = self.cfg.building_depth
        wt = self.cfg.wall_thickness
        ft = self.cfg.floor_thickness
        H = self.cfg.floor_height

        self._front_back_wall_length = W - 2 * wt
        self._left_right_wall_length = D - 2 * wt
        self._wall_net_height = H - ft
        self._interior_width = W - 2 * wt
        self._interior_depth = D - 2 * wt

        # 转角柱中心位置
        self._corners = [
            ("NE", (W/2 - wt/2,  D/2 - wt/2)),
            ("NW", (-(W/2 - wt/2), D/2 - wt/2)),
            ("SE", (W/2 - wt/2, -(D/2 - wt/2))),
            ("SW", (-(W/2 - wt/2), -(D/2 - wt/2))),
        ]

        # 全局窗户位置收集器（世界坐标）
        self._all_window_positions: List[Tuple[float, float, float]] = []
        self._all_window_orientations: List[Tuple[float, float, float, float]] = []

    # =========================================================================
    # 墙体布局创建
    # =========================================================================

    def _create_wall_layout(self, wall_height: float) -> WallLayout:
        """
        根据配置创建墙体布局。

        如果配置中有 wall_layout 字段，使用用户自定义布局；
        否则使用默认布局（所有边都是 WindowWall）。
        """
        wt = self.cfg.wall_thickness

        # 检查是否有用户自定义的墙体布局
        edge_configs = getattr(self.cfg, 'wall_layout', None)

        # 默认的窗户参数
        default_kwargs = {
            "window_width": self.cfg.window_width,
            "window_height": self.cfg.window_height,
            "window_sill_height": self.cfg.window_sill_height,
            "window_spacing": self.cfg.window_spacing,
            "color": self.cfg.wall_color,
        }

        layout = WallLayout.create_rectangular(
            width=self.cfg.building_width,
            depth=self.cfg.building_depth,
            wall_thickness=wt,
            wall_height=wall_height,
            edge_configs=edge_configs,
            default_segment_type="WindowWall",
            **default_kwargs,
        )

        return layout

    # =========================================================================
    # 模块化外墙生成（核心重构）
    # =========================================================================

    def _generate_modular_walls(self, root: str) -> Dict[str, Any]:
        """
        使用模块化拼接系统生成所有外墙。

        对每一层楼：
          1. 创建该层的 WallLayout
          2. 遍历四条边，沿每条边依次放置墙段模块
          3. 通过 Xform 变换将墙段从局部坐标映射到世界坐标
          4. 收集窗户位置用于后续 PointInstancer 生成
        """
        walls_root = f"{root}/ExteriorWalls"
        self.bridge.define_scope(walls_root)

        wt = self.cfg.wall_thickness
        H = self.cfg.floor_height
        ft = self.cfg.floor_thickness
        W = self.cfg.building_width
        D = self.cfg.building_depth

        total_segments = 0
        total_windows_in_walls = 0

        for floor_idx in range(self.cfg.num_floors):
            wall_bottom_y = floor_idx * H
            wall_h = H - ft

            floor_path = f"{walls_root}/Floor_{floor_idx}"
            self.bridge.define_xform(floor_path)

            # 为这一层创建墙体布局
            layout = self._create_wall_layout(wall_h)

            # 遍历四条边
            for edge in layout.edges:
                edge_path = f"{floor_path}/Edge_{edge.name}"
                self.bridge.define_xform(edge_path)

                # 计算这条边的起点世界坐标和方向
                sx, sz = edge.start_point  # XZ平面上的起点
                dx, dz = edge.direction     # 单位方向向量
                nx, nz = edge.outward_normal  # 外法线

                # 沿这条边的累积偏移
                cursor = 0.0

                for seg_idx, segment in enumerate(edge.segments):
                    seg_path = f"{edge_path}/Seg_{seg_idx}_{segment.name}"

                    # 计算墙段起点的世界坐标
                    world_x = sx + dx * cursor
                    world_z = sz + dz * cursor

                    # 创建 Xform 节点，将墙段从局部坐标映射到世界坐标
                    # 墙段局部坐标: X沿长度, Y沿高度, Z沿厚度(向内)
                    # 世界坐标: 需要旋转使X对齐edge方向, Z对齐外法线反方向(向内)
                    heading = edge.heading_angle_deg()

                    xform = self.bridge.define_xform(
                        seg_path,
                        translate=(world_x, wall_bottom_y, world_z),
                        rotate=(0, heading, 0),
                    )

                    # 生成墙段几何体（在局部坐标系中）
                    result = segment.generate_usd(self.bridge, f"{seg_path}/Geo")

                    # 将局部窗户位置转换为世界坐标
                    for lx, ly, lz in result.window_positions:
                        # 局部→世界变换：先旋转再平移
                        rad = math.radians(heading)
                        cos_a = math.cos(rad)
                        sin_a = math.sin(rad)
                        # Y轴旋转矩阵: [cos, 0, sin; 0, 1, 0; -sin, 0, cos]
                        wx = world_x + lx * cos_a + lz * sin_a
                        wz = world_z + lx * (-sin_a) + lz * cos_a
                        wy = wall_bottom_y + ly

                        self._all_window_positions.append((wx, wy, wz))

                        # 计算窗户朝向（四元数）
                        # 窗户法线应该朝向外法线方向
                        quat = self._heading_to_quaternion(heading)
                        self._all_window_orientations.append(quat)

                    total_segments += 1
                    total_windows_in_walls += len(result.window_positions)

                    # 移动游标到下一个墙段的起点
                    cursor += segment.length

        return {
            "num_wall_segments": total_segments,
            "num_window_holes": total_windows_in_walls,
        }

    def _heading_to_quaternion(self, heading_deg: float) -> Tuple[float, float, float, float]:
        """将Y轴旋转角度转换为四元数 (w, x, y, z)。"""
        rad = math.radians(heading_deg / 2)
        return (math.cos(rad), 0.0, math.sin(rad), 0.0)

    # =========================================================================
    # 窗户生成（PointInstancer）
    # =========================================================================

    def _generate_windows_from_layout(self, root: str) -> int:
        """使用PointInstancer批量生成所有窗户玻璃面板。"""
        if not self._all_window_positions:
            return 0

        windows_root = f"{root}/Windows"
        self.bridge.define_scope(windows_root)

        proto_path = f"{windows_root}/Prototypes"
        self.bridge.define_scope(proto_path)

        glass_path = f"{proto_path}/WindowGlass"
        self.bridge.create_box_mesh(
            glass_path,
            width=self.cfg.window_width,
            height=self.cfg.window_height,
            depth=0.02,
            display_color=self.cfg.window_color
        )
        self.bridge.bind_material(glass_path, f"{root}/Materials/GlassMaterial")

        positions = self._all_window_positions
        orientations = self._all_window_orientations
        proto_indices = [0] * len(positions)

        self.bridge.create_point_instancer(
            f"{windows_root}/WindowInstancer",
            prototype_paths=[glass_path],
            positions=positions,
            proto_indices=proto_indices,
            orientations=orientations,
        )

        return len(positions)

    # =========================================================================
    # 材质创建
    # =========================================================================

    def _create_materials(self, root: str) -> None:
        """创建建筑所需的所有材质。"""
        mat_root = f"{root}/Materials"
        self.bridge.define_scope(mat_root)

        self.bridge.create_material(f"{mat_root}/WallMaterial",
            diffuse_color=self.cfg.wall_color, roughness=0.8, metallic=0.0)
        self.bridge.create_material(f"{mat_root}/GlassMaterial",
            diffuse_color=self.cfg.window_color, roughness=0.1, metallic=0.0, opacity=0.3)
        self.bridge.create_material(f"{mat_root}/FloorMaterial",
            diffuse_color=self.cfg.floor_color, roughness=0.6, metallic=0.0)
        self.bridge.create_material(f"{mat_root}/RoofMaterial",
            diffuse_color=self.cfg.roof_color, roughness=0.7, metallic=0.1)
        self.bridge.create_material(f"{mat_root}/DoorMaterial",
            diffuse_color=(0.4, 0.25, 0.15), roughness=0.5, metallic=0.0)
        self.bridge.create_material(f"{mat_root}/InteriorWallMaterial",
            diffuse_color=(0.92, 0.91, 0.88), roughness=0.9, metallic=0.0)
        self.bridge.create_material(f"{mat_root}/CorridorFloorMaterial",
            diffuse_color=(0.75, 0.73, 0.70), roughness=0.4, metallic=0.0)
        self.bridge.create_material(f"{mat_root}/CornerMaterial",
            diffuse_color=(0.80, 0.77, 0.73), roughness=0.8, metallic=0.0)

    # =========================================================================
    # 楼板生成
    # =========================================================================

    def _generate_floor_slabs(self, root: str) -> int:
        """生成所有楼层的楼板。"""
        floors_root = f"{root}/FloorSlabs"
        self.bridge.define_scope(floors_root)

        W = self.cfg.building_width
        D = self.cfg.building_depth
        ft = self.cfg.floor_thickness
        H = self.cfg.floor_height

        num_slabs = 0
        for floor_idx in range(self.cfg.num_floors + 1):
            slab_top_y = floor_idx * H
            slab_center_y = slab_top_y - ft / 2

            slab_path = f"{floors_root}/Slab_F{floor_idx}"
            self.bridge.create_box_mesh(
                slab_path,
                width=W, height=ft, depth=D,
                translate=(0, slab_center_y, 0),
                display_color=self.cfg.floor_color
            )
            self.bridge.bind_material(slab_path, f"{root}/Materials/FloorMaterial")
            num_slabs += 1

        return num_slabs

    # =========================================================================
    # 转角柱生成
    # =========================================================================

    def _generate_corner_columns(self, root: str) -> int:
        """生成四个转角柱。"""
        corners_root = f"{root}/CornerColumns"
        self.bridge.define_scope(corners_root)

        wt = self.cfg.wall_thickness
        H = self.cfg.floor_height
        ft = self.cfg.floor_thickness
        num_floors = self.cfg.num_floors

        column_bottom_y = 0.0
        column_top_y = num_floors * H - ft
        column_height = column_top_y - column_bottom_y
        column_center_y = (column_bottom_y + column_top_y) / 2

        joiner = CornerJoiner90()
        count = 0
        for name, (cx, cz) in self._corners:
            col_path = f"{corners_root}/Corner_{name}"
            joiner.generate_usd(
                self.bridge, col_path,
                position=(cx, column_center_y, cz),
                height=column_height,
                thickness=wt,
                display_color=(0.80, 0.77, 0.73)
            )
            self.bridge.bind_material(col_path, f"{root}/Materials/CornerMaterial")
            count += 1

        return count

    # =========================================================================
    # 内部结构
    # =========================================================================

    def _generate_interior(self, root: str) -> Dict[str, Any]:
        """生成内部走廊和房间分隔。"""
        interior_root = f"{root}/Interior"
        self.bridge.define_scope(interior_root)

        stats = {"num_corridors": 0, "num_rooms": 0, "num_interior_walls": 0}

        wt = self.cfg.wall_thickness
        iwt = self.cfg.interior_wall_thickness
        cw = self.cfg.corridor_width
        H = self.cfg.floor_height
        ft = self.cfg.floor_thickness

        inner_w = self._interior_width
        inner_d = self._interior_depth

        for floor_idx in range(self.cfg.num_floors):
            floor_base_y = floor_idx * H
            wall_h = H - ft
            wall_cy = floor_base_y + wall_h / 2

            floor_path = f"{interior_root}/Floor_{floor_idx}"
            self.bridge.define_xform(floor_path)

            corridor_path = f"{floor_path}/Corridor"
            self.bridge.create_box_mesh(
                corridor_path,
                width=inner_w, height=0.01, depth=cw,
                translate=(0, floor_base_y + 0.005, 0),
                display_color=(0.75, 0.73, 0.70)
            )
            self.bridge.bind_material(corridor_path, f"{root}/Materials/CorridorFloorMaterial")
            stats["num_corridors"] += 1

            for side, z_off in [("North", cw/2), ("South", -cw/2)]:
                wall_path = f"{floor_path}/CorridorWall_{side}"
                self.bridge.create_box_mesh(
                    wall_path,
                    width=inner_w, height=wall_h, depth=iwt,
                    translate=(0, wall_cy, z_off),
                    display_color=(0.92, 0.91, 0.88)
                )
                self.bridge.bind_material(wall_path, f"{root}/Materials/InteriorWallMaterial")
                stats["num_interior_walls"] += 1

            room_depth_each = (inner_d - cw) / 2 - iwt

            for side, z_center in [
                ("North", cw/2 + iwt + room_depth_each/2),
                ("South", -(cw/2 + iwt + room_depth_each/2)),
            ]:
                num_rooms = max(1, int(inner_w / self.cfg.room_max_width))
                room_w = inner_w / num_rooms

                for room_idx in range(num_rooms):
                    stats["num_rooms"] += 1
                    if room_idx < num_rooms - 1:
                        wall_x = -inner_w/2 + (room_idx + 1) * room_w
                        sep_path = f"{floor_path}/RoomWall_{side}_{room_idx}"
                        self.bridge.create_box_mesh(
                            sep_path,
                            width=iwt, height=wall_h, depth=room_depth_each,
                            translate=(wall_x, wall_cy, z_center),
                            display_color=(0.92, 0.91, 0.88)
                        )
                        self.bridge.bind_material(sep_path, f"{root}/Materials/InteriorWallMaterial")
                        stats["num_interior_walls"] += 1

        return stats

    # =========================================================================
    # 屋顶
    # =========================================================================

    def _generate_roof(self, root: str) -> None:
        """生成屋顶。"""
        roof_root = f"{root}/Roof"
        self.bridge.define_scope(roof_root)

        W = self.cfg.building_width
        D = self.cfg.building_depth
        wt = self.cfg.wall_thickness
        H = self.cfg.floor_height
        num_floors = self.cfg.num_floors

        roof_slab_top = num_floors * H

        if self.cfg.roof_style == "parapet":
            ph = self.cfg.parapet_height
            parapet_cy = roof_slab_top + ph / 2

            fb_len = self._front_back_wall_length
            lr_len = self._left_right_wall_length
            fz = D/2 - wt/2
            bz = -(D/2 - wt/2)
            lx = -(W/2 - wt/2)
            rx = W/2 - wt/2

            self.bridge.create_box_mesh(f"{roof_root}/Parapet_Front",
                width=fb_len, height=ph, depth=wt,
                translate=(0, parapet_cy, fz), display_color=self.cfg.roof_color)
            self.bridge.create_box_mesh(f"{roof_root}/Parapet_Back",
                width=fb_len, height=ph, depth=wt,
                translate=(0, parapet_cy, bz), display_color=self.cfg.roof_color)
            self.bridge.create_box_mesh(f"{roof_root}/Parapet_Left",
                width=wt, height=ph, depth=lr_len,
                translate=(lx, parapet_cy, 0), display_color=self.cfg.roof_color)
            self.bridge.create_box_mesh(f"{roof_root}/Parapet_Right",
                width=wt, height=ph, depth=lr_len,
                translate=(rx, parapet_cy, 0), display_color=self.cfg.roof_color)

            for name, (cx, cz) in self._corners:
                self.bridge.create_box_mesh(
                    f"{roof_root}/ParapetCorner_{name}",
                    width=wt, height=ph, depth=wt,
                    translate=(cx, parapet_cy, cz),
                    display_color=self.cfg.roof_color
                )

        overhang = 0.25
        self.bridge.create_box_mesh(
            f"{roof_root}/RoofSlab",
            width=W + overhang * 2, height=0.15, depth=D + overhang * 2,
            translate=(0, roof_slab_top + 0.075, 0),
            display_color=self.cfg.roof_color
        )
        self.bridge.bind_material(f"{roof_root}/RoofSlab", f"{root}/Materials/RoofMaterial")

    # =========================================================================
    # 光照
    # =========================================================================

    def _create_lighting(self, root: str) -> None:
        """创建场景光照。"""
        lights_root = f"{root}/Lights"
        self.bridge.define_scope(lights_root)
        self.bridge.create_dome_light(f"{lights_root}/DomeLight", intensity=0.5)

        total_h = self.cfg.num_floors * self.cfg.floor_height
        self.bridge.create_rect_light(
            f"{lights_root}/SunLight",
            width=self.cfg.building_width * 2,
            height=self.cfg.building_depth * 2,
            intensity=1000.0,
            translate=(self.cfg.building_width, total_h * 1.5, self.cfg.building_depth)
        )
