"""
Building Generator v4: 多边形底面版。

核心架构变更：
  v3: 矩形底面 → 硬编码四条边
  v4: 任意多边形底面 → BuildingFootprint 驱动所有几何体

建筑外壳生成流程：
  1. 从配置创建 BuildingFootprint（矩形/L形/T形/六边形/自定义）
  2. 用 Footprint 生成多边形楼板（create_polygon_slab）
  3. 用 Footprint.corner_quad() 生成精确截面的转角柱（create_prism_mesh）
  4. 用 WallLayout.create_from_footprint() 创建墙体布局
  5. 沿每条边遍历墙段，通过 Xform 变换放置到世界坐标
  6. 收集窗户位置，用全局 PointInstancer 生成窗户

坐标约定：
  - 建筑质心在原点（XZ平面）
  - X轴: 建筑宽度方向
  - Y轴: 高度方向（向上）
  - Z轴: 建筑深度方向
  - 顶点按顺时针排列（从+Y俯视）
  - 外墙外表面对齐建筑外轮廓
  - 墙体厚度统一向内
"""

import math
import random
from typing import Dict, Any, List, Tuple, Optional
from pxr import Gf, Vt, Sdf, UsdGeom

from pcg_core.engine import GeneratorBase, BuildingConfig
from pcg_core.usd_bridge import UsdBridge
from pcg_core.footprint import BuildingFootprint
from pcg_core.wall_module import (
    IWallSegment, WallSegmentResult, WallLayout, WallEdge,
    CornerJoiner90, CornerJoinerGeneric, IJoiner
)
# 导入所有墙段类型以触发注册
import pcg_core.wall_segments  # noqa: F401


class BuildingGenerator(GeneratorBase):
    """办公楼程序化生成器（v4 - 多边形底面版）。"""

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
            "footprint_type": self.cfg.footprint_type,
        }

        # 第一步：创建建筑底面轮廓
        with self._time_it("footprint"):
            self._footprint = self._create_footprint()
            stats["footprint_vertices"] = self._footprint.num_vertices
            stats["footprint_area_m2"] = round(self._footprint.area(), 1)
            bbox = self._footprint.bounding_box_size()
            stats["bounding_box"] = f"{bbox[0]:.1f}x{bbox[1]:.1f}m"

        # 预计算
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

        if self.cfg.enable_interior and self.cfg.footprint_type == "rectangle":
            # 内部布局目前仅支持矩形（后续可扩展）
            with self._time_it("interior"):
                stats.update(self._generate_interior(root))

        with self._time_it("roof"):
            self._generate_roof(root)

        with self._time_it("lighting"):
            self._create_lighting(root)

        return stats

    # =========================================================================
    # 底面轮廓创建
    # =========================================================================

    def _create_footprint(self) -> BuildingFootprint:
        """根据配置创建建筑底面轮廓。"""
        ft = self.cfg.footprint_type
        params = self.cfg.footprint_params or {}

        if ft == "rectangle":
            return BuildingFootprint.rectangle(
                self.cfg.building_width,
                self.cfg.building_depth
            )
        elif ft == "l_shape":
            return BuildingFootprint.l_shape(
                w1=params.get("w1", self.cfg.building_width * 0.6),
                d1=params.get("d1", self.cfg.building_depth),
                w2=params.get("w2", self.cfg.building_width * 0.4),
                d2=params.get("d2", self.cfg.building_depth * 0.5),
                center=True,
            )
        elif ft == "t_shape":
            return BuildingFootprint.t_shape(
                w_main=params.get("w_main", self.cfg.building_width),
                d_main=params.get("d_main", self.cfg.building_depth * 0.4),
                w_stem=params.get("w_stem", self.cfg.building_width * 0.4),
                d_stem=params.get("d_stem", self.cfg.building_depth * 0.6),
                center=True,
            )
        elif ft == "hexagon":
            return BuildingFootprint.regular_polygon(
                n_sides=params.get("n_sides", 6),
                radius=params.get("radius", min(self.cfg.building_width, self.cfg.building_depth) / 2),
            )
        elif ft == "pentagon":
            return BuildingFootprint.regular_polygon(
                n_sides=5,
                radius=params.get("radius", min(self.cfg.building_width, self.cfg.building_depth) / 2),
            )
        elif ft == "octagon":
            return BuildingFootprint.regular_polygon(
                n_sides=8,
                radius=params.get("radius", min(self.cfg.building_width, self.cfg.building_depth) / 2),
            )
        elif ft == "custom":
            verts = self.cfg.custom_vertices
            if not verts:
                raise ValueError("custom footprint requires 'custom_vertices' in config")
            return BuildingFootprint.from_vertices(verts)
        else:
            raise ValueError(f"Unknown footprint_type: '{ft}'. "
                             f"Available: rectangle, l_shape, t_shape, hexagon, pentagon, octagon, custom")

    # =========================================================================
    # 预计算
    # =========================================================================

    def _precompute_dimensions(self):
        """预计算所有关键尺寸。"""
        wt = self.cfg.wall_thickness
        ft = self.cfg.floor_thickness
        H = self.cfg.floor_height

        self._wall_net_height = H - ft

        # 全局窗户位置收集器（世界坐标）
        self._all_window_positions: List[Tuple[float, float, float]] = []
        self._all_window_orientations: List[Tuple[float, float, float, float]] = []

    # =========================================================================
    # 墙体布局创建
    # =========================================================================

    def _create_wall_layout(self, wall_height: float) -> WallLayout:
        """
        根据配置和底面轮廓创建墙体布局。

        对于矩形底面，使用传统的 create_rectangular 方法（保持向后兼容）。
        对于多边形底面，使用新的 create_from_footprint 方法。
        """
        wt = self.cfg.wall_thickness

        # 默认的窗户参数
        default_kwargs = {
            "window_width": self.cfg.window_width,
            "window_height": self.cfg.window_height,
            "window_sill_height": self.cfg.window_sill_height,
            "window_spacing": self.cfg.window_spacing,
            "color": self.cfg.wall_color,
        }

        # 检查是否有用户自定义的墙体布局
        edge_configs = getattr(self.cfg, 'wall_layout', None)

        if self.cfg.footprint_type == "rectangle" and edge_configs:
            # 矩形 + 自定义边配置 → 使用传统方法
            layout = WallLayout.create_rectangular(
                width=self.cfg.building_width,
                depth=self.cfg.building_depth,
                wall_thickness=wt,
                wall_height=wall_height,
                edge_configs=edge_configs,
                default_segment_type="WindowWall",
                **default_kwargs,
            )
        else:
            # 通用多边形路径
            # 将 edge_configs 从 name-based 转换为 index-based（如果有的话）
            idx_configs = None
            if edge_configs and isinstance(edge_configs, dict):
                # 尝试将 "edge_0", "edge_1" 等转换为整数键
                idx_configs = {}
                for k, v in edge_configs.items():
                    if k.startswith("edge_"):
                        try:
                            idx = int(k.split("_")[1])
                            idx_configs[idx] = v
                        except (ValueError, IndexError):
                            pass

            layout = WallLayout.create_from_footprint(
                footprint=self._footprint,
                wall_thickness=wt,
                wall_height=wall_height,
                edge_configs=idx_configs,
                default_segment_type="WindowWall",
                **default_kwargs,
            )

        return layout

    # =========================================================================
    # 模块化外墙生成
    # =========================================================================

    def _generate_modular_walls(self, root: str) -> Dict[str, Any]:
        """
        使用模块化拼接系统生成所有外墙。

        对每一层楼：
          1. 创建该层的 WallLayout（基于 Footprint）
          2. 遍历每条边，沿边依次放置墙段模块
          3. 通过 Xform 变换将墙段从局部坐标映射到世界坐标
          4. 收集窗户位置用于后续 PointInstancer 生成
        """
        walls_root = f"{root}/ExteriorWalls"
        self.bridge.define_scope(walls_root)

        wt = self.cfg.wall_thickness
        H = self.cfg.floor_height
        ft = self.cfg.floor_thickness

        total_segments = 0
        total_windows_in_walls = 0

        for floor_idx in range(self.cfg.num_floors):
            wall_bottom_y = floor_idx * H
            wall_h = H - ft

            floor_path = f"{walls_root}/Floor_{floor_idx}"
            self.bridge.define_xform(floor_path)

            # 为这一层创建墙体布局
            layout = self._create_wall_layout(wall_h)

            # 遍历每条边
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
                        rad = math.radians(heading)
                        cos_a = math.cos(rad)
                        sin_a = math.sin(rad)
                        # Y轴旋转矩阵: [cos, 0, sin; 0, 1, 0; -sin, 0, cos]
                        wx = world_x + lx * cos_a + lz * sin_a
                        wz = world_z + lx * (-sin_a) + lz * cos_a
                        wy = wall_bottom_y + ly

                        self._all_window_positions.append((wx, wy, wz))

                        # 计算窗户朝向（四元数）
                        quat = self._heading_to_quaternion(heading)
                        self._all_window_orientations.append(quat)

                    total_segments += 1
                    total_windows_in_walls += len(result.window_positions)

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
        """创建所有材质。"""
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
    # 楼板生成（多边形版）
    # =========================================================================

    def _generate_floor_slabs(self, root: str) -> int:
        """生成所有楼层的楼板（支持多边形底面）。"""
        floors_root = f"{root}/FloorSlabs"
        self.bridge.define_scope(floors_root)

        ft = self.cfg.floor_thickness
        H = self.cfg.floor_height

        # 获取多边形顶点和三角化
        verts = self._footprint.vertices
        triangles = self._footprint.triangulate()

        num_slabs = 0
        for floor_idx in range(self.cfg.num_floors + 1):
            slab_top_y = floor_idx * H
            slab_center_y = slab_top_y - ft / 2

            slab_path = f"{floors_root}/Slab_F{floor_idx}"
            self.bridge.create_polygon_slab(
                slab_path,
                vertices_xz=verts,
                triangles=triangles,
                thickness=ft,
                y_center=slab_center_y,
                display_color=self.cfg.floor_color,
            )
            self.bridge.bind_material(slab_path, f"{root}/Materials/FloorMaterial")
            num_slabs += 1

        return num_slabs

    # =========================================================================
    # 转角柱生成（多边形版）
    # =========================================================================

    def _generate_corner_columns(self, root: str) -> int:
        """生成所有转角柱（支持任意角度）。"""
        corners_root = f"{root}/CornerColumns"
        self.bridge.define_scope(corners_root)

        wt = self.cfg.wall_thickness
        H = self.cfg.floor_height
        ft = self.cfg.floor_thickness
        num_floors = self.cfg.num_floors

        column_bottom_y = 0.0
        column_top_y = num_floors * H - ft
        column_height = column_top_y - column_bottom_y

        joiner = CornerJoinerGeneric()
        count = 0

        for i in range(self._footprint.num_vertices):
            # 获取该顶点处的转角柱截面
            quad = self._footprint.corner_quad(i, wt)
            angle = self._footprint.interior_angle_deg(i)

            col_path = f"{corners_root}/Corner_{i}"

            # 使用精确的四边形截面生成转角柱
            joiner.generate_usd_with_quad(
                self.bridge, col_path,
                quad_xz=quad,
                y_bottom=column_bottom_y,
                y_top=column_top_y,
                display_color=(0.80, 0.77, 0.73),
            )
            self.bridge.bind_material(col_path, f"{root}/Materials/CornerMaterial")
            count += 1

        return count

    # =========================================================================
    # 内部结构（矩形专用，后续可扩展）
    # =========================================================================

    def _generate_interior(self, root: str) -> Dict[str, Any]:
        """生成内部走廊和房间分隔（目前仅支持矩形底面）。"""
        interior_root = f"{root}/Interior"
        self.bridge.define_scope(interior_root)

        stats = {"num_corridors": 0, "num_rooms": 0, "num_interior_walls": 0}

        wt = self.cfg.wall_thickness
        iwt = self.cfg.interior_wall_thickness
        cw = self.cfg.corridor_width
        H = self.cfg.floor_height
        ft = self.cfg.floor_thickness

        W = self.cfg.building_width
        D = self.cfg.building_depth
        inner_w = W - 2 * wt
        inner_d = D - 2 * wt

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
    # 屋顶（多边形版）
    # =========================================================================

    def _generate_roof(self, root: str) -> None:
        """生成屋顶（支持多边形底面）。"""
        roof_root = f"{root}/Roof"
        self.bridge.define_scope(roof_root)

        wt = self.cfg.wall_thickness
        H = self.cfg.floor_height
        num_floors = self.cfg.num_floors
        roof_slab_top = num_floors * H

        if self.cfg.roof_style == "parapet":
            ph = self.cfg.parapet_height
            parapet_bottom = roof_slab_top
            parapet_top = roof_slab_top + ph

            # 为每条边生成女儿墙段
            for i in range(self._footprint.num_edges):
                net_len = self._footprint.wall_edge_net_length(i, wt)
                if net_len < 0.1:
                    continue

                start_pt = self._footprint.wall_edge_start_point(i, wt)
                d = self._footprint.edge_direction(i)
                n = self._footprint.edge_outward_normal(i)

                # 女儿墙中心位置
                mid_x = start_pt[0] + d[0] * net_len / 2
                mid_z = start_pt[1] + d[1] * net_len / 2
                parapet_cy = (parapet_bottom + parapet_top) / 2

                # 计算heading角度
                heading = self._footprint.edge_heading_deg(i)

                parapet_path = f"{roof_root}/Parapet_Edge_{i}"
                xform = self.bridge.define_xform(
                    parapet_path,
                    translate=(mid_x, parapet_cy, mid_z),
                    rotate=(0, heading, 0),
                )
                # 在局部坐标系中创建墙段（X沿长度，Z沿厚度）
                self.bridge.create_box_mesh(
                    f"{parapet_path}/Geo",
                    width=net_len, height=ph, depth=wt,
                    translate=(net_len / 2, 0, -wt / 2),  # 局部偏移使外表面对齐
                    display_color=self.cfg.roof_color,
                )

            # 女儿墙转角柱
            for i in range(self._footprint.num_vertices):
                quad = self._footprint.corner_quad(i, wt)
                col_path = f"{roof_root}/ParapetCorner_{i}"
                joiner = CornerJoinerGeneric()
                joiner.generate_usd_with_quad(
                    self.bridge, col_path,
                    quad_xz=quad,
                    y_bottom=parapet_bottom,
                    y_top=parapet_top,
                    display_color=self.cfg.roof_color,
                )

        # 屋顶板（带出挑）
        overhang = 0.25
        # 创建外扩的屋顶多边形
        roof_footprint = self._footprint.inset_polygon(-overhang)
        roof_verts = roof_footprint.vertices
        roof_tris = roof_footprint.triangulate()

        self.bridge.create_polygon_slab(
            f"{roof_root}/RoofSlab",
            vertices_xz=roof_verts,
            triangles=roof_tris,
            thickness=0.15,
            y_center=roof_slab_top + 0.075,
            display_color=self.cfg.roof_color,
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
        bbox = self._footprint.bounding_box_size()
        max_dim = max(bbox[0], bbox[1])

        self.bridge.create_rect_light(
            f"{lights_root}/SunLight",
            width=max_dim * 2,
            height=max_dim * 2,
            intensity=1000.0,
            translate=(max_dim, total_h * 1.5, max_dim)
        )

