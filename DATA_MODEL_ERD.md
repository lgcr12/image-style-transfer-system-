# 数据模型 ER 图

本项目的持久化核心在 `data/jobs.db`（SQLite），其中真正的关系型实体是：

- `jobs`
- `gallery_items`

此外还有两类“非关系持久化”：

- 文件系统资产（`uploads/`、`results/`）
- 浏览器本地记录（`localStorage`）

---

## 1) 核心关系模型（SQLite）

```mermaid
erDiagram
    JOBS ||--o| GALLERY_ITEMS : "published as"

    JOBS {
        TEXT job_id PK
        TEXT mode
        TEXT status
        TEXT phase
        TEXT phase_detail
        INTEGER progress
        TEXT error
        TEXT score_json
        TEXT next_recipe_json
        TEXT params_json
        TEXT content_path
        TEXT style_path
        TEXT result_path
        TEXT result_paths_json
        INTEGER created_at_ms
        INTEGER updated_at_ms
    }

    GALLERY_ITEMS {
        INTEGER id PK
        TEXT job_id UK
        TEXT title
        INTEGER anonymous
        INTEGER created_at_ms
    }
```

说明：

- `jobs.job_id` 是业务主键（UUID 字符串）。
- `gallery_items.job_id` 是唯一键（每个任务最多发布一次到画廊），通过应用层 `LEFT JOIN jobs ON jobs.job_id = gallery_items.job_id` 建立关联。
- `score_json / next_recipe_json / params_json / result_paths_json` 是 JSON 文本列，用于承载可变结构。

---

## 2) 扩展数据域（文件资产 + 前端本地记录）

```mermaid
erDiagram
    JOBS ||--o| FILE_UPLOAD_CONTENT : "content_path"
    JOBS ||--o| FILE_UPLOAD_STYLE : "style_path(optional)"
    JOBS ||--o| FILE_RESULT_MAIN : "result_path"
    JOBS ||--o{ FILE_RESULT_CANDIDATE : "result_paths_json"
    JOBS ||--o{ FILE_META_JSON : "results/meta/{job_id}.json"
    JOBS ||--o{ FILE_EXPORT_ASSET : "results/exports/*"
    JOBS ||--o{ FILE_SHARE_ASSET : "results/share/*"
    JOBS ||--o{ LOCAL_HISTORY_ITEM : "front-end references by jobId"

    FILE_UPLOAD_CONTENT {
        TEXT file_path PK
    }
    FILE_UPLOAD_STYLE {
        TEXT file_path PK
    }
    FILE_RESULT_MAIN {
        TEXT file_path PK
    }
    FILE_RESULT_CANDIDATE {
        TEXT file_path PK
    }
    FILE_META_JSON {
        TEXT file_path PK
    }
    FILE_EXPORT_ASSET {
        TEXT file_path PK
    }
    FILE_SHARE_ASSET {
        TEXT file_path PK
    }
    LOCAL_HISTORY_ITEM {
        TEXT jobId
        TEXT type
        INTEGER at
    }
```

说明：

- 这一层是“逻辑 ER”，用于表达系统真实数据流，不是 SQLite 物理表。
- `LOCAL_HISTORY_ITEM` 来自浏览器 `localStorage`（`models_local_history_v1`），不在后端 DB 中。

---

## 3) 设计约束与建议

- 当前 `gallery_items` 未声明外键约束（SQLite 物理层），是“软关联”。
- 若要增强一致性，可加：
  - `gallery_items.job_id` 外键到 `jobs.job_id`
  - 删除策略（`ON DELETE CASCADE` 或限制删除）
- JSON 字段若后续查询变多，建议把高频筛选项（如 `sd_style_name`、`total_score`）冗余为独立列并建索引。

