"""Deterministic multi-seed quorum safety campaign; synthetic timings only."""
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from omega_x.replication import run_campaign

ROOT=Path(__file__).resolve().parents[1]


def run():
    runs=[run_campaign(20261112+i,1000,3 if i%3==0 else 5 if i%3==1 else 7)
          for i in range(50)]
    passed=all(all(r['invariants'].values()) for r in runs)
    report={'mode':'DETERMINISTIC_SIMULATION_ONLY','seeds':len(runs),
            'total_events':sum(r['rounds'] for r in runs),
            'all_invariants_pass':passed,'runs':runs}
    report['campaign_sha256']=hashlib.sha256(json.dumps(report,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    (ROOT/'results/replication_campaign.json').write_text(json.dumps(report,indent=2)+'\n')
    if not passed:
        raise AssertionError('quorum invariant failed')
    return {'seeds':report['seeds'],'total_events':report['total_events'],
            'all_invariants_pass':passed,'campaign_sha256':report['campaign_sha256']}


if __name__=='__main__':
    print(json.dumps(run()))
