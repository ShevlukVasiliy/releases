import tempfile
import unittest
from pathlib import Path
from releases.db import Database
from releases.music import import_album

class MusicTests(unittest.TestCase):
    def test_import_keeps_original_and_verifies_repeated_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); folder=root/'album'; folder.mkdir()
            song=folder/'01 Song.mp3'; song.write_bytes(b'original')
            db=Database(root/'state'); db.initialize(); calls=[]
            def add(path, existing):
                calls.append(existing)
                return {'persistent_id':'ABC', 'location':str(path)}
            first=import_album(db, folder, add=add)
            second=import_album(db, folder, add=add)
            self.assertEqual(calls,['','ABC'])
            self.assertEqual([first['files'][0]['status'],second['files'][0]['status']],['imported','verified'])
            self.assertEqual(song.read_bytes(),b'original')
            song.write_bytes(b'changed file')
            self.assertEqual(import_album(db,folder,add=add)['errors'],1)
            self.assertEqual(calls,['','ABC'])

    def test_uncertain_attempt_is_not_automatically_repeated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); folder=root/'album'; folder.mkdir(); (folder/'song.mp3').write_bytes(b'audio')
            db=Database(root/'state'); db.initialize(); calls=[]
            def fail(path, existing): calls.append(1); raise TimeoutError('unknown outcome')
            self.assertEqual(import_album(db,folder,add=fail)['errors'],1)
            self.assertEqual(import_album(db,folder,add=fail)['errors'],1)
            self.assertEqual(len(calls),1)
