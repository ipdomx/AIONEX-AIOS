import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_fr06c4_closeout_is_complete_but_parent_open():
    d=json.loads((ROOT/'docs/project/receipts/FR-06C4-production-runtime-closeout.json').read_text())
    assert d['release_boundary']['fr06c4_completed'] is True
    assert d['release_boundary']['fr06_completed'] is False
    assert d['release_boundary']['next_subpart']=='FR-06C5'
    assert d['live_cutover']['running_containers']==36
    assert d['live_cutover']['unhealthy_running_containers']==0
    assert d['candidate_reconstruction']['historical_runtime_copy_performed'] is False
    assert d['post_cutover_recovery']['restore_validated'] is True
    assert d['post_cutover_recovery']['restore_offsite_validated'] is True
