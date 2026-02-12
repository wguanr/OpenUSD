"""
Wall Segments: 具体墙段模块实现。

所有墙段在局部坐标系中生成几何体：
  - X: [0, length]  沿墙段长度
  - Y: [0, height]  沿墙段高度
  - Z: [0, +thickness]  厚度向内（外表面Z=0，内表面Z=+thickness）

旋转后的世界坐标映射：
  - 局部+X → 边方向 (edge direction)
  - 局部+Z → 建筑内侧 (inward normal)
  - 局部-Z → 建筑外侧 (outward normal)

因此外表面(Z=0)对齐建筑外轮廓线，内表面(Z=+T)朝向建筑内部。

每种墙段类型通过 @IWallSegment.register("TypeName") 装饰器注册，
可通过 IWallSegment.create("TypeName", ...) 工厂方法实例化。
"""

from typing import List, Tuple, Dict, Any, Optional
from pxr import Gf, Vt, UsdGeom
import math

from .wall_module import IWallSegment, WallSegmentResult, Connector

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .usd_bridge import UsdBridge


# =============================================================================
# SolidWall: 实心墙（无开口）
# =============================================================================

@IWallSegment.register("SolidWall")
class SolidWallSegment(IWallSegment):
    """
    实心墙段：无任何开口的纯墙体。

    用途：建筑侧面、防火墙、隔墙等不需要开口的位置。
    """

    def __init__(self, length: float, height: float, thickness: float,
                 name: str = "solid", **kwargs):
        super().__init__(length, height, thickness, name, **kwargs)

    def generate_usd(self, bridge: 'UsdBridge', path: str) -> WallSegmentResult:
        mesh = UsdGeom.Mesh.Define(bridge.stage, path)
        L, H, T = self.length, self.height, self.thickness

        # 8个顶点，外表面Z=0，内表面Z=+T
        points = Vt.Vec3fArray([
            Gf.Vec3f(0, 0, 0),     Gf.Vec3f(L, 0, 0),      # 0:外底左, 1:外底右
            Gf.Vec3f(L, H, 0),     Gf.Vec3f(0, H, 0),      # 2:外顶右, 3:外顶左
            Gf.Vec3f(0, 0, T),     Gf.Vec3f(L, 0, T),      # 4:内底左, 5:内底右
            Gf.Vec3f(L, H, T),     Gf.Vec3f(0, H, T),      # 6:内顶右, 7:内顶左
        ])

        fvc = Vt.IntArray([4, 4, 4, 4, 4, 4])
        fvi = Vt.IntArray([
            0, 3, 2, 1,   # 外面 (Z=0) 法线朝-Z（朝外）
            4, 5, 6, 7,   # 内面 (Z=+T) 法线朝+Z（朝内）
            0, 4, 7, 3,   # 左端面 (-X) 法线朝-X
            1, 2, 6, 5,   # 右端面 (+X) 法线朝+X
            3, 7, 6, 2,   # 顶面 (+Y) 法线朝+Y
            0, 1, 5, 4,   # 底面 (-Y) 法线朝-Y
        ])

        mesh.GetPointsAttr().Set(points)
        mesh.GetFaceVertexCountsAttr().Set(fvc)
        mesh.GetFaceVertexIndicesAttr().Set(fvi)
        mesh.GetSubdivisionSchemeAttr().Set("none")
        mesh.GetExtentAttr().Set(Vt.Vec3fArray([Gf.Vec3f(0, 0, 0), Gf.Vec3f(L, H, T)]))

        color = self.extra_params.get("color", (0.85, 0.82, 0.78))
        mesh.GetDisplayColorAttr().Set(Vt.Vec3fArray([Gf.Vec3f(*color)]))

        return WallSegmentResult(stats={"type": "SolidWall", "length": self.length})


# =============================================================================
# WindowWall: 带窗户的墙段
# =============================================================================

@IWallSegment.register("WindowWall")
class WindowWallSegment(IWallSegment):
    """
    窗墙段：带有规则排列窗户的墙体。

    窗户参数：
      - window_width: 窗户宽度
      - window_height: 窗户高度
      - window_sill_height: 窗台高度（从墙段底部到窗户底边）
      - window_spacing: 窗户间距（中心到中心）
    """

    def __init__(self, length: float, height: float, thickness: float,
                 name: str = "window_wall",
                 window_width: float = 1.8,
                 window_height: float = 1.5,
                 window_sill_height: float = 0.9,
                 window_spacing: float = 3.0,
                 **kwargs):
        super().__init__(length, height, thickness, name, **kwargs)
        self.window_width = window_width
        self.window_height = window_height
        self.window_sill_height = window_sill_height
        self.window_spacing = window_spacing

    def _calc_window_positions(self) -> List[Dict[str, float]]:
        """计算窗户在局部坐标系中的位置。"""
        holes = []
        ww, wh = self.window_width, self.window_height
        sill = self.window_sill_height
        spacing = self.window_spacing

        # 窗户中心Y
        win_cy = sill + wh / 2
        if win_cy + wh / 2 > self.height:
            return holes

        # 可用宽度（两端留半个间距的边距）
        usable = self.length - spacing
        num_win = max(0, int(usable / spacing))
        if num_win <= 0:
            return holes

        total_span = (num_win - 1) * spacing if num_win > 1 else 0
        start_x = self.length / 2 - total_span / 2

        for i in range(num_win):
            holes.append({
                "cx": start_x + i * spacing,
                "cy": win_cy,
                "w": ww,
                "h": wh,
            })
        return holes

    def generate_usd(self, bridge: 'UsdBridge', path: str) -> WallSegmentResult:
        mesh = UsdGeom.Mesh.Define(bridge.stage, path)
        L, H, T = self.length, self.height, self.thickness
        holes = self._calc_window_positions()

        all_points = []
        all_fvc = []
        all_fvi = []

        # --- 外表面 (Z=0) 和 内表面 (Z=+T) ---
        for z_val, is_outer in [(0.0, True), (T, False)]:
            base = len(all_points)
            pts, fvc, fvi = self._gen_face_with_holes(L, H, holes, z_val, is_outer, base)
            all_points.extend(pts)
            all_fvc.extend(fvc)
            all_fvi.extend(fvi)

        # --- 顶面, 底面, 左端面, 右端面 ---
        self._add_border_faces(all_points, all_fvc, all_fvi, L, H, T)

        # --- 窗户孔洞内壁 ---
        for hole in holes:
            self._add_hole_inner_walls(all_points, all_fvc, all_fvi, hole, T)

        mesh.GetPointsAttr().Set(Vt.Vec3fArray(all_points))
        mesh.GetFaceVertexCountsAttr().Set(Vt.IntArray(all_fvc))
        mesh.GetFaceVertexIndicesAttr().Set(Vt.IntArray(all_fvi))
        mesh.GetSubdivisionSchemeAttr().Set("none")
        mesh.GetExtentAttr().Set(Vt.Vec3fArray([Gf.Vec3f(0, 0, 0), Gf.Vec3f(L, H, T)]))

        color = self.extra_params.get("color", (0.85, 0.82, 0.78))
        mesh.GetDisplayColorAttr().Set(Vt.Vec3fArray([Gf.Vec3f(*color)]))

        # 返回窗户位置（局部坐标，Z=+T/2 即墙体中心）
        win_positions = [(h["cx"], h["cy"], T / 2) for h in holes]
        return WallSegmentResult(
            window_positions=win_positions,
            stats={"type": "WindowWall", "length": self.length, "num_windows": len(holes)}
        )

    def _gen_face_with_holes(self, L, H, holes, z_val, is_outer, base_idx):
        """生成带孔洞的墙面（行列分割法）。"""
        points, fvc, fvi = [], [], []

        x_splits = sorted(set([0, L] + [h["cx"]-h["w"]/2 for h in holes] + [h["cx"]+h["w"]/2 for h in holes]))
        y_splits = sorted(set([0, H] + [h["cy"]-h["h"]/2 for h in holes] + [h["cy"]+h["h"]/2 for h in holes]))

        for i in range(len(y_splits) - 1):
            for j in range(len(x_splits) - 1):
                x0, x1 = x_splits[j], x_splits[j+1]
                y0, y1 = y_splits[i], y_splits[i+1]
                cx, cy = (x0+x1)/2, (y0+y1)/2

                in_hole = any(
                    (h["cx"]-h["w"]/2) <= cx <= (h["cx"]+h["w"]/2) and
                    (h["cy"]-h["h"]/2) <= cy <= (h["cy"]+h["h"]/2)
                    for h in holes
                )
                if not in_hole:
                    idx = base_idx + len(points)
                    points.extend([
                        Gf.Vec3f(x0, y0, z_val), Gf.Vec3f(x1, y0, z_val),
                        Gf.Vec3f(x1, y1, z_val), Gf.Vec3f(x0, y1, z_val),
                    ])
                    fvc.append(4)
                    if is_outer:
                        # 外面(Z=0): 法线朝-Z（朝外），winding CW from +Z
                        fvi.extend([idx, idx+3, idx+2, idx+1])
                    else:
                        # 内面(Z=+T): 法线朝+Z（朝内），winding CCW from +Z
                        fvi.extend([idx, idx+1, idx+2, idx+3])

        return points, fvc, fvi

    def _add_border_faces(self, pts, fvc, fvi, L, H, T):
        """添加墙段的顶面、底面、左端面、右端面。"""
        borders = [
            # 顶面 (Y=H): 法线朝+Y
            ([(0,H,0), (L,H,0), (L,H,T), (0,H,T)], [0,1,2,3]),
            # 底面 (Y=0): 法线朝-Y
            ([(0,0,0), (L,0,0), (L,0,T), (0,0,T)], [0,3,2,1]),
            # 左端面 (X=0): 法线朝-X
            ([(0,0,0), (0,H,0), (0,H,T), (0,0,T)], [0,3,2,1]),
            # 右端面 (X=L): 法线朝+X
            ([(L,0,0), (L,H,0), (L,H,T), (L,0,T)], [0,1,2,3]),
        ]
        for corners, winding in borders:
            idx = len(pts)
            for c in corners:
                pts.append(Gf.Vec3f(*c))
            fvc.append(4)
            fvi.extend([idx + w for w in winding])

    def _add_hole_inner_walls(self, pts, fvc, fvi, hole, T):
        """添加窗户孔洞的四个内壁面。"""
        cx, cy, w, h = hole["cx"], hole["cy"], hole["w"], hole["h"]
        hw, hh = w/2, h/2
        x0, x1 = cx - hw, cx + hw
        y0, y1 = cy - hh, cy + hh

        inner_faces = [
            # 底边内壁 (Y=y0平面, 法线朝-Y)
            ([(x0,y0,0), (x1,y0,0), (x1,y0,T), (x0,y0,T)], [0,3,2,1]),
            # 顶边内壁 (Y=y1平面, 法线朝+Y)
            ([(x0,y1,0), (x1,y1,0), (x1,y1,T), (x0,y1,T)], [0,1,2,3]),
            # 左边内壁 (X=x0平面, 法线朝-X)
            ([(x0,y0,0), (x0,y1,0), (x0,y1,T), (x0,y0,T)], [0,3,2,1]),
            # 右边内壁 (X=x1平面, 法线朝+X)
            ([(x1,y0,0), (x1,y1,0), (x1,y1,T), (x1,y0,T)], [0,1,2,3]),
        ]
        for corners, winding in inner_faces:
            idx = len(pts)
            for c in corners:
                pts.append(Gf.Vec3f(*c))
            fvc.append(4)
            fvi.extend([idx + w for w in winding])


# =============================================================================
# DoorWall: 带门的墙段
# =============================================================================

@IWallSegment.register("DoorWall")
class DoorWallSegment(IWallSegment):
    """
    门墙段：底部有门洞的墙体。

    门洞从墙段底部(Y=0)开始，高度为 door_height。
    门洞水平居中于墙段。
    """

    def __init__(self, length: float, height: float, thickness: float,
                 name: str = "door_wall",
                 door_width: float = 1.5,
                 door_height: float = 2.4,
                 **kwargs):
        super().__init__(length, height, thickness, name, **kwargs)
        self.door_width = door_width
        self.door_height = door_height

    def generate_usd(self, bridge: 'UsdBridge', path: str) -> WallSegmentResult:
        mesh = UsdGeom.Mesh.Define(bridge.stage, path)
        L, H, T = self.length, self.height, self.thickness
        dw, dh = self.door_width, self.door_height

        # 门洞作为一个从底部开始的孔洞
        hole = {
            "cx": L / 2,
            "cy": dh / 2,
            "w": dw,
            "h": dh,
        }
        holes = [hole]

        all_points = []
        all_fvc = []
        all_fvi = []

        # 外表面和内表面
        for z_val, is_outer in [(0.0, True), (T, False)]:
            base = len(all_points)
            pts, fvc, fvi = WindowWallSegment._gen_face_with_holes(
                self, L, H, holes, z_val, is_outer, base)
            all_points.extend(pts)
            all_fvc.extend(fvc)
            all_fvi.extend(fvi)

        # 边框面
        WindowWallSegment._add_border_faces(self, all_points, all_fvc, all_fvi, L, H, T)

        # 门洞内壁（只有顶边和两个侧边，底边是地面所以不需要）
        cx_door, dw2, dh2 = L/2, dw/2, dh
        x0, x1 = cx_door - dw2, cx_door + dw2

        inner_faces = [
            # 顶边内壁 (Y=dh): 法线朝+Y
            ([(x0,dh,0), (x1,dh,0), (x1,dh,T), (x0,dh,T)], [0,1,2,3]),
            # 左边内壁 (X=x0): 法线朝-X
            ([(x0,0,0), (x0,dh,0), (x0,dh,T), (x0,0,T)], [0,3,2,1]),
            # 右边内壁 (X=x1): 法线朝+X
            ([(x1,0,0), (x1,dh,0), (x1,dh,T), (x1,0,T)], [0,1,2,3]),
        ]
        for corners, winding in inner_faces:
            idx = len(all_points)
            for c in corners:
                all_points.append(Gf.Vec3f(*c))
            all_fvc.append(4)
            all_fvi.extend([idx + w for w in winding])

        mesh.GetPointsAttr().Set(Vt.Vec3fArray(all_points))
        mesh.GetFaceVertexCountsAttr().Set(Vt.IntArray(all_fvc))
        mesh.GetFaceVertexIndicesAttr().Set(Vt.IntArray(all_fvi))
        mesh.GetSubdivisionSchemeAttr().Set("none")
        mesh.GetExtentAttr().Set(Vt.Vec3fArray([Gf.Vec3f(0, 0, 0), Gf.Vec3f(L, H, T)]))

        color = self.extra_params.get("color", (0.85, 0.82, 0.78))
        mesh.GetDisplayColorAttr().Set(Vt.Vec3fArray([Gf.Vec3f(*color)]))

        return WallSegmentResult(
            door_positions=[(L/2, dh/2, T/2)],
            stats={"type": "DoorWall", "length": self.length, "num_doors": 1}
        )


# =============================================================================
# CurtainWall: 玻璃幕墙
# =============================================================================

@IWallSegment.register("CurtainWall")
class CurtainWallSegment(IWallSegment):
    """
    玻璃幕墙段：全玻璃立面，带金属框架网格。

    参数：
      - mullion_width: 竖框宽度
      - transom_height: 横框高度
      - grid_cols: 网格列数
      - grid_rows: 网格行数
    """

    def __init__(self, length: float, height: float, thickness: float,
                 name: str = "curtain_wall",
                 mullion_width: float = 0.08,
                 transom_height: float = 0.08,
                 grid_cols: int = 0,
                 grid_rows: int = 0,
                 glass_color: Tuple[float, float, float] = (0.6, 0.75, 0.9),
                 frame_color: Tuple[float, float, float] = (0.25, 0.25, 0.28),
                 **kwargs):
        super().__init__(length, height, thickness, name, **kwargs)
        self.mullion_width = mullion_width
        self.transom_height = transom_height
        self.grid_cols = grid_cols if grid_cols > 0 else max(1, int(length / 1.5))
        self.grid_rows = grid_rows if grid_rows > 0 else max(1, int(height / 1.2))
        self.glass_color = glass_color
        self.frame_color = frame_color

    def generate_usd(self, bridge: 'UsdBridge', path: str) -> WallSegmentResult:
        xform = bridge.define_xform(path)
        L, H, T = self.length, self.height, self.thickness

        # 玻璃面板（整块，略微内缩）
        glass_z = T * 0.3  # 玻璃在墙体厚度的30%处（向内）
        glass_t = 0.012     # 玻璃厚度12mm

        bridge.create_box_mesh(
            f"{path}/GlassPanel",
            width=L, height=H, depth=glass_t,
            translate=(L/2, H/2, glass_z),
            display_color=self.glass_color
        )

        # 金属框架
        frame_z = T * 0.15  # 框架在玻璃前面（更靠近外表面）
        mw = self.mullion_width
        th = self.transom_height

        # 竖框 (Mullions)
        col_spacing = L / self.grid_cols
        for i in range(self.grid_cols + 1):
            x = i * col_spacing
            bridge.create_box_mesh(
                f"{path}/Mullion_{i}",
                width=mw, height=H, depth=T * 0.6,
                translate=(x, H/2, frame_z),
                display_color=self.frame_color
            )

        # 横框 (Transoms)
        row_spacing = H / self.grid_rows
        for i in range(self.grid_rows + 1):
            y = i * row_spacing
            bridge.create_box_mesh(
                f"{path}/Transom_{i}",
                width=L, height=th, depth=T * 0.6,
                translate=(L/2, y, frame_z),
                display_color=self.frame_color
            )

        # 幕墙的每个玻璃格子都算一个"窗户"
        win_positions = []
        for r in range(self.grid_rows):
            for c in range(self.grid_cols):
                wx = (c + 0.5) * col_spacing
                wy = (r + 0.5) * row_spacing
                win_positions.append((wx, wy, glass_z))

        return WallSegmentResult(
            window_positions=win_positions,
            stats={
                "type": "CurtainWall", "length": self.length,
                "num_windows": len(win_positions),
                "grid": f"{self.grid_cols}x{self.grid_rows}",
            }
        )


# =============================================================================
# LouverWall: 百叶墙
# =============================================================================

@IWallSegment.register("LouverWall")
class LouverWallSegment(IWallSegment):
    """
    百叶墙段：带水平百叶片的通风墙体。

    上半部分是实墙，下半部分（或指定区域）是百叶。
    """

    def __init__(self, length: float, height: float, thickness: float,
                 name: str = "louver_wall",
                 louver_start_height: float = 0.5,
                 louver_end_height: float = 2.5,
                 louver_count: int = 12,
                 louver_angle: float = 45.0,
                 **kwargs):
        super().__init__(length, height, thickness, name, **kwargs)
        self.louver_start = louver_start_height
        self.louver_end = louver_end_height
        self.louver_count = louver_count
        self.louver_angle = louver_angle

    def generate_usd(self, bridge: 'UsdBridge', path: str) -> WallSegmentResult:
        xform = bridge.define_xform(path)
        L, H, T = self.length, self.height, self.thickness

        color = self.extra_params.get("color", (0.85, 0.82, 0.78))

        # 百叶区域上方的实墙
        if self.louver_end < H:
            top_h = H - self.louver_end
            bridge.create_box_mesh(
                f"{path}/TopSolid",
                width=L, height=top_h, depth=T,
                translate=(L/2, self.louver_end + top_h/2, T/2),
                display_color=color
            )

        # 百叶区域下方的实墙
        if self.louver_start > 0:
            bridge.create_box_mesh(
                f"{path}/BottomSolid",
                width=L, height=self.louver_start, depth=T,
                translate=(L/2, self.louver_start/2, T/2),
                display_color=color
            )

        # 百叶片
        louver_zone_h = self.louver_end - self.louver_start
        blade_spacing = louver_zone_h / self.louver_count
        blade_width = blade_spacing * 0.85
        blade_thickness = 0.003  # 3mm薄片

        louver_color = self.extra_params.get("louver_color", (0.6, 0.6, 0.62))

        for i in range(self.louver_count):
            y = self.louver_start + (i + 0.5) * blade_spacing
            bridge.create_box_mesh(
                f"{path}/Blade_{i}",
                width=L - 0.02, height=blade_width, depth=blade_thickness,
                translate=(L/2, y, T/2),
                display_color=louver_color
            )
            # 旋转百叶片
            prim = bridge.stage.GetPrimAtPath(f"{path}/Blade_{i}")
            UsdGeom.Xformable(prim).AddRotateXOp().Set(self.louver_angle)

        # 左右边框
        frame_w = 0.05
        for side, x in [("Left", frame_w/2), ("Right", L - frame_w/2)]:
            bridge.create_box_mesh(
                f"{path}/Frame_{side}",
                width=frame_w, height=louver_zone_h, depth=T,
                translate=(x, self.louver_start + louver_zone_h/2, T/2),
                display_color=(0.3, 0.3, 0.32)
            )

        return WallSegmentResult(
            stats={"type": "LouverWall", "length": self.length, "num_louvers": self.louver_count}
        )


# =============================================================================
# MixedWall: 混合墙（上窗下实 / 自定义分区）
# =============================================================================

@IWallSegment.register("MixedWall")
class MixedWallSegment(IWallSegment):
    """
    混合墙段：上部为窗户区域，下部为实墙区域。

    可以配置分界线高度和窗户参数。
    """

    def __init__(self, length: float, height: float, thickness: float,
                 name: str = "mixed_wall",
                 split_height: float = 1.2,
                 window_width: float = 1.8,
                 window_height: float = 1.2,
                 window_spacing: float = 3.0,
                 **kwargs):
        super().__init__(length, height, thickness, name, **kwargs)
        self.split_height = split_height
        self.window_width = window_width
        self.window_height = window_height
        self.window_spacing = window_spacing

    def generate_usd(self, bridge: 'UsdBridge', path: str) -> WallSegmentResult:
        xform = bridge.define_xform(path)
        L, H, T = self.length, self.height, self.thickness
        sh = self.split_height

        color = self.extra_params.get("color", (0.85, 0.82, 0.78))

        # 下部实墙
        bridge.create_box_mesh(
            f"{path}/LowerSolid",
            width=L, height=sh, depth=T,
            translate=(L/2, sh/2, T/2),
            display_color=color
        )

        # 上部窗墙（使用WindowWallSegment的逻辑）
        upper_h = H - sh
        upper_seg = WindowWallSegment(
            length=L, height=upper_h, thickness=T,
            name=f"{self.name}_upper",
            window_width=self.window_width,
            window_height=self.window_height,
            window_sill_height=0.3,
            window_spacing=self.window_spacing,
            color=color,
        )
        result = upper_seg.generate_usd(bridge, f"{path}/UpperWindow")

        # 将上部窗墙向上平移
        prim = bridge.stage.GetPrimAtPath(f"{path}/UpperWindow")
        UsdGeom.Xformable(prim).AddTranslateOp().Set(Gf.Vec3d(0, sh, 0))

        # 修正窗户位置（加上split_height偏移）
        adjusted_wins = [(x, y + sh, z) for x, y, z in result.window_positions]

        return WallSegmentResult(
            window_positions=adjusted_wins,
            stats={
                "type": "MixedWall", "length": self.length,
                "num_windows": len(adjusted_wins),
                "split_height": sh,
            }
        )


# =============================================================================
# SpandrelWall: 裙墙/窗间墙（占位符）
# =============================================================================

@IWallSegment.register("SpandrelWall")
class SpandrelWallSegment(IWallSegment):
    """
    裙墙/窗间墙段：上下两条水平装饰带 + 中间玻璃区域。

    常见于现代办公楼立面。上下的不透明裙板（spandrel panel）
    遮挡楼板结构，中间是视觉玻璃区域。

    占位符实现：三个水平分区方块。
    """

    def __init__(self, length: float, height: float, thickness: float,
                 name: str = "spandrel_wall",
                 spandrel_ratio: float = 0.25,
                 panel_color: Tuple[float, float, float] = (0.45, 0.45, 0.48),
                 glass_color: Tuple[float, float, float] = (0.6, 0.75, 0.9),
                 **kwargs):
        super().__init__(length, height, thickness, name, **kwargs)
        self.spandrel_ratio = spandrel_ratio
        self.panel_color = panel_color
        self.glass_color = glass_color

    def generate_usd(self, bridge: 'UsdBridge', path: str) -> WallSegmentResult:
        xform = bridge.define_xform(path)
        L, H, T = self.length, self.height, self.thickness
        sr = self.spandrel_ratio

        bottom_h = H * sr
        top_h = H * sr
        mid_h = H - bottom_h - top_h

        # 底部裙板（不透明面板）
        bridge.create_box_mesh(
            f"{path}/BottomSpandrel",
            width=L, height=bottom_h, depth=T,
            translate=(L/2, bottom_h/2, T/2),
            display_color=self.panel_color
        )

        # 中间玻璃区域
        glass_t = 0.015
        bridge.create_box_mesh(
            f"{path}/GlassZone",
            width=L, height=mid_h, depth=glass_t,
            translate=(L/2, bottom_h + mid_h/2, T * 0.3),
            display_color=self.glass_color
        )

        # 顶部裙板
        bridge.create_box_mesh(
            f"{path}/TopSpandrel",
            width=L, height=top_h, depth=T,
            translate=(L/2, bottom_h + mid_h + top_h/2, T/2),
            display_color=self.panel_color
        )

        # 竖向分隔条
        num_dividers = max(1, int(L / 2.0))
        div_spacing = L / num_dividers
        for i in range(num_dividers + 1):
            x = i * div_spacing
            bridge.create_box_mesh(
                f"{path}/Divider_{i}",
                width=0.05, height=mid_h, depth=T * 0.5,
                translate=(x, bottom_h + mid_h/2, T * 0.15),
                display_color=(0.3, 0.3, 0.32)
            )

        # 每个玻璃格子算一个窗户
        win_positions = []
        for i in range(num_dividers):
            wx = (i + 0.5) * div_spacing
            wy = bottom_h + mid_h / 2
            win_positions.append((wx, wy, T * 0.3))

        return WallSegmentResult(
            window_positions=win_positions,
            stats={"type": "SpandrelWall", "length": self.length,
                   "num_windows": len(win_positions)}
        )


# =============================================================================
# ColumnWall: 柱廊墙（占位符）
# =============================================================================

@IWallSegment.register("ColumnWall")
class ColumnWallSegment(IWallSegment):
    """
    柱廊墙段：带竖向柱子的墙体。

    常见于古典/新古典风格建筑。柱子之间是凹进的墙面或窗户。

    占位符实现：竖向方块柱子 + 凹进的背板。
    """

    def __init__(self, length: float, height: float, thickness: float,
                 name: str = "column_wall",
                 column_width: float = 0.4,
                 column_depth: float = 0.15,
                 column_spacing: float = 3.0,
                 column_color: Tuple[float, float, float] = (0.9, 0.88, 0.83),
                 **kwargs):
        super().__init__(length, height, thickness, name, **kwargs)
        self.column_width = column_width
        self.column_depth = column_depth
        self.column_spacing = column_spacing
        self.column_color = column_color

    def generate_usd(self, bridge: 'UsdBridge', path: str) -> WallSegmentResult:
        xform = bridge.define_xform(path)
        L, H, T = self.length, self.height, self.thickness

        color = self.extra_params.get("color", (0.85, 0.82, 0.78))

        # 背板（凹进的墙面）
        back_t = T - self.column_depth
        bridge.create_box_mesh(
            f"{path}/BackPanel",
            width=L, height=H, depth=back_t,
            translate=(L/2, H/2, T/2 + self.column_depth/2),
            display_color=color
        )

        # 柱子
        num_cols = max(2, int(L / self.column_spacing) + 1)
        col_spacing = L / (num_cols - 1) if num_cols > 1 else L

        for i in range(num_cols):
            x = i * col_spacing
            bridge.create_box_mesh(
                f"{path}/Column_{i}",
                width=self.column_width, height=H, depth=T,
                translate=(x, H/2, T/2),
                display_color=self.column_color
            )

        # 柱间窗户
        win_positions = []
        for i in range(num_cols - 1):
            wx = (i + 0.5) * col_spacing
            wy = H * 0.5
            win_positions.append((wx, wy, T * 0.3))

        return WallSegmentResult(
            window_positions=win_positions,
            stats={"type": "ColumnWall", "length": self.length,
                   "num_columns": num_cols, "num_windows": len(win_positions)}
        )


# =============================================================================
# ArchWall: 拱形墙（占位符）
# =============================================================================

@IWallSegment.register("ArchWall")
class ArchWallSegment(IWallSegment):
    """
    拱形墙段：带拱形开口的墙体。

    常见于欧式/古典建筑。拱形开口上方是实墙，下方是开口。

    占位符实现：矩形开口 + 顶部半圆弧近似（用方块堆叠）。
    """

    def __init__(self, length: float, height: float, thickness: float,
                 name: str = "arch_wall",
                 arch_width: float = 2.0,
                 arch_height: float = 2.5,
                 arch_spacing: float = 3.5,
                 keystone_color: Tuple[float, float, float] = (0.8, 0.75, 0.65),
                 **kwargs):
        super().__init__(length, height, thickness, name, **kwargs)
        self.arch_width = arch_width
        self.arch_height = arch_height
        self.arch_spacing = arch_spacing
        self.keystone_color = keystone_color

    def generate_usd(self, bridge: 'UsdBridge', path: str) -> WallSegmentResult:
        xform = bridge.define_xform(path)
        L, H, T = self.length, self.height, self.thickness

        color = self.extra_params.get("color", (0.85, 0.82, 0.78))

        # 整体背板
        bridge.create_box_mesh(
            f"{path}/WallBody",
            width=L, height=H, depth=T,
            translate=(L/2, H/2, T/2),
            display_color=color
        )

        # 拱形开口（用方块近似）
        num_arches = max(1, int(L / self.arch_spacing))
        arch_spacing = L / num_arches

        win_positions = []
        for i in range(num_arches):
            cx = (i + 0.5) * arch_spacing
            aw = min(self.arch_width, arch_spacing * 0.7)
            ah = min(self.arch_height, H * 0.75)

            # 矩形开口部分（用深色方块表示凹进）
            bridge.create_box_mesh(
                f"{path}/ArchOpening_{i}",
                width=aw, height=ah, depth=T * 0.6,
                translate=(cx, ah/2, T * 0.1),
                display_color=(0.15, 0.15, 0.18)  # 深色表示开口
            )

            # 拱顶拱心石（keystone）
            bridge.create_box_mesh(
                f"{path}/Keystone_{i}",
                width=aw * 0.2, height=aw * 0.15, depth=T * 0.3,
                translate=(cx, ah + aw * 0.075, T * 0.05),
                display_color=self.keystone_color
            )

            # 两侧柱头
            for side, sx in [("L", cx - aw/2), ("R", cx + aw/2)]:
                bridge.create_box_mesh(
                    f"{path}/Capital_{i}_{side}",
                    width=aw * 0.15, height=aw * 0.1, depth=T * 0.3,
                    translate=(sx, ah, T * 0.05),
                    display_color=self.keystone_color
                )

            win_positions.append((cx, ah * 0.5, T * 0.3))

        return WallSegmentResult(
            window_positions=win_positions,
            stats={"type": "ArchWall", "length": self.length,
                   "num_arches": num_arches}
        )


# =============================================================================
# PanelWall: 金属/石材面板墙（占位符）
# =============================================================================

@IWallSegment.register("PanelWall")
class PanelWallSegment(IWallSegment):
    """
    面板墙段：预制金属或石材面板拼接。

    常见于工业风/现代建筑。面板之间有可见的接缝。

    占位符实现：网格化的方块面板，带接缝间隙。
    """

    def __init__(self, length: float, height: float, thickness: float,
                 name: str = "panel_wall",
                 panel_width: float = 1.2,
                 panel_height: float = 0.8,
                 gap: float = 0.02,
                 panel_color: Tuple[float, float, float] = (0.55, 0.55, 0.58),
                 **kwargs):
        super().__init__(length, height, thickness, name, **kwargs)
        self.panel_width = panel_width
        self.panel_height = panel_height
        self.gap = gap
        self.panel_color = panel_color

    def generate_usd(self, bridge: 'UsdBridge', path: str) -> WallSegmentResult:
        xform = bridge.define_xform(path)
        L, H, T = self.length, self.height, self.thickness

        cols = max(1, int(L / self.panel_width))
        rows = max(1, int(H / self.panel_height))
        pw = L / cols
        ph = H / rows
        gap = self.gap

        count = 0
        for r in range(rows):
            for c in range(cols):
                cx = (c + 0.5) * pw
                cy = (r + 0.5) * ph
                bridge.create_box_mesh(
                    f"{path}/Panel_{r}_{c}",
                    width=pw - gap, height=ph - gap, depth=T,
                    translate=(cx, cy, T/2),
                    display_color=self.panel_color
                )
                count += 1

        return WallSegmentResult(
            stats={"type": "PanelWall", "length": self.length,
                   "num_panels": count}
        )


# =============================================================================
# BrickWall: 砖纹墙（占位符）
# =============================================================================

@IWallSegment.register("BrickWall")
class BrickWallSegment(IWallSegment):
    """
    砖纹墙段：带砖纹纹理的实墙。

    常见于传统建筑。表面有砖块排列的纹理效果。

    占位符实现：整体实墙 + 表面装饰条纹（水平线条模拟砖缝）。
    """

    def __init__(self, length: float, height: float, thickness: float,
                 name: str = "brick_wall",
                 brick_color: Tuple[float, float, float] = (0.72, 0.38, 0.28),
                 mortar_color: Tuple[float, float, float] = (0.8, 0.78, 0.75),
                 course_height: float = 0.075,
                 **kwargs):
        super().__init__(length, height, thickness, name, **kwargs)
        self.brick_color = brick_color
        self.mortar_color = mortar_color
        self.course_height = course_height

    def generate_usd(self, bridge: 'UsdBridge', path: str) -> WallSegmentResult:
        xform = bridge.define_xform(path)
        L, H, T = self.length, self.height, self.thickness

        # 主体砖墙
        bridge.create_box_mesh(
            f"{path}/BrickBody",
            width=L, height=H, depth=T,
            translate=(L/2, H/2, T/2),
            display_color=self.brick_color
        )

        # 水平砖缝线条（每隔 course_height 一条）
        mortar_t = 0.005  # 砖缝厚度
        num_courses = int(H / self.course_height)
        for i in range(1, num_courses):
            y = i * self.course_height
            bridge.create_box_mesh(
                f"{path}/HMortar_{i}",
                width=L + 0.002, height=mortar_t, depth=0.002,
                translate=(L/2, y, -0.001),  # 略微突出外表面
                display_color=self.mortar_color
            )

        return WallSegmentResult(
            stats={"type": "BrickWall", "length": self.length,
                   "num_courses": num_courses}
        )


# =============================================================================
# RibbonWindowWall: 带状窗墙（占位符）
# =============================================================================

@IWallSegment.register("RibbonWindowWall")
class RibbonWindowWallSegment(IWallSegment):
    """
    带状窗墙段：水平连续的带状窗户。

    常见于包豪斯/现代主义建筑。窗户水平连续延伸，
    上下是实墙或裙板，中间是一整条水平玻璃带。

    占位符实现：上下实墙方块 + 中间玻璃带方块。
    """

    def __init__(self, length: float, height: float, thickness: float,
                 name: str = "ribbon_window",
                 ribbon_bottom: float = 0.9,
                 ribbon_height: float = 1.5,
                 glass_color: Tuple[float, float, float] = (0.55, 0.7, 0.85),
                 frame_color: Tuple[float, float, float] = (0.2, 0.2, 0.22),
                 **kwargs):
        super().__init__(length, height, thickness, name, **kwargs)
        self.ribbon_bottom = ribbon_bottom
        self.ribbon_height = min(ribbon_height, height - ribbon_bottom)
        self.glass_color = glass_color
        self.frame_color = frame_color

    def generate_usd(self, bridge: 'UsdBridge', path: str) -> WallSegmentResult:
        xform = bridge.define_xform(path)
        L, H, T = self.length, self.height, self.thickness
        rb = self.ribbon_bottom
        rh = self.ribbon_height

        color = self.extra_params.get("color", (0.85, 0.82, 0.78))

        # 底部实墙（窗台以下）
        if rb > 0.01:
            bridge.create_box_mesh(
                f"{path}/BottomWall",
                width=L, height=rb, depth=T,
                translate=(L/2, rb/2, T/2),
                display_color=color
            )

        # 顶部实墙（窗户以上）
        top_start = rb + rh
        top_h = H - top_start
        if top_h > 0.01:
            bridge.create_box_mesh(
                f"{path}/TopWall",
                width=L, height=top_h, depth=T,
                translate=(L/2, top_start + top_h/2, T/2),
                display_color=color
            )

        # 水平玻璃带
        glass_t = 0.015
        bridge.create_box_mesh(
            f"{path}/RibbonGlass",
            width=L, height=rh, depth=glass_t,
            translate=(L/2, rb + rh/2, T * 0.3),
            display_color=self.glass_color
        )

        # 上下框架线条
        frame_h = 0.04
        for label, fy in [("TopFrame", rb + rh), ("BottomFrame", rb)]:
            bridge.create_box_mesh(
                f"{path}/{label}",
                width=L, height=frame_h, depth=T * 0.5,
                translate=(L/2, fy, T * 0.15),
                display_color=self.frame_color
            )

        # 竖向分隔条（每2m一个）
        num_dividers = max(1, int(L / 2.0))
        div_spacing = L / num_dividers
        for i in range(num_dividers + 1):
            x = i * div_spacing
            bridge.create_box_mesh(
                f"{path}/VDivider_{i}",
                width=0.03, height=rh, depth=T * 0.4,
                translate=(x, rb + rh/2, T * 0.15),
                display_color=self.frame_color
            )

        # 每个分隔区间算一个窗户
        win_positions = []
        for i in range(num_dividers):
            wx = (i + 0.5) * div_spacing
            wy = rb + rh / 2
            win_positions.append((wx, wy, T * 0.3))

        return WallSegmentResult(
            window_positions=win_positions,
            stats={"type": "RibbonWindowWall", "length": self.length,
                   "num_windows": len(win_positions)}
        )
