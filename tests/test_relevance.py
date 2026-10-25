"""Deterministic ranking tests; fake vectors test rules, not model quality."""
import json
import tempfile
import unittest
from pathlib import Path
from shotsearch.core import ScreenshotRepository, SearchService

class Vector(list):
    def tolist(self): return list(self)
class FakeModel:
    def encode(self, text, **kwargs): return Vector([1.0, 0.0])

class RelevanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = ScreenshotRepository(self.root/'db')
        self.search = SearchService(self.repo)
        self.search._model = FakeModel()
    def tearDown(self): self.repo.close(); self.temp.cleanup()
    def add(self, name, text, similarity=.1):
        path = self.root/name; path.write_text(text)
        self.repo.save(path, name, text, 'ready')
        row = self.repo.get(path)
        with self.repo.db:
            self.repo.db.execute('INSERT INTO vectors VALUES(?,?,?,?)', (row['id'], name, self.search.embedding_key, json.dumps([[similarity, 0]])))
        return row['id']
    def test_code_without_language_beats_form_and_java(self):
        python = self.add('python.png', 'def total(items):\n    return sum(items)\nprint(total([1,2]))', .6)
        self.add('java.png', 'public class Main { public static void main(String[] args) { System.out.println(3); }}', .3)
        self.add('form.png', 'Python course registration', .6)
        results = self.search.search('python', 'hybrid')
        self.assertEqual(results[0]['id'], python)
        self.assertIn('java.png', [Path(r['path']).name for r in results])
        self.assertEqual(len(self.search.search('python', 'keyword')), 1)
    def test_weak_matches_are_visible_below_closer_matches(self):
        weak = self.add('weak.png', 'unrelated technical document', .12)
        close = self.add('traffic.png', 'busy roads and slow moving vehicles', .32)
        results = self.search.search('congestion', 'hybrid')
        self.assertEqual([r['id'] for r in results], [close, weak])

    def test_all_keyword_results_are_returned(self):
        for i in range(230):
            self.add(f'{i}.png', 'traffic details')
        self.assertEqual(len(self.search.search('traffic')), 230)
        self.assertEqual(len(self.search.search('traffic', 'hybrid')), 230)

    def test_strong_semantics_can_outrank_incidental_keyword(self):
        self.add('incidental.png', 'traffic word in an unrelated list', .1)
        close = self.add('close.png', 'congested roads', .6)
        self.assertEqual(self.search.search('traffic', 'hybrid')[0]['id'], close)

    def test_paraphrase_can_match_without_words(self):
        image = self.add('error.png', 'ModuleNotFoundError: No module named pandas', .8)
        self.assertEqual(self.search.search('missing package problem', 'hybrid')[0]['id'], image)
        self.assertEqual(self.search.search('missing package problem', 'keyword'), [])
    def test_keywords_require_all_words_and_phrase_order(self):
        self.add('one.png', 'database connection failed')
        self.add('two.png', 'connection to database succeeded')
        self.assertEqual(len(self.search.search('database failed')), 1)
        self.assertEqual(len(self.search.search('"database connection"')), 1)
        self.assertEqual(self.search.search('database absent'), [])
    def test_single_code_clue_is_not_language(self):
        self.assertIsNone(self.search.code_language('Please print the menu.'))
        self.assertIsNone(self.search.code_language('print(value)'))
    def test_excerpt_near_matching_text(self):
        self.add('long.png', 'unrelated ' * 100 + 'specific needle here')
        self.assertIn('needle', self.search.search('needle')[0]['snippet'])
    def test_updated_text_invalidates_vectors(self):
        self.add('one.png', 'hello')
        self.repo.save(self.root/'one.png', 'new', 'changed', 'ready')
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            self.search.search('changed', 'hybrid')
