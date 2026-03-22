# SD 提示词帮助档案

适用页面：/sd（SD 动漫风格转换）  
适用模式：img2img + LoRA（lora1 / lora2 / default）

---

## 1. 快速上手模板

### 正向提示词（通用动漫）

masterpiece, best quality, anime style, detailed face, clean lineart, soft lighting

### 负向提示词（通用去瑕疵）

lowres, blurry, bad anatomy, bad hands, extra fingers, deformed face, watermark, text

### 新模型推荐负向词（默认）

(worst quality, low quality), (zombie, interlocked fingers)

无 Hires.fix 时可改用：(worst quality:1.6, low quality:1.6), (zombie, sketch, interlocked fingers, comic)

### 新模型推荐参数

- 采样：DPM++ 2M Karras，20~60 步
- CFG Scale：4~9
- 重绘强度：0.3~0.6（img2img）
- 人像分辨率：512x768, 512x1024
- 风景分辨率：768x512, 1024x512, 1536x512
- Clip Skip：2（部分环境支持）

---

## 2. 按目标套用（复制即用）

### A. 人像转动漫（保留人物结构）

正向：  
masterpiece, best quality, anime portrait, detailed face, clean lineart, natural skin shading, soft light, sharp eyes

负向：  
lowres, blurry, bad anatomy, bad hands, extra fingers, deformed face, ugly, watermark, text, logo

参数建议：
- denoising_strength: 0.45 ~ 0.60
- guidance_scale: 5.0 ~ 6.5
- num_inference_steps: 28 ~ 36

---

### B. 风格更重（更像插画/二次元）

正向：  
masterpiece, best quality, anime illustration, vibrant colors, dramatic lighting, detailed texture, stylized shading, high contrast

负向：  
lowres, blurry, noisy, bad anatomy, bad hands, overexposed, underexposed, watermark, text

参数建议：
- denoising_strength: 0.60 ~ 0.75
- guidance_scale: 5.5 ~ 7.5
- num_inference_steps: 32 ~ 45

---

### C. 建筑/场景转动漫背景

正向：  
masterpiece, best quality, anime background, detailed architecture, clean edges, cinematic composition, soft atmospheric light

负向：  
blurry, lowres, distorted perspective, noisy texture, watermark, text, logo

参数建议：
- denoising_strength: 0.50 ~ 0.68
- guidance_scale: 4.5 ~ 6.0
- num_inference_steps: 28 ~ 40

---

## 3. LoRA 选择建议

- lora1（水彩泼墨）：更偏柔和、水彩质感
- lora2（百花缭乱 Midjourney）：更偏浓艳、装饰感
- default（双 LoRA）：综合风格，通常更有味道，但偶尔会偏重

建议先单独试 lora1 和 lora2，确认你更喜欢哪种，再用 default 微调。

---

## 4. 调参口诀（实用）

- 想更像原图：denoising_strength 降低
- 想更像动漫：denoising_strength 提高
- 想更听提示词：guidance_scale 适当提高（别过高，容易僵硬）
- 想更细节：steps 适当增加（速度会变慢）

---

## 5. 常见问题与解决

### 问：脸糊、手崩、细节脏？

先加重负向词中的：  
bad hands, extra fingers, deformed face, blurry, lowres

并将：
- denoising_strength 调低一点（如 0.68 -> 0.58）
- guidance_scale 保持在 5~7

### 问：效果几乎没变化？

- 提高 denoising_strength（如 0.45 -> 0.62）
- 正向词增加风格词：anime illustration, stylized shading, vibrant colors

### 问：画面太 AI 味或失真？

- 降低 guidance_scale（如 7.5 -> 5.8）
- 减少过度夸张词（如 ultra detailed、extremely 之类）

---

## 6. 你的页面推荐默认值

建议默认使用：
- LoRA: default
- denoising_strength: 0.58
- guidance_scale: 5.8
- num_inference_steps: 32

正向词：  
masterpiece, best quality, anime style, detailed face, clean lineart, soft lighting

负向词：  
lowres, blurry, bad anatomy, bad hands, extra fingers, deformed face, watermark, text

---

## 7. 小建议（非常有效）

每次只改 1~2 个参数，连续做 3 组对比图，最快找到你喜欢的风格区间。
