"""
Building Generator: 办公楼程序化生成器。

根据BuildingConfig参数，程序化生成完整的办公楼USD场景，包括：
- 多层楼板
- 外墙（带窗户孔洞）
- 窗户（PointInstancer高性能实例化）
- 入口门
- 内部走廊和房间分隔
- 屋顶（平顶或带女儿墙）
- 材质系统
- 光照
"""

import math
import random
from typing import Dict, Any, List, Tuple, Optional
from pxr import Gf, Vt, Sdf, UsdGeom

from pcg_core.engine import GeneratorBase, BuildingConfig
from pcg_core.usd_bridge import UsdBridge


class BuildingGenerator(GeneratorBase):
    """办公楼程序化生成器。"""

    def __init__(self, bridge: UsdBridge, config: BuildingConfig):
        super().__init__(bridge, config)
        self.cfg: BuildingConfig = config
        random.seed(config.seed)

    def generate(self, parent_path: str = "") -> Dict[str, Any]:
        """执行完整的办公楼生成流程。"""
        root = f"{parent_path}/{self.cfg.building_name}"

        # 创建建筑根节点
        self.bridge.define_xform(root)

        # 统计数据
        stats = {
            "building_name": self.cfg.building_name,
            "num_floors": self.cfg.num_floors,
            "dimensions": f"{self.cfg.building_width}x{self.cfg.building_depth}x{self.cfg.num_floors * self.cfg.floor_height}m",
        }

        # 1. 创建材质
        with self._time_it("materials"):
            self._create_materials(root)

        # 2. 生成楼板
        with self._time_it("floor_slabs"):
            num_slabs = self._generate_floor_slabs(root)
            stats["num_floor_slabs"] = num_slabs

        # 3. 生成外墙
        with self._time_it("exterior_walls"):
            wall_info = self._generate_exterior_walls(root)
            stats["num_walls"] = wall_info["num_walls"]
            stats["num_window_holes"] = wall_info["num_window_holes"]

        # 4. 生成窗户（PointInstancer）
        with self._time_it("windows"):
            num_windows = self._generate_windows(root)
            stats["num_windows"] = num_windows

        # 5. 生成入口门
        with self._time_it("doors"):
            num_doors = self._generate_entrance_doors(root)
            stats["num_doors"] = num_doors

        # 6. 生成内部结构
        if self.cfg.enable_interior:
            with self._time_it("interior"):
                interior_info = self._generate_interior(root)
                stats.update(interior_info)

        # 7. 生成屋顶
        with self._time_it("roof"):
            self._generate_roof(root)

        # 8. 添加光照
        with self._time_it("lighting"):
            self._create_lighting(root)

        return stats

    # =========================================================================
    # 材质创建
    # =========================================================================

    def _create_materials(self, root: str) -> None:
        """创建建筑所需的所有材质。"""
        mat_root = f"{root}/Materials"
        self.bridge.define_scope(mat_root)

        # 外墙材质
        self.bridge.create_material(
            f"{mat_root}/WallMaterial",
            diffuse_color=self.cfg.wall_color,
            roughness=0.8, metallic=0.0
        )

        # 窗户材质（玻璃）
        self.bridge.create_material(
            f"{mat_root}/GlassMaterial",
            diffuse_color=self.cfg.window_color,
            roughness=0.1, metallic=0.0, opacity=0.3
        )

        # 楼板材质
        self.bridge.create_material(
            f"{mat_root}/FloorMaterial",
            diffuse_color=self.cfg.floor_color,
            roughness=0.6, metallic=0.0
        )

        # 屋顶材质
        self.bridge.create_material(
            f"{mat_root}/RoofMaterial",
            diffuse_color=self.cfg.roof_color,
            roughness=0.7, metallic=0.1
        )

        # 门材质
        self.bridge.create_material(
            f"{mat_root}/DoorMaterial",
            diffuse_color=(0.4, 0.25, 0.15),
            roughness=0.5, metallic=0.0
        )

        # 内墙材质
        self.bridge.create_material(
            f"{mat_root}/InteriorWallMaterial",
            diffuse_color=(0.92, 0.91, 0.88),
            roughness=0.9, metallic=0.0
        )

        # 走廊地板材质
        self.bridge.create_material(
            f"{mat_root}/CorridorFloorMaterial",
            diffuse_color=(0.75, 0.73, 0.70),
            roughness=0.4, metallic=0.0
        )

    # =========================================================================
    # 楼板生成
    # =========================================================================

    def _generate_floor_slabs(self, root: str) -> int:
        """生成所有楼层的楼板。"""
        floors_root = f"{root}/FloorSlabs"
        self.bridge.define_scope(floors_root)

        num_slabs = 0
        for floor_idx in range(self.cfg.num_floors + 1):  # +1 for roof slab
            y = floor_idx * self.cfg.floor_height
            slab_path = f"{floors_root}/Slab_F{floor_idx}"

            self.bridge.create_box_mesh(
                slab_path,
                width=self.cfg.building_width,
                height=self.cfg.floor_thickness,
                depth=self.cfg.building_depth,
                translate=(0, y, 0),
                display_color=self.cfg.floor_color
            )
            self.bridge.bind_material(slab_path, f"{root}/Materials/FloorMaterial")
            num_slabs += 1

        return num_slabs

    # =========================================================================
    # 外墙生成
    # =========================================================================

    def _generate_exterior_walls(self, root: str) -> Dict[str, int]:
        """生成所有外墙（带窗户孔洞）。"""
        walls_root = f"{root}/ExteriorWalls"
        self.bridge.define_scope(walls_root)

        total_walls = 0
        total_holes = 0

        W = self.cfg.building_width
        D = self.cfg.building_depth
        H = self.cfg.floor_height
        wt = self.cfg.wall_thickness

        for floor_idx in range(self.cfg.num_floors):
            floor_base_y = floor_idx * H + self.cfg.floor_thickness / 2
            wall_center_y = floor_base_y + (H - self.cfg.floor_thickness) / 2
            wall_h = H - self.cfg.floor_thickness

            floor_walls_path = f"{walls_root}/Floor_{floor_idx}"
            self.bridge.define_xform(floor_walls_path)

            # 计算窗户位置
            window_holes = self._calculate_window_positions(
                wall_h, floor_idx
            )

            # 前墙 (+Z)
            front_holes = self._map_holes_to_wall(window_holes, W)
            self.bridge.create_wall_mesh(
                f"{floor_walls_path}/Wall_Front",
                width=W, height=wall_h, thickness=wt,
                holes=front_holes,
                translate=(0, wall_center_y, D / 2),
                display_color=self.cfg.wall_color
            )
            self.bridge.bind_material(
                f"{floor_walls_path}/Wall_Front",
                f"{root}/Materials/WallMaterial"
            )
            total_walls += 1
            total_holes += len(front_holes)

            # 后墙 (-Z)
            back_holes = self._map_holes_to_wall(window_holes, W)
            self.bridge.create_wall_mesh(
                f"{floor_walls_path}/Wall_Back",
                width=W, height=wall_h, thickness=wt,
                holes=back_holes,
                translate=(0, wall_center_y, -D / 2),
                display_color=self.cfg.wall_color
            )
            self.bridge.bind_material(
                f"{floor_walls_path}/Wall_Back",
                f"{root}/Materials/WallMaterial"
            )
            total_walls += 1
            total_holes += len(back_holes)

            # 左墙 (-X)
            left_holes = self._map_holes_to_wall(window_holes, D)
            self.bridge.create_wall_mesh(
                f"{floor_walls_path}/Wall_Left",
                width=D, height=wall_h, thickness=wt,
                holes=left_holes,
                translate=(-W / 2, wall_center_y, 0),
                display_color=self.cfg.wall_color
            )
            # 旋转左墙
            prim = self.bridge.stage.GetPrimAtPath(f"{floor_walls_path}/Wall_Left")
            UsdGeom.Xformable(prim).AddRotateYOp().Set(90.0)
            self.bridge.bind_material(
                f"{floor_walls_path}/Wall_Left",
                f"{root}/Materials/WallMaterial"
            )
            total_walls += 1
            total_holes += len(left_holes)

            # 右墙 (+X)
            right_holes = self._map_holes_to_wall(window_holes, D)
            self.bridge.create_wall_mesh(
                f"{floor_walls_path}/Wall_Right",
                width=D, height=wall_h, thickness=wt,
                holes=right_holes,
                translate=(W / 2, wall_center_y, 0),
                display_color=self.cfg.wall_color
            )
            prim = self.bridge.stage.GetPrimAtPath(f"{floor_walls_path}/Wall_Right")
            UsdGeom.Xformable(prim).AddRotateYOp().Set(90.0)
            self.bridge.bind_material(
                f"{floor_walls_path}/Wall_Right",
                f"{root}/Materials/WallMaterial"
            )
            total_walls += 1
            total_holes += len(right_holes)

        return {"num_walls": total_walls, "num_window_holes": total_holes}

    def _calculate_window_positions(self, wall_height: float,
                                    floor_idx: int) -> List[Dict[str, float]]:
        """计算单面墙上的窗户位置（相对于墙体中心）。"""
        holes = []
        ww = self.cfg.window_width
        wh = self.cfg.window_height
        sill = self.cfg.window_sill_height

        # 窗户中心Y坐标（相对于墙体中心）
        window_center_y = sill + wh / 2 - wall_height / 2

        # 确保窗户在墙体范围内
        if window_center_y + wh / 2 > wall_height / 2:
            return holes

        return holes  # 位置在_map_holes_to_wall中计算

    def _map_holes_to_wall(self, base_holes: List, wall_width: float) -> List[Dict[str, float]]:
        """根据墙体宽度计算窗户孔洞的实际位置。"""
        holes = []
        ww = self.cfg.window_width
        wh = self.cfg.window_height
        spacing = self.cfg.window_spacing
        sill = self.cfg.window_sill_height
        wall_h = self.cfg.floor_height - self.cfg.floor_thickness

        # 窗户中心Y坐标
        window_center_y = sill + wh / 2 - wall_h / 2

        if window_center_y + wh / 2 > wall_h / 2:
            return holes

        # 计算可以放置多少个窗户
        usable_width = wall_width - spacing  # 两端留边
        num_windows = max(0, int(usable_width / spacing))

        if num_windows <= 0:
            return holes

        # 均匀分布窗户
        total_span = (num_windows - 1) * spacing if num_windows > 1 else 0
        start_x = -total_span / 2

        for i in range(num_windows):
            cx = start_x + i * spacing
            holes.append({
                "x": cx,
                "y": window_center_y,
                "w": ww,
                "h": wh,
            })

        return holes

    # =========================================================================
    # 窗户生成（PointInstancer高性能实例化）
    # =========================================================================

    def _generate_windows(self, root: str) -> int:
        """使用PointInstancer批量生成所有窗户。"""
        windows_root = f"{root}/Windows"
        self.bridge.define_scope(windows_root)

        # 创建窗户原型
        proto_path = f"{windows_root}/Prototypes"
        self.bridge.define_scope(proto_path)

        # 窗户面板原型（薄的玻璃面板）
        glass_path = f"{proto_path}/WindowGlass"
        self.bridge.create_box_mesh(
            glass_path,
            width=self.cfg.window_width,
            height=self.cfg.window_height,
            depth=0.02,  # 很薄的玻璃
            display_color=self.cfg.window_color
        )
        self.bridge.bind_material(glass_path, f"{root}/Materials/GlassMaterial")

        # 窗框原型
        frame_path = f"{proto_path}/WindowFrame"
        self._create_window_frame(frame_path)

        if not self.cfg.use_instancing:
            # 非实例化模式：逐个创建
            return self._generate_windows_individual(root, windows_root)

        # 收集所有窗户位置
        positions = []
        orientations = []
        proto_indices = []

        W = self.cfg.building_width
        D = self.cfg.building_depth
        H = self.cfg.floor_height
        wt = self.cfg.wall_thickness

        for floor_idx in range(self.cfg.num_floors):
            floor_base_y = floor_idx * H + self.cfg.floor_thickness / 2
            wall_h = H - self.cfg.floor_thickness
            sill = self.cfg.window_sill_height
            window_center_y = floor_base_y + sill + self.cfg.window_height / 2

            # 四面墙的窗户
            wall_configs = [
                # (wall_width, center_pos_func, rotation_quat)
                (W, lambda cx: (cx, window_center_y, D / 2 + 0.01),
                 (1.0, 0.0, 0.0, 0.0)),  # 前墙，无旋转
                (W, lambda cx: (cx, window_center_y, -D / 2 - 0.01),
                 (0.0, 0.0, 1.0, 0.0)),  # 后墙，旋转180度
                (D, lambda cx: (-W / 2 - 0.01, window_center_y, cx),
                 (0.707, 0.0, 0.707, 0.0)),  # 左墙，旋转-90度
                (D, lambda cx: (W / 2 + 0.01, window_center_y, cx),
                 (0.707, 0.0, -0.707, 0.0)),  # 右墙，旋转90度
            ]

            for wall_width, pos_func, quat in wall_configs:
                spacing = self.cfg.window_spacing
                usable_width = wall_width - spacing
                num_windows = max(0, int(usable_width / spacing))

                if num_windows <= 0:
                    continue

                total_span = (num_windows - 1) * spacing if num_windows > 1 else 0
                start_x = -total_span / 2

                for i in range(num_windows):
                    cx = start_x + i * spacing
                    pos = pos_func(cx)
                    positions.append(pos)
                    orientations.append(quat)
                    # 交替使用玻璃和窗框原型（每个窗户放两个实例）
                    proto_indices.append(0)  # 玻璃

        if not positions:
            return 0

        # 创建PointInstancer
        self.bridge.create_point_instancer(
            f"{windows_root}/WindowInstancer",
            prototype_paths=[glass_path],
            positions=positions,
            proto_indices=proto_indices,
            orientations=orientations,
        )

        return len(positions)

    def _generate_windows_individual(self, root: str, windows_root: str) -> int:
        """非实例化模式：逐个创建窗户（用于对比性能）。"""
        count = 0
        W = self.cfg.building_width
        D = self.cfg.building_depth
        H = self.cfg.floor_height

        for floor_idx in range(self.cfg.num_floors):
            floor_base_y = floor_idx * H + self.cfg.floor_thickness / 2
            sill = self.cfg.window_sill_height
            window_center_y = floor_base_y + sill + self.cfg.window_height / 2

            for wall_width, z_offset, rot_y in [
                (W, D / 2 + 0.01, 0),
                (W, -D / 2 - 0.01, 180),
            ]:
                spacing = self.cfg.window_spacing
                usable_width = wall_width - spacing
                num_windows = max(0, int(usable_width / spacing))
                total_span = (num_windows - 1) * spacing if num_windows > 1 else 0
                start_x = -total_span / 2

                for i in range(num_windows):
                    cx = start_x + i * spacing
                    path = f"{windows_root}/Window_F{floor_idx}_{count}"
                    self.bridge.create_box_mesh(
                        path,
                        width=self.cfg.window_width,
                        height=self.cfg.window_height,
                        depth=0.02,
                        translate=(cx, window_center_y, z_offset),
                        display_color=self.cfg.window_color
                    )
                    if rot_y != 0:
                        prim = self.bridge.stage.GetPrimAtPath(path)
                        UsdGeom.Xformable(prim).AddRotateYOp().Set(float(rot_y))
                    count += 1

        return count

    def _create_window_frame(self, path: str) -> None:
        """创建窗框原型。"""
        frame_thickness = 0.05
        ww = self.cfg.window_width
        wh = self.cfg.window_height

        xform = self.bridge.define_xform(path)

        # 上框
        self.bridge.create_box_mesh(
            f"{path}/Top",
            width=ww, height=frame_thickness, depth=frame_thickness,
            translate=(0, wh / 2 - frame_thickness / 2, 0),
            display_color=(0.3, 0.3, 0.3)
        )
        # 下框
        self.bridge.create_box_mesh(
            f"{path}/Bottom",
            width=ww, height=frame_thickness, depth=frame_thickness,
            translate=(0, -wh / 2 + frame_thickness / 2, 0),
            display_color=(0.3, 0.3, 0.3)
        )
        # 左框
        self.bridge.create_box_mesh(
            f"{path}/Left",
            width=frame_thickness, height=wh, depth=frame_thickness,
            translate=(-ww / 2 + frame_thickness / 2, 0, 0),
            display_color=(0.3, 0.3, 0.3)
        )
        # 右框
        self.bridge.create_box_mesh(
            f"{path}/Right",
            width=frame_thickness, height=wh, depth=frame_thickness,
            translate=(ww / 2 - frame_thickness / 2, 0, 0),
            display_color=(0.3, 0.3, 0.3)
        )
        # 中间横档
        self.bridge.create_box_mesh(
            f"{path}/MiddleH",
            width=ww - 2 * frame_thickness, height=frame_thickness, depth=frame_thickness,
            translate=(0, 0, 0),
            display_color=(0.3, 0.3, 0.3)
        )

    # =========================================================================
    # 入口门生成
    # =========================================================================

    def _generate_entrance_doors(self, root: str) -> int:
        """生成建筑入口门。"""
        doors_root = f"{root}/Doors"
        self.bridge.define_scope(doors_root)

        W = self.cfg.building_width
        D = self.cfg.building_depth
        door_y = self.cfg.floor_thickness / 2 + self.cfg.door_height / 2

        num_doors = 0
        # 在前墙中央放置入口
        for i in range(self.cfg.num_entrances):
            offset = 0 if self.cfg.num_entrances == 1 else (i - (self.cfg.num_entrances - 1) / 2) * 5

            door_path = f"{doors_root}/Entrance_{i}"
            self.bridge.create_box_mesh(
                door_path,
                width=self.cfg.door_width,
                height=self.cfg.door_height,
                depth=self.cfg.wall_thickness + 0.05,
                translate=(offset, door_y, D / 2),
                display_color=(0.4, 0.25, 0.15)
            )
            self.bridge.bind_material(door_path, f"{root}/Materials/DoorMaterial")
            num_doors += 1

        return num_doors

    # =========================================================================
    # 内部结构生成
    # =========================================================================

    def _generate_interior(self, root: str) -> Dict[str, Any]:
        """生成内部走廊和房间分隔。"""
        interior_root = f"{root}/Interior"
        self.bridge.define_scope(interior_root)

        stats = {"num_corridors": 0, "num_rooms": 0, "num_interior_walls": 0}

        W = self.cfg.building_width
        D = self.cfg.building_depth
        H = self.cfg.floor_height
        wt = self.cfg.interior_wall_thickness
        cw = self.cfg.corridor_width
        ext_wt = self.cfg.wall_thickness

        for floor_idx in range(self.cfg.num_floors):
            floor_base_y = floor_idx * H + self.cfg.floor_thickness
            floor_path = f"{interior_root}/Floor_{floor_idx}"
            self.bridge.define_xform(floor_path)

            wall_h = H - self.cfg.floor_thickness * 2  # 内墙高度
            if wall_h <= 0:
                wall_h = H - self.cfg.floor_thickness
            wall_center_y = floor_base_y + wall_h / 2

            # 中央走廊（沿X方向）
            corridor_path = f"{floor_path}/Corridor"
            self.bridge.create_box_mesh(
                corridor_path,
                width=W - 2 * ext_wt,
                height=0.01,  # 走廊地面标记
                depth=cw,
                translate=(0, floor_base_y + 0.005, 0),
                display_color=(0.75, 0.73, 0.70)
            )
            self.bridge.bind_material(
                corridor_path, f"{root}/Materials/CorridorFloorMaterial"
            )
            stats["num_corridors"] += 1

            # 走廊两侧的隔墙
            for side, z_offset in [("North", cw / 2), ("South", -cw / 2)]:
                wall_path = f"{floor_path}/CorridorWall_{side}"
                self.bridge.create_box_mesh(
                    wall_path,
                    width=W - 2 * ext_wt,
                    height=wall_h,
                    depth=wt,
                    translate=(0, wall_center_y, z_offset),
                    display_color=(0.92, 0.91, 0.88)
                )
                self.bridge.bind_material(
                    wall_path, f"{root}/Materials/InteriorWallMaterial"
                )
                stats["num_interior_walls"] += 1

            # 房间分隔墙（走廊两侧）
            room_depth_north = D / 2 - ext_wt - cw / 2
            room_depth_south = D / 2 - ext_wt - cw / 2

            for side, z_center, room_depth in [
                ("North", cw / 2 + room_depth_north / 2, room_depth_north),
                ("South", -(cw / 2 + room_depth_south / 2), room_depth_south),
            ]:
                # 计算房间数量
                usable_width = W - 2 * ext_wt
                num_rooms = max(1, int(usable_width / self.cfg.room_max_width))
                room_width = usable_width / num_rooms

                for room_idx in range(num_rooms):
                    stats["num_rooms"] += 1

                    # 房间分隔墙（除了最后一个房间的右墙）
                    if room_idx < num_rooms - 1:
                        wall_x = -usable_width / 2 + (room_idx + 1) * room_width
                        sep_wall_path = f"{floor_path}/RoomWall_{side}_{room_idx}"
                        self.bridge.create_box_mesh(
                            sep_wall_path,
                            width=wt,
                            height=wall_h,
                            depth=room_depth,
                            translate=(wall_x, wall_center_y, z_center),
                            display_color=(0.92, 0.91, 0.88)
                        )
                        self.bridge.bind_material(
                            sep_wall_path, f"{root}/Materials/InteriorWallMaterial"
                        )
                        stats["num_interior_walls"] += 1

        return stats

    # =========================================================================
    # 屋顶生成
    # =========================================================================

    def _generate_roof(self, root: str) -> None:
        """生成屋顶。"""
        roof_root = f"{root}/Roof"
        self.bridge.define_scope(roof_root)

        W = self.cfg.building_width
        D = self.cfg.building_depth
        roof_y = self.cfg.num_floors * self.cfg.floor_height + self.cfg.floor_thickness / 2

        if self.cfg.roof_style == "parapet":
            # 女儿墙
            ph = self.cfg.parapet_height
            pt = self.cfg.wall_thickness

            # 前女儿墙
            self.bridge.create_box_mesh(
                f"{roof_root}/Parapet_Front",
                width=W, height=ph, depth=pt,
                translate=(0, roof_y + ph / 2, D / 2),
                display_color=self.cfg.roof_color
            )
            # 后女儿墙
            self.bridge.create_box_mesh(
                f"{roof_root}/Parapet_Back",
                width=W, height=ph, depth=pt,
                translate=(0, roof_y + ph / 2, -D / 2),
                display_color=self.cfg.roof_color
            )
            # 左女儿墙
            self.bridge.create_box_mesh(
                f"{roof_root}/Parapet_Left",
                width=pt, height=ph, depth=D,
                translate=(-W / 2, roof_y + ph / 2, 0),
                display_color=self.cfg.roof_color
            )
            # 右女儿墙
            self.bridge.create_box_mesh(
                f"{roof_root}/Parapet_Right",
                width=pt, height=ph, depth=D,
                translate=(W / 2, roof_y + ph / 2, 0),
                display_color=self.cfg.roof_color
            )

        # 屋顶面板（所有样式都有）
        self.bridge.create_box_mesh(
            f"{roof_root}/RoofSlab",
            width=W + 0.5, height=0.15, depth=D + 0.5,
            translate=(0, roof_y + 0.075, 0),
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

        # 环境光
        self.bridge.create_dome_light(f"{lights_root}/DomeLight", intensity=0.5)

        # 主方向光（模拟太阳）
        total_h = self.cfg.num_floors * self.cfg.floor_height
        self.bridge.create_rect_light(
            f"{lights_root}/SunLight",
            width=self.cfg.building_width * 2,
            height=self.cfg.building_depth * 2,
            intensity=1000.0,
            translate=(self.cfg.building_width, total_h * 1.5, self.cfg.building_depth)
        )
