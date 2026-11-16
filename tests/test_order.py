import unittest
from unittest.mock import patch
from releases.order import preview_order, apply_order

class OrderTests(unittest.TestCase):
    def test_preview_proposes_changes_without_writing(self):
        snapshot={'ids':[1], 'persistent':['abc'], 'titles':['Song'], 'artists':['Artist'], 'albumArtists':['Artist'], 'albums':['Album'], 'numbers':[2], 'totals':[1], 'discs':[1], 'discTotals':[1]}
        with patch('releases.order.music_script',return_value=snapshot) as script, patch('releases.order.match_album_order',return_value=[(1,1,1,1)]):
            result=preview_order(object())
            self.assertEqual(result['changes'][0]['old'],[2,1,1,1])
            self.assertEqual(result['changes'][0]['values'],[1,1,1,1])
            self.assertEqual(script.call_count,1)
    def test_apply_reports_application_failures(self):
        with patch('releases.order.music_script',return_value={'updated':0,'errors':['track changed']}):
            result=apply_order([{'id':1}])
            self.assertEqual(result,{'updated':0,'errors':['track changed']})
