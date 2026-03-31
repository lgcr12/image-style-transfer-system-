# 项目数据流图

本文基于当前项目代码（FastAPI + 前端 JS + 本地文件存储 + 模型推理）整理。

## 1) 系统总览数据流

```mermaid
flowchart LR
    U[用户浏览器]
    FE[前端页面<br/>index/sd/local-history]
    API[FastAPI 服务<br/>app.py]
    JQ[任务队列<br/>JobQueue]
    JS[(内存任务状态<br/>jobs 字典)]
    FSU[(uploads/ 原图)]
    FSR[(results/ 结果图)]
    FSM[(results/meta 元数据)]
    FSE[(results/exports 导出产物)]
    FSS[(results/share 分享素材)]
    ST[传统风格迁移引擎<br/>style_transfer.py]
    SD[SD img2img 引擎<br/>sd_style_transfer.py]
    IA[输入图分析<br/>image_analyzer.py]
    RS[结果评分<br/>recipe_scorer.py]
    EX[导出模块<br/>exporter.py]
    SH[分享模块<br/>share_builder.py]
    QR[外部二维码服务<br/>api.qrserver.com]
    HF[模型源/缓存<br/>Hugging Face or 本地权重]

    U --> FE
    FE -->|上传图片/参数| API
    API --> JS
    API --> JQ
    API --> FSU
    JQ --> SD
    API --> ST
    ST --> FSR
    SD --> FSR
    SD --> RS
    API --> IA
    SD --> HF
    API --> FSM
    API --> EX --> FSE
    API --> SH --> FSS
    FE -->|轮询状态| API --> JS
    FE -->|读取结果| API --> FSR
    FE -->|扫码下载| QR
```

## 2) 核心流程 A：传统风格迁移 `/api/style-transfer`

```mermaid
sequenceDiagram
    participant B as 浏览器
    participant A as FastAPI
    participant M as style_transfer.py
    participant F as 文件系统
    participant S as jobs 状态

    B->>A: POST /api/style-transfer (content_image, style_image?, model_name, strength)
    A->>F: 保存 uploads/{job}_content.png / style.png
    A->>S: 创建 job 状态(queued/running...)
    A->>M: 后台线程运行 load_model + run_style_transfer
    M->>F: 写入 results/{job}_result.png
    M->>S: 更新 progress/phase/status
    B->>A: GET /api/status/{job} (轮询)
    A-->>B: 返回状态与进度
    B->>A: GET /api/result/{job}
    A-->>B: 返回 PNG
```

## 3) 核心流程 B：SD 风格迁移 `/api/sd-style-transfer`

```mermaid
sequenceDiagram
    participant B as 浏览器
    participant A as FastAPI
    participant Q as JobQueue
    participant D as sd_style_transfer.py
    participant R as recipe_scorer.py
    participant F as 文件系统
    participant S as jobs 状态

    B->>A: POST /api/sd-style-transfer (图片 + LoRA参数 + Prompt参数)
    A->>F: 保存 uploads/{job}_content.png
    A->>S: 初始化 job 状态
    A->>Q: submit QueueJob
    Q->>D: worker 执行 run_sd_style_transfer(...)
    D->>D: 加载/复用 SD Pipeline + LoRA
    D->>F: 写入 results/{job}_result.png 或候选图集
    D->>R: score_image(结果图) 计算评分与推荐
    D->>S: 回写 result_path/result_paths/score/next_recipe/status
    A->>F: 保存 results/meta/{job}.json
    B->>A: GET /api/status/{job} (轮询)
    A-->>B: 返回进度、阶段、评分、推荐参数
    B->>A: GET /api/result/{job}?index=n
    A-->>B: 返回结果图
```

## 4) 核心流程 C：导出与分享

```mermaid
flowchart TD
    FE[前端操作按钮]
    API[FastAPI 导出/分享接口]
    RES[(results 原图/结果图)]
    EX[exporter.py]
    SH[share_builder.py]
    OUT1[(results/exports)]
    OUT2[(results/share)]

    FE -->|/api/export/compare-batch| API --> EX
    FE -->|/api/export/nine-grid| API --> EX
    FE -->|/api/export/transition-video| API --> EX
    FE -->|/api/share/build| API --> SH
    EX --> RES
    SH --> RES
    EX --> OUT1
    SH --> OUT2
```

## 5) 数据存储与状态边界

- **短期状态**：`jobs` 与 `JobQueue._jobs` 在内存中；服务重启后会丢失。
- **持久化文件**：上传图、结果图、meta、导出图/视频、分享卡片保存在磁盘目录。
- **恢复能力**：`/api/result/{job_id}`、`/api/original/{job_id}` 会优先走磁盘路径，部分能力可跨重启继续访问。
- **外部依赖点**：
  - 二维码生成走公网接口 `api.qrserver.com`（前端直接调用）。
  - SD 基础模型可走本地权重，或在允许下载时走 Hugging Face。

