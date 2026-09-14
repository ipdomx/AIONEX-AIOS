#!/usr/bin/env python3
"""FR-06B3A isolated LUKS2, Docker restart, admission, and rollback lab."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ASSET_ROOTS = (
    "three_d_asset_data",
    "media_asset_data",
    "studio_asset_data",
    "course_package_data",
    "realtime_recording_data",
    "portal_asset_data",
    "mobile_release_data",
    "audio_song_ingress_data",
    "security_source_data",
    "security_remediation_data",
)
PROJECT_ROOTS = ("project_execution_data",)
ALL_ROOTS = (
    "three_d_asset_data",
    "media_asset_data",
    "project_execution_data",
    "studio_asset_data",
    "course_package_data",
    "realtime_recording_data",
    "portal_asset_data",
    "mobile_release_data",
    "audio_song_ingress_data",
    "security_source_data",
    "security_remediation_data",
)


class LabError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def exclusive_json(path: Path, value: dict[str, Any], mode: int = 0o600) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
    fd = os.open(path, flags, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


class Lab:
    def __init__(self, receipt: Path) -> None:
        self.receipt = receipt
        self.source_root = Path(__file__).resolve().parents[2]
        self.gate = self.source_root / "scripts/security/fr06b_cutover_admission.py"
        self.manifest = self.source_root / "scripts/security/fr06b_asset_copy_manifest.py"
        self.env_file = self.source_root / "web-dashboard/.env.production.example"
        self.lab_root = Path(
            subprocess.run(
                ["mktemp", "-d", "/var/tmp/aionex-fr06b3a-lab.XXXXXX"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        self.key_root = Path(
            subprocess.run(
                ["mktemp", "-d", "/dev/shm/aionex-fr06b3a-keys.XXXXXX"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        self.header_root = Path(
            subprocess.run(
                ["mktemp", "-d", "/dev/shm/aionex-fr06b3a-headers.XXXXXX"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        self._require_prefix(self.lab_root, "/var/tmp/aionex-fr06b3a-lab.")
        self._require_prefix(self.key_root, "/dev/shm/aionex-fr06b3a-keys.")
        self._require_prefix(self.header_root, "/dev/shm/aionex-fr06b3a-headers.")
        suffix = self.lab_root.name.rsplit(".", 1)[-1]
        if not suffix.isalnum():
            raise LabError("unsafe temporary suffix")
        lower = suffix.lower()
        self.asset_mapper_name = f"aionex-fr06b3a-asset-{suffix}"
        self.project_mapper_name = f"aionex-fr06b3a-project-{suffix}"
        self.asset_wrong_name = f"{self.asset_mapper_name}-wrong"
        self.project_wrong_name = f"{self.project_mapper_name}-wrong"
        self.asset_mapper = Path("/dev/mapper") / self.asset_mapper_name
        self.project_mapper = Path("/dev/mapper") / self.project_mapper_name
        self.asset_image = self.lab_root / "asset.luks2"
        self.project_image = self.lab_root / "project.luks2"
        self.asset_mount = self.lab_root / "asset-mount"
        self.project_mount = self.lab_root / "project-mount"
        self.legacy = self.lab_root / "legacy"
        self.legacy_view = self.lab_root / "legacy-retained"
        self.pre_rollback = self.lab_root / "pre-admission-rollback"
        self.manifests = self.lab_root / "manifests"
        self.data_root = self.lab_root / "docker-data"
        self.exec_root = self.lab_root / "docker-exec"
        self.socket = self.lab_root / "docker.sock"
        self.pidfile = self.lab_root / "dockerd.pid"
        self.docker_host = f"unix://{self.socket}"
        self.containerd_ns = f"fr06b3a-{lower}"
        self.plugin_ns = f"fr06b3a-plugins-{lower}"
        self.image = f"fr06b3a-busybox:{lower}"
        self.asset_volume = f"fr06b3a-{lower}-asset"
        self.project_volume = f"fr06b3a-{lower}-project"
        self.control = f"fr06b3a-{lower}-unless-control"
        self.failure_control = f"fr06b3a-{lower}-on-failure-control"
        self.asset_container = f"fr06b3a-{lower}-asset-candidate"
        self.project_container = f"fr06b3a-{lower}-project-candidate"
        self.asset_active = self.key_root / "asset-active.key"
        self.asset_recovery = self.key_root / "asset-recovery.key"
        self.project_active = self.key_root / "project-active.key"
        self.project_recovery = self.key_root / "project-recovery.key"
        self.wrong_key = self.key_root / "wrong.key"
        self.asset_header = self.header_root / "asset-header.backup"
        self.project_header = self.header_root / "project-header.backup"
        self.daemon_log = self.lab_root / "dockerd.log"
        self.daemon: subprocess.Popen[bytes] | None = None
        self.daemon_stream = None
        self.legacy_view_mounted = False
        self.production_digest_before = ""
        self.production_docker_id = ""
        self.isolated_docker_id = ""
        self.isolated_docker_version = ""
        for directory in (
            self.asset_mount,
            self.project_mount,
            self.legacy,
            self.legacy_view,
            self.pre_rollback,
            self.manifests,
            self.data_root,
            self.exec_root,
        ):
            directory.mkdir(mode=0o700)

    @staticmethod
    def _require_prefix(path: Path, prefix: str) -> None:
        if not str(path).startswith(prefix):
            raise LabError(f"unsafe temporary path: {path}")

    def run(
        self,
        command: list[str],
        *,
        timeout: int = 120,
        input_bytes: bytes | None = None,
    ) -> str:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            input=input_bytes,
            timeout=timeout,
        )
        if result.returncode != 0:
            raise LabError(
                f"{Path(command[0]).name} failed with exit code {result.returncode}; "
                "output withheld"
            )
        return result.stdout.decode("utf-8", "strict").strip()

    def run_result(self, command: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(command, check=False, capture_output=True, timeout=timeout)

    def iso_command(self, *arguments: str) -> list[str]:
        return ["docker", "--host", self.docker_host, *arguments]

    def iso(self, *arguments: str, timeout: int = 120) -> str:
        return self.run(self.iso_command(*arguments), timeout=timeout)

    def production_container_digest(self) -> str:
        value = self.run(
            ["docker", "ps", "--no-trunc", "--format", "{{.ID}} {{.Names}}"]
        )
        canonical = "\n".join(sorted(value.splitlines()))
        if canonical:
            canonical += "\n"
        return hashlib.sha256(canonical.encode()).hexdigest()

    def start_daemon(self) -> None:
        if self.daemon is not None:
            raise LabError("isolated Docker daemon is already running")
        self.socket.unlink(missing_ok=True)
        self.pidfile.unlink(missing_ok=True)
        self.daemon_stream = self.daemon_log.open("ab", buffering=0)
        command = [
            "dockerd",
            "--data-root", str(self.data_root),
            "--exec-root", str(self.exec_root),
            "--pidfile", str(self.pidfile),
            "--host", self.docker_host,
            "--bridge", "none",
            "--iptables=false",
            "--ip6tables=false",
            "--ip-forward=false",
            "--ip-masq=false",
            "--storage-driver", "vfs",
            "--containerd-namespace", self.containerd_ns,
            "--containerd-plugins-namespace", self.plugin_ns,
            "--shutdown-timeout", "5",
            "--log-level", "error",
        ]
        self.daemon = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=self.daemon_stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        for _ in range(80):
            if self.run_result(self.iso_command("info"), timeout=5).returncode == 0:
                return
            if self.daemon.poll() is not None:
                raise LabError("isolated Docker daemon exited during startup")
            time.sleep(0.25)
        raise LabError("isolated Docker daemon did not become ready")

    def stop_daemon(self) -> None:
        if self.daemon is None:
            return
        process = self.daemon
        self.daemon = None
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        if self.daemon_stream is not None:
            self.daemon_stream.close()
            self.daemon_stream = None
        self.socket.unlink(missing_ok=True)
        self.pidfile.unlink(missing_ok=True)

    def unmount_mapper_targets(self, mapper: Path) -> None:
        result = self.run_result(
            ["findmnt", "-rn", "-S", str(mapper), "-o", "TARGET"], timeout=15
        )
        if result.returncode not in (0, 1):
            raise LabError("cannot inspect mapper mount targets")
        for raw in result.stdout.decode().splitlines():
            target = Path(raw)
            allowed = (
                target in {self.asset_mount, self.project_mount}
                or str(target).startswith(str(self.data_root / "volumes") + "/")
            )
            if not allowed:
                raise LabError(f"refusing to unmount unexpected target: {target}")
            self.run(["umount", str(target)], timeout=30)

    def close_mapper(self, name: str, path: Path) -> None:
        if path.exists():
            self.run(["cryptsetup", "close", name], timeout=30)

    def cleanup(self) -> None:
        try:
            if self.daemon is not None:
                for container in (self.control, self.failure_control, self.asset_container, self.project_container):
                    self.run_result(self.iso_command("rm", "-f", container), timeout=30)
                for volume in (self.asset_volume, self.project_volume):
                    if not (
                        volume.startswith("fr06b3a-")
                        and (volume.endswith("-asset") or volume.endswith("-project"))
                    ):
                        raise LabError("unsafe isolated volume name")
                    self.run_result(self.iso_command("volume", "rm", "-f", volume), timeout=30)
                self.run_result(self.iso_command("image", "rm", "-f", self.image), timeout=30)
        finally:
            self.stop_daemon()
        if self.legacy_view_mounted and self.legacy_view.exists():
            self.run_result(["umount", str(self.legacy_view)], timeout=30)
            self.legacy_view_mounted = False
        for mapper in (self.project_mapper, self.asset_mapper):
            try:
                self.unmount_mapper_targets(mapper)
            except LabError:
                pass
        for name, path in (
            (self.asset_wrong_name, Path("/dev/mapper") / self.asset_wrong_name),
            (self.project_wrong_name, Path("/dev/mapper") / self.project_wrong_name),
            (self.project_mapper_name, self.project_mapper),
            (self.asset_mapper_name, self.asset_mapper),
        ):
            if path.exists():
                self.run_result(["cryptsetup", "close", name], timeout=30)
        for path, prefix in (
            (self.key_root, "/dev/shm/aionex-fr06b3a-keys."),
            (self.header_root, "/dev/shm/aionex-fr06b3a-headers."),
            (self.lab_root, "/var/tmp/aionex-fr06b3a-lab."),
        ):
            self._require_prefix(path, prefix)
            if path.exists():
                shutil.rmtree(path)

    def create_key(self, path: Path) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
        fd = os.open(path, flags, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(os.urandom(64))
            stream.flush()
            os.fsync(stream.fileno())
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1:
            raise LabError("unsafe temporary key")

    def prepare_vault(
        self,
        image: Path,
        active: Path,
        recovery: Path,
        mapper_name: str,
        label: str,
    ) -> None:
        self.run(["fallocate", "-l", "192M", str(image)])
        image.chmod(0o600)
        info = image.stat()
        if info.st_blocks * 512 < info.st_size:
            raise LabError("sparse lab image rejected")
        self.run(
            [
                "cryptsetup", "luksFormat", "--type", "luks2",
                "--cipher", "aes-xts-plain64", "--key-size", "512",
                "--pbkdf", "argon2id", "--batch-mode",
                "--key-file", str(active), str(image),
            ],
            timeout=180,
        )
        self.run(
            [
                "cryptsetup", "luksAddKey", str(image), str(recovery),
                "--key-file", str(active),
            ],
            timeout=180,
        )
        self.run(
            [
                "cryptsetup", "open", "--type", "luks",
                "--key-file", str(active), str(image), mapper_name,
            ]
        )
        self.run(["mkfs.ext4", "-q", "-L", label, f"/dev/mapper/{mapper_name}"])

    def candidate_root(self, name: str) -> Path:
        if name == "project_execution_data":
            return self.project_mount / name
        return self.asset_mount / name

    def sync_tree(self, source: Path, target: Path) -> None:
        target.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.run(
            [
                "rsync", "-aH", "--numeric-ids", "--delete", "--safe-links",
                "--no-specials", "--no-devices", f"{source}/", f"{target}/",
            ]
        )
        observed = source.stat()
        os.chown(target, observed.st_uid, observed.st_gid)
        os.chmod(target, stat.S_IMODE(observed.st_mode))

    def manifest_tree(self, root: Path, output: Path) -> None:
        self.run(
            [sys.executable, str(self.manifest), "manifest", "--root", str(root), "--output", str(output)]
        )

    def compare(self, left: Path, right: Path) -> None:
        self.run(
            [sys.executable, str(self.manifest), "compare", "--left", str(left), "--right", str(right)]
        )

    def state(self, container: str) -> bool:
        return self.iso("inspect", "--format", "{{.State.Running}}", container) == "true"

    def wait_running(self, container: str) -> None:
        for _ in range(40):
            if self.state(container):
                return
            time.sleep(0.25)
        raise LabError(f"isolated control container did not restart: {container}")

    def inspect_runtime(self, output: Path) -> None:
        stdout = self.run(
            [
                sys.executable,
                str(self.gate),
                "inspect-runtime",
                "--root", str(self.source_root),
                "--env-file", str(self.env_file),
                "--docker-host", self.docker_host,
                "--environment", "isolated_lab",
                "--asset-mapper", str(self.asset_mapper),
                "--project-mapper", str(self.project_mapper),
                "--asset-mount-root", str(self.asset_mount),
                "--project-mount-root", str(self.project_mount),
                "--asset-volume", self.asset_volume,
                "--project-volume", self.project_volume,
            ]
        )
        output.write_text(stdout + "\n", encoding="utf-8")
        output.chmod(0o600)

    def evaluate(self, evidence: Path, snapshot: Path, output: Path) -> None:
        stdout = self.run(
            [
                sys.executable,
                str(self.gate),
                "evaluate",
                "--evidence", str(evidence),
                "--snapshot", str(snapshot),
                "--allow-isolated-lab",
            ]
        )
        value = json.loads(stdout)
        if value.get("preflight_passed") is not True or value.get("production_authorized") is not False:
            raise LabError("isolated preflight decision was not safely bounded")
        output.write_text(stdout + "\n", encoding="utf-8")
        output.chmod(0o600)

    def run_lab(self) -> dict[str, Any]:
        if os.geteuid() != 0:
            raise LabError("FR-06B3A lab requires root")
        if not self.receipt.is_absolute() or self.receipt.exists():
            raise LabError("receipt must be a new absolute path")
        if self.run(["findmnt", "-n", "-o", "FSTYPE", "--target", "/dev/shm"]) != "tmpfs":
            raise LabError("/dev/shm must be tmpfs")
        for required in (self.gate, self.manifest, self.env_file):
            if not required.is_file() or required.is_symlink():
                raise LabError("required source file missing")
        file_output = self.run(["file", "-b", "/usr/bin/busybox"])
        if "statically linked" not in file_output:
            raise LabError("a static busybox binary is required")

        self.production_digest_before = self.production_container_digest()
        self.production_docker_id = self.run(["docker", "info", "--format", "{{.ID}}"])
        for path in (
            self.asset_active,
            self.asset_recovery,
            self.project_active,
            self.project_recovery,
            self.wrong_key,
        ):
            self.create_key(path)
        key_hashes = {
            hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (
                self.asset_active,
                self.asset_recovery,
                self.project_active,
                self.project_recovery,
                self.wrong_key,
            )
        }
        if len(key_hashes) != 5:
            raise LabError("temporary keys are not independent")

        self.prepare_vault(
            self.asset_image,
            self.asset_active,
            self.asset_recovery,
            self.asset_mapper_name,
            "AIONEX_B3A_A",
        )
        self.prepare_vault(
            self.project_image,
            self.project_active,
            self.project_recovery,
            self.project_mapper_name,
            "AIONEX_B3A_P",
        )
        self.run(
            [
                "cryptsetup", "luksHeaderBackup", str(self.asset_image),
                "--header-backup-file", str(self.asset_header),
            ]
        )
        self.run(
            [
                "cryptsetup", "luksHeaderBackup", str(self.project_image),
                "--header-backup-file", str(self.project_header),
            ]
        )
        self.asset_header.chmod(0o400)
        self.project_header.chmod(0o400)
        if self.asset_header.parent == self.key_root or self.project_header.parent == self.key_root:
            raise LabError("header backup custody was not separated")
        if hashlib.sha256(self.asset_header.read_bytes()).digest() == hashlib.sha256(
            self.project_header.read_bytes()
        ).digest():
            raise LabError("distinct vault headers unexpectedly match")

        self.run(
            ["mount", "-o", "nodev,nosuid,noexec", str(self.asset_mapper), str(self.asset_mount)]
        )
        self.run(
            ["mount", "-o", "nodev,nosuid", str(self.project_mapper), str(self.project_mount)]
        )
        for name in ALL_ROOTS:
            legacy_root = self.legacy / name
            legacy_root.mkdir(mode=0o750)
            (legacy_root / "preseed.txt").write_text(
                f"preseed:{name}\n", encoding="utf-8"
            )
            self.sync_tree(legacy_root, self.candidate_root(name))
            (legacy_root / "final-delta.txt").write_text(
                f"final-delta:{name}\n", encoding="utf-8"
            )
            source_pre = self.manifests / f"{name}.source-pre.json"
            source_post = self.manifests / f"{name}.source-post.json"
            candidate = self.manifests / f"{name}.candidate.json"
            self.manifest_tree(legacy_root, source_pre)
            self.sync_tree(legacy_root, self.candidate_root(name))
            self.manifest_tree(legacy_root, source_post)
            self.manifest_tree(self.candidate_root(name), candidate)
            self.compare(source_pre, source_post)
            self.compare(source_post, candidate)
        self.run(["sync", "-f", str(self.asset_mount)])
        self.run(["sync", "-f", str(self.project_mount)])

        self.run(["mount", "--bind", str(self.legacy), str(self.legacy_view)])
        self.legacy_view_mounted = True
        self.run(
            [
                "mount", "-o", "remount,bind,ro,nodev,nosuid,noexec",
                str(self.legacy_view),
            ]
        )
        options = set(
            self.run(["findmnt", "-n", "-o", "OPTIONS", "--target", str(self.legacy_view)]).split(",")
        )
        if "ro" not in options:
            raise LabError("retained legacy view is not read-only")
        try:
            (self.legacy_view / "write-must-fail").write_text("forbidden\n", encoding="utf-8")
        except OSError:
            pass
        else:
            raise LabError("retained legacy read-only view accepted a write")

        for name in ALL_ROOTS:
            target = self.pre_rollback / name
            self.sync_tree(self.legacy_view / name, target)
            pre_rollback = self.manifests / f"{name}.pre-rollback.json"
            self.manifest_tree(target, pre_rollback)
            self.compare(self.manifests / f"{name}.source-post.json", pre_rollback)

        self.start_daemon()
        self.isolated_docker_id = self.iso("info", "--format", "{{.ID}}")
        if not self.isolated_docker_id or self.isolated_docker_id == self.production_docker_id:
            raise LabError("isolated Docker identity was not independent")
        self.isolated_docker_version = self.iso("version", "--format", "{{.Server.Version}}")
        rootfs = self.lab_root / "rootfs"
        (rootfs / "bin").mkdir(parents=True)
        shutil.copy2("/usr/bin/busybox", rootfs / "bin/busybox")
        (rootfs / "bin/sh").symlink_to("busybox")
        archive = self.lab_root / "busybox.tar"
        with tarfile.open(archive, "w") as output:
            output.add(rootfs, arcname=".")
        self.iso("import", str(archive), self.image)

        self.iso(
            "volume", "create", "--driver", "local",
            "--opt", "type=ext4",
            "--opt", f"device={self.asset_mapper}",
            "--opt", "o=nodev,nosuid,noexec",
            self.asset_volume,
        )
        self.iso(
            "volume", "create", "--driver", "local",
            "--opt", "type=ext4",
            "--opt", f"device={self.project_mapper}",
            "--opt", "o=nodev,nosuid",
            self.project_volume,
        )
        common = [
            "create",
            "--read-only",
            "--network", "none",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--entrypoint", "/bin/busybox",
        ]
        self.iso(
            *common,
            "--name", self.control,
            "--restart", "unless-stopped",
            "--mount",
            f"type=volume,src={self.asset_volume},dst=/data,volume-subpath=media_asset_data",
            self.image,
            "sh", "-c", "while :; do sleep 60; done",
        )
        self.iso(
            *common,
            "--name", self.failure_control,
            "--restart", "on-failure:5",
            "--mount",
            f"type=volume,src={self.asset_volume},dst=/data,volume-subpath=media_asset_data",
            self.image,
            "sh", "-c", "while :; do sleep 60; done",
        )
        self.iso(
            *common,
            "--name", self.asset_container,
            "--restart", "no",
            "--mount",
            f"type=volume,src={self.asset_volume},dst=/data,volume-subpath=media_asset_data",
            self.image,
            "sh", "-c", "while :; do sleep 60; done",
        )
        self.iso(
            *common,
            "--name", self.project_container,
            "--restart", "no",
            "--mount",
            f"type=volume,src={self.project_volume},dst=/data,volume-subpath=project_execution_data",
            self.image,
            "sh", "-c", "while :; do sleep 60; done",
        )
        self.iso("start", self.control, self.failure_control, self.asset_container, self.project_container)
        if not all(self.state(name) for name in (self.control, self.failure_control, self.asset_container, self.project_container)):
            raise LabError("initial isolated containers did not start")

        self.stop_daemon()
        self.start_daemon()
        self.wait_running(self.control)
        self.wait_running(self.failure_control)
        if self.state(self.asset_container) or self.state(self.project_container):
            raise LabError("restart-no candidate restored after daemon restart")

        self.stop_daemon()
        self.run(["umount", str(self.project_mount)])
        self.run(["umount", str(self.asset_mount)])
        self.unmount_mapper_targets(self.project_mapper)
        self.unmount_mapper_targets(self.asset_mapper)
        self.close_mapper(self.project_mapper_name, self.project_mapper)
        self.close_mapper(self.asset_mapper_name, self.asset_mapper)
        if self.asset_mapper.exists() or self.project_mapper.exists():
            raise LabError("temporary mapper remained open")

        for image, wrong_name in (
            (self.asset_image, self.asset_wrong_name),
            (self.project_image, self.project_wrong_name),
        ):
            result = self.run_result(
                [
                    "cryptsetup", "open", "--type", "luks",
                    "--key-file", str(self.wrong_key), str(image), wrong_name,
                ],
                timeout=30,
            )
            if result.returncode == 0:
                self.run_result(["cryptsetup", "close", wrong_name])
                raise LabError("wrong key opened a lab vault")

        self.start_daemon()
        missing = self.run_result(
            [
                sys.executable,
                str(self.gate),
                "inspect-runtime",
                "--root", str(self.source_root),
                "--env-file", str(self.env_file),
                "--docker-host", self.docker_host,
                "--environment", "isolated_lab",
                "--asset-mapper", str(self.asset_mapper),
                "--project-mapper", str(self.project_mapper),
                "--asset-mount-root", str(self.asset_mount),
                "--project-mount-root", str(self.project_mount),
                "--asset-volume", self.asset_volume,
                "--project-volume", self.project_volume,
            ],
            timeout=180,
        )
        if missing.returncode != 2:
            raise LabError("missing mapper did not block runtime admission")
        missing_value = json.loads(missing.stdout.decode())
        if missing_value.get("preflight_passed") is not False:
            raise LabError("missing mapper block decision was malformed")
        missing_start = self.run_result(
            self.iso_command("start", self.asset_container), timeout=30
        )
        if missing_start.returncode == 0:
            raise LabError("missing mapper unexpectedly allowed candidate start")

        self.run(
            [
                "cryptsetup", "open", "--type", "luks",
                "--key-file", str(self.asset_recovery),
                str(self.asset_image), self.asset_mapper_name,
            ]
        )
        self.run(
            [
                "cryptsetup", "open", "--type", "luks",
                "--key-file", str(self.project_recovery),
                str(self.project_image), self.project_mapper_name,
            ]
        )
        self.run(
            ["mount", "-o", "nodev,nosuid,noexec", str(self.asset_mapper), str(self.asset_mount)]
        )
        self.run(
            ["mount", "-o", "nodev,nosuid", str(self.project_mapper), str(self.project_mount)]
        )
        if self.state(self.asset_container) or self.state(self.project_container):
            raise LabError("delayed unlock auto-started guarded candidates")

        for name in ALL_ROOTS:
            (self.candidate_root(name) / "candidate-write.txt").write_text(
                f"candidate-write:{name}\n", encoding="utf-8"
            )
        self.run(["umount", str(self.legacy_view)])
        self.legacy_view_mounted = False
        self.run(["mount", "--bind", str(self.legacy), str(self.legacy_view)])
        self.legacy_view_mounted = True
        self.run(
            [
                "mount", "-o", "remount,bind,rw,nodev,nosuid,noexec",
                str(self.legacy_view),
            ]
        )
        for name in ALL_ROOTS:
            source_pre = self.manifests / f"{name}.reverse-source-pre.json"
            source_post = self.manifests / f"{name}.reverse-source-post.json"
            target = self.manifests / f"{name}.reverse-target.json"
            self.manifest_tree(self.candidate_root(name), source_pre)
            self.sync_tree(self.candidate_root(name), self.legacy_view / name)
            self.manifest_tree(self.candidate_root(name), source_post)
            self.manifest_tree(self.legacy_view / name, target)
            self.compare(source_pre, source_post)
            self.compare(source_post, target)
        self.run(
            [
                "mount", "-o", "remount,bind,ro,nodev,nosuid,noexec",
                str(self.legacy_view),
            ]
        )

        snapshot_one = self.lab_root / "runtime-snapshot-one.json"
        snapshot_two = self.lab_root / "runtime-snapshot-two.json"
        evidence_path = self.lab_root / "evidence.json"
        decision_one = self.lab_root / "admission-one.json"
        decision_two = self.lab_root / "admission-two.json"
        self.inspect_runtime(snapshot_one)
        source_commit = self.run(["git", "-C", str(self.source_root), "rev-parse", "HEAD"])
        observed_at = utc_now()
        evidence = {
            "schema_version": 1,
            "environment": "isolated_lab",
            "observed_at": observed_at,
            "production_authorization": False,
            "safety": {
                "out_of_band_alert_passed": False,
                "boot_rehearsal_passed": False,
                "docker_restart_rehearsal_passed": True,
                "missing_mapper_rehearsal_passed": True,
                "wrong_key_rehearsal_passed": True,
                "delayed_unlock_rehearsal_passed": True,
                "pre_admission_rollback_passed": True,
                "post_admission_reverse_delta_rollback_passed": True,
            },
            "operations": {
                "admission_closed": True,
                "queues_drained": True,
                "writers_stopped": True,
                "initializers_stopped": True,
                "read_only_consumers_stopped": True,
                "no_unlisted_writable_descriptors": True,
                "final_delta_exact": True,
                "cloudflare_changed": False,
            },
            "source": {
                "lab_commit_sha": source_commit,
            },
        }
        exclusive_json(evidence_path, evidence)
        self.evaluate(evidence_path, snapshot_one, decision_one)

        self.iso("start", self.control, self.failure_control, self.asset_container, self.project_container)
        if not all(self.state(name) for name in (self.control, self.failure_control, self.asset_container, self.project_container)):
            raise LabError("explicit guarded start failed")
        self.stop_daemon()
        self.start_daemon()
        self.wait_running(self.control)
        self.wait_running(self.failure_control)
        if self.state(self.asset_container) or self.state(self.project_container):
            raise LabError("guarded candidates restored after second daemon restart")
        self.iso("stop", self.control, self.failure_control)
        self.inspect_runtime(snapshot_two)
        self.evaluate(evidence_path, snapshot_two, decision_two)
        self.iso("start", self.asset_container, self.project_container)
        if not self.state(self.asset_container) or not self.state(self.project_container):
            raise LabError("second explicit guarded start failed")

        for container in (self.control, self.failure_control, self.asset_container, self.project_container):
            self.iso("rm", "-f", container)
        for volume in (self.asset_volume, self.project_volume):
            self.iso("volume", "rm", volume)
        self.iso("image", "rm", "-f", self.image)
        self.stop_daemon()
        self.run(["umount", str(self.legacy_view)])
        self.legacy_view_mounted = False
        self.run(["umount", str(self.project_mount)])
        self.run(["umount", str(self.asset_mount)])
        self.unmount_mapper_targets(self.project_mapper)
        self.unmount_mapper_targets(self.asset_mapper)
        self.close_mapper(self.project_mapper_name, self.project_mapper)
        self.close_mapper(self.asset_mapper_name, self.asset_mapper)

        self.cleanup()
        if self.lab_root.exists() or self.key_root.exists() or self.header_root.exists():
            raise LabError("temporary lab resources remained")
        if self.asset_mapper.exists() or self.project_mapper.exists():
            raise LabError("temporary mapper remained after cleanup")
        production_after = self.production_container_digest()
        if production_after != self.production_digest_before:
            raise LabError("production container identity digest changed")
        if self.run(["docker", "info", "--format", "{{.ID}}"]) != self.production_docker_id:
            raise LabError("production Docker identity changed")

        return {
            "schema_version": 1,
            "observed_at": observed_at,
            "finished_at": utc_now(),
            "source_commit": source_commit,
            "batch_id": "FR-06",
            "subpart": "FR-06B3A",
            "lab": {
                "type": "two_file_backed_luks2_isolated_docker_admission_restart_and_rollback_rehearsal",
                "backing_file_bytes_each": 192 * 1024 * 1024,
                "filesystem": "ext4",
                "docker_server_version": self.isolated_docker_version,
                "keys_created_only_on_tmpfs": True,
                "headers_created_in_separate_tmpfs_directory": True,
                "key_material_persisted": False,
                "production_sources_used": False,
                "production_docker_daemon_used_for_lab_containers": False,
            },
            "restart_policy": {
                "control": "unless-stopped",
                "rejected_control": "on-failure:5",
                "candidate": "no",
                "guarded_candidate_count": 2,
                "source_overlay_service_count": 20,
            },
            "checks": {
                "isolated_docker_daemon_verified": True,
                "unless_stopped_control_restored_after_daemon_restart": True,
                "on_failure_5_control_restored_after_daemon_restart": True,
                "restart_no_candidates_not_restored_after_daemon_restart": True,
                "missing_mapper_blocked_admission": True,
                "missing_mapper_blocked_container_start": True,
                "wrong_key_rejected_for_both_vaults": True,
                "delayed_unlock_required_fresh_admission": True,
                "explicit_guarded_start_after_unlock_succeeded": True,
                "recovery_keys_reopened_both_vaults": True,
                "stable_final_delta_exact": True,
                "retained_legacy_read_only_rejected_write": True,
                "pre_admission_rollback_passed": True,
                "post_admission_reverse_delta_rollback_passed": True,
                "asset_mount_nodev_nosuid_noexec_verified": True,
                "project_mount_nodev_nosuid_exec_exception_verified": True,
                "all_eleven_target_subpaths_verified": True,
                "runtime_inspection_read_only": True,
                "isolated_admission_never_authorized_production": True,
                "temporary_resources_removed": True,
                "production_container_ids_unchanged": True,
                "production_services_stopped_or_restarted": False,
                "production_volumes_changed": False,
                "production_compose_applied": False,
                "production_restart_policy_changed": False,
                "production_vaults_or_keys_created": False,
                "production_docker_daemon_restarted": False,
                "host_rebooted": False,
                "host_boot_rehearsed": False,
                "external_alert_rehearsed": False,
                "protected_checks_claimed": False,
                "live_p95_measured": False,
                "systemd_unit_installed": False,
                "cloudflare_changed": False,
            },
            "cutover_gate": {
                "production_cutover_allowed_by_this_receipt": False,
                "fr06b_or_fr06_closed": False,
                "still_required": [
                    "fresh encrypted R2 restore receipt immediately before an owner-approved window",
                    "external independent active and recovery key custody",
                    "two distinct off-host LUKS2 header backups separate from recovery keys",
                    "independent owner-visible out-of-band alert proof",
                    "FR-06B3B guarded lifecycle and final-delta executor review",
                    "exact protected PR and post-merge main checks for every source batch",
                    "live workload p95 within the retained fifteen-percent ceiling",
                ],
            },
            "all_checks_passed": True,
            "production_changed": False,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    lab: Lab | None = None
    try:
        lab = Lab(args.receipt)
        result = lab.run_lab()
        exclusive_json(args.receipt, result, 0o644)
        print(json.dumps({"receipt": str(args.receipt), "all_checks_passed": True}))
        return 0
    except (LabError, OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(f"FR06B3A_LAB_FAIL: {exc}", file=sys.stderr)
        return 1
    finally:
        if lab is not None:
            try:
                lab.cleanup()
            except Exception as exc:
                print(f"FR06B3A_CLEANUP_FAIL: {exc}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
