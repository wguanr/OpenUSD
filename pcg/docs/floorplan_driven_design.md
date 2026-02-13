# 户型平面驱动的住宅生成器 v2 设计方案

## 核心思路变化

**v1（当前）**：先定义规则矩形外壳 → 再在外壳上贴窗户/阳台
**v2（新）**：先设计户型平面（房间级别）→ 户型拼合出不规则标准层轮廓 → 逐层复制

## 数据模型

### Room（房间）
```
@dataclass
class Room:
    room_type: str      # "living", "master_bed", "bedroom", "kitchen", "bathroom", "dining", "balcony", "corridor"
    width: float        # X方向面宽
    depth: float        # Z方向进深
    x: float            # 房间左下角X（相对户型原点）
    z: float            # 房间左下角Z（相对户型原点）
    
    # 立面属性（由room_type自动推导）
    south_facing: bool  # 是否朝南
    window_type: str    # "large"/"small"/"floor_to_ceiling"/"none"
    has_balcony: bool   # 是否有阳台
    has_ac_slot: bool   # 是否有空调机位
```

### UnitPlan（户型平面）
```
@dataclass
class UnitPlan:
    unit_type: str       # "1BR"/"2BR"/"3BR"/"4BR"
    rooms: List[Room]    # 所有房间列表
    total_width: float   # 户型总面宽
    total_depth: float   # 户型最大进深
    outline: List[(x,z)] # 户型外轮廓多边形顶点
```

### FloorPlan（标准层平面）
```
@dataclass
class FloorPlan:
    units: List[(UnitPlan, transform)]  # 户型 + 放置位置/镜像
    core: CorePlan                       # 核心筒
    outline: List[(x,z)]                 # 整层外轮廓（由units合并得到）
```

## 户型布局规则（符合中国住宅常理）

### 三室一厅（3BR）典型布局
```
南(+Z)
┌──────────────────────────────┐
│  主卧(4.2×3.8)  │ 客厅(5.0×4.5) │ ← 南向
│  [阳台]         │ [大阳台]       │
├─────────┬───────┤              │
│ 次卧    │ 次卧  │              │
│(3.5×3.5)│(3.2×3.5)│            │
├─────────┼───────┼──────────────┤
│ 卫生间  │ 厨房  │  餐厅/走廊    │ ← 北向
│(2.0×2.5)│(2.5×3.0)│(2.5×3.0)  │
└──────────────────────────────┘
北(-Z)
```

关键规则：
1. 客厅、主卧必须朝南（+Z面）
2. 厨房、卫生间朝北（-Z面）
3. 次卧可南可北
4. 南向房间有阳台
5. 北向有空调机位
6. 户型不一定是规则矩形（次卧可能比客厅浅，形成凹口）

### 两室一厅（2BR）
```
南(+Z)
┌────────────────────────┐
│ 主卧(3.8×3.8) │ 客厅(4.5×4.2) │
│ [阳台]        │ [大阳台]       │
├───────────────┼───────────────┤
│ 卫生间(2.0×2.5)│ 厨房(2.5×2.8) │
│               │ 次卧(3.2×3.5)  │ ← 次卧可能北向
└────────────────────────┘
北(-Z)
```

## 标准层拼合

板楼一梯两户：
```
[户型A(镜像)] [核心筒] [户型B]
```

由于户型A和B可能进深不同（3BR比2BR深），建筑轮廓就不是规则矩形。

## 生成流程

1. `_generate_unit_plans()` → 为每种户型类型生成房间级平面
2. `_generate_floor_plan()` → 将户型+核心筒拼合为标准层
3. `_compute_floor_outline()` → 计算标准层外轮廓多边形
4. `_generate_floor_slabs()` → 用多边形楼板（create_polygon_slab）
5. `_generate_walls_from_outline()` → 沿轮廓生成外墙
6. `_generate_facade_from_rooms()` → 根据房间类型自动放置窗户/阳台/空调位
7. 逐层复制（Y方向偏移）

## 关键API映射

- 不规则楼板 → `create_polygon_slab(vertices_xz, triangles, thickness)`
- 外墙段（带窗洞） → `create_wall_mesh(width, height, thickness, holes)`
- 实心墙段 → `create_box_mesh`
- 窗户/阳台/空调位 → `create_box_mesh` + `create_point_instancer`
