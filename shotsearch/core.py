"""Persistence, OCR, indexing, and retrieval with explicit responsibilities."""
import hashlib
import json
import logging
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile
from PIL import Image, ImageOps


class ScreenshotRepository:
    def __init__(self, path):
        path = Path(path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS images (
            id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL,
            digest TEXT NOT NULL, text TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL, error TEXT, updated TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE INDEX IF NOT EXISTS image_digest ON images(digest);
        CREATE VIRTUAL TABLE IF NOT EXISTS image_fts USING fts5(text);
        CREATE TABLE IF NOT EXISTS vectors (
            image_id INTEGER PRIMARY KEY, digest TEXT NOT NULL,
            model TEXT NOT NULL, data TEXT NOT NULL);
        ''')

    def get(self, path):
        return self.db.execute('SELECT * FROM images WHERE path=?', (str(path),)).fetchone()

    def save(self, path, digest, text, status, error=None):
        with self.db:
            self.db.execute('''INSERT INTO images(path,digest,text,status,error)
                VALUES(?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET
                digest=excluded.digest,text=excluded.text,status=excluded.status,
                error=excluded.error,updated=CURRENT_TIMESTAMP''',
                (str(path), digest, text, status, error))
            row = self.get(path)
            self.db.execute('DELETE FROM image_fts WHERE rowid=?', (row['id'],))
            self.db.execute('DELETE FROM vectors WHERE image_id=?', (row['id'],))
            if status == 'ready':
                self.db.execute('INSERT INTO image_fts(rowid,text) VALUES(?,?)', (row['id'], text))

    def remove(self, image_id):
        with self.db:
            self.db.execute('DELETE FROM image_fts WHERE rowid=?', (image_id,))
            self.db.execute('DELETE FROM vectors WHERE image_id=?', (image_id,))
            return self.db.execute('DELETE FROM images WHERE id=?', (image_id,)).rowcount

    def ready(self):
        return self.db.execute("SELECT * FROM images WHERE status='ready' ORDER BY id").fetchall()

    def close(self):
        self.db.close()


class OCRService:
    def __init__(self, executable='tesseract', language='eng'):
        self.executable = executable
        self.language = language

    def extract(self, path):
        if not shutil.which(self.executable):
            raise RuntimeError('Tesseract is missing. Install it and add it to PATH; see README.')
        # Normalize orientation/contrast and enlarge small screenshots for OCR.
        # Keep line structure and punctuation; never threshold away thin code glyphs.
        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source).convert('RGB')
            image.thumbnail((4000, 4000))
            if max(image.size) < 1800:
                image = image.resize((image.width * 2, image.height * 2), Image.Resampling.LANCZOS)
            image = ImageOps.grayscale(image)
            if image.resize((1, 1)).getpixel((0, 0)) < 110:
                image = ImageOps.invert(image)
            image = ImageOps.autocontrast(image)
            with tempfile.TemporaryDirectory() as folder:
                prepared = Path(folder) / 'prepared.png'
                image.save(prepared)
                result = subprocess.run(
                    [self.executable, str(prepared), 'stdout', '-l', self.language,
                     '-c', 'preserve_interword_spaces=1'],
                    capture_output=True, text=True, timeout=60, encoding='utf-8', errors='replace')
        if result.returncode:
            raise RuntimeError(result.stderr.strip()[-500:] or 'Could not read this image')
        return result.stdout.strip()



class IndexingService:
    extensions = {'.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff', '.webp'}

    def __init__(self, repository, ocr):
        self.repo, self.ocr = repository, ocr

    def index(self, directory, force=False, progress=None):
        root = Path(directory).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f'Not a directory: {root}')
        counts = dict(indexed=0, unchanged=0, reused=0, empty=0, failed=0)
        paths = [p for p in sorted(root.rglob('*')) if p.is_file() and not p.is_symlink() and p.suffix.lower() in self.extensions]
        for position, path in enumerate(paths):
            if progress:
                progress(position, len(paths), path.name)
            if not path.is_file() or path.is_symlink() or path.suffix.lower() not in self.extensions:
                continue
            path = path.resolve()
            digest = ''
            try:
                with path.open('rb') as stream:
                    digest = hashlib.file_digest(stream, 'sha256').hexdigest() if hasattr(hashlib, 'file_digest') else hashlib.sha256(stream.read()).hexdigest()
                old = self.repo.get(path)
                if old and old['digest'] == digest and old['status'] != 'error' and not force:
                    counts['unchanged'] += 1
                    continue
                cached = None if force else self.repo.db.execute(
                    "SELECT text,status FROM images WHERE digest=? AND status!='error' LIMIT 1", (digest,)).fetchone()
                text = cached['text'] if cached else self.ocr.extract(path)
                status = 'ready' if text else 'empty'
                self.repo.save(path, digest, text, status)
                counts['reused' if cached else ('indexed' if text else 'empty')] += 1
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                self.repo.save(path, digest, '', 'error', str(exc))
                counts['failed'] += 1
        if progress:
            progress(len(paths), len(paths), 'Text reading complete')
        return counts


class SearchService:
    model_name = 'sentence-transformers/all-MiniLM-L6-v2'
    embedding_key = model_name + ':text-v2'

    def __init__(self, repository):
        self.repo = repository
        self._model = None

    def model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError('Semantic support missing. Run: pip install -e .') from exc
            try:
                self._model = SentenceTransformer(self.model_name, device='cpu')
            except Exception as exc:
                logging.getLogger(__name__).exception('Could not load the search model')
                raise RuntimeError('Could not load the local search model. Check your internet connection for first setup, then retry preparation. If offline mode is enabled before the download finished, turn it off and restart.') from exc
        return self._model

    @staticmethod
    def terms(query):
        # Quoted phrases stay together. Everything else requires all query words.
        return [phrase or word for phrase, word in re.findall(r'"([^"\n]+)"|(\w+)', query)]

    def lexical(self, query):
        terms = self.terms(query)
        if not terms:
            return []
        expression = ' AND '.join('"' + term.replace('"', '""') + '"' for term in terms)
        return [dict(row) for row in self.repo.db.execute('''SELECT images.* FROM image_fts
            JOIN images ON images.id=image_fts.rowid WHERE image_fts MATCH ?
            ORDER BY bm25(image_fts),images.id''', (expression,))]

    @staticmethod
    def code_language(text):
        patterns = {
            'python': [r'\bdef\s+\w+\s*\(', r'\b(?:from\s+\w+\s+)?import\s+\w+',
                       r'\bself\.', r'\bprint\s*\(', r'__name__', r'\b(?:for|if|while)\b[^\n]+:\s*(?:\n|$)'],
            'java': [r'\bpublic\s+(?:static\s+)?(?:class|void)', r'System\.out\.',
                     r'\bString\s*\[\s*\]', r'\bnew\s+\w+\s*\(', r'\bprivate\s+\w+'],
        }
        scores = {language: sum(bool(re.search(p, text)) for p in rules) for language, rules in patterns.items()}
        winner = max(scores, key=scores.get)
        return winner if scores[winner] >= 2 and scores[winner] > min(scores.values()) else None

    @staticmethod
    def searchable_text(text):
        # Explain standard error identifiers to a prose embedding model. This is
        # deterministic metadata, not generated text or a change to the OCR result.
        errors = {
            'ModuleNotFoundError': 'Python import error: missing package or module; dependency not installed.',
            'ImportError': 'Python import error: cannot import a module or name.',
            'SyntaxError': 'Programming syntax error: invalid code syntax.',
            'PermissionError': 'File access error: permission denied, cannot read or write a file.',
            'MemoryError': 'Out of memory error: insufficient memory for allocation.',
            'FileNotFoundError': 'Missing file error: file path does not exist.',
            'ConnectionRefusedError': 'Network connection error: server refused the connection.',
        }
        descriptions = [description for name, description in errors.items()
                        if re.search(r'\b' + name + r'\b', text)]
        return ' '.join(descriptions) + '\n' + text

    @staticmethod
    def excerpt(text, query):
        terms = re.findall(r'\w+', query)
        matches = list(re.finditer('|'.join(re.escape(t) for t in terms), text, re.I)) if terms else []
        start = max(0, matches[0].start() - 65) if matches else 0
        return ('…' if start else '') + text[start:start+240].strip() + ('…' if start+240 < len(text) else '')

    def prepared(self):
        return self.repo.db.execute("SELECT COUNT(*) FROM images i JOIN vectors v ON v.image_id=i.id WHERE i.status='ready' AND i.digest=v.digest AND v.model=?", (self.embedding_key,)).fetchone()[0]

    def embed(self, progress=None):
        if progress:
            progress(0, 0, 'Getting search ready… First setup may download the local model.')
        rows = self.repo.ready()
        if not rows:
            return 0
        model = self.model()
        count = 0
        for position, row in enumerate(rows):
            if progress:
                progress(position, len(rows), Path(row['path']).name)
            cached = self.repo.db.execute('SELECT * FROM vectors WHERE image_id=?', (row['id'],)).fetchone()
            if cached and cached['digest'] == row['digest'] and cached['model'] == self.embedding_key:
                continue
            # Short overlapping chunks avoid losing the end of long screenshots.
            words = self.searchable_text(row['text']).split()
            chunks = [' '.join(words[i:i+100]) for i in range(0, len(words), 75)]
            vectors = model.encode(chunks, normalize_embeddings=True).tolist()
            with self.repo.db:
                self.repo.db.execute('INSERT OR REPLACE INTO vectors VALUES(?,?,?,?)',
                    (row['id'], row['digest'], self.embedding_key, json.dumps(vectors)))
            count += 1
        if progress:
            progress(len(rows), len(rows), 'Ready to search')
        return count

    def search(self, query, mode='keyword', limit=None):
        if not query.strip():
            raise ValueError('Search query must not be empty.')
        if mode not in ('keyword', 'hybrid'):
            raise ValueError('Choose Keyword or Keyword + meaning.')
        if limit is not None and limit < 1:
            raise ValueError('Limit must be positive.')
        lexical = self.lexical(query)
        records = {r['id']: r for r in lexical}
        # Keyword mode follows BM25. Combined mode primarily follows cosine
        # similarity, with small lexical/code boosts rather than exclusion gates.
        scores = {r['id']: 2 + 1/(i+1) for i, r in enumerate(lexical)}
        reasons = {r['id']: 'Matching words' for r in lexical}
        if mode == 'hybrid':
            rows = self.repo.ready()
            if self.prepared() != len(rows):
                raise ValueError('Search preparation is incomplete. Open Manage collection and retry preparation.')
            q = self.model().encode(query, normalize_embeddings=True).tolist() if rows else []
            vectors = {r['image_id']: json.loads(r['data']) for r in self.repo.db.execute('SELECT * FROM vectors')}
            words = set(re.findall(r'\w+', query.lower()))
            requested = next((lang for lang in ('python','java') if lang in words), None)
            code_intent = requested and words <= {requested, 'code', 'program', 'programming', 'snippet', 'example', 'examples'}
            for raw in rows:
                row = dict(raw)
                language = self.code_language(row['text'])
                similarity = max((sum(a*b for a,b in zip(q,v)) for v in vectors[row['id']]), default=0)
                exact = row['id'] in records
                # Restore broad semantic recall: weak positive matches stay visible
                # lower down instead of being rejected by a fixed high cutoff.
                if similarity > 0 or exact or (code_intent and language == requested):
                    records[row['id']] = row
                    score = max(similarity, 0)
                    if exact:
                        score += 0.15
                    if code_intent and language == requested:
                        score += 0.25
                        reason = f'Likely {language.title()} code'
                    else:
                        reason = 'Matching words' if exact else 'Related text'
                    if code_intent and language and language != requested:
                        score -= 0.15
                    scores[row['id']] = score
                    reasons[row['id']] = reason
        results, seen = [], set()
        for key in sorted(scores, key=lambda k: (-scores[k], k)):
            row = records[key]
            if row['digest'] in seen or not Path(row['path']).is_file():
                continue
            seen.add(row['digest'])
            results.append({'id': key, 'path': row['path'], 'snippet': self.excerpt(row['text'], query),
                            'match_reason': reasons[key], 'rank_score': scores[key]})
            if limit is not None and len(results) == limit:
                break
        return results
