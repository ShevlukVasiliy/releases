import json
import tempfile
import unittest
from pathlib import Path
from releases.db import Database
from releases.catalog import check, compare

class Provider:
    def __init__(self): self.finds = 0; self.calls = 0
    def find(self, name):
        self.finds += 1
        if name == 'Broken': raise OSError('offline')
        return {'id': '42', 'name': name}
    def albums(self, artist_id):
        self.calls += 1
        return [dict(id=1, title='Owned', version=None, type='album', year=2025, date='2025', tracks=10, artists=['42']), dict(id=2, title='New', version=None, type='single', year=2026, date='2026', tracks=1, artists=['42'])]

class CatalogTests(unittest.TestCase):
    def test_compare_filters_and_local_matches(self):
        albums = Provider().albums('42')
        local = {'albums': {'owned'}, 'tracks': set()}
        self.assertEqual([x['id'] for x in compare(albums,'42','A',local,{})], [2])
        self.assertEqual(compare(albums,'42','A',local,{'no_singles':True}), [])
        self.assertEqual(compare(albums,'42','A',local,{'since':2027}), [])

    def test_partial_errors_cache_and_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Database(Path(tmp)/'db'); db.initialize()
            with db.connect() as c:
                c.execute("INSERT INTO artists(name,normalized_name,track_count) VALUES('Good','good',1),('Broken','broken',1)")
                c.execute("INSERT INTO files VALUES('one',1,1,?,CURRENT_TIMESTAMP)", (json.dumps({'artist':'Good','album':'Owned','title':'Song'}),))
            provider=Provider(); updates=[]
            result=check(db,provider,[1,2],{},lambda *a: updates.append(a))
            self.assertEqual(result['results'][0]['missing'][0]['id'],2)
            self.assertEqual(result['errors'],1)
            self.assertEqual(len(updates),2)
            check(db,provider,[1],{})
            self.assertEqual(provider.calls,1)
            self.assertEqual(provider.finds,2)
