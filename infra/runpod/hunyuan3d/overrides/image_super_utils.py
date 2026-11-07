"""AIONEX replacement for hy3dpaint/utils/image_super_utils.py (FR-16D).

Upstream builds Real-ESRGAN x4plus through ``realesrgan``/``basicsr``, which
loads the pickled ``RealESRGAN_x4plus.pth`` with ``torch.load``, may download
weights from a URL and drags in tb-nightly, lmdb and other unused packages.
This file keeps the same ``imageSuperNet`` interface and numerics for the
tile-free, pre_pad=0, 4x RGB path Hunyuan uses, but loads the network from the
build-time converted, checksum-verified safetensors file only.

The RRDBNet architecture below follows basicsr/archs/rrdbnet_arch.py
(Apache License 2.0, Copyright (c) 2022 BasicSR Authors), reduced to inference.
"""
from __future__ import annotations

import numpy as np
from PIL import Image
import safetensors.torch
import torch
from torch import nn
from torch.nn import functional as F


class ResidualDenseBlock(nn.Module):
    def __init__(self, num_feat: int = 64, num_grow_ch: int = 32) -> None:
        super().__init__()
        self.conv1 = nn.Conv2d(num_feat, num_grow_ch, 3, 1, 1)
        self.conv2 = nn.Conv2d(num_feat + num_grow_ch, num_grow_ch, 3, 1, 1)
        self.conv3 = nn.Conv2d(num_feat + 2 * num_grow_ch, num_grow_ch, 3, 1, 1)
        self.conv4 = nn.Conv2d(num_feat + 3 * num_grow_ch, num_grow_ch, 3, 1, 1)
        self.conv5 = nn.Conv2d(num_feat + 4 * num_grow_ch, num_feat, 3, 1, 1)
        self.lrelu = nn.LeakyReLU(negative_slope=0.2, inplace=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x1 = self.lrelu(self.conv1(x))
        x2 = self.lrelu(self.conv2(torch.cat((x, x1), 1)))
        x3 = self.lrelu(self.conv3(torch.cat((x, x1, x2), 1)))
        x4 = self.lrelu(self.conv4(torch.cat((x, x1, x2, x3), 1)))
        x5 = self.conv5(torch.cat((x, x1, x2, x3, x4), 1))
        return x5 * 0.2 + x


class RRDB(nn.Module):
    def __init__(self, num_feat: int, num_grow_ch: int = 32) -> None:
        super().__init__()
        self.rdb1 = ResidualDenseBlock(num_feat, num_grow_ch)
        self.rdb2 = ResidualDenseBlock(num_feat, num_grow_ch)
        self.rdb3 = ResidualDenseBlock(num_feat, num_grow_ch)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out = self.rdb1(x)
        out = self.rdb2(out)
        out = self.rdb3(out)
        return out * 0.2 + x


class RRDBNet(nn.Module):
    """Real-ESRGAN x4plus generator (scale 4: no pixel-unshuffle)."""

    def __init__(self, num_in_ch: int = 3, num_out_ch: int = 3, num_feat: int = 64, num_block: int = 23, num_grow_ch: int = 32) -> None:
        super().__init__()
        self.conv_first = nn.Conv2d(num_in_ch, num_feat, 3, 1, 1)
        self.body = nn.Sequential(*[RRDB(num_feat, num_grow_ch) for _ in range(num_block)])
        self.conv_body = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.conv_up1 = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.conv_up2 = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.conv_hr = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.conv_last = nn.Conv2d(num_feat, num_out_ch, 3, 1, 1)
        self.lrelu = nn.LeakyReLU(negative_slope=0.2, inplace=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        feat = self.conv_first(x)
        feat = feat + self.conv_body(self.body(feat))
        feat = self.lrelu(self.conv_up1(F.interpolate(feat, scale_factor=2, mode="nearest")))
        feat = self.lrelu(self.conv_up2(F.interpolate(feat, scale_factor=2, mode="nearest")))
        return self.conv_last(self.lrelu(self.conv_hr(feat)))


class imageSuperNet:  # noqa: N801 - upstream interface name
    def __init__(self, config) -> None:
        path = str(config.realesrgan_ckpt_path)
        if not path.endswith(".safetensors"):
            raise RuntimeError("Real-ESRGAN weights must be a baked safetensors file")
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32)
        model.load_state_dict(safetensors.torch.load_file(path, device="cpu"), strict=True)
        model.eval()
        self.model = model.to(self.device)
        self.half = self.device.type == "cuda"
        if self.half:
            self.model = self.model.half()

    @torch.no_grad()
    def __call__(self, image: Image.Image) -> Image.Image:
        # Mirrors RealESRGANer.enhance(np.array(image)) for 8-bit RGB input,
        # tile=0, pre_pad=0, outscale=None: the array is treated as BGR and
        # flipped to RGB, then the output is flipped back.
        array = np.array(image.convert("RGB")).astype(np.float32) / 255.0
        array = array[:, :, ::-1]
        tensor = torch.from_numpy(np.ascontiguousarray(np.transpose(array, (2, 0, 1)))).float().unsqueeze(0).to(self.device)
        if self.half:
            tensor = tensor.half()
        output = self.model(tensor).data.squeeze().float().cpu().clamp_(0, 1).numpy()
        output = np.transpose(output[[2, 1, 0], :, :], (1, 2, 0))
        return Image.fromarray((output * 255.0).round().astype(np.uint8))
