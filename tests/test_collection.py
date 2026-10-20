import csv
from datetime import date
import hashlib
import json
from pathlib import Path
import unittest
from collect_reviews import parse_feed

ROOT=Path(__file__).resolve().parents[1]

class CollectionTests(unittest.TestCase):
    def test_source_snapshots_match_collected_reviews(self):
        for country in ['us','gb']:
            manifest=json.loads((ROOT/f'data/collection_manifest_{country}.json').read_text())
            actual={}
            for capture in manifest['captures']:
                raw=(ROOT/capture['path']).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(),capture['sha256'])
                for row in parse_feed(json.loads(raw),capture['url'],date(2026,10,20),12,manifest['retrieved_at']):
                    actual[row['review_id']]=row
            with (ROOT/f'data/reviews_app_store_{country}.csv').open() as f:rows=list(csv.DictReader(f))
            self.assertEqual(len(rows),500)
            self.assertEqual(len({r['review_id'] for r in rows}),500)
            for row in rows:
                source=actual[row['review_id']]
                for field in ['date','review_text','rating','source_feed_url','source_updated_at','retrieved_at']:
                    self.assertEqual(row[field],source[field])
    def test_default_expansion_keeps_source_evidence(self):
        with (ROOT/'reviews_sample.csv').open() as f:rows=list(csv.DictReader(f))
        self.assertEqual(len(rows),512)
        self.assertEqual(sum(r['review_id'].startswith('APPLE_') for r in rows),500)
        self.assertEqual(sum(r['review_id'].startswith('R') for r in rows),12)
        self.assertTrue(all(date(2026,7,28)<=date.fromisoformat(r['date'])<=date(2026,10,20) for r in rows))

if __name__=='__main__':unittest.main()
