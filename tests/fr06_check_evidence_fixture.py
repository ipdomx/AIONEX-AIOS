"""Explicit synthetic GitHub job/run evidence; no network or authorization."""
from copy import deepcopy
REPO = 'ipdomx/AIONEX-AIOS'
API = 'https://api.github.com/repos/' + REPO

def attach(checks, sha, *, event='pull_request', pr=835, base_ref='main', base_sha='7'*40):
    evidence = {}
    for index, check in enumerate(checks['check_runs']):
        ident = 1000 + index
        check.update(id=ident, check_suite={'id':2000})
        run = {'id':3000,'run_attempt':1,'head_sha':sha,'head_branch':'fixture' if event=='pull_request' else 'main',
               'event':event,'status':'completed','conclusion':'success','check_suite_id':2000,
               'repository':{'full_name':REPO},'head_repository':{'full_name':REPO},
               'pull_requests':[{'number':pr,'head':{'sha':sha},'base':{'ref':base_ref,'sha':base_sha}}] if event=='pull_request' else []}
        job = {'id':ident,'name':check['name'],'head_sha':sha,'status':'completed','conclusion':'success',
               'run_id':3000,'run_attempt':1,'check_run_url':API+'/check-runs/'+str(ident),'run_url':API+'/actions/runs/3000'}
        evidence[str(ident)] = {'job':job,'run':deepcopy(run)}
    return evidence
