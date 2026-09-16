"""Behavioral tests for FR-06C5E swap identity; all OS mutations are mocked."""
from io import BytesIO
import os
from pathlib import Path
import stat
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/security/fr06c5_memory_controls.py"
MAPPER = "/dev/mapper/aionex-fr06c5-swap"
ALIAS = "/dev/dm-7"
OTHER = "/dev/dm-8"


class FakePath:
    def __init__(self, name, present=True):
        self.name = name
        self.present = present
        self.unlink_calls = 0

    def __str__(self):
        return self.name

    def __fspath__(self):
        return self.name

    @property
    def parent(self):
        return self

    def exists(self):
        return self.present

    def is_file(self):
        return self.present

    def mkdir(self, **kwargs):
        pass

    def unlink(self, **kwargs):
        self.unlink_calls += 1
        self.present = False


def block(device, inode):
    return SimpleNamespace(st_mode=stat.S_IFBLK | 0o600,
                           st_rdev=device, st_dev=4, st_ino=inode)


def swap_row(name):
    return {"name": name, "type": "partition", "size_bytes": 8589934592,
            "used_bytes": 4096, "priority": -3}


class SwapIdentityTests(unittest.TestCase):
    def setUp(self):
        self.m = ModuleType("fr06c5_memory_controls_under_test")
        exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), self.m.__dict__)
        self.mapper = FakePath(MAPPER)
        self.key = FakePath("/run/mock-fr06c5-swap.key", present=False)
        self.devices = {
            MAPPER: block(os.makedev(253, 7), 17),
            ALIAS: block(os.makedev(253, 7), 29),
            OTHER: block(os.makedev(253, 8), 17),
        }
        self.m.MAPPER = self.mapper
        self.m.KEY = self.key
        self.m.os = SimpleNamespace(stat=self.device_stat, geteuid=lambda: 0)
        self.m.swap_rows = Mock(return_value=[swap_row(ALIAS)])
        self.m.backing_prepare = Mock()
        self.m.run = Mock(side_effect=AssertionError("unexpected system command"))

    def device_stat(self, path):
        result = self.devices.get(str(path), FileNotFoundError(str(path)))
        if isinstance(result, Exception):
            raise result
        return result

    def ready_verification(self):
        self.m.tmp_ready = Mock(return_value=True)
        self.m.FSTAB = SimpleNamespace(read_text=lambda: "# legacy swap disabled\n")
        self.m.BACKING = SimpleNamespace(open=lambda mode: BytesIO(b"synthetic ciphertext"))
        allowed = [
            ["systemctl", "is-enabled", "aionex-fr06c5-encrypted-swap.service"],
            ["systemctl", "is-enabled", "tmp.mount"],
        ]

        def query(command, *args, **kwargs):
            self.assertIn(command, allowed)
            return "enabled"

        self.m.run = Mock(side_effect=query)

    def test_block_aliases_match_even_with_different_device_node_inodes(self):
        self.assertTrue(self.m.same_swap_device(ALIAS, self.mapper))

    def test_different_device_is_not_accepted_even_with_same_inode_and_filesystem(self):
        self.assertFalse(self.m.same_swap_device(OTHER, self.mapper))

    def test_regular_file_does_not_match_mapper_device_number(self):
        self.devices[ALIAS] = SimpleNamespace(
            st_mode=stat.S_IFREG | 0o600, st_rdev=os.makedev(253, 7))
        self.assertFalse(self.m.same_swap_device(ALIAS, self.mapper))

    def test_expected_mapper_must_be_a_block_device(self):
        regular = SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_rdev=0)
        self.devices[MAPPER] = regular
        self.devices[ALIAS] = regular
        with self.assertRaisesRegex(self.m.B, "not a block device"):
            self.m.same_swap_device(ALIAS, self.mapper)

    def test_missing_identical_path_is_not_identity_evidence(self):
        self.devices.pop(MAPPER)
        with self.assertRaisesRegex(self.m.B, "identity unavailable"):
            self.m.same_swap_device(MAPPER, self.mapper)

    def test_unresolved_aliases_block_instead_of_becoming_nonmatches(self):
        for error in (FileNotFoundError("missing"), PermissionError("denied"),
                      OSError(40, "symlink loop")):
            with self.subTest(error=type(error).__name__):
                self.devices[ALIAS] = error
                with self.assertRaisesRegex(self.m.B, "identity unavailable"):
                    self.m.same_swap_device(ALIAS, self.mapper)

    def test_start_recognizes_active_alias_without_reformatting(self):
        result = self.m.boot_swap_start()
        self.assertEqual(result["status"], "encrypted_swap_active")
        self.m.run.assert_not_called()

    def test_start_does_not_accept_another_active_device_or_empty_rows(self):
        for rows in ([swap_row(OTHER)], []):
            with self.subTest(names=[row["name"] for row in rows]):
                self.m.swap_rows.return_value = rows
                with self.assertRaisesRegex(self.m.B, "not active"):
                    self.m.boot_swap_start()
        self.m.backing_prepare.assert_not_called()
        self.m.run.assert_not_called()

    def mock_new_activation(self, final_rows):
        self.mapper.present = False
        self.m.swap_rows.side_effect = [[], final_rows]
        self.m.os = SimpleNamespace(
            stat=self.device_stat, geteuid=lambda: 0,
            open=lambda *args: 99, write=lambda fd, data: len(data),
            fsync=lambda fd: None, close=lambda fd: None,
            urandom=lambda size: b"x" * size,
            O_WRONLY=os.O_WRONLY, O_CREAT=os.O_CREAT,
            O_EXCL=os.O_EXCL, O_NOFOLLOW=os.O_NOFOLLOW,
        )
        commands = []

        def execute(command, *args, **kwargs):
            commands.append(command)
            if command[:2] == ["cryptsetup", "open"]:
                self.mapper.present = True
            return ""

        self.m.run = Mock(side_effect=execute)
        return commands

    def test_new_activation_accepts_kernel_alias_after_swapon(self):
        commands = self.mock_new_activation([swap_row(ALIAS)])
        result = self.m.boot_swap_start()
        self.assertEqual(result["status"], "encrypted_swap_active")
        self.assertEqual([command[0] for command in commands],
                         ["cryptsetup", "mkswap", "swapon"])
        self.assertFalse(self.key.present)

    def test_start_rejects_extra_or_duplicate_swaps_before_any_mutation(self):
        for rows in ([swap_row(ALIAS), swap_row(OTHER)],
                     [swap_row(OTHER), swap_row(ALIAS)],
                     [swap_row(MAPPER), swap_row(ALIAS)],
                     [swap_row(ALIAS), swap_row("/extra.swap")]):
            with self.subTest(names=[row["name"] for row in rows]):
                self.m.swap_rows.return_value = rows
                with self.assertRaisesRegex(self.m.B, "additional active swaps"):
                    self.m.boot_swap_start()
        self.m.backing_prepare.assert_not_called()
        self.m.run.assert_not_called()
        self.assertEqual(self.key.unlink_calls, 0)

    def test_start_rejects_foreign_swap_with_absent_mapper_before_mutation(self):
        self.mapper.present = False
        self.m.swap_rows.return_value = [swap_row(OTHER)]
        with self.assertRaisesRegex(self.m.B, "unexpected active swap device"):
            self.m.boot_swap_start()
        self.m.backing_prepare.assert_not_called()
        self.m.run.assert_not_called()

    def test_new_activation_rejects_additional_swaps_after_swapon(self):
        for rows in ([swap_row(ALIAS), swap_row(OTHER)],
                     [swap_row(ALIAS), swap_row(MAPPER)]):
            with self.subTest(names=[row["name"] for row in rows]):
                self.mock_new_activation(rows)
                with self.assertRaisesRegex(self.m.B, "encrypted swap did not activate"):
                    self.m.boot_swap_start()

    def test_stop_swaps_off_alias_before_mapper_close(self):
        commands = []
        self.m.run = Mock(side_effect=lambda command, *args: commands.append(command) or "")
        result = self.m.boot_swap_stop()
        self.assertEqual(result["status"], "encrypted_swap_inactive")
        self.assertEqual(commands, [
            ["swapoff", MAPPER],
            ["cryptsetup", "close", self.m.MAPPER_NAME],
        ])
        self.assertEqual(self.key.unlink_calls, 1)

    def test_stop_only_swaps_off_target_when_another_known_device_is_active(self):
        for rows in ([swap_row(OTHER), swap_row(ALIAS)],
                     [swap_row(ALIAS), swap_row(OTHER)]):
            with self.subTest(names=[row["name"] for row in rows]):
                self.m.swap_rows.return_value = rows
                commands = []
                self.m.run = Mock(side_effect=lambda command, *args: commands.append(command) or "")
                self.m.boot_swap_stop()
                self.assertEqual(commands, [
                    ["swapoff", MAPPER],
                    ["cryptsetup", "close", self.m.MAPPER_NAME],
                ])

    def test_stop_does_not_swap_off_a_different_device(self):
        self.m.swap_rows.return_value = [swap_row(OTHER)]
        self.m.run = Mock(return_value="")
        self.m.boot_swap_stop()
        self.m.run.assert_called_once_with(
            ["cryptsetup", "close", self.m.MAPPER_NAME], 60)

    def test_stop_does_not_close_mapper_when_identity_is_unresolved(self):
        self.devices[ALIAS] = PermissionError("unreadable active swap")
        with self.assertRaisesRegex(self.m.B, "identity unavailable"):
            self.m.boot_swap_stop()
        self.m.run.assert_not_called()

    def test_stop_preserves_absent_mapper_noop_only_without_active_swaps(self):
        self.mapper.present = False
        self.m.swap_rows.return_value = []
        result = self.m.boot_swap_stop()
        self.assertEqual(result["status"], "encrypted_swap_inactive")
        self.m.run.assert_not_called()

    def test_stop_blocks_missing_mapper_identity_with_any_active_swap(self):
        self.mapper.present = False
        for name in (MAPPER, ALIAS, OTHER, "/swap.img"):
            with self.subTest(name=name):
                self.m.swap_rows.return_value = [swap_row(name)]
                with self.assertRaisesRegex(self.m.B, "identity unavailable"):
                    self.m.boot_swap_stop()
        self.m.run.assert_not_called()
        self.assertEqual(self.key.unlink_calls, 0)

    def test_verify_accepts_only_target_alias(self):
        self.ready_verification()
        result = self.m.verify_live()
        self.assertEqual(result["validation"], "FR06C5_MEMORY_CONTROLS_READY")
        self.assertEqual(result["encrypted_swap"]["name"], ALIAS)

    def test_verify_rejects_a_different_device(self):
        self.m.swap_rows.return_value = [swap_row(OTHER)]
        with self.assertRaisesRegex(self.m.B, "swap acceptance failed"):
            self.m.verify_live()
        self.m.run.assert_not_called()

    def test_verify_rejects_empty_extra_and_duplicate_swaps(self):
        self.ready_verification()
        for rows in ([], [swap_row(ALIAS), swap_row(OTHER)],
                     [swap_row(MAPPER), swap_row(OTHER)],
                     [swap_row(ALIAS), swap_row("/swap.img")],
                     [swap_row(ALIAS), swap_row(MAPPER)]):
            with self.subTest(names=[row["name"] for row in rows]):
                self.m.swap_rows.return_value = rows
                with self.assertRaisesRegex(self.m.B, "swap acceptance failed"):
                    self.m.verify_live()
        self.m.run.assert_not_called()

    def test_verify_blocks_unresolved_device_identity(self):
        self.devices[ALIAS] = FileNotFoundError("unresolved")
        with self.assertRaisesRegex(self.m.B, "identity unavailable"):
            self.m.verify_live()
        self.m.run.assert_not_called()

    def test_preflight_still_allows_expected_absent_mapper(self):
        self.mapper.present = False
        self.m.LEGACY = FakePath("/swap.img")
        self.m.swap_rows.return_value = [swap_row("/swap.img")]
        self.m.host_state_receipt = Mock(return_value={"accepted": True})
        self.m.exact_mount = Mock(return_value=False)
        self.m.mem_available = Mock(return_value=2 * self.m.RESERVE)
        self.m.tmp_holders = Mock(return_value=[])
        result = self.m.current_preflight(Path("/virtual/receipt"))
        self.assertEqual(result["legacy_swap"]["name"], "/swap.img")

    def test_preflight_rejects_an_extra_swap_file_before_mutation(self):
        self.mapper.present = False
        self.m.LEGACY = FakePath("/swap.img")
        self.m.swap_rows.return_value = [swap_row("/swap.img"), swap_row("/extra.swap")]
        self.m.host_state_receipt = Mock(return_value={"accepted": True})
        self.m.exact_mount = Mock(return_value=False)
        self.m.mem_available = Mock(return_value=2 * self.m.RESERVE)
        self.m.tmp_holders = Mock(return_value=[])
        with self.assertRaisesRegex(self.m.B, "only active legacy"):
            self.m.current_preflight(Path("/virtual/receipt"))
        self.m.exact_mount.assert_not_called()
        self.m.mem_available.assert_not_called()
        self.m.tmp_holders.assert_not_called()
        self.m.backing_prepare.assert_not_called()
        self.m.run.assert_not_called()

    def test_preflight_rejects_active_mapper_alias_alongside_legacy(self):
        self.devices["/swap.img"] = SimpleNamespace(
            st_mode=stat.S_IFREG | 0o600, st_rdev=0)
        self.m.swap_rows.return_value = [swap_row("/swap.img"), swap_row(ALIAS)]
        self.m.host_state_receipt = Mock(return_value={"accepted": True})
        with self.assertRaisesRegex(self.m.B, "only active legacy"):
            self.m.current_preflight(Path("/virtual/receipt"))


if __name__ == "__main__":
    unittest.main()
