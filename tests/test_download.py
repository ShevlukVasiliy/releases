import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as Obj
from unittest.mock import patch
from releases.download import download_album

class Info:
    codec='mp3'; preview=False; bitrate_in_kbps=320
    def download(self, path): Path(path).write_bytes(b'audio')

class DownloadTests(unittest.TestCase):
    def test_existing_files_are_not_overwritten_and_new_files_are_published(self):
        track=Obj(title='Song', version=None, available=True, get_download_info=lambda: [Info()])
        album=Obj(title='Album', version=None, year=2025, artists=[Obj(name='Artist')], volumes=[[track]], cover_uri=None)
        client=Obj(albums_with_tracks=lambda _: album)
        with tempfile.TemporaryDirectory() as tmp:
            with patch('releases.download.tag_file'):
                first=download_album(client, 42, tmp)
                file=Path(first['folder'])/'01 Song.mp3'
                self.assertEqual(file.read_bytes(),b'audio')
                file.write_bytes(b'original')
                second=download_album(client, 42, tmp)
                self.assertEqual(file.read_bytes(),b'original')
                self.assertEqual((first['downloaded'],second['skipped']),(1,1))
                self.assertEqual(list(Path(first['folder']).glob('*.part')),[])

    def test_tag_failure_does_not_publish_partial_file(self):
        track=Obj(title='Song', version=None, available=True, get_download_info=lambda: [Info()])
        album=Obj(title='Album', version=None, year=None, artists=[Obj(name='Artist')], volumes=[[track]], cover_uri=None)
        with tempfile.TemporaryDirectory() as tmp, patch('releases.download.tag_file', side_effect=ValueError('tag failed')):
            with self.assertRaises(ValueError): download_album(Obj(albums_with_tracks=lambda _:album),42,tmp)
            self.assertEqual(list(Path(tmp).rglob('*.mp3')),[])
            self.assertEqual(list(Path(tmp).rglob('*.part')),[])
