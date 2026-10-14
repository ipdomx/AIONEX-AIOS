"""Offline regression tests; no SSH, HTTP or production calls are executed."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / "scripts" / "ops" / "ns12_observer_v2.py"
spec = importlib.util.spec_from_file_location('ns12_observer_v2_compat', PATH)
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)


def http_result(stdout='200 0.12', code=0, error=None):
    fields = stdout.split()
    if len(fields) == 2 and len(fields[0]) == 3:
        status, latency = fields
        stdout = '|'.join([status, latency, latency, latency, latency, latency])
    return {'exit_code': code, 'stdout': stdout, 'seconds': 0.2, 'error_type': error}


def row(name='frontend', state='running', health='healthy', restart=0, oom='false'):
    return '\t'.join(['a' * 64, '/web-dashboard-' + name + '-1', observer.OWNER_IMAGE,
                      state, str(restart), oom, health, '2026-10-08T13:52:00Z', '0', 'no'])


def healthy_host():
    raw = '\n'.join([row()] + [row('worker-' + str(i)) for i in range(35)])
    return {'status': 'MEASURED', 'hostname': 'nc-ph-4354', 'checks': {
        'containers': observer.parse_containers({'status': 'MEASURED', 'value': raw}),
        'owner_next_version': {'status': 'MEASURED', 'value': '15.5.27'},
        'owner_rollback_image': {'status': 'MEASURED', 'value': 'sha256:' + 'b' * 64},
        'resources': {'status': 'MEASURED', 'value': {'filesystems': [
            {'path': '/var/lib/docker', 'total_bytes': 1000, 'available_bytes': 500,
             'total_inodes': 1000, 'free_inodes': 800}],
            'memory': {'MemTotal_bytes': 1000, 'MemAvailable_bytes': 500}, 'cpus': 64, 'load': [2, 2, 2]}},
        'raid': {'status': 'MEASURED', 'value': [{'device': 'md2', 'degraded': '0',
                  'mismatch_cnt': '0', 'sync_action': 'idle'}]},
    }}


def receipt(host=None):
    http = {name: observer.decode_http(http_result(str(expected[0]) + ' 0.2'), expected)
            for name, (_, expected) in observer.URLS.items()}
    return observer.make_receipt(http, host or healthy_host(), '2026-10-08T17:00:00Z')


class ObserverTests(unittest.TestCase):
    def test_remote_health_lookup_uses_optional_map_index(self):
        self.assertIn('index .State', observer.REMOTE)
        self.assertNotIn('if .State.Health', observer.REMOTE)
        compile(observer.REMOTE, '<remote>', 'exec')

    def test_completed_initializer_is_separate(self):
        r = observer.parse_containers({'status': 'MEASURED', 'value': row('realtime-recording-init', state='exited', health='none')})
        self.assertEqual(r['total'], 0)
        self.assertEqual(len(r['completed_initializers']), 1)
        self.assertEqual(r['all_project_container_count'], 1)

    def test_failed_initializer_is_not_ignored(self):
        raw = row('realtime-recording-init', state='exited', health='none')
        raw = raw.rsplit('\t', 2)[0] + '\t1\tno'
        r = observer.parse_containers({'status': 'MEASURED', 'value': raw})
        self.assertEqual(r['total'], 1)
        self.assertEqual(r['completed_initializers'], [])

    def test_nonredundant_raid_is_not_reported_as_degraded(self):
        h = healthy_host()
        h['checks']['raid']['value'].append({'device': 'md1', 'level': 'raid0', 'array_state': 'clean',
                                            'degraded': None, 'mismatch_cnt': None, 'sync_action': None})
        self.assertEqual(receipt(h)['status'], 'PARTIAL_SAMPLE_EXPECTED')

    def test_http_ok(self):
        self.assertEqual(observer.decode_http(http_result(), [200])['status'], 'EXPECTED')

    def test_access_is_not_login_page_success(self):
        self.assertEqual(observer.decode_http(http_result(), [302])['status'], 'UNEXPECTED')
        self.assertFalse(observer.decode_http(http_result('302 0.1'), [302])['redirects_followed'])

    def test_curl_failure_is_unavailable(self):
        r = observer.decode_http(http_result('200 0.1', 7, 'PROCESS_EXIT'), [200])
        self.assertEqual(r['status'], 'UNAVAILABLE')
        self.assertIsNone(r['http_code'])

    def test_http_zero_is_not_a_response(self):
        self.assertEqual(observer.decode_http(http_result('000 0.1'), [200])['status'], 'UNAVAILABLE')

    def test_nonfinite_http_latency_rejected(self):
        for value in ('nan', 'inf', '-inf'):
            with self.subTest(value=value):
                self.assertEqual(observer.decode_http(http_result('200 ' + value), [200])['status'], 'UNAVAILABLE')

    def test_malformed_http(self):
        self.assertEqual(observer.decode_http(http_result('bad'), [200])['status'], 'UNAVAILABLE')

    def test_docker_failure_is_not_zero_containers(self):
        r = observer.parse_containers({'status': 'UNAVAILABLE', 'value': None})
        self.assertIsNone(r['running'])
        self.assertIsNone(r['total'])

    def test_optional_health_is_safe(self):
        r = observer.parse_containers({'status': 'MEASURED', 'value': row('cloudflared', health='none')})
        self.assertEqual(r['running'], 1)
        self.assertEqual(r['without_healthcheck'], 1)

    def test_bad_inventory_unavailable(self):
        r = observer.parse_containers({'status': 'MEASURED', 'value': 'malformed'})
        self.assertEqual(r['status'], 'UNAVAILABLE')
        self.assertIsNone(r['running'])

    def test_wrong_project_rejected(self):
        r = observer.parse_containers({'status': 'MEASURED', 'value': row().replace('/web-dashboard-', '/unrelated-')})
        self.assertEqual(r['status'], 'UNAVAILABLE')

    def test_negative_restart_count_rejected(self):
        self.assertEqual(observer.parse_containers({'status': 'MEASURED', 'value': row(restart=-1)})['status'], 'UNAVAILABLE')

    def test_measured_empty_inventory_is_review(self):
        h = healthy_host()
        h['checks']['containers'] = observer.parse_containers({'status': 'MEASURED', 'value': ''})
        self.assertEqual(receipt(h)['status'], 'REVIEW_REQUIRED')

    def test_starting_health_is_not_accepted(self):
        h = healthy_host()
        h['checks']['containers']['containers'][1]['health'] = 'starting'
        self.assertEqual(receipt(h)['status'], 'REVIEW_REQUIRED')

    def test_oom_is_not_hidden(self):
        h = healthy_host()
        h['checks']['containers']['containers'][1]['oom_killed'] = True
        self.assertEqual(receipt(h)['status'], 'REVIEW_REQUIRED')

    def test_disk_pressure_is_reported(self):
        h = healthy_host()
        h['checks']['resources']['value']['filesystems'][0]['available_bytes'] = 100
        self.assertEqual(receipt(h)['status'], 'REVIEW_REQUIRED')

    def test_inode_pressure_is_reported(self):
        h = healthy_host()
        h['checks']['resources']['value']['filesystems'][0]['free_inodes'] = 100
        self.assertEqual(receipt(h)['status'], 'REVIEW_REQUIRED')

    def test_missing_raid_evidence_is_not_healthy(self):
        h = healthy_host()
        h['checks']['raid']['value'] = []
        self.assertEqual(receipt(h)['status'], 'REVIEW_REQUIRED')

    def test_unknown_raid_fields_are_not_zero(self):
        h = healthy_host()
        h['checks']['raid']['value'][0]['degraded'] = None
        self.assertEqual(receipt(h)['status'], 'REVIEW_REQUIRED')

    def test_owner_image_mismatch_is_reported(self):
        h = healthy_host()
        h['checks']['containers']['containers'][0]['image'] = 'sha256:' + 'c' * 64
        r = receipt(h)
        self.assertFalse(r['owner_runtime_identity_matches_accepted_receipt'])
        self.assertEqual(r['status'], 'REVIEW_REQUIRED')

    def test_complete_sample_is_never_full_acceptance(self):
        r = receipt()
        self.assertEqual(r['status'], 'PARTIAL_SAMPLE_EXPECTED')
        self.assertFalse(r['continuous_72h_certified'])
        self.assertFalse(r['full_release_accepted'])
        self.assertIn('current_backup_and_independent_restore', r['not_measured'])

    def test_host_failure_is_recorded(self):
        with patch.object(observer, 'invoke', return_value=http_result('', 255, 'PROCESS_EXIT')):
            h = observer.host_probe()
        self.assertEqual(h['status'], 'UNAVAILABLE')
        self.assertEqual(receipt(h)['status'], 'REVIEW_REQUIRED')

    def test_no_http_redirect_argument(self):
        with patch.object(observer, 'invoke', return_value=http_result()) as run:
            observer.http_probe('https://api.vip-e.net/ready', [200])
        argv = run.call_args[0][0]
        self.assertNotIn('-L', argv)
        self.assertNotIn('--location', argv)
        self.assertNotIn('-k', argv)

    def test_evidence_is_new_and_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            p1 = observer.persist({'id': 1}, Path(directory))
            p2 = observer.persist({'id': 2}, Path(directory))
            self.assertNotEqual(p1, p2)
            self.assertEqual(json.loads(p1.read_text()), {'id': 1})
            self.assertEqual(json.loads(p2.read_text()), {'id': 2})
            self.assertEqual(p1.stat().st_mode & 0o777, 0o600)
            self.assertFalse((Path(directory) / 'CURRENT-NS00-CHECKPOINT.json').exists())

    def test_unexpected_probe_exception_keeps_partial_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(observer, 'EVIDENCE', Path(directory)), \
                 patch.object(observer, 'host_probe', return_value=healthy_host()), \
                 patch.object(observer, 'http_probe', side_effect=RuntimeError('synthetic failure')), \
                 patch('builtins.print'):
                observer.main()
            files = list(Path(directory).glob('NS12-WATCH-*.json'))
            self.assertEqual(len(files), 1)
            r = json.loads(files[0].read_text())
            self.assertEqual(r['status'], 'REVIEW_REQUIRED')
            self.assertTrue(all(x['status'] == 'UNAVAILABLE' for x in r['http'].values()))


if __name__ == '__main__':
    unittest.main(verbosity=2)
