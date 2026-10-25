import re
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from shotsearch.web import create_app

class WebTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
  self.app=create_app(self.root/'db', prepare_on_start=False); self.client=self.app.test_client(); self.w=self.app.extensions['workspace']
  html=self.client.get('/').get_data(as_text=True)
  self.headers={'X-Shotsearch-Token':re.search('name="csrf-token" content="([^"]+)',html)[1]}
  self.image=self.root/'test.png'; self.image.write_bytes(b'example image')
  self.w.call(lambda:self.w.repo.save(self.image,'hash','navigation traffic internship','ready'))
 def tearDown(self): self.w.close(); self.temp.cleanup()
 def test_search_view_delete_preserves_original(self):
  r=self.client.post('/api/search',json={'query':'traffic','mode':'keyword'},headers=self.headers)
  self.assertEqual(r.status_code,200); image_id=r.json['items'][0]['id']
  self.assertEqual(self.client.get(f'/api/images/{image_id}').json['text'],'navigation traffic internship')
  with self.client.get(f'/api/images/{image_id}/file') as response:
   self.assertEqual(response.data,b'example image')
  self.assertEqual(self.client.delete(f'/api/images/{image_id}',headers=self.headers).json['removed'],1)
  self.assertTrue(self.image.exists())
 def test_csrf_and_host(self):
  self.assertEqual(self.client.post('/api/prepare').status_code,403)
  self.assertEqual(self.client.post('/api/prepare',headers={**self.headers,'Origin':'https://evil.example'}).status_code,403)
  self.assertEqual(self.client.get('/',headers={'Host':'evil.example'}).status_code,400)
 def test_invalid_and_stale(self):
  for data in ({'query':''},{'query':'x','mode':'wrong'},{'query':'x','mode':'semantic'}):
   self.assertEqual(self.client.post('/api/search',json=data,headers=self.headers).status_code,400)
  self.assertEqual(self.client.get('/api/images/999/file').status_code,400)
 def test_job_failure_and_busy(self):
  from threading import Event
  release=Event()
  self.w.start(lambda:release.wait(3))
  self.assertEqual(self.client.get('/api/job').json['state'],'running')
  self.assertEqual(self.client.post('/api/prepare',headers=self.headers).status_code,400)
  release.set(); self.w.call(lambda:None)
  self.assertEqual(self.client.get('/api/job').json['state'],'complete')
  def fail(): raise RuntimeError('test failure')
  self.w.start(fail); self.w.call(lambda:None)
  self.assertEqual(self.client.get('/api/job').json['message'],'test failure')
 def test_index_preflight(self):
  with patch('shotsearch.web.shutil.which',return_value=None):
   r=self.client.post('/api/folders',json={'directory':str(self.root)},headers=self.headers)
   self.assertEqual(r.status_code,400); self.assertIn('Tesseract',r.json['error'])
 def test_status_existing_db(self):
  self.assertEqual(self.client.get('/api/status').json['counts']['ready'],1)
  self.assertEqual(self.client.get('/api/images').json['total'],1)
 def test_folder_automatically_prepares(self):
  events=[]
  with patch('shotsearch.web.shutil.which',return_value='/fake/tesseract'), patch('shotsearch.web.IndexingService.index',side_effect=lambda *a:events.append('read') or {'indexed':1}), patch('shotsearch.web.SearchService.embed',side_effect=lambda *a:events.append('prepare') or 1):
   response=self.client.post('/api/folders',json={'directory':str(self.root)},headers=self.headers)
   self.assertEqual(response.status_code,202)
   self.w.call(lambda:None)
  self.assertEqual(events,['read','prepare'])
  self.assertEqual(self.w.status()['state'],'complete')
 def test_only_two_modes_and_default_combined(self):
  with patch.object(self.w.search,'prepared',return_value=1), patch.object(self.w.search,'search',return_value=[]) as search:
   self.assertEqual(self.client.post('/api/search',json={'query':'traffic'},headers=self.headers).status_code,200)
   self.assertEqual(search.call_args.args[1],'hybrid')
  self.assertEqual(self.client.post('/api/search',json={'query':'traffic','mode':'semantic'},headers=self.headers).status_code,400)
 def test_startup_prepares_existing_collection(self):
  with patch('shotsearch.web.SearchService.embed',return_value=1) as embed:
   app=create_app(self.root/'db')
   w=app.extensions['workspace']; w.call(lambda:None)
   self.assertEqual(embed.call_count,1); w.close()

 def test_search_returns_all_results_and_total(self):
  results=[{'id':i,'path':f'{i}.png'} for i in range(250)]
  with patch.object(self.w.search,'search',return_value=results) as search:
   response=self.client.post('/api/search',json={'query':'traffic','mode':'keyword','limit':12},headers=self.headers)
   self.assertEqual(response.status_code,200)
   self.assertEqual(response.json['total'],250)
   self.assertEqual(len(response.json['items']),250)
   self.assertEqual(search.call_args.args,('traffic','keyword'))
