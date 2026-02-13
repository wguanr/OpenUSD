# 户型生成模块设计方案

## 1. 模块定位

`unit_plan_generator.py` 是独立的户型平面生成模块，职责是：
- 提供多种户型模板（Template）
- 每种模板可根据参数（面宽/进深/随机种子）生成不同变体
- 输出标准的 `UnitPlan` 对象，供 `FloorPlanFactory` 和 `ResidentialGenerator` 消费

## 2. 核心架构

### 2.1 UnitTemplate（户型模板基类）

每种户型模板是一个类，实现 `generate(params) -> UnitPlan` 方法。
模板定义的是"布局规则"而非固定尺寸——通过参数化的房间尺寸范围和布局约束，
同一模板可以生成多种不同的平面布局。

### 2.2 参数化维度

每种模板接受以下参数：

| 参数 | 类型 | 说明 |
|------|------|------|
| bay_width | float | 总面宽（米），影响房间宽度分配 |
| depth_south | float | 南区进深 |
| depth_north | float | 北区进深 |
| seed | int | 随机种子，控制房间比例微调 |

### 2.3 户型模板清单

| 模板ID | 中文名 | 房间数 | 面宽范围 | 特征 |
|--------|--------|--------|----------|------|
| compact_1br | 紧凑一居 | 4~5 | 6.0~8.0m | 开间式，客厅+卧室一体或分离 |
| standard_2br | 标准两居 | 6~7 | 7.5~10.0m | 南北通透，主卧+客厅朝南 |
| comfort_3br | 舒适三居 | 8~10 | 10.0~14.0m | 双卫，主卧套间 |
| luxury_4br | 豪华四居 | 10~12 | 13.0~18.0m | 双卫双阳台，独立餐厅 |
| studio | 开间/公寓 | 2~3 | 4.0~6.0m | 无独立卧室，开放式 |
| loft_duplex | 复式/LOFT | 5~8 | 6.0~10.0m | 上下两层，挑高客厅 |

### 2.4 布局规则引擎

每种模板内部的布局逻辑遵循中国住宅设计规范：

1. **南北分区**：南区放客厅/卧室（采光面），北区放厨卫/走廊
2. **面宽分配**：按优先级分配面宽（客厅 > 主卧 > 次卧 > 厨房 > 卫生间）
3. **进深约束**：南区进深 > 北区进深（通常 4.0~5.0 vs 2.5~3.5）
4. **走廊连接**：南北区之间必须有走廊/过道连接
5. **卫生间位置**：主卫靠近主卧，公卫靠近走廊
6. **阳台规则**：客厅和主卧朝南面可设阳台
7. **空调位规则**：每个卧室配一个空调外机位

### 2.5 随机变体机制

同一模板通过以下方式生成变体：
- 房间宽度在允许范围内随机微调（±0.3m）
- 房间进深在允许范围内随机微调（±0.2m）
- 可选房间的有无（如储物间、独立餐厅）
- 阳台数量和位置的变化
- 卫生间数量（单卫/双卫）

## 3. 接口设计

```python
class UnitPlanGenerator:
    """户型平面生成器。"""
    
    @staticmethod
    def generate(template: str, 
                 bay_width: float = 0,  # 0=使用模板默认值
                 depth_south: float = 0,
                 depth_north: float = 0,
                 seed: int = 0) -> UnitPlan:
        """根据模板和参数生成户型平面。"""
    
    @staticmethod
    def random(unit_type: str, seed: int = 0) -> UnitPlan:
        """根据户型类型随机选择模板和参数生成。"""
    
    @staticmethod
    def list_templates() -> Dict[str, TemplateInfo]:
        """列出所有可用模板及其参数范围。"""
```

## 4. 与现有模块的关系

- `UnitPlanGenerator` 替代 `UnitPlanPresets`
- `FloorPlanFactory` 改为调用 `UnitPlanGenerator.generate()` 或 `.random()`
- `ResidentialConfig.unit_types` 支持模板ID（如 "comfort_3br"）或简写（如 "3BR"）
- 向后兼容：简写 "1BR"~"4BR" 映射到对应的默认模板
