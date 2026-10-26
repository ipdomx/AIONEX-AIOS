"""FR09 server-side websocket evidence; all identities and secrets are synthetic.

No provider, production Redis, real browser credentials or live API calls.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
import unittest
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import patch

from fastapi import WebSocketDisconnect

from app.realtime.authorized_socket import StreamAuthorizationLost, StreamPrincipal
from app.realtime import fr09_authenticated_presence as m
from app.realtime.fr09_presence_capture import collect_signed_presence, _signed_content


KEY = b"fr09-identity-fixture-only-do-not-use-in-production-20261026"
SIGNER = b"fr09-independent-signature-fixture-not-for-production-20261026"
RUN_ID = "fr09-20261026-ephemeral-lab-a1b2c3"


def principal(user="actor-1", tenant="org-1", generation=0):
    return StreamPrincipal(
        user_id=user,
        organization_id=tenant,
        auth_version=generation,
        role="Paid user",
        plan="pro",
        permissions=("project.create",),
    )


class SimulatedRedis:
    """Strict fake of the three existing atomic Lua operations."""
    def __init__(self):
        self.identities = {}
        self.score = {}
        self.fail = False
        self.calls = []

    async def eval(self, script, number, *args):
        assert number == 2
        self.calls.append(("EVAL", number))
        if self.fail:
            raise RuntimeError("simulated Redis outage")
        if "ZADD" in script:
            _, _, sid, identity, timestamp, ttl = args
            assert int(ttl) >= 20
            self.identities[sid] = identity
            self.score[sid] = float(timestamp)
            return 1
        if "ZREM" in script and "ZREMRANGEBYSCORE" not in script:
            _, _, sid = args
            self.identities.pop(sid, None)
            self.score.pop(sid, None)
            return 1
        if "ZREMRANGEBYSCORE" in script:
            _, _, now, ttl = args
            cutoff = float(now) - float(ttl)
            for sid, score in list(self.score.items()):
                if score <= cutoff:
                    self.score.pop(sid)
                    self.identities.pop(sid, None)
            if any(sid not in self.identities for sid in self.score):
                raise RuntimeError("tampered socket identity")
            return [len(self.score), len({self.identities[s] for s in self.score})]
        raise AssertionError("unknown Redis operation")


class PresenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.config = m.PresenceConfig(RUN_ID, KEY)
        self.redis = SimulatedRedis()
        self.recorder = m.ServerPresenceRecorder(self.config, self.redis)

    async def test_two_real_authorized_socket_joins_one_distinct_user(self):
        with patch.object(m.time, "time", return_value=1_790_000_000.0):
            sid1, hash1 = await self.recorder.register(principal())
            sid2, hash2 = await self.recorder.register(principal())
            sample = await self.recorder.sample()
        self.assertNotEqual(sid1, sid2)
        self.assertEqual(hash1, hash2)
        self.assertEqual(len(sid1), 48)
        self.assertNotIn("actor-1", str(self.redis.identities))
        self.assertNotIn("org-1", str(self.redis.identities))
        self.assertEqual(sample["authenticated_sessions"], 2)
        self.assertEqual(sample["distinct_authenticated_users"], 1)
        await self.recorder.disconnect(sid1)
        with patch.object(m.time, "time", return_value=1_790_000_001.0):
            sampled = await self.recorder.sample()
        self.assertEqual(sampled["authenticated_sessions"], 1)

    async def test_same_user_id_in_other_tenant_is_different_identity(self):
        with patch.object(m.time, "time", return_value=1_790_000_000.0):
            _, digest_a = await self.recorder.register(principal(tenant="org-A"))
            _, digest_b = await self.recorder.register(principal(tenant="org-B"))
            sample = await self.recorder.sample()
        self.assertNotEqual(digest_a, digest_b)
        self.assertEqual(sample["distinct_authenticated_users"], 2)

    async def test_revoked_auth_generation_cannot_refresh_original_socket(self):
        with patch.object(m.time, "time", return_value=1_790_000_000.0):
            sid, digest = await self.recorder.register(principal())
        with self.assertRaisesRegex(ValueError, "principal changed"):
            await self.recorder.revalidate(sid, digest, principal(generation=1))
        with self.assertRaisesRegex(ValueError, "principal changed"):
            await self.recorder.revalidate(sid, digest, principal(user="someone-else"))
        await self.recorder.disconnect(sid)

    async def test_idle_stale_socket_expires_from_authenticated_counter(self):
        with patch.object(m.time, "time", return_value=1_790_000_000.0):
            await self.recorder.register(principal())
        with patch.object(m.time, "time", return_value=1_790_000_021.0):
            sample = await self.recorder.sample()
        self.assertEqual(sample["authenticated_sessions"], 0)
        self.assertEqual(sample["distinct_authenticated_users"], 0)

    async def test_real_heartbeat_persists_only_after_revalidation(self):
        with patch.object(m.time, "time", return_value=1_790_000_000.0):
            sid, digest = await self.recorder.register(principal())
        with patch.object(m.time, "time", return_value=1_790_000_015.0):
            await self.recorder.revalidate(sid, digest, principal())
        with patch.object(m.time, "time", return_value=1_790_000_024.0):
            sample = await self.recorder.sample()
        self.assertEqual(sample["authenticated_sessions"], 1)

    async def test_redis_loss_is_failure_not_signed_fake_zero(self):
        self.redis.fail = True
        with self.assertRaisesRegex(RuntimeError, "Redis outage"):
            await self.recorder.register(principal())
        with self.assertRaisesRegex(RuntimeError, "Redis outage"):
            await self.recorder.sample()

    async def test_private_key_file_enforcement(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "identity.key"
            path.write_bytes(KEY)
            path.chmod(0o600)
            self.assertEqual(m.read_private_key(str(path)), KEY)
            path.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "0600"):
                m.read_private_key(str(path))
            path.chmod(0o600)
            symlink = Path(temp) / "identity.link"
            symlink.symlink_to(path)
            with self.assertRaises(OSError):
                m.read_private_key(str(symlink))

    async def test_configuration_disabled_never_loads_key_or_redis(self):
        m.optional_presence_config.cache_clear()
        with patch.dict(os.environ, {
            "AIOS_FR09_AUTHENTICATED_PRESENCE_ENABLED": "false",
            "AIOS_FR09_AUTHENTICATED_PRESENCE_KEY_FILE": "/missing"
        }):
            self.assertIsNone(await m.ServerPresenceRecorder.from_enabled_config())
        m.optional_presence_config.cache_clear()

    async def test_invalid_run_or_boolean_configuration_fails_closed(self):
        for run in ("fr09-short", "../fr09-long-invalid", "", "FR09-NOT-VALID"):
            with self.subTest(run=run):
                with self.assertRaises(ValueError):
                    m.PresenceConfig(run, KEY)
        m.optional_presence_config.cache_clear()
        with patch.dict(os.environ, {
            "AIOS_FR09_AUTHENTICATED_PRESENCE_ENABLED": "invalid"
        }):
            with self.assertRaises(ValueError):
                m.optional_presence_config()
        m.optional_presence_config.cache_clear()

    async def test_capture_is_signed_from_server_samples_not_client_claims(self):
        class SimulatedServer:
            config = m.PresenceConfig(RUN_ID, KEY)

            def __init__(self):
                self.clock = 0.0

            async def sample(self):
                return {
                    "at_epoch": 1_790_000_000.0 + self.clock,
                    "authenticated_sessions": 5000,
                    "distinct_authenticated_users": 5000,
                }

        server = SimulatedServer()
        async def simulated_sleep(duration):
            server.clock += duration
        with tempfile.TemporaryDirectory() as folder:
            key_file = Path(folder)/"signing.key"
            key_file.write_bytes(SIGNER)
            key_file.chmod(0o600)
            proof = await collect_signed_presence(
                server,
                signing_key_file=str(key_file),
                sleep=simulated_sleep,
                monotonic=lambda: server.clock,
            )
            self.assertEqual(len(proof.server_concurrency["samples"]), 32)
            self.assertGreater(
                proof.window_end_epoch-proof.window_start_epoch, 900
            )
            self.assertEqual(proof.server_concurrency["run_id"], RUN_ID)
            signature_data = {
                "run_id": RUN_ID,
                "window_start_epoch": proof.window_start_epoch,
                "window_end_epoch": proof.window_end_epoch,
                "source": m.SOURCE,
                "samples": proof.server_concurrency["samples"],
            }
            expected = hmac.new(
                SIGNER,
                json.dumps(
                    signature_data, sort_keys=True, separators=(",", ":"),
                    allow_nan=False,
                ).encode(), hashlib.sha256,
            ).hexdigest()
            self.assertEqual(proof.server_concurrency["hmac_sha256"], expected)
            # End-to-end schema compatibility with the *real* merged FR09
            # verifier; this is still explicitly synthetic test data.
            import importlib.util
            path = (
                Path(__file__).resolve().parents[3]
                / "scripts/capacity/fr09_evidence_gate.py"
            )
            spec = importlib.util.spec_from_file_location("fr09_proof_gate_test", path)
            assert spec is not None and spec.loader is not None
            gate = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(gate)
            steady = {
                "window_start_epoch": proof.window_start_epoch,
                "window_end_epoch": proof.window_end_epoch,
                "unique_authenticated_users": 5000,
                "server_concurrency": proof.server_concurrency,
            }
            self.assertEqual(
                gate.sampled_authenticated_concurrency(
                    steady, trusted_key=SIGNER, expected_run_id=RUN_ID
                ),
                (True, 5000),
            )
            self.assertEqual(
                gate.sampled_authenticated_concurrency(
                    steady, trusted_key=SIGNER,
                    expected_run_id="fr09-20261026-other-test-run-abcd",
                ),
                (False, None),
            )

    async def test_capture_rejects_late_scheduled_snapshot_without_filling_gap(self):
        class DelayedSampler:
            config = m.PresenceConfig(RUN_ID, KEY)
            def __init__(self):
                self.clock = 0.0
            async def sample(self):
                return {
                    "at_epoch": 1_790_000_000.0 + self.clock,
                    "authenticated_sessions": 5000,
                    "distinct_authenticated_users": 5000,
                }
        sampler = DelayedSampler()
        count = [0]
        async def delayed_sleep(seconds):
            count[0] += 1
            sampler.clock += seconds
            if count[0] == 17:
                sampler.clock += 1.5
        with tempfile.TemporaryDirectory() as folder:
            key_file = Path(folder)/"sign.key"
            key_file.write_bytes(SIGNER)
            key_file.chmod(0o600)
            with self.assertRaisesRegex(ValueError, "inconsistent"):
                await collect_signed_presence(
                    sampler, signing_key_file=str(key_file),
                    sleep=delayed_sleep, monotonic=lambda: sampler.clock
                )

    async def test_false_redis_return_values_fail_closed(self):
        class BadRedis:
            async def eval(self, *args):
                return [5000, 5001]
        sampler = m.ServerPresenceRecorder(self.config, BadRedis())
        with self.assertRaisesRegex(ValueError, "count invalid"):
            await sampler.sample()

    async def test_malformed_identity_key_or_private_principal_refused(self):
        with self.assertRaisesRegex(ValueError, "key"):
            m.PresenceConfig(RUN_ID, b"short")
        with self.assertRaisesRegex(ValueError, "principal"):
            m.identity_digest(
                self.config, principal(user="", tenant="org-1")
            )
        with self.assertRaisesRegex(ValueError, "principal"):
            m.identity_digest(
                self.config, principal(user="user-1", tenant="")
            )

    async def test_malformed_or_huge_collector_timestamp_never_signs(self):
        base = [
            {
                "at_epoch": 1_790_000_000.0 + i * 29.5,
                "authenticated_sessions": 5000,
                "distinct_authenticated_users": 5000,
            }
            for i in range(32)
        ]
        for bad in (None, True, float("nan"), float("inf"), 10 ** 400, "1790000000"):
            with self.subTest(value=str(bad)[:40]):
                rows = [dict(x) for x in base]
                rows[12]["at_epoch"] = bad
                with self.assertRaises(ValueError):
                    _signed_content(RUN_ID, rows)

    async def test_same_signing_and_identity_key_not_accepted(self):
        class NoSideEffects:
            config = m.PresenceConfig(RUN_ID, KEY)
            async def sample(self):
                raise AssertionError("never sample before key admission")
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder)/"same.key"
            file.write_bytes(KEY)
            file.chmod(0o600)
            with self.assertRaises(ValueError):
                await collect_signed_presence(
                    NoSideEffects(), signing_key_file=str(file)
                )


class SocketLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_authorized_route_registers_only_after_hub_connect(self):
        from app.api.v1.endpoints import websocket as route
        sequence = []
        verified = principal()

        class FakeGuarded:
            closed = False
            principal = verified
            def __init__(self, *_args, **_kwargs):
                pass
            async def ensure_authorized(self):
                sequence.append("auth")
                return verified
            async def send_json(self, _data):
                sequence.append("send")
            async def close(self, code=1000):
                sequence.append("close")

        class FakeRealtime:
            async def connect(self, tenant, guarded, **kwargs):
                sequence.append("hub_connect")
            async def disconnect(self, tenant, guarded):
                sequence.append("hub_disconnect")
            async def replay(self, *args, **kwargs):
                raise AssertionError("no replay requested")

        class FakeRecorder:
            async def register(self, p):
                self.outer.append("register")
                self.outer.append("actor_valid" if p == verified else "wrong_actor")
                return "s" * 48, "u" * 64
            async def revalidate(self, *args):
                self.outer.append("refresh")
            async def disconnect(self, sid):
                self.outer.append("drop")
        recorder = FakeRecorder()
        recorder.outer = sequence

        async def get_recorder(cls):
            sequence.append("config")
            return recorder

        class FakeSocket:
            async def receive_text(self):
                raise WebSocketDisconnect(code=1000)

        with ExitStack() as patches:
            patches.enter_context(
                patch.object(route, "AuthorizedRealtimeSocket", FakeGuarded)
            )
            patches.enter_context(
                patch.object(route, "realtime_event_runtime", FakeRealtime())
            )
            patches.enter_context(
                patch.object(
                    route.ServerPresenceRecorder,
                    "from_enabled_config",
                    classmethod(get_recorder),
                )
            )
            await route.websocket_connect(FakeSocket(), token="test-no-real-token")
        self.assertLess(sequence.index("auth"), sequence.index("hub_connect"))
        self.assertLess(sequence.index("hub_connect"), sequence.index("register"))
        self.assertIn("drop", sequence)
        self.assertIn("hub_disconnect", sequence)

    async def test_failed_auth_never_enrolls_presence(self):
        from app.api.v1.endpoints import websocket as route
        sequence = []
        class FailGuarded:
            def __init__(self, *_args, **_kwargs):
                pass
            async def ensure_authorized(self):
                sequence.append("auth_failed")
                raise StreamAuthorizationLost("denied")
            async def close(self, code=1000):
                sequence.append("close")
        async def must_not_get_recorder(cls):
            raise AssertionError("invalid socket must not reach FR09 collector")
        with ExitStack() as patches:
            patches.enter_context(
                patch.object(route, "AuthorizedRealtimeSocket", FailGuarded)
            )
            patches.enter_context(
                patch.object(
                    route.ServerPresenceRecorder,
                    "from_enabled_config",
                    classmethod(must_not_get_recorder),
                )
            )
            await route.websocket_connect(object(), token="invalid")
        self.assertEqual(sequence, ["auth_failed", "close"])
