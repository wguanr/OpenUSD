"""
BuildingFootprint: 建筑底面轮廓数据模型。

支持任意凸/凹多边形底面，提供几何计算工具：
  - 边长、方向、法线
  - 内角计算
  - 内缩多边形（用于墙体厚度向内偏移）
  - 转角柱截面计算
  - 多边形三角化（用于楼板/屋顶Mesh生成）
  - 面积、质心、包围盒

坐标约定：
  - 顶点在XZ平面上（Y轴为高度方向）
  - 顶点按顺时针排列（从Y轴正方向俯视）
  - 外法线指向多边形外部
  - 顺时针约定：对于direction (dx, dz)，外法线 = (dz, -dx)
"""

from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import List, Tuple, Optional


@dataclass
class BuildingFootprint:
    """
    建筑底面轮廓——由有序顶点列表定义的闭合多边形。

    顶点在XZ平面上，按顺时针排列（从+Y俯视）。
    顺时针约定确保外法线 = (dz, -dx) 指向多边形外部。
    """
    vertices: List[Tuple[float, float]] = field(default_factory=list)

    # =========================================================================
    # 基本属性
    # =========================================================================

    @property
    def num_vertices(self) -> int:
        return len(self.vertices)

    @property
    def num_edges(self) -> int:
        return len(self.vertices)

    def vertex(self, i: int) -> Tuple[float, float]:
        """获取第i个顶点（支持负索引和环绕）。"""
        return self.vertices[i % self.num_vertices]

    # =========================================================================
    # 边的几何属性
    # =========================================================================

    def edge_start(self, i: int) -> Tuple[float, float]:
        """第i条边的起点。"""
        return self.vertex(i)

    def edge_end(self, i: int) -> Tuple[float, float]:
        """第i条边的终点。"""
        return self.vertex(i + 1)

    def edge_vector(self, i: int) -> Tuple[float, float]:
        """第i条边的方向向量（未归一化）。"""
        s = self.edge_start(i)
        e = self.edge_end(i)
        return (e[0] - s[0], e[1] - s[1])

    def edge_length(self, i: int) -> float:
        """第i条边的长度。"""
        dx, dz = self.edge_vector(i)
        return math.sqrt(dx * dx + dz * dz)

    def edge_direction(self, i: int) -> Tuple[float, float]:
        """第i条边的单位方向向量。"""
        dx, dz = self.edge_vector(i)
        length = math.sqrt(dx * dx + dz * dz)
        if length < 1e-9:
            return (1.0, 0.0)
        return (dx / length, dz / length)

    def edge_outward_normal(self, i: int) -> Tuple[float, float]:
        """
        第i条边的外法线方向（单位向量）。

        对于顺时针排列的顶点（从+Y俯视），外法线 = (dz, -dx)。
        这确保法线指向多边形外部。
        """
        dx, dz = self.edge_direction(i)
        return (dz, -dx)

    def edge_heading_deg(self, i: int) -> float:
        """第i条边相对于+X轴的角度（度），用于Xform旋转。"""
        dx, dz = self.edge_direction(i)
        return math.degrees(math.atan2(-dz, dx))

    # =========================================================================
    # 顶点角度
    # =========================================================================

    def interior_angle_rad(self, i: int) -> float:
        """
        顶点i处的内角（弧度）。

        内角 = π - 从前一条边到后一条边的有符号转角。
        对于凸多边形的逆时针顶点，内角 < π。
        """
        # 前一条边的方向
        d_prev = self.edge_direction(i - 1)
        # 后一条边的方向
        d_next = self.edge_direction(i)

        # 叉积和点积
        cross = d_prev[0] * d_next[1] - d_prev[1] * d_next[0]
        dot = d_prev[0] * d_next[0] + d_prev[1] * d_next[1]

        # 外角 = atan2(cross, dot)
        exterior = math.atan2(cross, dot)

        # 内角 = π - 外角
        interior = math.pi - exterior
        return interior

    def interior_angle_deg(self, i: int) -> float:
        """顶点i处的内角（度）。"""
        return math.degrees(self.interior_angle_rad(i))

    # =========================================================================
    # 内缩多边形（Inset / Offset Polygon）
    # =========================================================================

    def inset_polygon(self, offset: float) -> BuildingFootprint:
        """
        将多边形向内偏移offset距离。

        每条边沿内法线方向（即外法线的反方向）偏移offset，
        然后计算相邻偏移边的交点作为新顶点。

        Args:
            offset: 偏移距离（正值向内）

        Returns:
            内缩后的新 BuildingFootprint
        """
        n = self.num_vertices
        if n < 3:
            return BuildingFootprint(vertices=list(self.vertices))

        # 计算每条边偏移后的直线方程
        # 偏移边: 原始边沿内法线方向（-outward_normal）移动offset
        offset_lines = []
        for i in range(n):
            nx, nz = self.edge_outward_normal(i)
            # 内法线 = -外法线
            inx, inz = -nx, -nz
            # 偏移后的边上一点
            sx, sz = self.edge_start(i)
            px = sx + inx * offset
            pz = sz + inz * offset
            # 边的方向
            dx, dz = self.edge_direction(i)
            offset_lines.append((px, pz, dx, dz))

        # 计算相邻偏移边的交点
        new_vertices = []
        for i in range(n):
            # 第i条偏移边和第(i+1)条偏移边的交点 → 新的第(i+1)个顶点
            # 但实际上，顶点i是第(i-1)条边和第i条边的交点
            prev = (i - 1) % n
            p1x, p1z, d1x, d1z = offset_lines[prev]
            p2x, p2z, d2x, d2z = offset_lines[i]

            # 求两条参数直线的交点
            # P1 + t * D1 = P2 + s * D2
            # t * D1 - s * D2 = P2 - P1
            det = d1x * (-d2z) - d1z * (-d2x)
            if abs(det) < 1e-12:
                # 平行边，取中点
                new_vertices.append((
                    (p1x + p2x) / 2,
                    (p1z + p2z) / 2,
                ))
            else:
                dpx = p2x - p1x
                dpz = p2z - p1z
                t = (dpx * (-d2z) - dpz * (-d2x)) / det
                new_vertices.append((
                    p1x + t * d1x,
                    p1z + t * d1z,
                ))

        return BuildingFootprint(vertices=new_vertices)

    def inset_vertex(self, i: int, offset: float) -> Tuple[float, float]:
        """计算顶点i向内偏移offset后的位置。"""
        inset = self.inset_polygon(offset)
        return inset.vertex(i)

    # =========================================================================
    # 转角柱截面计算
    # =========================================================================

    def corner_quad(self, i: int, wall_thickness: float
                    ) -> List[Tuple[float, float]]:
        """
        计算顶点i处转角柱的四边形截面（XZ平面）。

        转角柱截面由4个点定义：
          1. 外轮廓顶点
          2. 前一条边内缩后在该顶点处的端点
          3. 内缩多边形的顶点
          4. 后一条边内缩后在该顶点处的端点

        实际上简化为：外顶点 + 两个相邻边的内偏移端点 + 内缩顶点。

        Returns:
            四个XZ坐标的列表（逆时针）
        """
        outer = self.vertex(i)
        inset = self.inset_polygon(wall_thickness)
        inner = inset.vertex(i)

        # 前一条边的方向（从vertex(i-1)到vertex(i)）
        d_prev = self.edge_direction(i - 1)
        n_prev = self.edge_outward_normal(i - 1)

        # 后一条边的方向（从vertex(i)到vertex(i+1)）
        d_next = self.edge_direction(i)
        n_next = self.edge_outward_normal(i)

        # 前一条边内偏移后在顶点i处的端点
        # = outer + 内法线prev * thickness
        pt_prev = (outer[0] - n_prev[0] * wall_thickness,
                   outer[1] - n_prev[1] * wall_thickness)

        # 后一条边内偏移后在顶点i处的端点
        # = outer + 内法线next * thickness
        pt_next = (outer[0] - n_next[0] * wall_thickness,
                   outer[1] - n_next[1] * wall_thickness)

        return [outer, pt_next, inner, pt_prev]

    def wall_edge_net_length(self, i: int, wall_thickness: float) -> float:
        """
        第i条边扣除两端转角柱后的净墙段长度。

        净长度 = 边长 - 两端转角柱在该边方向上的投影。
        """
        inset = self.inset_polygon(wall_thickness)

        # 边的方向
        d = self.edge_direction(i)

        # 起点处转角柱在边方向上的投影长度
        outer_start = self.vertex(i)
        inner_start = inset.vertex(i)
        proj_start = abs(
            (inner_start[0] - outer_start[0]) * d[0] +
            (inner_start[1] - outer_start[1]) * d[1]
        )

        # 终点处转角柱在边方向上的投影长度
        outer_end = self.vertex(i + 1)
        inner_end = inset.vertex(i + 1)
        proj_end = abs(
            (inner_end[0] - outer_end[0]) * d[0] +
            (inner_end[1] - outer_end[1]) * d[1]
        )

        net = self.edge_length(i) - proj_start - proj_end
        return max(0.0, net)

    def wall_edge_start_point(self, i: int, wall_thickness: float
                              ) -> Tuple[float, float]:
        """
        第i条边的墙段起点（扣除起始转角柱后）。

        墙段起点 = 外轮廓起点 + 转角柱投影长度 * 边方向
        同时沿内法线偏移 thickness/2（墙体中心线）。

        但实际上墙段在局部坐标系中生成，外表面Z=0对齐外轮廓。
        所以起点就是沿边方向偏移转角柱投影后的外轮廓点。
        """
        inset = self.inset_polygon(wall_thickness)
        d = self.edge_direction(i)

        outer_start = self.vertex(i)
        inner_start = inset.vertex(i)
        proj_start = (
            (inner_start[0] - outer_start[0]) * d[0] +
            (inner_start[1] - outer_start[1]) * d[1]
        )

        return (
            outer_start[0] + proj_start * d[0],
            outer_start[1] + proj_start * d[1],
        )

    # =========================================================================
    # 多边形三角化（用于楼板/屋顶Mesh）
    # =========================================================================

    def triangulate(self) -> List[Tuple[int, int, int]]:
        """
        将多边形三角化（Fan Triangulation）。

        对于凸多边形，使用简单的扇形三角化。
        对于凹多边形，使用 Ear Clipping 算法。

        Returns:
            三角形索引列表，每个元素为 (i0, i1, i2)
        """
        n = self.num_vertices
        if n < 3:
            return []

        if self.is_convex():
            # 凸多边形：扇形三角化
            return [(0, i, i + 1) for i in range(1, n - 1)]
        else:
            # 凹多边形：Ear Clipping
            return self._ear_clip_triangulate()

    def is_convex(self) -> bool:
        """判断多边形是否为凸多边形。"""
        n = self.num_vertices
        if n < 3:
            return True

        # 对于顺时针多边形（XZ平面，正面积），所有叉积应该 >= 0
        # 注意：在XZ平面中，顺时针的signed_area > 0
        # 叉积 > 0 表示左转，对于正面积多边形这是凸顶点
        # 叉积 < 0 表示右转，这是凹顶点
        for i in range(n):
            v0 = self.vertex(i)
            v1 = self.vertex(i + 1)
            v2 = self.vertex(i + 2)
            cross = ((v1[0] - v0[0]) * (v2[1] - v1[1]) -
                     (v1[1] - v0[1]) * (v2[0] - v1[0]))
            if cross < -1e-6:
                return False  # 凹顶点
        return True

    def _ear_clip_triangulate(self) -> List[Tuple[int, int, int]]:
        """Ear Clipping 三角化算法。"""
        indices = list(range(self.num_vertices))
        triangles = []

        while len(indices) > 2:
            found_ear = False
            n = len(indices)
            for i in range(n):
                prev_idx = indices[(i - 1) % n]
                curr_idx = indices[i]
                next_idx = indices[(i + 1) % n]

                v0 = self.vertices[prev_idx]
                v1 = self.vertices[curr_idx]
                v2 = self.vertices[next_idx]

                # 检查是否是凸顶点
                # 对于正面积多边形（XZ平面顺时针），凸顶点的叉积 >= 0
                cross = ((v1[0] - v0[0]) * (v2[1] - v1[1]) -
                         (v1[1] - v0[1]) * (v2[0] - v1[0]))
                if cross < 0:
                    continue  # 凹顶点（右转），跳过

                # 检查三角形内是否有其他顶点
                is_ear = True
                for j in range(n):
                    if j in ((i - 1) % n, i, (i + 1) % n):
                        continue
                    pt = self.vertices[indices[j]]
                    if self._point_in_triangle(pt, v0, v1, v2):
                        is_ear = False
                        break

                if is_ear:
                    triangles.append((prev_idx, curr_idx, next_idx))
                    indices.pop(i)
                    found_ear = True
                    break

            if not found_ear:
                # 退化情况，强制切割
                if len(indices) >= 3:
                    triangles.append((indices[0], indices[1], indices[2]))
                    indices.pop(1)
                else:
                    break

        return triangles

    @staticmethod
    def _point_in_triangle(p, v0, v1, v2) -> bool:
        """判断点p是否在三角形v0v1v2内部。"""
        def sign(p1, p2, p3):
            return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])

        d1 = sign(p, v0, v1)
        d2 = sign(p, v1, v2)
        d3 = sign(p, v2, v0)

        has_neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
        has_pos = (d1 > 0) or (d2 > 0) or (d3 > 0)

        return not (has_neg and has_pos)

    # =========================================================================
    # 面积、质心、包围盒
    # =========================================================================

    def signed_area(self) -> float:
        """计算有符号面积（逆时针为正）。"""
        n = self.num_vertices
        area = 0.0
        for i in range(n):
            x0, z0 = self.vertex(i)
            x1, z1 = self.vertex(i + 1)
            area += x0 * z1 - x1 * z0
        return area / 2.0

    def area(self) -> float:
        """计算面积。"""
        return abs(self.signed_area())

    def centroid(self) -> Tuple[float, float]:
        """计算质心。"""
        n = self.num_vertices
        if n == 0:
            return (0.0, 0.0)
        cx = sum(v[0] for v in self.vertices) / n
        cz = sum(v[1] for v in self.vertices) / n
        return (cx, cz)

    def bounding_box(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        """计算包围盒 ((min_x, min_z), (max_x, max_z))。"""
        xs = [v[0] for v in self.vertices]
        zs = [v[1] for v in self.vertices]
        return ((min(xs), min(zs)), (max(xs), max(zs)))

    def bounding_box_size(self) -> Tuple[float, float]:
        """包围盒尺寸 (width_x, depth_z)。"""
        bb = self.bounding_box()
        return (bb[1][0] - bb[0][0], bb[1][1] - bb[0][1])

    # =========================================================================
    # 工厂方法
    # =========================================================================

    @classmethod
    def rectangle(cls, width: float, depth: float) -> BuildingFootprint:
        """
        创建矩形底面（中心在原点）。

        顶点按顺时针排列（从+Y俯视）：
          NW → SW → SE → NE
        这样每条边的外法线正确指向外部：
          Edge 0 (NW→SW): 法线指向-X（左侧外部）  → 实际是left
          Edge 1 (SW→SE): 法线指向-Z（后方外部）  → 实际是back
          Edge 2 (SE→NE): 法线指向+X（右侧外部）  → 实际是right
          Edge 3 (NE→NW): 法线指向+Z（前方外部）  → 实际是front
        """
        hw, hd = width / 2, depth / 2
        # 顺时针 (从+Y俯视): front-left → back-left → back-right → front-right
        return cls(vertices=[
            (-hw, hd),   # NW (front-left)
            (-hw, -hd),  # SW (back-left)
            (hw, -hd),   # SE (back-right)
            (hw, hd),    # NE (front-right)
        ])

    @classmethod
    def l_shape(cls, w1: float, d1: float,
                w2: float, d2: float,
                center: bool = True) -> BuildingFootprint:
        """
        创建L形底面。

        L形由两个矩形叠加：
          主体: w1 x d1 (左下角在原点)
          翼部: w2 x d2 (从主体右上角向右延伸)

        如果 center=True，将质心移到原点。

        俯视图 (XZ平面, Z向上为前):
            ┌──────────────┐
            │              │ d2
            ┌────┘              │
            │                   │
            │  d1                │
            └───────────────────┘
               w1        w2
        """
        # 顺时针顶点 (从+Y俯视)
        verts = [
            (0, d1),             # 左上
            (0, 0),              # 左下
            (w1 + w2, 0),        # 右下
            (w1 + w2, d2),       # 右上(翼部)
            (w1, d2),            # 内角
            (w1, d1),            # 主体右上
        ]

        if center:
            cx = sum(v[0] for v in verts) / len(verts)
            cz = sum(v[1] for v in verts) / len(verts)
            verts = [(v[0] - cx, v[1] - cz) for v in verts]

        return cls(vertices=verts)

    @classmethod
    def t_shape(cls, w_main: float, d_main: float,
                w_stem: float, d_stem: float,
                center: bool = True) -> BuildingFootprint:
        """
        创建T形底面。

        T形 = 上方横条 + 下方竖条。

        俯视图 (Z向上为前):
            ┌──────────────┐
            │   横条 w_main │ d_main
            └──┬────────┬──┘
               │  竖条  │ d_stem
               └────────┘
                w_stem
        """
        hw = w_main / 2
        hs = w_stem / 2

        # 顺时针顶点 (从+Y俯视)
        verts = [
            (-hw, d_main),           # 左上
            (-hw, 0),                # 横条左下
            (-hs, 0),                # 竖条左上
            (-hs, -d_stem),          # 竖条左下
            (hs, -d_stem),           # 竖条右下
            (hs, 0),                 # 竖条右上
            (hw, 0),                 # 横条右下
            (hw, d_main),            # 右上
        ]

        if center:
            cx = sum(v[0] for v in verts) / len(verts)
            cz = sum(v[1] for v in verts) / len(verts)
            verts = [(v[0] - cx, v[1] - cz) for v in verts]

        return cls(vertices=verts)

    @classmethod
    def regular_polygon(cls, n_sides: int, radius: float) -> BuildingFootprint:
        """
        创建正多边形底面（中心在原点）。

        Args:
            n_sides: 边数 (>=3)
            radius: 外接圆半径
        """
        if n_sides < 3:
            raise ValueError(f"n_sides must be >= 3, got {n_sides}")

        verts = []
        for i in range(n_sides):
            # 从+Z方向开始，顺时针（从+Y俯视）
            # 在XZ平面中，顺时针 = 角度递增（因为Z轴向前）
            angle = math.pi / 2 + 2 * math.pi * i / n_sides
            x = radius * math.cos(angle)
            z = radius * math.sin(angle)
            verts.append((x, z))

        return cls(vertices=verts)

    @classmethod
    def from_vertices(cls, vertices: List[Tuple[float, float]]) -> BuildingFootprint:
        """从顶点列表创建（确保顺时针排列）。"""
        fp = cls(vertices=list(vertices))
        if fp.signed_area() > 0:
            # 如果是逆时针（正面积），翻转为顺时针
            fp.vertices.reverse()
        return fp

    # =========================================================================
    # 字符串表示
    # =========================================================================

    def __repr__(self) -> str:
        return (f"BuildingFootprint(n={self.num_vertices}, "
                f"area={self.area():.1f}m², "
                f"bbox={self.bounding_box_size()})")
