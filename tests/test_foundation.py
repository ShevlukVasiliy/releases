import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from releases.db import Database
from releases.server import create_app

class FoundationTests(unittest.TestCase):
    def test_database_persists_and_reinitializes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'data' / 'state.sqlite3'
            db = Database(path)
            db.initialize()
            with db.connect() as conn:
                conn.execute("INSERT INTO jobs(kind,status,params_json) VALUES('scan','queued','{}')")
            Database(path).initialize()
            self.assertEqual(Database(path).jobs()[0]['status'], 'queued')
            self.assertEqual(db.status()['jobs'], 1)

    def test_local_http_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / 'test.sqlite3')
            db.initialize()
            app = create_app(db, Path(tmp), Path(tmp), 'test-token', 8771)
            client = app.test_client()
            headers = {'Host': '127.0.0.1:8771'}
            self.assertEqual(client.get('/api/status',headers=headers).json['service'], 'releases')
            self.assertEqual(client.get('/api/jobs',headers=headers).json, [])
            self.assertEqual(client.post('/api/scan',headers=headers).status_code,403)
            self.assertEqual(client.get('/api/status',headers={'Host':'attacker.test:8771'}).status_code,403)
            self.assertEqual(client.get('/',headers=headers).status_code,200)
            response = client.get('/app.js',headers=headers)
            self.assertEqual(response.status_code,200)
            response.close()

if __name__ == '__main__':
    unittest.main()
