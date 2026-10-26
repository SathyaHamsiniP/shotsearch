"""Developer evaluation runner. Uses real OCR + embeddings in an isolated database."""
import argparse
import csv
import json
from pathlib import Path
import sys
import tempfile
from time import perf_counter
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shotsearch.core import ScreenshotRepository, IndexingService, OCRService, SearchService

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--images',type=Path,default=Path(__file__).parent/'images')
    parser.add_argument('--labels',type=Path,default=Path(__file__).parent/'queries.csv')
    parser.add_argument('--mode',choices=['keyword','hybrid'],help='Override all query modes for baseline comparison')
    parser.add_argument('--split',choices=['development','holdout','all'],default='development')
    parser.add_argument('--output',type=Path,default=Path(__file__).parent/'report.json')
    args=parser.parse_args()
    with args.labels.open(encoding='utf-8-sig',newline='') as file: labels=list(csv.DictReader(file))
    labels=[r for r in labels if args.split=='all' or r['split']==args.split]
    names=[p.name for p in args.images.rglob('*') if p.suffix.lower() in IndexingService.extensions]
    if len(names)!=len(set(names)): raise ValueError('Use unique image filenames in the evaluation collection.')
    for row in labels:
        for expected in filter(None,row['expected_files'].split(';')):
            if expected not in names: raise ValueError('Expected image missing: '+expected)
    results=[]
    with tempfile.TemporaryDirectory() as folder:
        repo=ScreenshotRepository(Path(folder)/'evaluation.sqlite3')
        try:
            counts=IndexingService(repo,OCRService()).index(args.images)
            search=SearchService(repo)
            if any((args.mode or r['mode'])=='hybrid' for r in labels): search.embed()
            for row in labels:
                expected=set(filter(None,row['expected_files'].split(';')))
                start=perf_counter(); found=search.search(row['query'],args.mode or row['mode'],5); seconds=perf_counter()-start
                actual=[Path(r['path']).name for r in found]
                hits=expected.intersection(actual)
                results.append(dict(query=row['query'],mode=args.mode or row['mode'],expected=sorted(expected),actual=actual,
                    recall_at_5=len(hits)/len(expected) if expected else None,
                    reciprocal_rank=next((1/(i+1) for i,name in enumerate(actual) if name in expected),0) if expected else None,
                    irrelevant_results=sum(name not in expected for name in actual),
                    correct_empty=not actual if not expected else None,seconds=round(seconds,4)))
        finally: repo.close()
    positives=[r for r in results if r['expected']]; negatives=[r for r in results if not r['expected']]
    report=dict(note='Synthetic fixtures measure a narrow baseline, not real-world accuracy. Timings exclude model startup.',
        split=args.split,processing=counts,queries=results,
        mean_recall_at_5=sum(r['recall_at_5'] for r in positives)/len(positives) if positives else None,
        mean_reciprocal_rank=sum(r['reciprocal_rank'] for r in positives)/len(positives) if positives else None,
        correct_no_result_rate=sum(r['correct_empty'] for r in negatives)/len(negatives) if negatives else None)
    args.output.write_text(json.dumps(report,indent=2),encoding='utf-8'); print(json.dumps(report,indent=2))
if __name__=='__main__': main()
