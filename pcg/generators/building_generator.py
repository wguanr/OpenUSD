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
    CornerJoiner90, CornerJoinerGeneric, IJoiner, FacadeStyleRegistry
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

        # 大厅层高计算
        lobby_floors = max(0, self.cfg.lobby_floors)
        if lobby_floors > 0:
            if self.cfg.lobby_height > 0:
                self._lobby_total_height = self.cfg.lobby_height
            else:
                self._lobby_total_height = lobby_floors * H
            self._lobby_wall_height = self._lobby_total_height - ft
        else:
            self._lobby_total_height = 0.0
            self._lobby_wall_height = 0.0

        self._lobby_floors = lobby_floors
        self._entrance_edges = self.cfg.lobby_entrance_edges or [0]

        # 全局窗户位置收集器（世界坐标）
        self._all_window_positions: List[Tuple[float, float, float]] = []
        self._all_window_orientations: List[Tuple[float, float, float, float]] = []

    # =========================================================================
    # 墙体布局创建
    # =========================================================================

    def _create_wall_layout(self, wall_height: float, is_lobby: bool = False,
                             floor_idx: int = 0) -> WallLayout:
        """
        根据配置和底面轮廓创建墙体布局。

        Args:
            wall_height: 墙体高度
            is_lobby: 是否为大厅层（大厅层使用不同的墙体配置）
            floor_idx: 楼层索引（0-based），用于解析分层外立面风格
        """
        wt = self.cfg.wall_thickness

        if is_lobby:
            return self._create_lobby_wall_layout(wall_height)

        # 解析该层的外立面风格
        style_name = FacadeStyleRegistry.resolve_style_for_floor(
            floor_idx=floor_idx,
            facade_config=self.cfg.facade_styles,
            lobby_floors=self._lobby_floors,
            num_floors=self.cfg.num_floors,
        )

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
            idx_configs = None
            if edge_configs and isinstance(edge_configs, dict):
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
                randomize=getattr(self.cfg, 'randomize_walls', True),
                seed=self.cfg.seed,
                style_name=style_name,
                **default_kwargs,
            )

        return layout

    def _create_lobby_wall_layout(self, wall_height: float) -> WallLayout:
        """
        创建大厅层专用的墙体布局。

        大厅层特征：
          - 默认使用大面积玻璃幕墙（CurtainWall）
          - 入口边包含门墙（DoorWall）
          - 不使用随机拼接，而是确定性的大厅布局
        """
        wt = self.cfg.wall_thickness
        lobby_wall_type = self.cfg.lobby_wall_type  # 默认 "CurtainWall"
        entrance_edges = self._entrance_edges  # 默认 [0]

        default_kwargs = {
            "window_width": self.cfg.window_width,
            "window_height": min(self.cfg.window_height, wall_height * 0.6),
            "window_sill_height": self.cfg.window_sill_height,
            "window_spacing": self.cfg.window_spacing,
            "color": self.cfg.lobby_color,
        }

        # 为每条边构建配置
        edge_configs = {}
        for i in range(self._footprint.num_edges):
            net_len = self._footprint.wall_edge_net_length(i, wt)
            if net_len < 0.5:
                continue

            if self.cfg.lobby_has_entrance and i in entrance_edges:
                # 入口边：幕墙 + 门墙 + 幕墙
                door_len = max(3.0, min(5.0, net_len * 0.25))  # 门墙占边长的25%，3~5m
                side_len = (net_len - door_len) / 2

                segs = []
                if side_len > 0.5:
                    segs.append({
                        "type": lobby_wall_type,
                        "length": side_len,
                    })
                segs.append({
                    "type": "DoorWall",
                    "length": door_len,
                })
                if side_len > 0.5:
                    segs.append({
                        "type": lobby_wall_type,
                        "length": side_len,
                    })
                edge_configs[i] = segs
            else:
                # 非入口边：整条幕墙
                edge_configs[i] = [{
                    "type": lobby_wall_type,
                    "length": net_len,
                }]

        # 使用 create_from_footprint 并传入确定性配置
        layout = WallLayout.create_from_footprint(
            footprint=self._footprint,
            wall_thickness=wt,
            wall_height=wall_height,
            edge_configs=edge_configs,
            default_segment_type=lobby_wall_type,
            randomize=False,  # 大厅层不随机
            seed=self.cfg.seed,
            **default_kwargs,
        )

        return layout

    # =========================================================================
    # 模块化外墙生成
    # =========================================================================

    def _generate_modular_walls(self, root: str) -> Dict[str, Any]:
        """
        使用模块化拼接系统生成所有外墙。

        区分大厅层和标准层：
          - 大厅层：使用幕墙+门墙的确定性布局，层高可能更高
          - 标准层：使用随机墙体模块拼接
        """
        walls_root = f"{root}/ExteriorWalls"
        self.bridge.define_scope(walls_root)

        wt = self.cfg.wall_thickness
        H = self.cfg.floor_height
        ft = self.cfg.floor_thickness
        lobby_floors = self._lobby_floors

        total_segments = 0
        total_windows_in_walls = 0

        # 构建楼层信息列表: (floor_idx, wall_bottom_y, wall_height, is_lobby)
        floor_infos = []

        if lobby_floors > 0:
            # 大厅层（可能是通高的）
            lobby_wall_h = self._lobby_wall_height
            floor_infos.append((0, 0.0, lobby_wall_h, True))

            # 标准层
            for i in range(lobby_floors, self.cfg.num_floors):
                std_bottom = self._lobby_total_height + (i - lobby_floors) * H
                std_wall_h = H - ft
                floor_infos.append((i, std_bottom, std_wall_h, False))
        else:
            # 无大厅：所有楼层统一处理
            for i in range(self.cfg.num_floors):
                floor_infos.append((i, i * H, H - ft, False))

        for floor_idx, wall_bottom_y, wall_h, is_lobby in floor_infos:
            floor_label = "Lobby" if is_lobby else f"Floor_{floor_idx}"
            floor_path = f"{walls_root}/{floor_label}"
            self.bridge.define_xform(floor_path)

            # 为这一层创建墙体布局（传递floor_idx用于分层风格解析）
            layout = self._create_wall_layout(wall_h, is_lobby=is_lobby, floor_idx=floor_idx)

            # 遍历每条边
            for edge in layout.edges:
                edge_path = f"{floor_path}/Edge_{edge.name}"
                self.bridge.define_xform(edge_path)

                sx, sz = edge.start_point
                dx, dz = edge.direction
                nx, nz = edge.outward_normal

                cursor = 0.0

                for seg_idx, segment in enumerate(edge.segments):
                    seg_path = f"{edge_path}/Seg_{seg_idx}_{segment.name}"

                    world_x = sx + dx * cursor
                    world_z = sz + dz * cursor

                    heading = edge.heading_angle_deg()

                    xform = self.bridge.define_xform(
                        seg_path,
                        translate=(world_x, wall_bottom_y, world_z),
                        rotate=(0, heading, 0),
                    )

                    result = segment.generate_usd(self.bridge, f"{seg_path}/Geo")

                    for lx, ly, lz in result.window_positions:
                        rad = math.radians(heading)
                        cos_a = math.cos(rad)
                        sin_a = math.sin(rad)
                        wx = world_x + lx * cos_a + lz * sin_a
                        wz = world_z + lx * (-sin_a) + lz * cos_a
                        wy = wall_bottom_y + ly

                        self._all_window_positions.append((wx, wy, wz))
                        quat = self._heading_to_quaternion(heading)
                        self._all_window_orientations.append(quat)

                    total_segments += 1
                    total_windows_in_walls += len(result.window_positions)

                    cursor += segment.length

        return {
            "num_wall_segments": total_segments,
            "num_window_holes": total_windows_in_walls,
            "lobby_floors": lobby_floors,
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
        # 大厅材质
        self.bridge.create_material(f"{mat_root}/LobbyWallMaterial",
            diffuse_color=self.cfg.lobby_color, roughness=0.6, metallic=0.0)
        self.bridge.create_material(f"{mat_root}/LobbyGlassMaterial",
            diffuse_color=(0.5, 0.7, 0.85), roughness=0.05, metallic=0.1, opacity=0.25)
        self.bridge.create_material(f"{mat_root}/LobbyFloorMaterial",
            diffuse_color=(0.82, 0.78, 0.72), roughness=0.3, metallic=0.05)

    # =========================================================================
    # 楼板生成（多边形版）
    # =========================================================================

    def _generate_floor_slabs(self, root: str) -> int:
        """生成所有楼层的楼板（支持多边形底面和双层通高大厅）。"""
        floors_root = f"{root}/FloorSlabs"
        self.bridge.define_scope(floors_root)

        ft = self.cfg.floor_thickness
        H = self.cfg.floor_height
        lobby_floors = self._lobby_floors

        # 获取多边形顶点和三角化
        verts = self._footprint.vertices
        triangles = self._footprint.triangulate()

        # 计算每层楼板的Y坐标
        # 大厅层：如果双层通高，跳过中间楼板
        slab_y_positions = []  # (floor_idx, slab_top_y, material_suffix)

        for floor_idx in range(self.cfg.num_floors + 1):
            # 双层通高大厅：跳过 F1 到 F(lobby_floors-1) 的中间楼板
            if lobby_floors > 1 and 0 < floor_idx < lobby_floors:
                continue  # 跳过中间楼板

            if floor_idx < lobby_floors:
                # 大厅地面板
                slab_y_positions.append((floor_idx, floor_idx * H, "LobbyFloorMaterial"))
            elif floor_idx == lobby_floors and lobby_floors > 0:
                # 大厅顶部楼板（也是标准层的地面）
                slab_top_y = self._lobby_total_height
                slab_y_positions.append((floor_idx, slab_top_y, "FloorMaterial"))
            else:
                # 标准层楼板
                if lobby_floors > 0:
                    slab_top_y = self._lobby_total_height + (floor_idx - lobby_floors) * H
                else:
                    slab_top_y = floor_idx * H
                slab_y_positions.append((floor_idx, slab_top_y, "FloorMaterial"))

        num_slabs = 0
        for floor_idx, slab_top_y, mat_name in slab_y_positions:
            slab_center_y = slab_top_y - ft / 2

            slab_path = f"{floors_root}/Slab_F{floor_idx}"
            color = self.cfg.floor_color
            if "Lobby" in mat_name:
                color = (0.82, 0.78, 0.72)  # 大厅地面颜色

            self.bridge.create_polygon_slab(
                slab_path,
                vertices_xz=verts,
                triangles=triangles,
                thickness=ft,
                y_center=slab_center_y,
                display_color=color,
            )
            self.bridge.bind_material(slab_path, f"{root}/Materials/{mat_name}")
            num_slabs += 1

        return num_slabs

    # =========================================================================
    # 转角柱生成（多边形版）
    # =========================================================================

    def _generate_corner_columns(self, root: str) -> int:
        """生成所有转角柱（支持任意角度，大厅层和标准层分段）。"""
        corners_root = f"{root}/CornerColumns"
        self.bridge.define_scope(corners_root)

        wt = self.cfg.wall_thickness
        H = self.cfg.floor_height
        ft = self.cfg.floor_thickness
        num_floors = self.cfg.num_floors
        lobby_floors = self._lobby_floors

        joiner = CornerJoinerGeneric()
        count = 0

        # 计算建筑总高
        if lobby_floors > 0:
            building_top = self._lobby_total_height + (num_floors - lobby_floors) * H
        else:
            building_top = num_floors * H

        for i in range(self._footprint.num_vertices):
            quad = self._footprint.corner_quad(i, wt)

            if lobby_floors > 0:
                # 大厅层转角柱（从地面到大厅顶部）
                lobby_col_path = f"{corners_root}/Corner_{i}_Lobby"
                lobby_top = self._lobby_total_height - ft
                joiner.generate_usd_with_quad(
                    self.bridge, lobby_col_path,
                    quad_xz=quad,
                    y_bottom=0.0,
                    y_top=lobby_top,
                    display_color=self.cfg.lobby_color,
                )
                self.bridge.bind_material(lobby_col_path, f"{root}/Materials/LobbyWallMaterial")
                count += 1

                # 标准层转角柱（从大厅顶部到建筑顶部）
                if num_floors > lobby_floors:
                    std_col_path = f"{corners_root}/Corner_{i}_Std"
                    std_bottom = self._lobby_total_height
                    std_top = building_top - ft
                    joiner.generate_usd_with_quad(
                        self.bridge, std_col_path,
                        quad_xz=quad,
                        y_bottom=std_bottom,
                        y_top=std_top,
                        display_color=(0.80, 0.77, 0.73),
                    )
                    self.bridge.bind_material(std_col_path, f"{root}/Materials/CornerMaterial")
                    count += 1
            else:
                # 无大厅：整体转角柱
                col_path = f"{corners_root}/Corner_{i}"
                joiner.generate_usd_with_quad(
                    self.bridge, col_path,
                    quad_xz=quad,
                    y_bottom=0.0,
                    y_top=building_top - ft,
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
        lobby_floors = self._lobby_floors

        # 计算屋顶板顶面Y坐标
        if lobby_floors > 0:
            roof_slab_top = self._lobby_total_height + (num_floors - lobby_floors) * H
        else:
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
                # 局部坐标原点在墙段起点，X沿长度方向，Z沿厚度方向
                # Xform已经把原点放在了边的中点，所以局部坐标中墙段居中
                self.bridge.create_box_mesh(
                    f"{parapet_path}/Geo",
                    width=net_len, height=ph, depth=wt,
                    translate=(0, 0, -wt / 2),  # 居中放置，外表面对齐Z=0
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
        # 注意：楼板循环已经生成了顶层楼板（Slab_F{num_floors}），
        # 这里只在有parapet时生成额外的出挑檐口板，位于parapet顶部
        if self.cfg.roof_style == "parapet":
            overhang = 0.25
            roof_footprint = self._footprint.inset_polygon(-overhang)
            roof_verts = roof_footprint.vertices
            roof_tris = roof_footprint.triangulate()

            # 檐口板在女儿墙顶部
            cap_y = roof_slab_top + self.cfg.parapet_height + 0.075
            self.bridge.create_polygon_slab(
                f"{roof_root}/RoofCap",
                vertices_xz=roof_verts,
                triangles=roof_tris,
                thickness=0.15,
                y_center=cap_y,
                display_color=self.cfg.roof_color,
            )
            self.bridge.bind_material(f"{roof_root}/RoofCap", f"{root}/Materials/RoofMaterial")

    # =========================================================================
    # 光照
    # =========================================================================

    def _create_lighting(self, root: str) -> None:
        """创建场景光照。"""
        lights_root = f"{root}/Lights"
        self.bridge.define_scope(lights_root)
        self.bridge.create_dome_light(f"{lights_root}/DomeLight", intensity=0.5)

        if self._lobby_floors > 0:
            total_h = self._lobby_total_height + (self.cfg.num_floors - self._lobby_floors) * self.cfg.floor_height
        else:
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

