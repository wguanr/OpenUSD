"""
Building Generator: 办公楼程序化生成器（v2 - 精确建模版）。

核心建模规范：
  ┌─────────────────────────────────────────────┐
  │  建筑外轮廓: X ∈ [-W/2, W/2], Z ∈ [-D/2, D/2]  │
  │                                               │
  │  1. 外墙外表面与建筑外轮廓对齐                    │
  │  2. 墙体厚度(wt)完全向内延伸                      │
  │  3. 四个转角由独立的CornerColumn填充               │
  │  4. 前后墙长度 = W - 2*wt (扣除转角)              │
  │  5. 左右墙长度 = D - 2*wt (扣除转角)              │
  │  6. 楼板外边界与建筑外轮廓齐平                     │
  │  7. 所有模块严格无缝隙、无重叠                     │
  └─────────────────────────────────────────────┘

  俯视图 (Y轴朝上，看向-Y方向):

      -W/2                              +W/2
        ┌──┬────────────────────────┬──┐  +D/2
        │CC│     Front Wall (+Z)    │CC│
        ├──┤                        ├──┤
        │  │                        │  │
        │L │    Interior Space      │R │
        │  │                        │  │
        ├──┤                        ├──┤
        │CC│     Back Wall (-Z)     │CC│
        └──┴────────────────────────┴──┘  -D/2

  CC = Corner Column (wt x wt)
  L  = Left Wall, R = Right Wall
"""

import math
import random
from typing import Dict, Any, List, Tuple, Optional
from pxr import Gf, Vt, Sdf, UsdGeom

from pcg_core.engine import GeneratorBase, BuildingConfig
from pcg_core.usd_bridge import UsdBridge


class BuildingGenerator(GeneratorBase):
    """办公楼程序化生成器（v2 - 精确建模版）。"""

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
            "dimensions": f"{self.cfg.building_width}x{self.cfg.building_depth}x{self.cfg.num_floors * self.cfg.floor_height}m",
        }

        # 预计算关键尺寸
        self._precompute_dimensions()

        with self._time_it("materials"):
            self._create_materials(root)

        with self._time_it("floor_slabs"):
            stats["num_floor_slabs"] = self._generate_floor_slabs(root)

        with self._time_it("corner_columns"):
            stats["num_corner_columns"] = self._generate_corner_columns(root)

        with self._time_it("exterior_walls"):
            wall_info = self._generate_exterior_walls(root)
            stats.update(wall_info)

        with self._time_it("windows"):
            stats["num_windows"] = self._generate_windows(root)

        with self._time_it("doors"):
            stats["num_doors"] = self._generate_entrance_doors(root)

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
        """预计算所有关键尺寸，确保全局一致性。"""
        W = self.cfg.building_width
        D = self.cfg.building_depth
        wt = self.cfg.wall_thickness
        ft = self.cfg.floor_thickness
        H = self.cfg.floor_height

        # 前后墙：扣除两端转角柱的宽度
        self._front_back_wall_length = W - 2 * wt
        # 左右墙：扣除两端转角柱的深度
        self._left_right_wall_length = D - 2 * wt

        # 墙体中心位置（外表面对齐建筑外轮廓，厚度向内）
        self._front_wall_z = D / 2 - wt / 2    # 前墙中心Z
        self._back_wall_z = -(D / 2 - wt / 2)  # 后墙中心Z
        self._left_wall_x = -(W / 2 - wt / 2)  # 左墙中心X
        self._right_wall_x = W / 2 - wt / 2    # 右墙中心X

        # 转角柱位置（四个角，外边对齐建筑外轮廓）
        self._corners = [
            ("NE", (W / 2 - wt / 2,  D / 2 - wt / 2)),   # 右前 (+X, +Z)
            ("NW", (-(W / 2 - wt / 2), D / 2 - wt / 2)),  # 左前 (-X, +Z)
            ("SE", (W / 2 - wt / 2, -(D / 2 - wt / 2))),  # 右后 (+X, -Z)
            ("SW", (-(W / 2 - wt / 2), -(D / 2 - wt / 2))), # 左后 (-X, -Z)
        ]

        # 每层墙体的净高度（楼板之间的净空）
        self._wall_net_height = H - ft

        # 建筑内部净空间
        self._interior_width = W - 2 * wt   # 内部X方向净宽
        self._interior_depth = D - 2 * wt   # 内部Z方向净深

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
        """
        生成所有楼层的楼板。

        楼板外边界与建筑外轮廓齐平 (width=W, depth=D)。
        楼板顶面是每层的地面标高。
        """
        floors_root = f"{root}/FloorSlabs"
        self.bridge.define_scope(floors_root)

        W = self.cfg.building_width
        D = self.cfg.building_depth
        ft = self.cfg.floor_thickness
        H = self.cfg.floor_height

        num_slabs = 0
        for floor_idx in range(self.cfg.num_floors + 1):
            # 楼板顶面标高 = floor_idx * H
            # 楼板中心Y = floor_idx * H - ft/2
            slab_top_y = floor_idx * H
            slab_center_y = slab_top_y - ft / 2

            # 地面层(floor_idx=0)的楼板底面在 -ft，顶面在 0
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
        """
        生成四个转角柱。

        转角柱是 wt x wt 的实心柱体，从地面楼板顶面延伸到屋顶楼板底面。
        它们填充了前后墙与左右墙交接处的空隙，确保建筑外壳水密。

        俯视图中转角柱的位置：
          ┌──┐          ┌──┐
          │NW│          │NE│
          └──┘          └──┘

          ┌──┐          ┌──┐
          │SW│          │SE│
          └──┘          └──┘
        """
        corners_root = f"{root}/CornerColumns"
        self.bridge.define_scope(corners_root)

        wt = self.cfg.wall_thickness
        H = self.cfg.floor_height
        ft = self.cfg.floor_thickness
        num_floors = self.cfg.num_floors

        # 柱体从地面楼板顶面(Y=0)到屋顶楼板底面(Y=num_floors*H - ft)
        column_bottom_y = 0.0
        column_top_y = num_floors * H - ft
        column_height = column_top_y - column_bottom_y
        column_center_y = (column_bottom_y + column_top_y) / 2

        count = 0
        for name, (cx, cz) in self._corners:
            col_path = f"{corners_root}/Corner_{name}"
            self.bridge.create_box_mesh(
                col_path,
                width=wt, height=column_height, depth=wt,
                translate=(cx, column_center_y, cz),
                display_color=(0.80, 0.77, 0.73)
            )
            self.bridge.bind_material(col_path, f"{root}/Materials/CornerMaterial")
            count += 1

        return count

    # =========================================================================
    # 外墙生成
    # =========================================================================

    def _generate_exterior_walls(self, root: str) -> Dict[str, int]:
        """
        生成所有外墙（带窗户孔洞）。

        关键规范：
        - 前后墙长度 = W - 2*wt，位于两个转角柱之间
        - 左右墙长度 = D - 2*wt，位于两个转角柱之间
        - 墙体外表面与建筑外轮廓对齐，厚度向内
        - 左右墙不使用旋转，而是直接用正确的width/depth参数
        """
        walls_root = f"{root}/ExteriorWalls"
        self.bridge.define_scope(walls_root)

        wt = self.cfg.wall_thickness
        H = self.cfg.floor_height
        ft = self.cfg.floor_thickness

        total_walls = 0
        total_holes = 0

        for floor_idx in range(self.cfg.num_floors):
            # 每层墙体：从楼板顶面到上层楼板底面
            wall_bottom_y = floor_idx * H          # 本层楼板顶面
            wall_top_y = (floor_idx + 1) * H - ft  # 上层楼板底面
            wall_h = wall_top_y - wall_bottom_y
            wall_center_y = (wall_bottom_y + wall_top_y) / 2

            floor_path = f"{walls_root}/Floor_{floor_idx}"
            self.bridge.define_xform(floor_path)

            # --- 前墙 (+Z面) ---
            front_holes = self._calc_wall_holes(self._front_back_wall_length, wall_h)
            self.bridge.create_wall_mesh(
                f"{floor_path}/Wall_Front",
                width=self._front_back_wall_length,
                height=wall_h,
                thickness=wt,
                holes=front_holes,
                translate=(0, wall_center_y, self._front_wall_z),
                display_color=self.cfg.wall_color
            )
            self.bridge.bind_material(f"{floor_path}/Wall_Front", f"{root}/Materials/WallMaterial")
            total_walls += 1
            total_holes += len(front_holes)

            # --- 后墙 (-Z面) ---
            back_holes = self._calc_wall_holes(self._front_back_wall_length, wall_h)
            self.bridge.create_wall_mesh(
                f"{floor_path}/Wall_Back",
                width=self._front_back_wall_length,
                height=wall_h,
                thickness=wt,
                holes=back_holes,
                translate=(0, wall_center_y, self._back_wall_z),
                display_color=self.cfg.wall_color
            )
            self.bridge.bind_material(f"{floor_path}/Wall_Back", f"{root}/Materials/WallMaterial")
            total_walls += 1
            total_holes += len(back_holes)

            # --- 左墙 (-X面) ---
            # 不使用旋转！直接创建一个 depth=墙长, width=wt 的墙体
            left_holes = self._calc_wall_holes(self._left_right_wall_length, wall_h)
            self._create_side_wall(
                f"{floor_path}/Wall_Left",
                wall_length=self._left_right_wall_length,
                wall_height=wall_h,
                wall_thickness=wt,
                holes=left_holes,
                center_x=self._left_wall_x,
                center_y=wall_center_y,
                center_z=0,
                facing="left",
            )
            self.bridge.bind_material(f"{floor_path}/Wall_Left", f"{root}/Materials/WallMaterial")
            total_walls += 1
            total_holes += len(left_holes)

            # --- 右墙 (+X面) ---
            right_holes = self._calc_wall_holes(self._left_right_wall_length, wall_h)
            self._create_side_wall(
                f"{floor_path}/Wall_Right",
                wall_length=self._left_right_wall_length,
                wall_height=wall_h,
                wall_thickness=wt,
                holes=right_holes,
                center_x=self._right_wall_x,
                center_y=wall_center_y,
                center_z=0,
                facing="right",
            )
            self.bridge.bind_material(f"{floor_path}/Wall_Right", f"{root}/Materials/WallMaterial")
            total_walls += 1
            total_holes += len(right_holes)

        return {"num_walls": total_walls, "num_window_holes": total_holes}

    def _create_side_wall(self, path: str, wall_length: float, wall_height: float,
                          wall_thickness: float, holes: List[Dict],
                          center_x: float, center_y: float, center_z: float,
                          facing: str):
        """
        创建侧墙（左墙或右墙），沿Z方向延伸。

        与前后墙不同，侧墙的"宽度"方向是Z轴。
        我们直接构建正确朝向的几何体，不使用旋转变换。

        Args:
            facing: "left" 表示法线朝-X, "right" 表示法线朝+X
        """
        mesh = UsdGeom.Mesh.Define(self.bridge.stage, path)
        ht = wall_thickness / 2  # 半厚度（X方向）
        hl = wall_length / 2     # 半长度（Z方向）
        hh = wall_height / 2     # 半高度（Y方向）

        all_points = []
        all_fvc = []
        all_fvi = []

        # 排序孔洞（从-Z到+Z）
        sorted_holes = sorted(holes, key=lambda h: h["x"] - h["w"] / 2)

        # 外表面和内表面（沿X方向）
        if facing == "left":
            x_outer = -ht  # 外表面（朝-X）
            x_inner = ht   # 内表面
        else:
            x_outer = ht   # 外表面（朝+X）
            x_inner = -ht  # 内表面

        # 生成外表面（带孔洞）
        base_idx = len(all_points)
        pts, fvc, fvi = self._gen_side_wall_face(
            hl, hh, sorted_holes, x_outer, facing, "outer", base_idx
        )
        all_points.extend(pts)
        all_fvc.extend(fvc)
        all_fvi.extend(fvi)

        # 生成内表面（带孔洞）
        base_idx = len(all_points)
        pts, fvc, fvi = self._gen_side_wall_face(
            hl, hh, sorted_holes, x_inner, facing, "inner", base_idx
        )
        all_points.extend(pts)
        all_fvc.extend(fvc)
        all_fvi.extend(fvi)

        # 顶面、底面、前端面、后端面
        base_idx = len(all_points)

        # 顶面
        all_points.extend([
            Gf.Vec3f(x_outer, hh, -hl), Gf.Vec3f(x_outer, hh, hl),
            Gf.Vec3f(x_inner, hh, hl), Gf.Vec3f(x_inner, hh, -hl),
        ])
        all_fvc.append(4)
        if facing == "left":
            all_fvi.extend([base_idx, base_idx+3, base_idx+2, base_idx+1])
        else:
            all_fvi.extend([base_idx, base_idx+1, base_idx+2, base_idx+3])
        base_idx += 4

        # 底面
        all_points.extend([
            Gf.Vec3f(x_outer, -hh, -hl), Gf.Vec3f(x_outer, -hh, hl),
            Gf.Vec3f(x_inner, -hh, hl), Gf.Vec3f(x_inner, -hh, -hl),
        ])
        all_fvc.append(4)
        if facing == "left":
            all_fvi.extend([base_idx, base_idx+1, base_idx+2, base_idx+3])
        else:
            all_fvi.extend([base_idx, base_idx+3, base_idx+2, base_idx+1])
        base_idx += 4

        # 前端面 (+Z端)
        all_points.extend([
            Gf.Vec3f(x_outer, -hh, hl), Gf.Vec3f(x_outer, hh, hl),
            Gf.Vec3f(x_inner, hh, hl), Gf.Vec3f(x_inner, -hh, hl),
        ])
        all_fvc.append(4)
        if facing == "left":
            all_fvi.extend([base_idx, base_idx+1, base_idx+2, base_idx+3])
        else:
            all_fvi.extend([base_idx, base_idx+3, base_idx+2, base_idx+1])
        base_idx += 4

        # 后端面 (-Z端)
        all_points.extend([
            Gf.Vec3f(x_outer, -hh, -hl), Gf.Vec3f(x_outer, hh, -hl),
            Gf.Vec3f(x_inner, hh, -hl), Gf.Vec3f(x_inner, -hh, -hl),
        ])
        all_fvc.append(4)
        if facing == "left":
            all_fvi.extend([base_idx, base_idx+3, base_idx+2, base_idx+1])
        else:
            all_fvi.extend([base_idx, base_idx+1, base_idx+2, base_idx+3])
        base_idx += 4

        # 孔洞内壁（连接外表面和内表面）
        for hole in sorted_holes:
            hz, hy = hole["x"], hole["y"]  # x在侧墙中映射到Z方向
            hw_h, hh_h = hole["w"] / 2, hole["h"] / 2

            edges = [
                # 底边 (Y = hy - hh_h)
                [(x_outer, hy - hh_h, hz - hw_h), (x_outer, hy - hh_h, hz + hw_h),
                 (x_inner, hy - hh_h, hz + hw_h), (x_inner, hy - hh_h, hz - hw_h)],
                # 顶边 (Y = hy + hh_h)
                [(x_outer, hy + hh_h, hz - hw_h), (x_outer, hy + hh_h, hz + hw_h),
                 (x_inner, hy + hh_h, hz + hw_h), (x_inner, hy + hh_h, hz - hw_h)],
                # 左边 (Z = hz - hw_h)
                [(x_outer, hy - hh_h, hz - hw_h), (x_outer, hy + hh_h, hz - hw_h),
                 (x_inner, hy + hh_h, hz - hw_h), (x_inner, hy - hh_h, hz - hw_h)],
                # 右边 (Z = hz + hw_h)
                [(x_outer, hy - hh_h, hz + hw_h), (x_outer, hy + hh_h, hz + hw_h),
                 (x_inner, hy + hh_h, hz + hw_h), (x_inner, hy - hh_h, hz + hw_h)],
            ]
            for j, edge in enumerate(edges):
                idx = len(all_points)
                for pt in edge:
                    all_points.append(Gf.Vec3f(*pt))
                all_fvc.append(4)
                # 法线朝向孔洞内部
                if facing == "left":
                    if j == 0:
                        all_fvi.extend([idx, idx+1, idx+2, idx+3])
                    elif j == 1:
                        all_fvi.extend([idx, idx+3, idx+2, idx+1])
                    elif j == 2:
                        all_fvi.extend([idx, idx+3, idx+2, idx+1])
                    else:
                        all_fvi.extend([idx, idx+1, idx+2, idx+3])
                else:
                    if j == 0:
                        all_fvi.extend([idx, idx+3, idx+2, idx+1])
                    elif j == 1:
                        all_fvi.extend([idx, idx+1, idx+2, idx+3])
                    elif j == 2:
                        all_fvi.extend([idx, idx+1, idx+2, idx+3])
                    else:
                        all_fvi.extend([idx, idx+3, idx+2, idx+1])

        mesh.GetPointsAttr().Set(Vt.Vec3fArray(all_points))
        mesh.GetFaceVertexCountsAttr().Set(Vt.IntArray(all_fvc))
        mesh.GetFaceVertexIndicesAttr().Set(Vt.IntArray(all_fvi))
        mesh.GetSubdivisionSchemeAttr().Set("none")

        # 设置位置
        xformable = UsdGeom.Xformable(mesh.GetPrim())
        xformable.AddTranslateOp().Set(Gf.Vec3d(center_x, center_y, center_z))

        mesh.GetDisplayColorAttr().Set(Vt.Vec3fArray([Gf.Vec3f(*self.cfg.wall_color)]))

    def _gen_side_wall_face(self, half_length, half_height, holes, x_val,
                            facing, surface_type, base_idx):
        """生成侧墙的一个面（外表面或内表面），带孔洞。面在YZ平面上。"""
        points = []
        fvc = []
        fvi = []

        # 分割线
        z_splits = sorted(set([-half_length, half_length] +
            [h["x"] - h["w"]/2 for h in holes] + [h["x"] + h["w"]/2 for h in holes]))
        y_splits = sorted(set([-half_height, half_height] +
            [h["y"] - h["h"]/2 for h in holes] + [h["y"] + h["h"]/2 for h in holes]))

        idx_offset = base_idx
        for i in range(len(y_splits) - 1):
            for j in range(len(z_splits) - 1):
                z0, z1 = z_splits[j], z_splits[j+1]
                y0, y1 = y_splits[i], y_splits[i+1]

                cz, cy = (z0+z1)/2, (y0+y1)/2
                in_hole = any(
                    (h["x"]-h["w"]/2) <= cz <= (h["x"]+h["w"]/2) and
                    (h["y"]-h["h"]/2) <= cy <= (h["y"]+h["h"]/2)
                    for h in holes
                )

                if not in_hole:
                    idx = idx_offset + len(points)
                    points.extend([
                        Gf.Vec3f(x_val, y0, z0), Gf.Vec3f(x_val, y0, z1),
                        Gf.Vec3f(x_val, y1, z1), Gf.Vec3f(x_val, y1, z0),
                    ])
                    fvc.append(4)
                    # 法线方向：外表面朝外，内表面朝内
                    if (facing == "left" and surface_type == "outer") or \
                       (facing == "right" and surface_type == "inner"):
                        fvi.extend([idx, idx+3, idx+2, idx+1])  # 法线朝-X
                    else:
                        fvi.extend([idx, idx+1, idx+2, idx+3])  # 法线朝+X

        return points, fvc, fvi

    def _calc_wall_holes(self, wall_length: float, wall_height: float) -> List[Dict[str, float]]:
        """
        计算墙面上的窗户孔洞位置。

        孔洞坐标相对于墙体中心，X方向沿墙面宽度，Y方向沿高度。
        """
        holes = []
        ww = self.cfg.window_width
        wh = self.cfg.window_height
        spacing = self.cfg.window_spacing
        sill = self.cfg.window_sill_height

        # 窗户中心Y（相对于墙体中心）
        window_cy = sill + wh / 2 - wall_height / 2
        if window_cy + wh / 2 > wall_height / 2:
            return holes

        # 可用宽度（两端留半个间距的边距）
        usable = wall_length - spacing
        num_win = max(0, int(usable / spacing))
        if num_win <= 0:
            return holes

        total_span = (num_win - 1) * spacing if num_win > 1 else 0
        start_x = -total_span / 2

        for i in range(num_win):
            holes.append({
                "x": start_x + i * spacing,
                "y": window_cy,
                "w": ww,
                "h": wh,
            })

        return holes

    # =========================================================================
    # 窗户生成（PointInstancer）
    # =========================================================================

    def _generate_windows(self, root: str) -> int:
        """使用PointInstancer批量生成所有窗户玻璃面板。"""
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

        if not self.cfg.use_instancing:
            return self._generate_windows_individual(root, windows_root)

        positions = []
        orientations = []
        proto_indices = []

        wt = self.cfg.wall_thickness
        H = self.cfg.floor_height
        ft = self.cfg.floor_thickness
        W = self.cfg.building_width
        D = self.cfg.building_depth

        for floor_idx in range(self.cfg.num_floors):
            wall_bottom_y = floor_idx * H
            sill = self.cfg.window_sill_height
            win_cy = wall_bottom_y + sill + self.cfg.window_height / 2

            # 前墙窗户：Z = D/2 - wt/2 (墙体中心，玻璃嵌入墙内)
            front_z = D / 2 - wt / 2
            for hole in self._calc_wall_holes(self._front_back_wall_length, self._wall_net_height):
                positions.append((hole["x"], win_cy, front_z))
                orientations.append((1.0, 0.0, 0.0, 0.0))
                proto_indices.append(0)

            # 后墙窗户：Z = -(D/2 - wt/2)
            back_z = -(D / 2 - wt / 2)
            for hole in self._calc_wall_holes(self._front_back_wall_length, self._wall_net_height):
                positions.append((hole["x"], win_cy, back_z))
                orientations.append((0.0, 0.0, 1.0, 0.0))
                proto_indices.append(0)

            # 左墙窗户：X = -(W/2 - wt/2)，窗户沿Z方向排列
            left_x = -(W / 2 - wt / 2)
            for hole in self._calc_wall_holes(self._left_right_wall_length, self._wall_net_height):
                positions.append((left_x, win_cy, hole["x"]))
                orientations.append((0.707, 0.0, 0.707, 0.0))
                proto_indices.append(0)

            # 右墙窗户：X = W/2 - wt/2
            right_x = W / 2 - wt / 2
            for hole in self._calc_wall_holes(self._left_right_wall_length, self._wall_net_height):
                positions.append((right_x, win_cy, hole["x"]))
                orientations.append((0.707, 0.0, -0.707, 0.0))
                proto_indices.append(0)

        if not positions:
            return 0

        self.bridge.create_point_instancer(
            f"{windows_root}/WindowInstancer",
            prototype_paths=[glass_path],
            positions=positions,
            proto_indices=proto_indices,
            orientations=orientations,
        )

        return len(positions)

    def _generate_windows_individual(self, root: str, windows_root: str) -> int:
        """非实例化模式（用于性能对比）。"""
        count = 0
        W = self.cfg.building_width
        D = self.cfg.building_depth
        H = self.cfg.floor_height

        for floor_idx in range(self.cfg.num_floors):
            wall_bottom_y = floor_idx * H
            sill = self.cfg.window_sill_height
            win_cy = wall_bottom_y + sill + self.cfg.window_height / 2

            for hole in self._calc_wall_holes(self._front_back_wall_length, self._wall_net_height):
                path = f"{windows_root}/Win_{count}"
                self.bridge.create_box_mesh(path,
                    width=self.cfg.window_width, height=self.cfg.window_height, depth=0.02,
                    translate=(hole["x"], win_cy, D/2 - self.cfg.wall_thickness/2),
                    display_color=self.cfg.window_color)
                count += 1

            for hole in self._calc_wall_holes(self._front_back_wall_length, self._wall_net_height):
                path = f"{windows_root}/Win_{count}"
                self.bridge.create_box_mesh(path,
                    width=self.cfg.window_width, height=self.cfg.window_height, depth=0.02,
                    translate=(hole["x"], win_cy, -(D/2 - self.cfg.wall_thickness/2)),
                    display_color=self.cfg.window_color)
                count += 1

        return count

    def _create_window_frame(self, path: str) -> None:
        """创建窗框原型。"""
        ft = 0.05
        ww = self.cfg.window_width
        wh = self.cfg.window_height
        self.bridge.define_xform(path)
        for name, w, h, d, tx, ty in [
            ("Top", ww, ft, ft, 0, wh/2-ft/2),
            ("Bot", ww, ft, ft, 0, -wh/2+ft/2),
            ("Left", ft, wh, ft, -ww/2+ft/2, 0),
            ("Right", ft, wh, ft, ww/2-ft/2, 0),
        ]:
            self.bridge.create_box_mesh(f"{path}/{name}", width=w, height=h, depth=d,
                translate=(tx, ty, 0), display_color=(0.3, 0.3, 0.3))

    # =========================================================================
    # 入口门
    # =========================================================================

    def _generate_entrance_doors(self, root: str) -> int:
        """生成建筑入口门。"""
        doors_root = f"{root}/Doors"
        self.bridge.define_scope(doors_root)

        D = self.cfg.building_depth
        wt = self.cfg.wall_thickness
        door_y = self.cfg.door_height / 2  # 门底面在Y=0（地面楼板顶面）

        num_doors = 0
        for i in range(self.cfg.num_entrances):
            offset = 0 if self.cfg.num_entrances == 1 else (i - (self.cfg.num_entrances - 1) / 2) * 5
            door_path = f"{doors_root}/Entrance_{i}"
            self.bridge.create_box_mesh(
                door_path,
                width=self.cfg.door_width,
                height=self.cfg.door_height,
                depth=wt + 0.02,
                translate=(offset, door_y, D / 2 - wt / 2),
                display_color=(0.4, 0.25, 0.15)
            )
            self.bridge.bind_material(door_path, f"{root}/Materials/DoorMaterial")
            num_doors += 1

        return num_doors

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

        # 内部空间边界
        inner_w = self._interior_width
        inner_d = self._interior_depth

        for floor_idx in range(self.cfg.num_floors):
            floor_base_y = floor_idx * H
            wall_h = H - ft
            wall_cy = floor_base_y + wall_h / 2

            floor_path = f"{interior_root}/Floor_{floor_idx}"
            self.bridge.define_xform(floor_path)

            # 走廊地面标记
            corridor_path = f"{floor_path}/Corridor"
            self.bridge.create_box_mesh(
                corridor_path,
                width=inner_w, height=0.01, depth=cw,
                translate=(0, floor_base_y + 0.005, 0),
                display_color=(0.75, 0.73, 0.70)
            )
            self.bridge.bind_material(corridor_path, f"{root}/Materials/CorridorFloorMaterial")
            stats["num_corridors"] += 1

            # 走廊两侧隔墙
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

            # 房间分隔墙
            room_depth_each = (inner_d - cw) / 2 - iwt  # 每侧房间深度

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
        ft = self.cfg.floor_thickness
        num_floors = self.cfg.num_floors

        # 屋顶楼板顶面标高
        roof_slab_top = num_floors * H

        if self.cfg.roof_style == "parapet":
            ph = self.cfg.parapet_height
            parapet_bottom = roof_slab_top
            parapet_cy = parapet_bottom + ph / 2

            # 前女儿墙（与前墙对齐，长度=W-2*wt）
            self.bridge.create_box_mesh(
                f"{roof_root}/Parapet_Front",
                width=self._front_back_wall_length, height=ph, depth=wt,
                translate=(0, parapet_cy, self._front_wall_z),
                display_color=self.cfg.roof_color
            )
            # 后女儿墙
            self.bridge.create_box_mesh(
                f"{roof_root}/Parapet_Back",
                width=self._front_back_wall_length, height=ph, depth=wt,
                translate=(0, parapet_cy, self._back_wall_z),
                display_color=self.cfg.roof_color
            )
            # 左女儿墙
            self.bridge.create_box_mesh(
                f"{roof_root}/Parapet_Left",
                width=wt, height=ph, depth=self._left_right_wall_length,
                translate=(self._left_wall_x, parapet_cy, 0),
                display_color=self.cfg.roof_color
            )
            # 右女儿墙
            self.bridge.create_box_mesh(
                f"{roof_root}/Parapet_Right",
                width=wt, height=ph, depth=self._left_right_wall_length,
                translate=(self._right_wall_x, parapet_cy, 0),
                display_color=self.cfg.roof_color
            )
            # 女儿墙转角柱
            for name, (cx, cz) in self._corners:
                self.bridge.create_box_mesh(
                    f"{roof_root}/ParapetCorner_{name}",
                    width=wt, height=ph, depth=wt,
                    translate=(cx, parapet_cy, cz),
                    display_color=self.cfg.roof_color
                )

        # 屋顶面板（略微外挑）
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
