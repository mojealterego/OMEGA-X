"""Versioned, canonical JSON Digital-Life bridge; no network, repo writes or auto-apply."""
from dataclasses import asdict
import hashlib
import json
from .model import Workload, workload_from_dict

MAX_MESSAGE = 2_000_000


def encode(workloads: list[Workload], request_id: str) -> bytes:
    if not request_id.isascii() or len(request_id) > 128 or not request_id:
        raise ValueError('invalid request id')
    body = {'version': 1, 'request_id': request_id, 'tasks': [asdict(w) for w in workloads]}
    # Enum derives from str; canonical JSON emits the stable value.
    raw = json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()
    if len(raw) > MAX_MESSAGE:
        raise ValueError('message too large')
    return raw


def _reject_duplicates(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError('duplicate JSON key')
        obj[key] = value
    return obj


def decode(raw: bytes) -> tuple[str, list[Workload]]:
    if len(raw) > MAX_MESSAGE:
        raise ValueError('message too large')
    body = json.loads(raw, object_pairs_hook=_reject_duplicates,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
    if not isinstance(body, dict) or set(body) != {'version', 'request_id', 'tasks'}:
        raise ValueError('invalid envelope keys')
    if type(body['version']) is not int or body['version'] != 1 or not isinstance(body['request_id'], str) or not body['request_id'].isascii() or not 0 < len(body['request_id']) <= 128:
        raise ValueError('unsupported protocol version or request id')
    if not isinstance(body['tasks'], list) or len(body['tasks']) > 4096:
        raise ValueError('invalid task array')
    tasks = [workload_from_dict(task) for task in body['tasks']]
    if len({task.task_id for task in tasks}) != len(tasks):
        raise ValueError('duplicate task identifiers')
    return body['request_id'], tasks


def idempotency_key(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()
