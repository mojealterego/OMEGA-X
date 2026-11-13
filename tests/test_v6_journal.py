"""RED-first tests: authenticated replayable append-only events."""
from pathlib import Path
import json
import os
import tempfile
import threading
import unittest

from omega_x.proof_stream import ProofStream, IntegrityViolation


class ProofStreamTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.key = bytes.fromhex('55'*32)

    def make(self):
        return ProofStream(self.dir/'events.jsonl', self.key, max_records=128)

    def test_roundtrip_and_external_anchor(self):
        stream = self.make()
        one = stream.append('JOB', {'id': 1, 'tenant': 't'})
        two = stream.append('RESULT', {'status':'accepted'})
        self.assertNotEqual(one['head'], two['head'])
        self.assertEqual(stream.verify(expected_head=two['head'], expected_count=2)['count'], 2)
        self.assertEqual(self.make().verify()['head'], two['head'])
        with self.assertRaises(IntegrityViolation):
            stream.verify(expected_head=one['head'])

    def test_rewrite_detected(self):
        stream = self.make()
        stream.append('JOB', {'id': 11})
        path = self.dir/'events.jsonl'
        path.write_bytes(path.read_bytes().replace(b'"id":11', b'"id":12'))
        with self.assertRaises(IntegrityViolation):
            stream.verify()
        with self.assertRaises(IntegrityViolation):
            stream.append('JOB', {'id': 2})

    def test_truncated_tail_denied(self):
        stream = self.make()
        stream.append('JOB', {'id': 11})
        with (self.dir/'events.jsonl').open('ab') as f:
            f.write(b'{"partial":')
        with self.assertRaises(IntegrityViolation):
            stream.verify()

    def test_oversize_nan_and_invalid_type_rejected(self):
        stream = self.make()
        for payload in ({'value':float('nan')}, {'blob':'X'*10000}, {'thing':object()}):
            with self.assertRaises((ValueError, TypeError)):
                stream.append('JOB', payload)
        self.assertEqual(stream.verify()['count'], 0)

    def test_non_private_file_rejected(self):
        path = self.dir/'events.jsonl'
        path.write_bytes(b'')
        os.chmod(path, 0o644)
        with self.assertRaises(PermissionError):
            self.make()

    def test_external_count_anchor_detects_truncation(self):
        stream = self.make()
        first = stream.append('E', {'i':1})
        head = stream.append('E', {'i':2})['head']
        path = self.dir/'events.jsonl'
        path.write_bytes(path.read_bytes().splitlines(keepends=True)[0])
        # The surviving prefix is internally well-formed, but externally pinned
        # sequence and head prove a rollback of the complete suffix.
        self.assertEqual(stream.verify()['count'], 1)
        with self.assertRaises(IntegrityViolation):
            stream.verify(expected_head=head, expected_count=2)

    def test_symlink_forbidden(self):
        target = self.dir/'target'
        target.write_text('hidden')
        link = self.dir/'alias'
        link.symlink_to(target)
        with self.assertRaises((OSError, PermissionError)):
            ProofStream(link, self.key)

    def test_parallel_appends_have_unique_seq(self):
        stream = self.make()
        errors = []
        def task(i):
            try:
                stream.append('EVENT', {'i': i})
            except Exception as exc:
                errors.append(str(exc))
        threads = [threading.Thread(target=task, args=(i,)) for i in range(16)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertFalse(errors)
        self.assertEqual(stream.verify()['count'], 16)

    def test_verify_missing_is_not_created(self):
        stream = self.make()
        with self.assertRaises(IntegrityViolation):
            stream.verify()
        self.assertFalse((self.dir/'events.jsonl').exists())

    def test_wrong_mac_key_rejected(self):
        stream = self.make()
        stream.append('E', {'ok': True})
        with self.assertRaises(IntegrityViolation):
            ProofStream(self.dir/'events.jsonl', b'B'*32).verify()

    def test_bounded_append(self):
        stream = ProofStream(self.dir/'events.jsonl', self.key, max_records=1)
        stream.append('E', {'ok': True})
        with self.assertRaises(ValueError):
            stream.append('E', {'ok': True})


if __name__ == '__main__':
    unittest.main()
