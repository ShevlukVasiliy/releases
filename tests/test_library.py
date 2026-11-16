import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from releases.db import Database
from releases.library import scan
from releases.jobs import JobRunner

class LibraryTests(unittest.TestCase):
    def test_incremental_scan_preserves_previous_index_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'music'
            (root / 'Artist').mkdir(parents=True)
            track = root / 'Artist' / 'one.mp3'
            track.write_bytes(b'first')
            db = Database(Path(tmp) / 'db.sqlite3'); db.initialize()
            metadata = {'artist': 'Artist', 'album': 'Album', 'title': 'One', 'credited': [], 'read_error': None}
            with patch('releases.library.read_metadata', return_value=metadata) as reader:
                self.assertEqual(scan(db, root)['read'], 1)
                self.assertEqual(scan(db, root)['reused'], 1)
                self.assertEqual(reader.call_count, 1)
                track.write_bytes(b'changed')
                self.assertEqual(scan(db, root)['read'], 1)
                with patch('releases.library.os.walk', side_effect=PermissionError('denied')):
                    with self.assertRaises(PermissionError): scan(db, root)
                self.assertEqual(db.status()['indexed_files'], 1)
                track.unlink()
                self.assertEqual(scan(db, root)['files'], 0)
                self.assertEqual(db.status()['indexed_files'], 0)

    def test_interrupted_job_is_not_replayed(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / 'db.sqlite3'); db.initialize()
            with db.connect() as conn:
                conn.execute("INSERT INTO jobs(kind,status,params_json) VALUES('scan','running','{}')")
            JobRunner(db)
            self.assertEqual(db.jobs()[0]['status'], 'interrupted')
