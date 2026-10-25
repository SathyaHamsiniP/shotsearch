"""Single-user loopback web UI. A single worker owns SQLite and the ML model."""
import argparse
import atexit
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import secrets
import shutil
from threading import Lock
from time import perf_counter
from urllib.parse import urlsplit
from flask import Flask, jsonify, render_template, request, send_file
from .core import ScreenshotRepository, SearchService, OCRService, IndexingService


class Workspace:
    def __init__(self, db):
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='shotsearch')
        self.lock = Lock()
        self.job = {'state':'idle','done':0,'total':0,'message':'Ready'}
        self.repo = None
        self.db = db
        self.pool.submit(self.initialize).result()

    def initialize(self):
        self.repo = ScreenshotRepository(self.db)
        self.search = SearchService(self.repo)

    def call(self, fn):
        return self.pool.submit(fn).result()

    def close(self):
        if self.repo is not None:
            self.pool.submit(self.repo.close).result()
            self.repo = None
            self.pool.shutdown()

    def status(self):
        with self.lock:
            return dict(self.job)

    def progress(self, done, total, message):
        with self.lock:
            self.job.update(done=done,total=total,message=message)

    def start(self, action):
        with self.lock:
            if self.job['state']=='running':
                raise ValueError('A job is already running. Wait for it to finish.')
            self.job={'state':'running','done':0,'total':0,'message':'Starting…'}
        def work():
            try:
                result=action()
                with self.lock:
                    self.job.update(state='complete',result=result,message='Completed')
            except Exception as exc:
                with self.lock:
                    self.job.update(state='error',message=str(exc))
        self.pool.submit(work)


def create_app(db=None, prepare_on_start=True):
    app=Flask(__name__)
    app.config['MAX_CONTENT_LENGTH']=16*1024
    app.config['TRUSTED_HOSTS']=['127.0.0.1','localhost']
    workspace=Workspace(db or Path.home()/'.shotsearch'/'index.sqlite3')
    app.extensions['workspace']=workspace
    if prepare_on_start:
        workspace.start(lambda: {'prepared': workspace.search.embed(workspace.progress)}
                        if workspace.repo.ready() else {'prepared': 0})
    token=secrets.token_urlsafe(32)
    atexit.register(workspace.close)

    @app.before_request
    def local_only():
        if request.remote_addr not in ('127.0.0.1','::1',None):
            return jsonify(error='Local access only.'),403
        if request.method not in ('GET','HEAD','OPTIONS'):
            if request.headers.get('X-Shotsearch-Token')!=token:
                return jsonify(error='Reload this page before trying again.'),403
            origin=request.headers.get('Origin')
            if origin and urlsplit(origin).netloc!=request.host:
                return jsonify(error='Cross-origin request rejected.'),403

    @app.after_request
    def headers(response):
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Content-Security-Policy']="default-src 'self'; img-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        return response

    @app.errorhandler(ValueError)
    def bad_input(exc): return jsonify(error=str(exc)),400

    def available():
        if workspace.status()['state']=='running':
            raise ValueError('Processing screenshots. Please wait for the current job to finish.')

    @app.get('/')
    def home(): return render_template('index.html',token=token)

    @app.get('/api/job')
    def job(): return jsonify(workspace.status())

    @app.get('/api/status')
    def status():
        available()
        def read():
            counts={r['status']:r['count'] for r in workspace.repo.db.execute('SELECT status,COUNT(*) count FROM images GROUP BY status')}
            prepared=workspace.repo.db.execute("SELECT COUNT(*) FROM images i JOIN vectors v ON v.image_id=i.id WHERE i.status='ready' AND i.digest=v.digest AND v.model=?",(SearchService.embedding_key,)).fetchone()[0]
            return dict(counts=counts,prepared=prepared,model_loaded=workspace.search._model is not None,
                        tesseract=shutil.which('tesseract'),database=str(workspace.db))
        return jsonify(workspace.call(read))

    @app.get('/api/images')
    def images():
        available()
        page=max(1,int(request.args.get('page',1)))
        def read():
            rows=workspace.repo.db.execute('SELECT id,path,text,status,error FROM images ORDER BY id DESC LIMIT 30 OFFSET ?',((page-1)*30,)).fetchall()
            total=workspace.repo.db.execute('SELECT COUNT(*) FROM images').fetchone()[0]
            return {'items':[dict(r) for r in rows],'total':total,'page':page}
        return jsonify(workspace.call(read))

    @app.post('/api/search')
    def search():
        available()
        data=request.get_json() or {}
        query=data.get('query',''); mode=data.get('mode','hybrid')
        if not isinstance(query,str) or len(query)>1000 or not query.strip(): raise ValueError('Enter a query of 1–1000 characters.')
        if mode not in ('keyword','hybrid'): raise ValueError('Invalid search mode.')
        def run():
            if mode!='keyword':
                ready=workspace.repo.ready()
                n=workspace.search.prepared()
                if n!=len(ready): raise ValueError('Search is not ready yet. Open Manage collection and retry preparation.')
            start=perf_counter()
            try: items=workspace.search.search(query,mode)
            except Exception as exc: raise ValueError(str(exc)) from exc
            return {'items':items,'total':len(items),'seconds':round(perf_counter()-start,2)}
        return jsonify(workspace.call(run))

    @app.post('/api/folders')
    def index():
        data=request.get_json() or {}; directory=data.get('directory','')
        if not isinstance(directory,str) or not directory.strip(): raise ValueError('Enter a folder path.')
        if not Path(directory).expanduser().is_dir(): raise ValueError('Folder not found on this computer.')
        if not shutil.which('tesseract'): raise ValueError('Tesseract not found. Add its installation folder to PATH and restart the server.')
        force=data.get('force',False); language=data.get('language','eng')
        if not isinstance(force,bool) or not isinstance(language,str) or not language.strip(): raise ValueError('Invalid folder options.')
        def prepare_folder():
            result = IndexingService(workspace.repo, OCRService(language=language)).index(directory, force, workspace.progress)
            result['prepared'] = workspace.search.embed(workspace.progress)
            return result
        workspace.start(prepare_folder)
        return jsonify(started=True),202

    @app.post('/api/prepare')
    def embed():
        workspace.start(lambda:{'embedded':workspace.search.embed(workspace.progress)})
        return jsonify(started=True),202

    @app.get('/api/images/<int:image_id>')
    def image_info(image_id):
        available()
        def read():
            row=workspace.repo.db.execute('SELECT * FROM images WHERE id=?',(image_id,)).fetchone()
            if not row: raise ValueError('Image is no longer in your collection.')
            return dict(row)
        return jsonify(workspace.call(read))

    @app.get('/api/images/<int:image_id>/file')
    def image_file(image_id):
        available()
        def read():
            row=workspace.repo.db.execute('SELECT path FROM images WHERE id=?',(image_id,)).fetchone()
            if not row: raise ValueError('Image is no longer in your collection.')
            return Path(row['path'])
        path=workspace.call(read)
        if path.suffix.lower() not in IndexingService.extensions or not path.is_file():
            return jsonify(error='Original image is missing.'),404
        return send_file(path,conditional=False)

    @app.delete('/api/images/<int:image_id>')
    def remove(image_id):
        available()
        return jsonify(removed=workspace.call(lambda:workspace.repo.remove(image_id)))
    return app


def main():
    p=argparse.ArgumentParser(description='ShotSearch local website')
    p.add_argument('--db',default=str(Path.home()/'.shotsearch'/'index.sqlite3'))
    p.add_argument('--port',type=int,default=5000)
    args=p.parse_args()
    app=create_app(args.db)
    print(f'Open http://127.0.0.1:{args.port} in your browser. Ctrl+C stops the server.')
    try: app.run(host='127.0.0.1',port=args.port,debug=False,use_reloader=False,threaded=True)
    finally: app.extensions['workspace'].close()

if __name__=='__main__': main()
