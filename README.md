# 灵境画炉 / AetherCanvas

基于深度学习的图像风格迁移与智能重绘工作站。项目将传统图像风格迁移模型、Stable Diffusion 图生图、LoRA 风格模型、模型导入管理、本地历史记录和云端 ComfyUI 推理整合到一个 Web 应用中，适合课程设计、毕业设计展示和个人 AI 图像创作实验。

## 项目简介

本系统面向“上传图片后快速获得不同艺术风格结果”的使用场景，提供两条主要生成路线：

- **风格迁移**：使用 AnimeGANv2、CycleGAN、VGG 等传统风格迁移模型，对图片进行动漫化、油画化、浮世绘、水墨等转换。
- **SD 智能重绘**：使用 Stable Diffusion / SDXL / LoRA 对输入图片进行图生图重绘，支持提示词、重绘强度、采样步数、CFG、基础模型和 LoRA 组合配置。

系统采用 Browser/Server 架构，后端使用 FastAPI 管理任务、模型、文件和云端推理，前端使用 HTML、Tailwind CSS 和 JavaScript 实现交互页面。

## 技术栈

### 后端

- Python 3.10+
- FastAPI
- Uvicorn
- Jinja2
- Pillow / OpenCV / NumPy
- SQLite
- Paramiko

### AI 与图像生成

- PyTorch
- ONNX Runtime GPU
- Diffusers
- Transformers
- Accelerate
- Safetensors
- PEFT
- Stable Diffusion 1.5
- SDXL / Illustrious / Animagine 等基础模型
- LoRA 风格模型
- ComfyUI 云端工作流

### 前端

- HTML
- Tailwind CSS
- JavaScript
- Fetch API
- Canvas 动画
- LocalStorage 本地历史记录

### 数据与文件

- `uploads/`：用户上传图片
- `results/`：生成结果
- `results/meta/`：任务元数据
- `results/exports/`：导出产物
- `data/jobs.db`：任务记录数据库
- `config/sd_styles.json`：SD 风格、基础模型、LoRA 绑定配置

## 功能说明

### 1. 风格迁移页面

入口：`/`

主要功能：

- 上传内容图
- 上传可选风格图
- 选择传统风格迁移模型
- 调整风格强度
- 执行风格迁移
- 查看生成结果
- 下载结果图
- 保存到本地历史记录

支持模型类型：

- AnimeGANv2
- CycleGAN
- VGG 风格迁移
- ONNX 动漫化模型

### 2. SD 智能重绘页面

入口：`/sd`

主要功能：

- 上传内容图
- 选择 SD 风格
- 选择基础模型
- 自动匹配 LoRA 绑定基础模型
- 设置正向提示词
- 设置负向提示词
- 调整重绘强度
- 调整采样步数
- 调整 CFG 强度
- 查看实时生成进度
- 下载生成结果
- 写入历史记录

适用场景：

- 图片动漫化重绘
- 像素风转换
- 水彩 / 水墨风格
- JOJO 漫画风格
- SDXL 大模型重绘
- LoRA 细分风格创作

### 3. 模型导入与管理

入口：`/model-import`

主要功能：

- 查看已配置风格模型
- 查看已配置 SD 基础模型
- 查看已配置 LoRA
- 导入新模型
- 将模型上传到云端
- 管理模型启用状态

支持的模型类型：

- `.safetensors`
- `.ckpt`
- `.pth`
- `.onnx`
- Diffusers 目录模型

说明：

- 基础模型用于决定生成能力和模型体系，例如 SD1.5、SDXL、Illustrious。
- LoRA 用于控制具体风格，例如水彩、像素、漫画、角色风格。
- 不同 LoRA 通常需要匹配对应基础模型，系统支持在配置中绑定推荐基础模型，避免每次手动切换。

### 4. 本地历史记录

入口：`/local-history`

主要功能：

- 查看最近生成结果
- 区分风格迁移和 SD 重绘结果
- 按时间展示历史记录
- 点击查看图片
- 支持生态风格 UI
- 支持天气状态挂件与页面动效

历史数据主要保存在浏览器本地，同时后端任务记录保存在 SQLite 中。

### 5. 云端 ComfyUI 接入

入口：

- `/cloud-settings`
- `/cloud-upload-monitor`

主要功能：

- 配置远端 SSH 信息
- 检测云端 GPU 状态
- 检测 ComfyUI 是否运行
- 上传本地模型到云端
- 同步远端 checkpoint 和 LoRA
- 将前端风格映射到云端模型文件
- 使用云端 GPU 执行 SD 图生图任务

适用场景：

- 本地没有高性能显卡
- SDXL 本地推理太慢
- 需要使用 RTX 4090 等云端 GPU
- 需要避免大模型占用本地显存

## 项目结构

```text
.
├── app.py                         # FastAPI 主入口
├── style_transfer.py              # 传统风格迁移
├── sd_style_transfer.py           # Stable Diffusion 本地推理
├── cloud_comfyui.py               # 云端 ComfyUI 推理
├── job_queue.py                   # 任务队列
├── job_store.py                   # SQLite 任务持久化
├── image_analyzer.py              # 输入图像分析
├── recipe_scorer.py               # 结果评分与参数推荐
├── exporter.py                    # 结果导出
├── share_builder.py               # 分享卡片生成
├── config/
│   └── sd_styles.json             # SD 风格与模型配置
├── templates/
│   ├── index.html                 # 风格迁移页面
│   ├── sd.html                    # SD 重绘页面
│   ├── model_import.html          # 模型管理页面
│   ├── local_history.html         # 本地历史记录页面
│   ├── cloud_settings.html        # 云端配置页面
│   └── cloud_upload_monitor.html  # 云端上传监控页面
├── static/
│   ├── main.js                    # 风格迁移前端逻辑
│   ├── sd.js                      # SD 页面前端逻辑
│   ├── history_page.js            # 历史记录页面逻辑
│   └── local_history.css          # 历史记录页面独立样式
├── uploads/                       # 上传图片目录，运行时生成
├── results/                       # 生成结果目录，运行时生成
├── imported_models/               # 导入模型目录，本地使用
└── data/                          # 数据库与本地私有配置
```

## 安装与运行

### 1. 克隆项目

```bash
git clone https://github.com/lgcr12/image-style-transfer-system-.git
cd image-style-transfer-system-
```

### 2. 创建虚拟环境

Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
```

macOS / Linux:

```bash
python -m venv .venv
source .venv/bin/activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

如果需要 GPU 推理，请根据本机 CUDA 版本安装对应的 PyTorch 和 ONNX Runtime GPU 版本。

### 4. 启动服务

```bash
python -m uvicorn app:app --host 127.0.0.1 --port 8001
```

浏览器访问：

```text
http://127.0.0.1:8001/
```

常用页面：

```text
http://127.0.0.1:8001/                  风格迁移
http://127.0.0.1:8001/sd                SD 智能重绘
http://127.0.0.1:8001/model-import      模型导入
http://127.0.0.1:8001/local-history     本地历史
http://127.0.0.1:8001/cloud-settings    云端配置
```

## 模型准备

项目不会提交大模型权重，需要用户自行准备模型文件。

推荐目录：

```text
E:/models/
├── v1-5-pruned-emaonly.safetensors
├── MeinaMixV12.safetensors
├── imported_models/
│   ├── Illustrious-XL-v2.0.safetensors
│   └── *.safetensors
```

模型配置文件：

```text
config/sd_styles.json
```

基础模型配置示例：

```json
{
  "base_models": {
    "sd15": {
      "label": "SD 1.5",
      "type": "single_file",
      "model_type": "sd15",
      "path": "E:/models/v1-5-pruned-emaonly.safetensors"
    }
  }
}
```

LoRA 风格绑定示例：

```json
{
  "styles": {
    "pixel_style": {
      "label": "像素风",
      "adapters": ["pixel_lora"],
      "weights": [0.8],
      "base_model": "sd15"
    }
  }
}
```

## 云端 GPU 使用方法

### 1. 准备云端环境

云端需要具备：

- Linux 实例
- NVIDIA GPU
- 可 SSH 登录
- Python / Conda
- ComfyUI
- ComfyUI 默认端口 `8188`

推荐远端目录结构：

```text
/root/autodl-tmp/ComfyUI/
├── main.py
├── models/
│   ├── checkpoints/
│   └── loras/
├── input/
└── output/
```

### 2. 配置云端连接

进入：

```text
http://127.0.0.1:8001/cloud-settings
```

填写：

- Host
- Port
- Username
- Password
- ComfyUI Root

敏感信息会写入本地私有配置：

```text
data/cloud_upload_config.local.json
```

该文件已加入 `.gitignore`，不会上传到 GitHub。

### 3. 上传模型

进入：

```text
http://127.0.0.1:8001/model-import
```

点击对应模型的“上传云端”按钮，系统会进入上传监控页面：

```text
http://127.0.0.1:8001/cloud-upload-monitor
```

### 4. 运行云端生成

云端生成前需要确认：

- SSH 正常
- GPU 可用
- ComfyUI 可访问
- 选择的 checkpoint 已上传
- 选择的 LoRA 已上传
- 映射文件中的模型名与 ComfyUI `object_info` 列表一致

如果云端实例是无卡模式，会出现：

```text
No devices were found
```

需要先在云平台切回 GPU 模式。

## 常见问题

### 1. 页面可以打开，但生成失败

先检查后端日志和任务状态接口：

```text
GET /api/status/{job_id}
```

常见原因：

- 没有上传图片
- 模型文件不存在
- LoRA 与基础模型不兼容
- GPU 显存不足
- 云端 ComfyUI 未启动
- 云端实例没有挂载 GPU

### 2. 云端提示 ComfyUI 未运行

检查：

- 云端实例是否开机
- SSH 是否能连上
- `ComfyUI/main.py` 是否存在
- 端口 `8188` 是否可访问
- GPU 是否可用

### 3. ComfyUI 返回 HTTP 400

通常是工作流校验失败，常见原因：

- checkpoint 名称不在 ComfyUI 可用列表中
- LoRA 名称不在 ComfyUI 可用列表中
- 中文文件名在远端识别不一致
- SD1.5 LoRA 和 SDXL 基础模型混用

处理方式：

- 打开云端模型能力页面刷新映射
- 将 LoRA 文件改为英文或拼音文件名
- 在映射配置中使用 ComfyUI 实际识别到的文件名

### 4. 本地 SDXL 很慢

SDXL 对显存和计算资源要求较高。本地显卡不足时建议：

- 使用云端 RTX 4090
- 降低分辨率
- 减少采样步数
- 开启快速模式
- 使用 SD1.5 模型

### 5. 为什么仓库里没有模型文件

模型文件通常非常大，不适合提交到 GitHub。以下文件类型已被忽略：

```text
*.safetensors
*.ckpt
*.pth
*.onnx
*.pt
*.bin
*.mat
```

需要用户自行下载并放到本地模型目录。

## API 简表

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 风格迁移首页 |
| GET | `/sd` | SD 重绘页面 |
| POST | `/api/style-transfer` | 提交传统风格迁移任务 |
| POST | `/api/sd-style-transfer` | 提交 SD 重绘任务 |
| GET | `/api/status/{job_id}` | 查询任务状态 |
| GET | `/api/result/{job_id}` | 获取生成结果 |
| GET | `/api/plugins/sd-styles` | 获取 SD 风格与模型配置 |
| GET | `/api/model-import/config` | 获取模型导入配置 |
| POST | `/api/cloud-upload/start` | 启动云端模型上传 |
| GET | `/api/cloud-runtime/status` | 查询云端运行环境 |
| GET | `/api/cloud-comfyui/capabilities` | 查询云端模型能力 |

## 开发建议

- 新增模型时，优先在 `config/sd_styles.json` 中配置，不要直接写死在页面中。
- 新增 LoRA 时，应同时记录推荐基础模型，避免用户每次手动切换。
- 云端模型文件尽量使用英文文件名，避免 ComfyUI 对中文文件名识别不一致。
- 任务状态和错误提示应通过 `/api/status/{job_id}` 统一返回。
- 大文件、运行日志、本地数据库、SSH 配置和模型权重不要提交到 GitHub。

## License

本项目用于学习、课程设计和毕业设计展示。使用第三方模型时，请遵守对应模型的开源协议、授权范围和商用限制。
