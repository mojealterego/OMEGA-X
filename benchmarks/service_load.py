"""Bounded real loopback API load check, not a throughput or hardware guarantee."""
from pathlib import Path
import hashlib
import json
import secrets
import statistics
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from omega_x.service import LocalControlPlane
from omega_x.client import OmegaClient

ROOT=Path(__file__).resolve().parents[1]


def run(jobs=18, workers=3):
    if not 3 <= jobs <= 60 or not 1 <= workers <= 8:
        raise ValueError('load test budget exceeded')
    keys={tenant:secrets.token_bytes(32) for tenant in ('alpha','beta','gamma')}
    with tempfile.TemporaryDirectory(dir=ROOT/'results/tmp') as root:
        plane=LocalControlPlane(Path(root)/'jobs.sqlite3',keys,workers=workers,max_pending=64)
        plane.start()
        try:
            clients={t:OmegaClient(key,port=plane.port) for t,key in keys.items()}
            ids=[]
            started=time.perf_counter_ns()
            for i in range(jobs):
                tenant=list(keys)[i%len(keys)]
                req=clients[tenant].submit('sha256',4096,idempotency_key=f'load-{i}')
                ids.append((tenant,req['job_id']))
            completed=[]
            for tenant,job_id in ids:
                completed.append(clients[tenant].wait(job_id,timeout_s=40,interval_s=.02))
            wall_ns=time.perf_counter_ns()-started
            durations=sorted(x['result']['wall_ns'] for x in completed if x['status']=='SUCCEEDED')
            success=all(x['status']=='SUCCEEDED' for x in completed)
            integrity=plane.store.integrity()
            result={'mode':'ACTUAL_LOCAL_CPU_AND_LOOPBACK','jobs':jobs,'workers':workers,
                    'tenant_count':len(keys),'successes':len(durations),'failed':jobs-len(durations),
                    'wall_ns':wall_ns,'job_kernel_median_ns':int(statistics.median(durations)) if durations else None,
                    'job_kernel_p95_ns':durations[min(len(durations)-1,int(len(durations)*.95))] if durations else None,
                    'journal_integrity':integrity,
                    'limits':'Host-specific; includes HTTP, process startup, SQLite and actual CPU SHA-256; no NPU or remote cluster'}
            if not success or not integrity:
                raise AssertionError('service load invariant failed')
            (ROOT/'results/service_load.json').write_text(json.dumps(result,indent=2)+'\n')
            return result
        finally:
            plane.stop()


if __name__=='__main__':
    (ROOT/'results/tmp').mkdir(exist_ok=True)
    print(json.dumps(run()))
