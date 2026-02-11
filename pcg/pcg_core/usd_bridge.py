"""
USD Bridge: USD底层API的高级封装层。

提供面向PCG任务的简洁接口，封装Stage管理、批量Prim创建、
Mesh生成、PointInstancer实例化和材质绑定等核心操作。
"""

from pxr import Usd, UsdGeom, UsdShade, UsdLux, Sdf, Gf, Vt
from typing import List, Tuple, Optional, Dict, Any
import numpy as np
import time
import os


class UsdBridge:
    """USD操作的高级封装，为PCG生成器提供简洁的API。"""

    def __init__(self, filepath: Optional[str] = None, up_axis: str = "Y"):
        """
        初始化USD Bridge。

        Args:
            filepath: USD文件路径。如果为None，则创建内存中的Stage。
            up_axis: 场景的上轴方向，默认为"Y"。
        """
        if filepath:
            # 确保目录存在
            os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
            self.stage = Usd.Stage.CreateNew(filepath)
            self._filepath = filepath
        else:
            self.stage = Usd.Stage.CreateInMemory()
            self._filepath = None

        # 设置场景元数据
        if up_axis == "Y":
            UsdGeom.SetStageUpAxis(self.stage, UsdGeom.Tokens.y)
        else:
            UsdGeom.SetStageUpAxis(self.stage, UsdGeom.Tokens.z)

        UsdGeom.SetStageMetersPerUnit(self.stage, 1.0)  # 1单位 = 1米

        self._layer = self.stage.GetRootLayer()
        self._material_cache: Dict[str, UsdShade.Material] = {}

    # =========================================================================
    # Stage管理
    # =========================================================================

    def save(self, filepath: Optional[str] = None) -> str:
        """保存Stage到文件。"""
        if filepath:
            self._layer.Export(filepath)
            return filepath
        elif self._filepath:
            self._layer.Save()
            return self._filepath
        else:
            # 默认保存到临时文件
            filepath = "/tmp/pcg_output.usda"
            self._layer.Export(filepath)
            return filepath

    def export_to_string(self) -> str:
        """将Stage导出为USDA字符串。"""
        return self._layer.ExportToString()

    # =========================================================================
    # Prim创建（高级API）
    # =========================================================================

    def define_xform(self, path: str,
                     translate: Optional[Tuple[float, float, float]] = None,
                     rotate: Optional[Tuple[float, float, float]] = None,
                     scale: Optional[Tuple[float, float, float]] = None) -> UsdGeom.Xform:
        """
        定义一个Xform变换节点。

        Args:
            path: Prim路径
            translate: 平移 (x, y, z)
            rotate: 旋转 (rx, ry, rz) 欧拉角
            scale: 缩放 (sx, sy, sz)
        """
        xform = UsdGeom.Xform.Define(self.stage, path)
        if translate:
            xform.AddTranslateOp().Set(Gf.Vec3d(*translate))
        if rotate:
            xform.AddRotateXYZOp().Set(Gf.Vec3f(*rotate))
        if scale:
            xform.AddScaleOp().Set(Gf.Vec3d(*scale))
        return xform

    def define_scope(self, path: str) -> UsdGeom.Scope:
        """定义一个Scope分组节点（无变换开销）。"""
        return UsdGeom.Scope.Define(self.stage, path)

    # =========================================================================
    # 几何体创建
    # =========================================================================

    def create_box_mesh(self, path: str,
                        width: float, height: float, depth: float,
                        translate: Optional[Tuple[float, float, float]] = None,
                        display_color: Optional[Tuple[float, float, float]] = None
                        ) -> UsdGeom.Mesh:
        """
        创建一个长方体Mesh。

        Args:
            path: Prim路径
            width: X方向宽度
            height: Y方向高度
            depth: Z方向深度
            translate: 可选的平移
            display_color: 可选的显示颜色 (r, g, b)，范围0-1
        """
        mesh = UsdGeom.Mesh.Define(self.stage, path)

        # 半尺寸
        hw, hh, hd = width / 2, height / 2, depth / 2

        # 8个顶点
        points = Vt.Vec3fArray([
            (-hw, -hh, -hd), (hw, -hh, -hd), (hw, hh, -hd), (-hw, hh, -hd),  # 后面
            (-hw, -hh, hd), (hw, -hh, hd), (hw, hh, hd), (-hw, hh, hd),      # 前面
        ])

        # 6个面，每面4个顶点 (逆时针法线朝外)
        face_vertex_counts = Vt.IntArray([4, 4, 4, 4, 4, 4])
        face_vertex_indices = Vt.IntArray([
            0, 3, 2, 1,  # 后面 (-Z)
            4, 5, 6, 7,  # 前面 (+Z)
            0, 1, 5, 4,  # 底面 (-Y)
            2, 3, 7, 6,  # 顶面 (+Y)
            0, 4, 7, 3,  # 左面 (-X)
            1, 2, 6, 5,  # 右面 (+X)
        ])

        mesh.GetPointsAttr().Set(points)
        mesh.GetFaceVertexCountsAttr().Set(face_vertex_counts)
        mesh.GetFaceVertexIndicesAttr().Set(face_vertex_indices)
        mesh.GetSubdivisionSchemeAttr().Set("none")

        # 设置extent
        mesh.GetExtentAttr().Set(Vt.Vec3fArray([(-hw, -hh, -hd), (hw, hh, hd)]))

        # 可选变换
        if translate:
            xformable = UsdGeom.Xformable(mesh.GetPrim())
            xformable.AddTranslateOp().Set(Gf.Vec3d(*translate))

        # 可选颜色
        if display_color:
            mesh.GetDisplayColorAttr().Set(
                Vt.Vec3fArray([Gf.Vec3f(*display_color)])
            )

        return mesh

    def create_plane_mesh(self, path: str,
                          width: float, depth: float,
                          translate: Optional[Tuple[float, float, float]] = None,
                          normal_direction: str = "up",
                          display_color: Optional[Tuple[float, float, float]] = None
                          ) -> UsdGeom.Mesh:
        """
        创建一个平面Mesh。

        Args:
            path: Prim路径
            width: X方向宽度
            depth: Z方向深度
            translate: 可选的平移
            normal_direction: 法线方向 ("up", "down", "front", "back", "left", "right")
            display_color: 可选的显示颜色
        """
        mesh = UsdGeom.Mesh.Define(self.stage, path)

        hw, hd = width / 2, depth / 2

        if normal_direction in ("up", "down"):
            points = Vt.Vec3fArray([
                (-hw, 0, -hd), (hw, 0, -hd), (hw, 0, hd), (-hw, 0, hd)
            ])
            if normal_direction == "up":
                indices = Vt.IntArray([0, 3, 2, 1])
            else:
                indices = Vt.IntArray([0, 1, 2, 3])
        elif normal_direction in ("front", "back"):
            points = Vt.Vec3fArray([
                (-hw, -hd, 0), (hw, -hd, 0), (hw, hd, 0), (-hw, hd, 0)
            ])
            if normal_direction == "front":
                indices = Vt.IntArray([0, 1, 2, 3])
            else:
                indices = Vt.IntArray([0, 3, 2, 1])
        else:  # left/right
            points = Vt.Vec3fArray([
                (0, -hw, -hd), (0, hw, -hd), (0, hw, hd), (0, -hw, hd)
            ])
            if normal_direction == "right":
                indices = Vt.IntArray([0, 1, 2, 3])
            else:
                indices = Vt.IntArray([0, 3, 2, 1])

        mesh.GetPointsAttr().Set(points)
        mesh.GetFaceVertexCountsAttr().Set(Vt.IntArray([4]))
        mesh.GetFaceVertexIndicesAttr().Set(indices)
        mesh.GetSubdivisionSchemeAttr().Set("none")

        if translate:
            xformable = UsdGeom.Xformable(mesh.GetPrim())
            xformable.AddTranslateOp().Set(Gf.Vec3d(*translate))

        if display_color:
            mesh.GetDisplayColorAttr().Set(
                Vt.Vec3fArray([Gf.Vec3f(*display_color)])
            )

        return mesh

    def create_wall_mesh(self, path: str,
                         width: float, height: float, thickness: float,
                         holes: Optional[List[Dict[str, float]]] = None,
                         translate: Optional[Tuple[float, float, float]] = None,
                         display_color: Optional[Tuple[float, float, float]] = None
                         ) -> UsdGeom.Mesh:
        """
        创建一面带有可选孔洞（窗户/门）的墙体Mesh。

        Args:
            path: Prim路径
            width: 墙体宽度
            height: 墙体高度
            thickness: 墙体厚度
            holes: 孔洞列表，每个孔洞为 {"x": center_x, "y": center_y, "w": width, "h": height}
            translate: 可选的平移
            display_color: 可选的显示颜色
        """
        if not holes:
            # 无孔洞，直接创建一个长方体
            return self.create_box_mesh(path, width, height, thickness,
                                        translate=translate,
                                        display_color=display_color)

        mesh = UsdGeom.Mesh.Define(self.stage, path)
        ht = thickness / 2

        # 使用简化方法：将墙面分割为多个矩形面片
        # 对于每个孔洞，在前后面生成围绕孔洞的面片
        all_points = []
        all_face_vertex_counts = []
        all_face_vertex_indices = []

        # 排序孔洞（从左到右）
        sorted_holes = sorted(holes, key=lambda h: h["x"] - h["w"] / 2)

        # 生成前面和后面的面片
        for z_sign, z_val in [(-1, -ht), (1, ht)]:
            base_idx = len(all_points)
            face_points, face_counts, face_indices = self._generate_wall_face_with_holes(
                width, height, sorted_holes, z_val, z_sign, base_idx
            )
            all_points.extend(face_points)
            all_face_vertex_counts.extend(face_counts)
            all_face_vertex_indices.extend(face_indices)

        # 生成顶面、底面、左面、右面
        hw, hh = width / 2, height / 2
        base_idx = len(all_points)

        # 顶面
        all_points.extend([
            Gf.Vec3f(-hw, hh, -ht), Gf.Vec3f(hw, hh, -ht),
            Gf.Vec3f(hw, hh, ht), Gf.Vec3f(-hw, hh, ht)
        ])
        all_face_vertex_counts.append(4)
        all_face_vertex_indices.extend([base_idx, base_idx + 3, base_idx + 2, base_idx + 1])
        base_idx += 4

        # 底面
        all_points.extend([
            Gf.Vec3f(-hw, -hh, -ht), Gf.Vec3f(hw, -hh, -ht),
            Gf.Vec3f(hw, -hh, ht), Gf.Vec3f(-hw, -hh, ht)
        ])
        all_face_vertex_counts.append(4)
        all_face_vertex_indices.extend([base_idx, base_idx + 1, base_idx + 2, base_idx + 3])
        base_idx += 4

        # 左面
        all_points.extend([
            Gf.Vec3f(-hw, -hh, -ht), Gf.Vec3f(-hw, hh, -ht),
            Gf.Vec3f(-hw, hh, ht), Gf.Vec3f(-hw, -hh, ht)
        ])
        all_face_vertex_counts.append(4)
        all_face_vertex_indices.extend([base_idx, base_idx + 3, base_idx + 2, base_idx + 1])
        base_idx += 4

        # 右面
        all_points.extend([
            Gf.Vec3f(hw, -hh, -ht), Gf.Vec3f(hw, hh, -ht),
            Gf.Vec3f(hw, hh, ht), Gf.Vec3f(hw, -hh, ht)
        ])
        all_face_vertex_counts.append(4)
        all_face_vertex_indices.extend([base_idx, base_idx + 1, base_idx + 2, base_idx + 3])
        base_idx += 4

        # 孔洞内壁（连接前后面）
        for hole in sorted_holes:
            hx, hy, hw_h, hh_h = hole["x"], hole["y"], hole["w"] / 2, hole["h"] / 2
            # 孔洞4条边的内壁
            edges = [
                # 底边
                [(hx - hw_h, hy - hh_h, -ht), (hx + hw_h, hy - hh_h, -ht),
                 (hx + hw_h, hy - hh_h, ht), (hx - hw_h, hy - hh_h, ht)],
                # 顶边
                [(hx - hw_h, hy + hh_h, -ht), (hx + hw_h, hy + hh_h, -ht),
                 (hx + hw_h, hy + hh_h, ht), (hx - hw_h, hy + hh_h, ht)],
                # 左边
                [(hx - hw_h, hy - hh_h, -ht), (hx - hw_h, hy + hh_h, -ht),
                 (hx - hw_h, hy + hh_h, ht), (hx - hw_h, hy - hh_h, ht)],
                # 右边
                [(hx + hw_h, hy - hh_h, -ht), (hx + hw_h, hy + hh_h, -ht),
                 (hx + hw_h, hy + hh_h, ht), (hx + hw_h, hy - hh_h, ht)],
            ]
            for j, edge in enumerate(edges):
                idx = len(all_points)
                for pt in edge:
                    all_points.append(Gf.Vec3f(*pt))
                all_face_vertex_counts.append(4)
                if j < 2:  # 底边和顶边
                    winding = [idx, idx + 1, idx + 2, idx + 3] if j == 0 else [idx, idx + 3, idx + 2, idx + 1]
                else:  # 左边和右边
                    winding = [idx, idx + 3, idx + 2, idx + 1] if j == 2 else [idx, idx + 1, idx + 2, idx + 3]
                all_face_vertex_indices.extend(winding)

        mesh.GetPointsAttr().Set(Vt.Vec3fArray(all_points))
        mesh.GetFaceVertexCountsAttr().Set(Vt.IntArray(all_face_vertex_counts))
        mesh.GetFaceVertexIndicesAttr().Set(Vt.IntArray(all_face_vertex_indices))
        mesh.GetSubdivisionSchemeAttr().Set("none")

        if translate:
            xformable = UsdGeom.Xformable(mesh.GetPrim())
            xformable.AddTranslateOp().Set(Gf.Vec3d(*translate))

        if display_color:
            mesh.GetDisplayColorAttr().Set(
                Vt.Vec3fArray([Gf.Vec3f(*display_color)])
            )

        return mesh

    def _generate_wall_face_with_holes(
        self, width: float, height: float,
        holes: List[Dict[str, float]],
        z_val: float, z_sign: int, base_idx: int
    ) -> Tuple[List, List, List]:
        """生成带孔洞的墙面（前面或后面）。使用行列分割法。"""
        hw, hh = width / 2, height / 2
        points = []
        face_counts = []
        face_indices = []

        # 收集所有Y方向的分割线
        y_splits = [-hh, hh]
        for hole in holes:
            y_splits.append(hole["y"] - hole["h"] / 2)
            y_splits.append(hole["y"] + hole["h"] / 2)
        y_splits = sorted(set(y_splits))

        # 收集所有X方向的分割线
        x_splits = [-hw, hw]
        for hole in holes:
            x_splits.append(hole["x"] - hole["w"] / 2)
            x_splits.append(hole["x"] + hole["w"] / 2)
        x_splits = sorted(set(x_splits))

        # 对每个小矩形区域判断是否在孔洞内
        idx_offset = base_idx
        for i in range(len(y_splits) - 1):
            for j in range(len(x_splits) - 1):
                x0, x1 = x_splits[j], x_splits[j + 1]
                y0, y1 = y_splits[i], y_splits[i + 1]

                # 检查此区域是否在某个孔洞内
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                in_hole = False
                for hole in holes:
                    hx, hy = hole["x"], hole["y"]
                    hw_h, hh_h = hole["w"] / 2, hole["h"] / 2
                    if (hx - hw_h) <= cx <= (hx + hw_h) and (hy - hh_h) <= cy <= (hy + hh_h):
                        in_hole = True
                        break

                if not in_hole:
                    # 添加这个矩形面片
                    idx = idx_offset + len(points)
                    points.extend([
                        Gf.Vec3f(x0, y0, z_val),
                        Gf.Vec3f(x1, y0, z_val),
                        Gf.Vec3f(x1, y1, z_val),
                        Gf.Vec3f(x0, y1, z_val),
                    ])
                    face_counts.append(4)
                    if z_sign > 0:  # 前面
                        face_indices.extend([idx, idx + 1, idx + 2, idx + 3])
                    else:  # 后面
                        face_indices.extend([idx, idx + 3, idx + 2, idx + 1])

        return points, face_counts, face_indices

    # =========================================================================
    # 高性能实例化
    # =========================================================================

    def create_point_instancer(self, path: str,
                               prototype_paths: List[str],
                               positions: List[Tuple[float, float, float]],
                               proto_indices: List[int],
                               orientations: Optional[List[Tuple[float, float, float, float]]] = None,
                               scales: Optional[List[Tuple[float, float, float]]] = None
                               ) -> UsdGeom.PointInstancer:
        """
        创建PointInstancer进行高性能实例化。

        Args:
            path: Instancer的Prim路径
            prototype_paths: 原型Prim路径列表
            positions: 每个实例的位置
            proto_indices: 每个实例使用的原型索引
            orientations: 可选的四元数旋转 (qw, qx, qy, qz)
            scales: 可选的缩放
        """
        instancer = UsdGeom.PointInstancer.Define(self.stage, path)

        # 设置原型关系
        instancer.CreatePrototypesRel().SetTargets(
            [Sdf.Path(p) for p in prototype_paths]
        )

        # 设置实例数据
        instancer.CreateProtoIndicesAttr(Vt.IntArray(proto_indices))
        instancer.CreatePositionsAttr(
            Vt.Vec3fArray([Gf.Vec3f(*p) for p in positions])
        )

        if orientations:
            instancer.CreateOrientationsAttr(
                Vt.QuathArray([Gf.Quath(*o) for o in orientations])
            )

        if scales:
            instancer.CreateScalesAttr(
                Vt.Vec3fArray([Gf.Vec3f(*s) for s in scales])
            )

        return instancer

    # =========================================================================
    # 批量操作（高性能）
    # =========================================================================

    def batch_create_prims(self, prim_specs: List[Dict[str, Any]]) -> None:
        """
        使用SdfChangeBlock批量创建Prim（高性能模式）。

        Args:
            prim_specs: Prim规格列表，每个元素为:
                {"path": str, "type": str, "attributes": dict}
        """
        with Sdf.ChangeBlock():
            for spec in prim_specs:
                prim_spec = Sdf.CreatePrimInLayer(self._layer, spec["path"])
                prim_spec.specifier = Sdf.SpecifierDef
                prim_spec.typeName = spec.get("type", "Xform")

                # 设置属性
                for attr_name, attr_value in spec.get("attributes", {}).items():
                    attr_spec = Sdf.AttributeSpec(
                        prim_spec, attr_name,
                        Sdf.ValueTypeNames.Find(
                            self._get_sdf_type_name(attr_value)
                        )
                    )
                    attr_spec.default = attr_value

    def _get_sdf_type_name(self, value) -> str:
        """根据Python值推断Sdf类型名。"""
        if isinstance(value, float):
            return "double"
        elif isinstance(value, int):
            return "int"
        elif isinstance(value, str):
            return "string"
        elif isinstance(value, bool):
            return "bool"
        elif isinstance(value, Gf.Vec3f):
            return "float3"
        elif isinstance(value, Gf.Vec3d):
            return "double3"
        return "token"

    # =========================================================================
    # 多边形几何体
    # =========================================================================

    def create_polygon_slab(self, path: str,
                            vertices_xz: list,
                            triangles: list,
                            thickness: float,
                            y_center: float = 0.0,
                            display_color=None) -> UsdGeom.Mesh:
        """
        创建多边形楼板/屋顶Mesh。

        通过拉伸多边形生成带厚度的楼板，包含上下表面和侧面。

        Args:
            path: Prim路径
            vertices_xz: XZ平面上的顶点列表 [(x,z), ...]
            triangles: 三角化索引 [(i0,i1,i2), ...]
            thickness: 楼板厚度
            y_center: 楼板Y方向中心
            display_color: 显示颜色
        """
        mesh = UsdGeom.Mesh.Define(self.stage, path)
        n = len(vertices_xz)
        ht = thickness / 2
        y_top = y_center + ht
        y_bot = y_center - ht

        # 顶点: 上表面n个 + 下表面n个
        points = []
        for x, z in vertices_xz:
            points.append(Gf.Vec3f(x, y_top, z))  # 上表面 [0..n-1]
        for x, z in vertices_xz:
            points.append(Gf.Vec3f(x, y_bot, z))   # 下表面 [n..2n-1]

        face_counts = []
        face_indices = []

        # 上表面（法线朝上）
        for i0, i1, i2 in triangles:
            face_counts.append(3)
            face_indices.extend([i0, i2, i1])  # 逆时针 → 法线朝上

        # 下表面（法线朝下）
        for i0, i1, i2 in triangles:
            face_counts.append(3)
            face_indices.extend([i0 + n, i1 + n, i2 + n])  # 顺时针 → 法线朝下

        # 侧面（每条边一个矩形）
        for i in range(n):
            j = (i + 1) % n
            # 上表面的边: i_top, j_top
            # 下表面的边: i_bot, j_bot
            face_counts.append(4)
            face_indices.extend([i, j, j + n, i + n])  # 法线朝外

        mesh.GetPointsAttr().Set(Vt.Vec3fArray(points))
        mesh.GetFaceVertexCountsAttr().Set(Vt.IntArray(face_counts))
        mesh.GetFaceVertexIndicesAttr().Set(Vt.IntArray(face_indices))
        mesh.GetSubdivisionSchemeAttr().Set("none")

        # Extent
        xs = [v[0] for v in vertices_xz]
        zs = [v[1] for v in vertices_xz]
        mesh.GetExtentAttr().Set(Vt.Vec3fArray([
            Gf.Vec3f(min(xs), y_bot, min(zs)),
            Gf.Vec3f(max(xs), y_top, max(zs)),
        ]))

        if display_color:
            mesh.GetDisplayColorAttr().Set(
                Vt.Vec3fArray([Gf.Vec3f(*display_color)])
            )

        return mesh

    def create_prism_mesh(self, path: str,
                          quad_xz: list,
                          y_bottom: float, y_top: float,
                          display_color=None) -> UsdGeom.Mesh:
        """
        创建四边形截面的棱柱体Mesh（用于转角柱）。

        Args:
            path: Prim路径
            quad_xz: XZ平面上的四边形顶点 [(x,z), ...]（顺时针）
            y_bottom: 底部Y坐标
            y_top: 顶部Y坐标
            display_color: 显示颜色
        """
        mesh = UsdGeom.Mesh.Define(self.stage, path)
        n = len(quad_xz)

        # 顶点: 上表面n个 + 下表面n个
        points = []
        for x, z in quad_xz:
            points.append(Gf.Vec3f(x, y_top, z))   # 上 [0..n-1]
        for x, z in quad_xz:
            points.append(Gf.Vec3f(x, y_bottom, z)) # 下 [n..2n-1]

        face_counts = []
        face_indices = []

        # 上表面（法线朝上）- 顺时针多边形需要翻转为逆时针
        face_counts.append(n)
        face_indices.extend(list(range(n - 1, -1, -1)))

        # 下表面（法线朝下）
        face_counts.append(n)
        face_indices.extend(list(range(n, 2 * n)))

        # 侧面
        for i in range(n):
            j = (i + 1) % n
            face_counts.append(4)
            face_indices.extend([i, j, j + n, i + n])

        mesh.GetPointsAttr().Set(Vt.Vec3fArray(points))
        mesh.GetFaceVertexCountsAttr().Set(Vt.IntArray(face_counts))
        mesh.GetFaceVertexIndicesAttr().Set(Vt.IntArray(face_indices))
        mesh.GetSubdivisionSchemeAttr().Set("none")

        xs = [v[0] for v in quad_xz]
        zs = [v[1] for v in quad_xz]
        mesh.GetExtentAttr().Set(Vt.Vec3fArray([
            Gf.Vec3f(min(xs), y_bottom, min(zs)),
            Gf.Vec3f(max(xs), y_top, max(zs)),
        ]))

        if display_color:
            mesh.GetDisplayColorAttr().Set(
                Vt.Vec3fArray([Gf.Vec3f(*display_color)])
            )

        return mesh

    # =========================================================================
    # 材质系统
    # =========================================================================

    def create_material(self, path: str,
                        diffuse_color: Tuple[float, float, float] = (0.8, 0.8, 0.8),
                        roughness: float = 0.5,
                        metallic: float = 0.0,
                        opacity: float = 1.0) -> UsdShade.Material:
        """
        创建一个UsdPreviewSurface材质。

        Args:
            path: 材质Prim路径
            diffuse_color: 漫反射颜色
            roughness: 粗糙度
            metallic: 金属度
            opacity: 不透明度
        """
        material = UsdShade.Material.Define(self.stage, path)
        shader = UsdShade.Shader.Define(self.stage, f"{path}/PBRShader")
        shader.CreateIdAttr("UsdPreviewSurface")
        shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(
            Gf.Vec3f(*diffuse_color)
        )
        shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(roughness)
        shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(metallic)
        shader.CreateInput("opacity", Sdf.ValueTypeNames.Float).Set(opacity)

        material.CreateSurfaceOutput().ConnectToSource(
            shader.ConnectableAPI(), "surface"
        )

        self._material_cache[path] = material
        return material

    def bind_material(self, prim_path: str, material_path: str) -> None:
        """将材质绑定到Prim。"""
        prim = self.stage.GetPrimAtPath(prim_path)
        if prim and material_path in self._material_cache:
            UsdShade.MaterialBindingAPI.Apply(prim).Bind(
                self._material_cache[material_path]
            )

    # =========================================================================
    # 光照
    # =========================================================================

    def create_dome_light(self, path: str = "/lights/domeLight",
                          intensity: float = 1.0) -> None:
        """创建环境穹顶光。"""
        dome = UsdLux.DomeLight.Define(self.stage, path)
        dome.CreateIntensityAttr(intensity)

    def create_rect_light(self, path: str,
                          width: float = 1.0, height: float = 1.0,
                          intensity: float = 500.0,
                          translate: Optional[Tuple[float, float, float]] = None
                          ) -> None:
        """创建矩形区域光。"""
        light = UsdLux.RectLight.Define(self.stage, path)
        light.CreateWidthAttr(width)
        light.CreateHeightAttr(height)
        light.CreateIntensityAttr(intensity)
        if translate:
            xformable = UsdGeom.Xformable(light.GetPrim())
            xformable.AddTranslateOp().Set(Gf.Vec3d(*translate))
