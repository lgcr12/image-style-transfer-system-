from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, Optional, Union

import torch
import torch.nn.functional as F
from PIL import Image
from torchvision import transforms

import onnxruntime as ort
import cv2
import numpy as np
from torchvision import models

# 可在这里挂载不同的风格迁移模型
AVAILABLE_MODELS: Dict[str, str] = {
    "animegan_shinkai": "AnimeGANv2 新海诚风格 (ONNX)",
    "animegan_hayao": "AnimeGANv2 宫崎骏风格 (ONNX)",
    "animegan_shinkai_face": "AnimeGANv2 人脸增强（不改原效果）",
    "animegan_hayao_face": "AnimeGANv2 宫崎骏人像增强（人脸更稳）",
    "cyclegan_g_ab": "CycleGAN G_AB_epoch174 (PTH)",
    "cyclegan_style_ukiyoe": "CycleGAN 浮世绘风格 (PTH)",
    "vgg19_neural_style": "VGG19 经典风格迁移（迭代优化）",
}


def get_device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def load_image(path: Path, max_size: int = 512) -> torch.Tensor:
    image = Image.open(path).convert("RGB")
    transform_list = [transforms.Resize(max_size), transforms.ToTensor()]
    transform = transforms.Compose(transform_list)
    tensor = transform(image).unsqueeze(0)
    return tensor


def save_tensor_image(tensor: torch.Tensor, path: Path) -> None:
    img = tensor.clone().detach().cpu().squeeze(0)
    img = transforms.ToPILImage()(img)
    img.save(path)


def load_model(model_name: str) -> Union[torch.nn.Module, ort.InferenceSession]:
    """
    根据模型名称加载对应模型。
    - animegan_shinkai: 使用 ONNXRuntime，优先 CUDAExecutionProvider。
    - cyclegan/style_xxx: torch.load 得到的是 state_dict，需要重建网络结构再 load_state_dict。
    - 其他: 使用简单的 torch 示例模型（你可以按需替换为真实模型）。
    """
    if model_name in {
        "animegan_shinkai",
        "animegan_shinkai_face",
        "animegan_hayao",
        "animegan_hayao_face",
    }:
        onnx_by_name = {
            "animegan_shinkai": "Shinkai_53.onnx",
            "animegan_shinkai_face": "Shinkai_53.onnx",
            "animegan_hayao": "AnimeGANv2_Hayao.onnx",
            "animegan_hayao_face": "AnimeGANv2_Hayao.onnx",
        }
        onnx_file = onnx_by_name[model_name]
        if not Path(onnx_file).exists():
            raise FileNotFoundError(f"找不到 ONNX 模型文件: {onnx_file}")
        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        session = ort.InferenceSession(onnx_file, providers=providers)
        return session

    # 这些 state_dict 的键名结构与 ResNet generator 一致
    # - cyclegan_g_ab：residual block 使用 residual_attr="block"，InstanceNorm track_running_stats=False
    # - style_xxx：residual block 使用 residual_attr="conv_block"，InstanceNorm track_running_stats=True
    model_cfg = {
        "cyclegan_g_ab": ("G_AB_epoch174.pth", False, "block"),
        "cyclegan_style_ukiyoe": ("style_ukiyoe.pth", True, "conv_block"),
    }

    device = get_device()
    if model_name in model_cfg:
        # 简单缓存，避免重复 torch.load / load_state_dict
        cache: Dict[str, Union[torch.nn.Module, ort.InferenceSession]] = getattr(
            load_model, "_cache", {}
        )
        if model_name in cache:
            return cache[model_name]

        ckpt, norm_track_running_stats, residual_attr = model_cfg[model_name]
        ckpt_path = Path(ckpt)
        if not ckpt_path.exists():
            raise FileNotFoundError(f"找不到模型文件: {ckpt}")

        state_dict = torch.load(str(ckpt_path), map_location="cpu")
        if not isinstance(state_dict, dict):
            raise RuntimeError(
                f"模型文件 {ckpt} 加载结果不是 state_dict（实际类型：{type(state_dict)}）。"
            )

        net = _build_resnet_generator(
            norm_track_running_stats=norm_track_running_stats,
            residual_attr=residual_attr,
        )
        net.load_state_dict(state_dict, strict=True)
        net.to(device)
        net.eval()

        cache[model_name] = net
        setattr(load_model, "_cache", cache)
        return net

    # 下面是占位的 torch 模型，方便你后续替换成自己的权重
    if model_name.startswith("fast_neural_style"):
        model = torch.nn.Conv2d(3, 3, kernel_size=1)
    else:
        model = torch.nn.Conv2d(3, 3, kernel_size=1)
    model.to(device)
    return model


class _ResnetResidualBlock(torch.nn.Module):
    def __init__(
        self,
        dim: int,
        norm_track_running_stats: bool,
        residual_attr: str,
    ):
        super().__init__()
        assert residual_attr in {"block", "conv_block"}

        def Norm():
            return torch.nn.InstanceNorm2d(
                dim, affine=False, track_running_stats=norm_track_running_stats
            )

        # 关键点：保证 state_dict 键名能对上：
        # - residual_attr 决定了 model.<idx>.<residual_attr>.<layer_idx>.* 前缀
        # - conv 在 sequential 的 index=1 和 index=5，符合你的权重键名
        conv_block = torch.nn.Sequential(
            torch.nn.ReflectionPad2d(1),  # 0
            torch.nn.Conv2d(dim, dim, kernel_size=3, bias=True),  # 1
            Norm(),  # 2
            torch.nn.ReLU(True),  # 3
            torch.nn.ReflectionPad2d(1),  # 4
            torch.nn.Conv2d(dim, dim, kernel_size=3, bias=True),  # 5
            Norm(),  # 6
        )

        setattr(self, residual_attr, conv_block)
        self.residual_attr = residual_attr

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        block = getattr(self, self.residual_attr)
        return x + block(x)


def _build_resnet_generator(
    norm_track_running_stats: bool,
    residual_attr: str,
) -> torch.nn.Module:
    dim = 256

    def Norm(ch: int) -> torch.nn.Module:
        return torch.nn.InstanceNorm2d(
            ch, affine=False, track_running_stats=norm_track_running_stats
        )

    class Generator(torch.nn.Module):
        def __init__(self):
            super().__init__()
            # 这里把“可带权重/缓冲的模块”都放进 self.model，这样 state_dict 键名能保持一致
            self.model = torch.nn.Sequential(
                torch.nn.ReflectionPad2d(3),  # 0
                torch.nn.Conv2d(3, 64, kernel_size=7, bias=True),  # 1
                Norm(64),  # 2
                torch.nn.ReLU(True),  # 3
                torch.nn.Conv2d(64, 128, kernel_size=3, stride=2, padding=1, bias=True),  # 4
                Norm(128),  # 5
                torch.nn.ReLU(True),  # 6
                torch.nn.Conv2d(128, dim, kernel_size=3, stride=2, padding=1, bias=True),  # 7
                Norm(dim),  # 8
                torch.nn.ReLU(True),  # 9
            )

            # 残差块：确保它们落在 indices 10..18
            for _ in range(9):
                self.model.append(
                    _ResnetResidualBlock(
                        dim=dim,
                        norm_track_running_stats=norm_track_running_stats,
                        residual_attr=residual_attr,
                    )
                )

            # 残差块后：conv19 / norm20 / relu21 / conv22 / norm23 / relu24 / pad25 / conv26
            self.model.append(
                torch.nn.ConvTranspose2d(
                    dim,
                    128,
                    kernel_size=3,
                    stride=2,
                    padding=1,
                    output_padding=1,
                    bias=True,
                )
            )  # 19
            self.model.append(Norm(128))  # 20
            self.model.append(torch.nn.ReLU(True))  # 21
            self.model.append(
                torch.nn.ConvTranspose2d(
                    128,
                    64,
                    kernel_size=3,
                    stride=2,
                    padding=1,
                    output_padding=1,
                    bias=True,
                )
            )  # 22
            self.model.append(Norm(64))  # 23
            self.model.append(torch.nn.ReLU(True))  # 24
            self.model.append(torch.nn.ReflectionPad2d(3))  # 25
            self.model.append(
                torch.nn.Conv2d(64, 3, kernel_size=7, padding=0, bias=True)
            )  # 26

            self.out_act = torch.nn.Tanh()  # 无权重

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            # 0..9
            for i in range(0, 10):
                x = self.model[i](x)

            # 10..18 residual blocks
            for i in range(10, 19):
                x = self.model[i](x)
            x = self.model[19](x)
            x = self.model[20](x)
            x = self.model[21](x)
            x = self.model[22](x)
            x = self.model[23](x)
            x = self.model[24](x)
            x = self.model[25](x)
            x = self.model[26](x)
            x = self.out_act(x)
            return x

    return Generator()


def run_style_transfer(
    model_name: str,
    model: Union[torch.nn.Module, ort.InferenceSession],
    content_path: Path,
    style_path: Optional[Path],
    output_path: Path,
    strength: float,
    progress_callback: Callable[[int], None],
    phase_callback: Optional[Callable[[str, Optional[str]], None]] = None,
) -> None:
    def _ph(phase: str, detail: Optional[str] = None) -> None:
        if phase_callback is not None:
            phase_callback(phase, detail)

    _ph("running", "正在执行风格迁移与图像处理…")
    def _animegan_stylize_bgr(bgr: np.ndarray, session: ort.InferenceSession) -> np.ndarray:
        """
        对单张 BGR 图做 AnimeGANv2 推理，返回 BGR（与输入分辨率一致）。
        """
        h, w = bgr.shape[:2]

        def to_32s(x: int) -> int:
            return 256 if x < 256 else x - x % 32

        resized = cv2.resize(bgr, (to_32s(w), to_32s(h)))
        img = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 127.5 - 1.0
        img = np.expand_dims(img, axis=0)

        x_name = session.get_inputs()[0].name
        fake_img = session.run(None, {x_name: img})

        images = (np.squeeze(fake_img[0]) + 1.0) / 2.0 * 255.0
        images = np.clip(images, 0, 255).astype(np.uint8)
        images = cv2.resize(images, (w, h))
        images = cv2.cvtColor(images, cv2.COLOR_RGB2BGR)
        return images

    # 1) AnimeGANv2 ONNX 模型
    if model_name in {"animegan_shinkai", "animegan_hayao"}:
        progress_callback(5)
        # 读取原图（BGR）
        bgr = cv2.imread(str(content_path))
        if bgr is None:
            raise RuntimeError(f"无法读取内容图像: {content_path}")
        h, w = bgr.shape[:2]

        # 参照 animeGANv2_onnx.py 的预处理
        def to_32s(x: int) -> int:
            return 256 if x < 256 else x - x % 32

        resized = cv2.resize(bgr, (to_32s(w), to_32s(h)))
        img = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 127.5 - 1.0
        img = np.expand_dims(img, axis=0)

        session: ort.InferenceSession = model  # type: ignore[assignment]
        x_name = session.get_inputs()[0].name

        progress_callback(25)
        fake_img = session.run(None, {x_name: img})
        progress_callback(70)

        # 后处理与还原尺寸
        images = (np.squeeze(fake_img[0]) + 1.0) / 2 * 255.0
        images = np.clip(images, 0, 255).astype(np.uint8)
        images = cv2.resize(images, (w, h))
        images = cv2.cvtColor(images, cv2.COLOR_RGB2BGR)

        # 风格增强混合：strength=0 -> 原图，strength=1 -> 模型结果，>1 -> 风格增强
        strength = float(strength)
        if strength < 0.0:
            strength = 0.0
        if strength > 3.0:
            strength = 3.0

        content_bgr = bgr.astype(np.float32) / 255.0
        styl_bgr = images.astype(np.float32) / 255.0
        out = content_bgr + strength * (styl_bgr - content_bgr)
        out = np.clip(out, 0.0, 1.0)
        out_u8 = (out * 255.0).astype(np.uint8)

        cv2.imwrite(str(output_path), out_u8)
        progress_callback(100)
        return

    # 1.1) AnimeGANv2 人脸增强：整图动漫化 + 脸部区域二次动漫化并羽化融合
    # 重要：这个分支不会影响你当前的 animegan_shinkai 原始效果（保险起见可随时回切）。
    if model_name in {"animegan_shinkai_face", "animegan_hayao_face"}:
        progress_callback(5)
        bgr = cv2.imread(str(content_path))
        if bgr is None:
            raise RuntimeError(f"无法读取内容图像: {content_path}")

        content_bgr = bgr.astype(np.float32) / 255.0
        h, w = bgr.shape[:2]

        # 1) 整图动漫化一次
        progress_callback(20)
        styl_full_bgr = _animegan_stylize_bgr(bgr, model)  # type: ignore[arg-type]
        styl_full = styl_full_bgr.astype(np.float32) / 255.0

        # 2) 人脸检测
        progress_callback(35)
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        faces = face_cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30)
        )

        faces = list(faces) if faces is not None else []
        if len(faces) == 0:
            # 没有检测到脸：回退到普通 animegan_shinkai 的“strength 混合”
            strength_f = float(strength)
            strength_f = max(0.0, min(3.0, strength_f))
            out = content_bgr + strength_f * (styl_full - content_bgr)
            out = np.clip(out, 0.0, 1.0)
            out_u8 = (out * 255.0).astype(np.uint8)
            cv2.imwrite(str(output_path), out_u8)
            progress_callback(100)
            return

        # 3) 对每个脸部区域二次动漫化并羽化融合
        base_progress = 45
        n = len(faces)
        for i, (x, y, fw, fh) in enumerate(faces):
            pad = int(max(fw, fh) * 0.20)
            x1 = max(0, x - pad)
            y1 = max(0, y - pad)
            x2 = min(w, x + fw + pad)
            y2 = min(h, y + fh + pad)

            crop = bgr[y1:y2, x1:x2]
            if crop.size == 0:
                continue

            styl_crop_bgr = _animegan_stylize_bgr(crop, model)  # type: ignore[arg-type]
            styl_crop = styl_crop_bgr.astype(np.float32) / 255.0

            # 局部羽化 mask
            mask = np.ones((y2 - y1, x2 - x1), dtype=np.float32)
            k = int(max(15, min(x2 - x1, y2 - y1) / 3))
            if k % 2 == 0:
                k += 1
            mask = cv2.GaussianBlur(mask, (k, k), 0)
            mask = np.clip(mask, 0.0, 1.0)
            alpha = mask[:, :, None]

            region = styl_full[y1:y2, x1:x2]
            styl_full[y1:y2, x1:x2] = region * (1.0 - alpha) + styl_crop * alpha

            p = base_progress + int((i + 1) / n * 40)
            progress_callback(min(95, p))

        # 4) 最终 strength 混合（对比你原 animegan_shinkai 保持一致）
        strength_f = float(strength)
        strength_f = max(0.0, min(3.0, strength_f))
        out = content_bgr + strength_f * (styl_full - content_bgr)
        out = np.clip(out, 0.0, 1.0)
        out_u8 = (out * 255.0).astype(np.uint8)
        cv2.imwrite(str(output_path), out_u8)
        progress_callback(100)
        return

    # 1.5) VGG19 经典神经风格迁移（Gatys / Johnson 思路）
    if model_name == "vgg19_neural_style":
        if style_path is None:
            raise RuntimeError("VGG19 风格迁移需要上传风格图（style_image）。")

        device = get_device()
        progress_callback(5)

        # 记录原始尺寸（最后输出需要回到原尺寸）
        content_orig = Image.open(content_path).convert("RGB")
        orig_w, orig_h = content_orig.size

        # 优化阶段用较小分辨率，提升迭代速度/稳定性
        opt_max_size = 384
        content = load_image(content_path, max_size=opt_max_size).to(device)  # [1,3,H,W], 0..1
        style = load_image(style_path, max_size=opt_max_size).to(device)  # [1,3,H,W], 0..1

        if style.shape[-2:] != content.shape[-2:]:
            style = torch.nn.functional.interpolate(
                style, size=content.shape[-2:], mode="bilinear", align_corners=False
            )

        # VGG19 特征提取（features 部分）
        vgg = models.vgg19(weights=models.VGG19_Weights.IMAGENET1K_V1).features
        vgg.to(device).eval()

        # ImageNet mean/std 归一化
        mean = torch.tensor([0.485, 0.456, 0.406], device=device).view(1, 3, 1, 1)
        std = torch.tensor([0.229, 0.224, 0.225], device=device).view(1, 3, 1, 1)

        # 捕获 relu 层特征（用 enumerate 方式给 relu 编号）
        # 典型选择：
        # - content: relu4_2
        # - style: relu1_1, relu2_1, relu3_1, relu4_1, relu5_1
        relu_name_by_index: Dict[int, str] = {}
        block = 1
        relu_in_block = 0
        for idx, layer in enumerate(vgg):
            # VGG features 里：MaxPool2d 之后进入下一个 block
            if isinstance(layer, torch.nn.MaxPool2d):
                block += 1
                relu_in_block = 0
                continue
            if isinstance(layer, torch.nn.ReLU):
                relu_in_block += 1
                relu_name_by_index[idx] = f"relu{block}_{relu_in_block}"

        content_layer = "relu4_2"
        style_layers = {"relu1_1", "relu2_1", "relu3_1", "relu4_1", "relu5_1"}

        def get_features(x_norm: torch.Tensor) -> Dict[str, torch.Tensor]:
            feats: Dict[str, torch.Tensor] = {}
            y = x_norm
            for idx, layer in enumerate(vgg):
                y = layer(y)
                name = relu_name_by_index.get(idx)
                if name is not None:
                    if name == content_layer or name in style_layers:
                        feats[name] = y
            return feats

        progress_callback(10)
        with torch.no_grad():
            content_norm = (content - mean) / std
            style_norm = (style - mean) / std
            content_feats = get_features(content_norm)
            style_feats = get_features(style_norm)

        generated = content.clone().requires_grad_(True)

        # strength 直接映射到 style_weight
        strength = float(strength)
        if strength < 0:
            strength = 0.0
        if strength > 3:
            strength = 3.0

        # 调大风格权重、减小内容权重，避免“看起来不明显”
        base_style_weight = 2e5
        base_content_weight = 1e-2
        style_weight = base_style_weight * strength
        content_weight = base_content_weight

        def gram_matrix(feat: torch.Tensor) -> torch.Tensor:
            # feat: [1,C,H,W] -> [C, C]
            b, c, h, w = feat.shape
            f = feat.view(c, h * w)
            # 归一化：让风格损失尺度更稳定，减少训练“偏内容/偏原图”的概率
            g = torch.mm(f, f.t())
            return g / (c * h * w)

        # 迭代次数：建议更高一点才能更明显
        num_steps = 140
        lr = 0.01
        optimizer = torch.optim.Adam([generated], lr=lr)

        for step in range(num_steps):
            optimizer.zero_grad()
            gen_norm = (generated - mean) / std
            gen_feats = get_features(gen_norm)

            # content loss
            c_loss = torch.nn.functional.mse_loss(
                gen_feats[content_layer], content_feats[content_layer]
            )

            # style loss
            s_loss = 0.0
            for ln in style_layers:
                g = gram_matrix(gen_feats[ln])
                s = gram_matrix(style_feats[ln])
                s_loss = s_loss + torch.nn.functional.mse_loss(g, s)

            loss = content_weight * c_loss + style_weight * s_loss
            loss.backward()
            optimizer.step()

            # 保持在 0..1
            with torch.no_grad():
                generated.clamp_(0.0, 1.0)

            progress = int((step + 1) / num_steps * 90) + 10
            progress_callback(progress)

        out = generated.detach()
        # 输出回到原尺寸
        if out.shape[-2:] != (orig_h, orig_w):
            out = torch.nn.functional.interpolate(
                out, size=(orig_h, orig_w), mode="bilinear", align_corners=False
            )

        # 保存到 output_path
        save_tensor_image(out, output_path)
        progress_callback(100)
        return

    # 2) CycleGAN 风格生成器
    if model_name in {"cyclegan_g_ab", "cyclegan_style_ukiyoe"}:
        device = get_device()
        # 使用 PIL+ToTensor 读图（0~1）
        content = load_image(content_path).to(device)  # [1,3,H,W], 0~1

        # 归一化组合在不同训练代码里可能不一致：
        # - 典型 CycleGAN：输入 [-1,1]，输出 tanh [-1,1]，再映射到 [0,1]
        # - 有些导出/预处理：输入直接 [0,1]
        # 为了避免“生成像原图”，这里跑两次并自动选择更有风格差异的结果。
        with torch.no_grad():
            progress_callback(10)

            # A) 输入 [-1,1]
            y_a = model(content * 2.0 - 1.0)  # type: ignore[call-arg]
            progress_callback(55)
            y_a = (y_a + 1.0) / 2.0
            y_a = y_a.clamp(0.0, 1.0)
            if y_a.shape[-2:] != content.shape[-2:]:
                y_a = torch.nn.functional.interpolate(
                    y_a,
                    size=content.shape[-2:],
                    mode="bilinear",
                    align_corners=False,
                )

            # B) 输入 [0,1]
            y_b = model(content)  # type: ignore[call-arg]
            progress_callback(75)
            y_b = (y_b + 1.0) / 2.0
            y_b = y_b.clamp(0.0, 1.0)
            if y_b.shape[-2:] != content.shape[-2:]:
                y_b = torch.nn.functional.interpolate(
                    y_b,
                    size=content.shape[-2:],
                    mode="bilinear",
                    align_corners=False,
                )

            # 选择输出差异更大的版本（更可能“风格迁移明显”）
            diff_a = torch.mean(torch.abs(y_a - content)).item()
            diff_b = torch.mean(torch.abs(y_b - content)).item()
            y = y_a if diff_a >= diff_b else y_b

        progress_callback(95)
        # 风格增强混合：strength=0 -> 原图，strength=1 -> 模型结果，strength>1 -> 更明显风格
        strength = float(strength)
        if strength < 0.0:
            strength = 0.0
        if strength > 3.0:
            strength = 3.0
        out = content + strength * (y - content)
        out = out.clamp(0.0, 1.0)

        save_tensor_image(out, output_path)
        progress_callback(100)
        return

    # 3) 其余 torch 模型：示例逻辑
    device = get_device()
    content = load_image(content_path).to(device)

    # 快速风格模型：单次前向
    # 当前 AVAILABLE_MODELS 已删减，因此这里保留占位即可

    # 经典慢风格迁移（极度简化版，只作为进度展示示例）
    input_img = content.clone().requires_grad_(True)
    optimizer = torch.optim.LBFGS([input_img])

    num_steps = 50
    step = 0

    def closure():
        nonlocal step
        optimizer.zero_grad()
        # 这里理论上应该是内容损失+风格损失，我们用一个简单的 L2 占位
        loss = torch.nn.functional.mse_loss(input_img, content)
        loss.backward()
        step += 1
        progress = min(100, int(step / num_steps * 100))
        progress_callback(progress)
        return loss

    while step < num_steps:
        optimizer.step(closure)

    save_tensor_image(input_img.detach(), output_path)
    progress_callback(100)
