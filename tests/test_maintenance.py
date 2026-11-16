import tempfile
import unittest
from pathlib import Path
from mutagen.id3 import ID3, TIT2, TPE1, TPE2
from releases.maintenance import preview, apply

class MaintenanceTests(unittest.TestCase):
    def test_preview_apply_and_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'track.mp3'; tags=ID3(); tags.add(TIT2(encoding=3,text='  Title  ')); tags.add(TPE1(encoding=3,text='Artist')); tags.save(path,v2_version=4)
            original=path.read_bytes(); result=preview(temp)
            self.assertEqual(len(result['changes']),1)
            self.assertEqual(path.read_bytes(),original)
            outcome=apply(result)
            self.assertEqual(outcome['errors'],0)
            self.assertEqual(Path(str(path)+'.releases-backup').read_bytes(),original)
            self.assertEqual(str(ID3(path)['TIT2']), 'Title')
            self.assertIn('TPE2',ID3(path))
            self.assertEqual(apply(result)['errors'],1)

    def test_changed_file_is_not_written(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'track.mp3'; tags=ID3(); tags.add(TPE1(encoding=3,text='Artist')); tags.save(path)
            result=preview(temp); path.write_bytes(b'changed'); outcome=apply(result)
            self.assertEqual(outcome['errors'],1);self.assertEqual(path.read_bytes(),b'changed')
