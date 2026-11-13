"""Authenticated offline demonstration client for an owner-operated local service."""
import argparse
import json
from omega_x.client import OmegaClient
from omega_x.service import load_keys


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--keys-file',required=True)
    parser.add_argument('--tenant',required=True)
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--kind',choices=('sha256','saxpy','memory'),default='sha256')
    parser.add_argument('--size',type=int,default=1024)
    parser.add_argument('--idempotency-key')
    args=parser.parse_args(argv)
    key=load_keys(args.keys_file)[args.tenant]
    client=OmegaClient(key,port=args.port)
    job=client.submit(args.kind,args.size,idempotency_key=args.idempotency_key)
    result=client.wait(job['job_id'])
    print(json.dumps(result,indent=2,sort_keys=True))
    return 0 if result['status']=='SUCCEEDED' else 2


if __name__=='__main__':
    raise SystemExit(main())
