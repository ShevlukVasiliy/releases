import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from releases.db import Database
from releases.legacy import import_legacy
from releases.links import parse_album_ids
from releases.credentials import set_token, get_token

class FakeBackend:
    def __init__(self): self.value = None
    def set_password(self, service, account, value): self.value = value
    def get_password(self, service, account): return self.value

class MigrationTests(unittest.TestCase):
    def test_import_only_missing_settings_preserves_source_and_manual_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); db=Database(root/'state'); db.initialize()
            with db.connect() as conn:
                conn.execute("INSERT INTO artists(name,normalized_name,track_count) VALUES('One','one',1),('Two','two',1)")
                conn.execute("INSERT INTO artist_matches(artist_id,provider_id,provider_name,is_manual) VALUES(1,'99','Manual',1)")
            exclude=root/'exclude'; exclude.write_text('One # reason\nUnknown\n')
            cache=root/'cache'; original=json.dumps({'one':{'id':1,'name':'Old'},'two':{'id':2,'name':'Two'}}); cache.write_text(original)
            result=import_legacy(db,exclude,cache)
            self.assertEqual((result['excluded_added'],result['matches_added'],result['excluded_not_in_library']),(1,1,1))
            with db.connect() as conn:
                self.assertEqual(conn.execute('SELECT provider_id FROM artist_matches WHERE artist_id=1').fetchone()[0],'99')
            self.assertEqual(cache.read_text(),original)
            self.assertEqual(import_legacy(db,exclude,cache)['matches_added'],0)

    def test_parse_only_yandex_album_urls_or_ids(self):
        self.assertEqual(parse_album_ids('https://music.yandex.ru/album/123?x=1\n123\n456\nhttps://evil.test/album/789\nhttps://music.yandex.ru.evil.test/album/10'),[123,456])

    def test_token_storage_uses_backend_and_rejects_invalid(self):
        fake=FakeBackend()
        with patch('releases.credentials.backend',return_value=fake):
            set_token('sample-token'); self.assertEqual(get_token(),'sample-token')
            with self.assertRaises(ValueError): set_token('invalid token')
