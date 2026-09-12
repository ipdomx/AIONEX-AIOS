"""Companion backup for the local media asset volume."""
from __future__ import annotations

from app.core.config import Settings, settings
from app.services.file_tree_snapshot import FileTreeSnapshotExecutor


class MediaAssetSnapshotExecutor(FileTreeSnapshotExecutor):
    def __init__(self, config: Settings = settings) -> None:
        super().__init__(
            enabled=bool(config.BACKUP_MEDIA_ASSETS_ENABLED),
            source_root=config.MEDIA_STORAGE_ROOT,
            backup_dir=config.BACKUP_DIR,
            slug="media-assets",
            manifest_kind="aionex-media-assets",
            label="media asset",
        )
