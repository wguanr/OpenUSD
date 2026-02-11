# USD-PCG: 基于USD的高性能程序化生成框架

基于OpenUSD构建的高性能、高并发的程序化内容生成（PCG）框架，以办公楼生成为标杆应用。

## 项目结构

```
pcg/
├── pcg_core/              # 核心框架层
│   ├── __init__.py
│   ├── engine.py          # PCG引擎：参数解析、生成器调度
│   └── usd_bridge.py      # USD抽象层：封装底层USD API
├── generators/            # 生成器库
│   ├── __init__.py
│   └── building_generator.py  # 办公楼生成器
├── configs/               # 配置文件
│   └── default_office.json    # 默认办公楼参数
├── tests/                 # 测试与基准
│   ├── batch_benchmark.py     # 高性能批量化测试
│   └── visualize_benchmark.py # 性能可视化
├── output/                # 生成输出目录
├── main.py                # 主入口
└── README.md
```

## 快速开始

```bash
# 安装依赖
pip install usd-core

# 使用默认参数生成5层办公楼
python pcg/main.py

# 自定义参数
python pcg/main.py --floors 20 --width 50 --depth 30 --roof parapet

# 使用配置文件
python pcg/main.py --config pcg/configs/default_office.json

# 运行性能基准测试
python pcg/tests/batch_benchmark.py
```

## 核心性能指标

| 指标 | 结果 |
|------|------|
| 100层建筑生成 | 2.24秒 |
| 峰值吞吐量 | 3300+ 窗户/秒 |
| PointInstancer加速 | 1.8x |
| 并行生成加速(4核) | 2.6x |

## 技术特性

- **SdfChangeBlock**: 批量原子化操作，9x性能提升
- **PointInstancer**: 大规模实例化，显著降低内存和文件大小
- **多进程并行**: 支持并行批量生成多个独立场景
- **参数驱动**: JSON配置文件驱动，支持CLI参数覆盖
- **模块化架构**: 生成器可插拔，易于扩展
