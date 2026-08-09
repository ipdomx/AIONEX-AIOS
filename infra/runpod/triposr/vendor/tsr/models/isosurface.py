from typing import Optional, Tuple

import numpy as np
import torch
import torch.nn as nn
from skimage import measure


class IsosurfaceHelper(nn.Module):
    points_range: Tuple[float, float] = (0, 1)

    @property
    def grid_vertices(self) -> torch.FloatTensor:
        raise NotImplementedError


class MarchingCubeHelper(IsosurfaceHelper):
    """CPU marching cubes fallback without a compiled CUDA extension."""

    def __init__(self, resolution: int) -> None:
        super().__init__()
        self.resolution = resolution
        self._grid_vertices: Optional[torch.FloatTensor] = None

    @property
    def grid_vertices(self) -> torch.FloatTensor:
        if self._grid_vertices is None:
            x, y, z = (
                torch.linspace(*self.points_range, self.resolution),
                torch.linspace(*self.points_range, self.resolution),
                torch.linspace(*self.points_range, self.resolution),
            )
            x, y, z = torch.meshgrid(x, y, z, indexing="ij")
            self._grid_vertices = torch.cat(
                [x.reshape(-1, 1), y.reshape(-1, 1), z.reshape(-1, 1)], dim=-1
            ).reshape(-1, 3)
        return self._grid_vertices

    def forward(self, level: torch.FloatTensor) -> Tuple[torch.FloatTensor, torch.LongTensor]:
        device = level.device
        volume = (-level).view(self.resolution, self.resolution, self.resolution).detach().float().cpu().numpy()
        vertices, faces, _, _ = measure.marching_cubes(volume, level=0.0)
        vertices = np.asarray(vertices[:, [2, 1, 0]], dtype=np.float32) / (self.resolution - 1.0)
        faces = np.asarray(faces, dtype=np.int64).copy()
        return torch.from_numpy(vertices).to(device), torch.from_numpy(faces).to(device)
