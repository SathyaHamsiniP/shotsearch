# ShotSearch

A local website for finding screenshots and photos by the **text inside them**. Images stay in their original folders. No API key, paid service, or account is needed.

## Install and run (Windows PowerShell)

Use Python 3.10 or newer. From this folder:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m shotsearch.web
```

Open **http://127.0.0.1:5000**. Leave the server running; Ctrl+C stops it.

Tesseract must also be installed. If it is installed in the usual Windows location but cannot be found, run this before starting the website:

```powershell
$env:Path += ";C:\Program Files\Tesseract-OCR"
```

See Tesseract's installation documentation: https://tesseract-ocr.github.io/tessdoc/Installation.html

The first preparation downloads `sentence-transformers/all-MiniLM-L6-v2`. This can take a few minutes and needs internet access. A Hugging Face token is not required. Later runs use the downloaded model. If the model is already fully downloaded, you can skip online checks with:

```powershell
$env:HF_HUB_OFFLINE = "1"
python -m shotsearch.web
```

Do not enable offline mode before the first successful download. Meaning search has no per-query charge; it uses your computer's CPU and memory.

## Upgrading from the previous version

Extract this version into a **fresh folder** so old CLI files are not left behind. Activate a virtual environment and run `python -m pip install -e .` there. Stop the old server before starting the new one.

Your existing database at `%USERPROFILE%\.shotsearch\index.sqlite3` is reused automatically. This version refreshes existing embeddings once on startup to include descriptions of common error messages. Subsequent runs reuse valid embeddings. Your image files are unaffected.

To apply the improved text reader to previously added images, add the same folder once with **Reprocess unchanged images** checked. That also replaces their saved search data automatically.

## Using the website

1. Open **Manage collection** and paste your own full image-folder path. It need not match anyone else's computer.
2. Click **Add folder**. The app scans supported images in that folder and its subfolders, reads text, and prepares meaning search automatically.
3. Wait for **Your collection is ready**. Progress is shown while processing. The model stays loaded while the server runs.
4. Search using **Keyword + meaning** (default), or choose **Keyword**.
5. Click an image for its full preview, text, and original path. Clear the search with **✕** or **Back to collection** to restore your previous collection page and scroll position.

- **Keyword:** all entered words must occur in the extracted text. Quote a phrase, such as `"database connection"`, to require that word order. There is no typo correction.
- **Keyword + meaning:** includes exact matches and sufficiently similar extracted text. All positive-similarity candidates are retained and ranked by similarity with small exact-word and code-language boosts. Weaker results may be unrelated; they appear lower down. Conservative Python/Java syntax clues can identify likely code without the language name being printed; this is a heuristic, not a reliable language classifier.
- Search shows **all results, most relevant first**, with a full result count. There is no 12/24-result selector or hidden 200-result cap. Exact duplicate files are represented once, and missing originals are omitted. Broad meaning search prioritizes recall and may return weak candidates even for a query with no true answer. Use Keyword for strict word matching.
- Text excerpts appear only on search results. Matching words are highlighted. Full text is available in image details.
- Removing an image from the collection never deletes its original. Adding its folder again restores it.
- Folders are not continuously watched. Add the folder again to pick up changes; unchanged content is reused.
- If preparation fails, keyword search is still available for images whose text was read. Open **Manage collection → Retry search preparation**. For an OCR failure, fix the cause and add the folder again.

## Scope and limitations

Supported: PNG, JPG/JPEG, BMP, TIFF, WEBP. Printed-text screenshots, scanned pages, notices, and ordinary photos containing readable text can work. The default text language is English (`eng`); another Tesseract language must be installed before selecting its code.

Handwriting, mathematical notation, tiny or blurry text, and unusual layouts may be read incorrectly. The app normalizes orientation and contrast, lightens dark backgrounds, and enlarges smaller images, but these steps cannot recover unreadable text. “No readable text” differs from a processing error.

This is **text search inside images**, not general visual recognition. It does not identify objects, faces, or scenes. Semantic search embeds OCR text, not image pixels. It does not generate answers or use an LLM. No visual model, reranker, or handwriting-specific model is included.

This website runs locally on the user's computer. A typed folder path refers to the computer running Flask. A remotely hosted version would require uploads or explicit browser file access; do not expose this single-user server publicly. There is no native folder-picker dialog or account system.

## Architecture and data

- **Backend:** Python + Flask. A single background worker owns the SQLite connection and cached model; processing jobs serialize model/database work.
- **Database:** SQLite; FTS5 provides keyword retrieval. Tables hold image paths, hashes, extracted text, processing state, and JSON embedding vectors. Original image bytes are not stored in SQLite.
- **Frontend:** Jinja HTML templates, CSS, vanilla JavaScript. No Node build step.
- **OCR:** Tesseract with Pillow preprocessing.
- **Meaning search:** local Sentence Transformers `all-MiniLM-L6-v2`, overlapping text chunks, cosine similarity, broad candidate retrieval, descriptions of standard error identifiers, and explicit lexical priority.

The app listens only on `127.0.0.1`. Mutating requests require a page token; host and origin checks prevent ordinary cross-site requests. Images and extracted text are not uploaded by the application. Initial dependency/model downloads contact their respective providers.

Moving or deleting original files makes their previews unavailable; missing files are omitted from search. Search scores are internal ranking values, not calibrated confidence probabilities.

## Testing and measuring search quality

```powershell
python -m unittest discover -s tests -v
```

Unit tests use fake embeddings to verify ranking rules without downloads. They **do not prove the real embedding model is accurate**.

The `evaluation/` folder contains 26 synthetic printed-text images and 14 labelled queries, including code without language names, distractors, terminal errors, paraphrases, and no-answer searches. Images are generated from our own text; they contain no private screenshots. This is a narrow reproducible fixture, not a public-dataset benchmark or an evaluation of handwriting.

Run an end-to-end benchmark with real Tesseract and the local embedding model:

```powershell
python evaluation/evaluate.py --output evaluation/combined-report.json
python evaluation/evaluate.py --mode keyword --output evaluation/keyword-report.json
```

The runner builds a separate temporary database, leaving your collection untouched. Reports contain results for each query, recall in the first five results, reciprocal rank, irrelevant-result counts, no-result correctness, and query latency (excluding startup). This is a developer test utility, not a second end-user CLI interface.

Use the `development` rows for tuning. Once changes are settled, evaluate the reserved rows with `--split holdout`. Do not repeatedly tune against that split. Add real examples before claiming general accuracy.

To test your own 20–30 images, copy them into a separate evaluation folder and make a CSV with these columns:

```csv
query,mode,expected_files,split
Python code,hybrid,example1.png;example2.png,development
flight ticket,hybrid,,holdout
```

Use unique filenames, semicolons between expected matches, and an empty `expected_files` for no-answer queries. Decide the correct matches manually **before** inspecting search output.

```powershell
python evaluation/evaluate.py --images "C:\path\to\test-images" --labels "C:\path\to\labels.csv" --output evaluation/my-report.json
```

Included reports use real Tesseract and the local embedding model. The development collection now includes both `traffic` and `congestion` against an image containing “traffic intelligence.” Reports measure top-five retrieval; the website shows all candidates. Broad retrieval intentionally trades no-answer precision for fewer missed relevant images. These tiny synthetic results are a regression baseline, not evidence of general accuracy on your screenshots. No model-quality claim is based on mocked tests.


## Files

`shotsearch/core.py`: persistence, OCR, preparation and retrieval. `shotsearch/web.py`: local server and background jobs. `shotsearch/templates/` and `shotsearch/static/`: interface. `tests/` and `evaluation/`: regression checks and quality evaluation. CLI-only files and commands have been removed.
