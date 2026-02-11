#!/usr/bin/env python3
"""
USD模型3D可视化渲染器。

将USD模型转换为多视角的全景截图，用于快速检查生成结果。
使用matplotlib的3D投影进行离屏渲染，无需GPU。
"""

import sys
import os
import math
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from pxr import Usd, UsdGeom, Gf, Vt, Sdf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))


def extract_meshes_from_stage(stage):
    """从USD Stage中提取所有Mesh的几何数据和颜色。"""
    meshes = []

    for prim in stage.Traverse():
        if prim.IsA(UsdGeom.Mesh):
            mesh = UsdGeom.Mesh(prim)
            points_attr = mesh.GetPointsAttr().Get()
            fvc_attr = mesh.GetFaceVertexCountsAttr().Get()
            fvi_attr = mesh.GetFaceVertexIndicesAttr().Get()

            if not points_attr or not fvc_attr or not fvi_attr:
                continue

            # 获取世界变换
            xform_cache = UsdGeom.XformCache()
            world_transform = xform_cache.GetLocalToWorldTransform(prim)
            mat = np.array(world_transform).T  # USD矩阵是行优先

            # 转换顶点到世界坐标
            points = np.array(points_attr, dtype=np.float64)
            ones = np.ones((len(points), 1))
            points_h = np.hstack([points, ones])
            world_points = (mat @ points_h.T).T[:, :3]

            # 获取显示颜色
            color_attr = mesh.GetDisplayColorAttr().Get()
            if color_attr and len(color_attr) > 0:
                color = tuple(float(c) for c in color_attr[0])
            else:
                color = (0.7, 0.7, 0.7)

            # 提取面
            faces = []
            idx = 0
            for count in fvc_attr:
                face_indices = [int(fvi_attr[idx + j]) for j in range(count)]
                faces.append(face_indices)
                idx += count

            meshes.append({
                'points': world_points,
                'faces': faces,
                'color': color,
                'path': str(prim.GetPath()),
            })

    return meshes


def extract_instances_from_stage(stage):
    """从USD Stage中提取PointInstancer数据。"""
    instances = []

    for prim in stage.Traverse():
        if prim.IsA(UsdGeom.PointInstancer):
            instancer = UsdGeom.PointInstancer(prim)
            positions = instancer.GetPositionsAttr().Get()
            proto_indices = instancer.GetProtoIndicesAttr().Get()
            orientations = instancer.GetOrientationsAttr().Get()

            if not positions:
                continue

            # 获取原型
            proto_rels = instancer.GetPrototypesRel().GetTargets()

            instances.append({
                'positions': np.array(positions),
                'proto_indices': list(proto_indices) if proto_indices else [],
                'orientations': list(orientations) if orientations else [],
                'prototypes': [str(p) for p in proto_rels],
                'path': str(prim.GetPath()),
            })

    return instances


def compute_scene_bounds(meshes, instances):
    """计算场景的包围盒。"""
    all_points = []

    for m in meshes:
        all_points.append(m['points'])

    for inst in instances:
        all_points.append(inst['positions'])

    if not all_points:
        return np.array([0, 0, 0]), np.array([10, 10, 10])

    all_pts = np.vstack(all_points)
    bbox_min = all_pts.min(axis=0)
    bbox_max = all_pts.max(axis=0)

    return bbox_min, bbox_max


def render_panoramic_views(usd_path, output_dir, prefix="model"):
    """
    渲染USD模型的多视角全景截图。

    Args:
        usd_path: USD文件路径
        output_dir: 输出目录
        prefix: 输出文件名前缀
    """
    os.makedirs(output_dir, exist_ok=True)

    # 加载USD Stage
    stage = Usd.Stage.Open(usd_path)
    if not stage:
        print(f"Error: Cannot open {usd_path}")
        return []

    print(f"Loading: {usd_path}")

    # 提取几何数据
    meshes = extract_meshes_from_stage(stage)
    instances = extract_instances_from_stage(stage)

    print(f"  Meshes: {len(meshes)}, PointInstancers: {len(instances)}")

    # 计算场景边界
    bbox_min, bbox_max = compute_scene_bounds(meshes, instances)
    center = (bbox_min + bbox_max) / 2
    extent = bbox_max - bbox_min
    max_extent = max(extent)

    print(f"  Bounds: {bbox_min} -> {bbox_max}")
    print(f"  Center: {center}, Max extent: {max_extent:.1f}m")

    # 定义视角
    views = [
        {"name": "perspective_front", "title": "Perspective Front (SE)", "elev": 25, "azim": -60},
        {"name": "perspective_back", "title": "Perspective Back (NW)", "elev": 25, "azim": 120},
        {"name": "front", "title": "Front View (+Z)", "elev": 10, "azim": -90},
        {"name": "side", "title": "Side View (+X)", "elev": 10, "azim": 0},
        {"name": "top", "title": "Top View (Plan)", "elev": 89, "azim": -90},
        {"name": "bird_eye", "title": "Bird's Eye View", "elev": 45, "azim": -45},
    ]

    output_files = []

    # =========================================================================
    # 渲染综合全景图（2x3网格）
    # =========================================================================
    fig = plt.figure(figsize=(24, 16))
    fig.suptitle(f'USD-PCG Model Panoramic View\n{os.path.basename(usd_path)}',
                 fontsize=18, fontweight='bold', y=0.98)

    for i, view in enumerate(views):
        ax = fig.add_subplot(2, 3, i + 1, projection='3d')
        _render_scene_to_ax(ax, meshes, instances, bbox_min, bbox_max, center, max_extent, view)

    plt.subplots_adjust(top=0.92, bottom=0.02, left=0.02, right=0.98, hspace=0.1, wspace=0.05)

    panoramic_path = os.path.join(output_dir, f"{prefix}_panoramic.png")
    plt.savefig(panoramic_path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()
    output_files.append(panoramic_path)
    print(f"  Saved: {panoramic_path}")

    # =========================================================================
    # 渲染单独的高分辨率主视角
    # =========================================================================
    for view in [views[0], views[5]]:  # perspective_front 和 bird_eye
        fig = plt.figure(figsize=(16, 12))
        ax = fig.add_subplot(111, projection='3d')
        _render_scene_to_ax(ax, meshes, instances, bbox_min, bbox_max, center, max_extent, view)

        single_path = os.path.join(output_dir, f"{prefix}_{view['name']}.png")
        plt.savefig(single_path, dpi=200, bbox_inches='tight', facecolor='white')
        plt.close()
        output_files.append(single_path)
        print(f"  Saved: {single_path}")

    return output_files


def _render_scene_to_ax(ax, meshes, instances, bbox_min, bbox_max, center, max_extent, view):
    """将场景渲染到matplotlib 3D轴上。"""

    # 渲染Mesh面片
    for m in meshes:
        pts = m['points']
        color = m['color']
        alpha = 0.85

        # 对于玻璃材质（蓝色调），使用半透明
        if color[2] > color[0] and color[2] > 0.7:
            alpha = 0.4

        polygons = []
        for face in m['faces']:
            if len(face) >= 3:
                try:
                    verts = [pts[idx] for idx in face]
                    polygons.append(verts)
                except IndexError:
                    continue

        if polygons:
            poly_collection = Poly3DCollection(
                polygons,
                alpha=alpha,
                facecolor=color,
                edgecolor=(min(color[0] * 0.7, 1), min(color[1] * 0.7, 1), min(color[2] * 0.7, 1)),
                linewidth=0.2,
            )
            ax.add_collection3d(poly_collection)

    # 渲染PointInstancer实例（用小方块标记位置）
    for inst in instances:
        positions = inst['positions']
        if len(positions) > 0:
            ax.scatter(
                positions[:, 0], positions[:, 1], positions[:, 2],
                c='#5599DD', s=8, alpha=0.6, marker='s',
                label=f'Windows ({len(positions)})'
            )

    # 设置视角
    ax.view_init(elev=view['elev'], azim=view['azim'])

    # 设置坐标范围（等比例）
    half = max_extent / 2 * 1.2
    ax.set_xlim(center[0] - half, center[0] + half)
    ax.set_ylim(center[1] - half, center[1] + half)
    ax.set_zlim(center[2] - half, center[2] + half)

    ax.set_xlabel('X (m)', fontsize=9)
    ax.set_ylabel('Y / Height (m)', fontsize=9)
    ax.set_zlabel('Z (m)', fontsize=9)
    ax.set_title(view['title'], fontsize=12, fontweight='bold', pad=10)

    # 设置背景
    ax.xaxis.pane.fill = False
    ax.yaxis.pane.fill = False
    ax.zaxis.pane.fill = False
    ax.xaxis.pane.set_edgecolor('lightgray')
    ax.yaxis.pane.set_edgecolor('lightgray')
    ax.zaxis.pane.set_edgecolor('lightgray')
    ax.grid(True, alpha=0.3)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="USD模型全景渲染器")
    parser.add_argument("usd_file", help="USD文件路径")
    parser.add_argument("--output-dir", "-o", default="./output/renders",
                        help="输出目录")
    parser.add_argument("--prefix", "-p", default=None,
                        help="输出文件名前缀")
    args = parser.parse_args()

    if args.prefix is None:
        args.prefix = os.path.splitext(os.path.basename(args.usd_file))[0]

    files = render_panoramic_views(args.usd_file, args.output_dir, args.prefix)
    print(f"\nRendered {len(files)} images.")


if __name__ == "__main__":
    main()
