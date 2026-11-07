import json
import tempfile
import hashlib
from pathlib import Path
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from rent_app import load_data, make_handler, search_rows, natural_key, verified_metrics

class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows,source,demo=load_data(demo=True)
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(cls.rows,source,demo))
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join()
    def get(self,path,host=None):
        c=HTTPConnection('127.0.0.1',self.server.server_port)
        c.request('GET',path,headers={'Host':host} if host else {})
        r=c.getresponse();b=r.read();status=r.status;c.close()
        return status,b
    def test_metrics_require_matching_predictions(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);csv=root/'rents_2more.csv';csv.write_text('example')
            (root/'history_manifest.json').write_text(json.dumps({'prediction_sha256':hashlib.sha256(csv.read_bytes()).hexdigest(),'iterations':1000}))
            (root/'history_check.json').write_text(json.dumps({'iterations':1000,'median_absolute_error':45.5}))
            self.assertEqual(verified_metrics(root,'rents_2more.csv')['median_absolute_error'],45.5)
            csv.write_text('different predictions')
            self.assertIsNone(verified_metrics(root,'rents_2more.csv'))

    def test_pagination_and_natural_sort(self):
        rows=[dict(self.rows[0],gnaf_id=str(i),address=f'UNIT {i}, EXAMPLE LANE') for i in range(45,0,-1)]
        rows=sorted(rows,key=lambda r:natural_key(r['address']))
        keys={r['gnaf_id']:r['address'].casefold() for r in rows}
        first=search_rows(rows,keys,{})
        second=search_rows(rows,keys,{'page':['2']})
        last=search_rows(rows,keys,{'page':['999']})
        self.assertEqual((first['total'],first['pages'],first['start'],first['end']),(45,3,1,20))
        self.assertEqual(first['items'][0]['gnaf_id'],'1')
        self.assertEqual(second['items'][0]['gnaf_id'],'21')
        self.assertEqual((last['page'],last['start'],last['end']),(3,41,45))
        all_ids=[r['gnaf_id'] for batch in [first,second,last] for r in batch['items']]
        self.assertEqual(len(set(all_ids)),45)
        self.assertEqual(search_rows(rows,keys,{'page':['bad']})['page'],1)
        self.assertEqual(search_rows(rows,keys,{'q':['nothing']})['start'],0)
    def test_report_link(self):
        meta=json.loads(self.get('/api/meta')[1])
        self.assertTrue(meta['report_available'])
        self.assertEqual(self.get('/report')[0],200)
    def test_search_filters_and_empty(self):
        status,b=self.get('/api/search?q=fictional&beds=0')
        r=json.loads(b);self.assertEqual(status,200);self.assertEqual(r['total'],1);self.assertEqual(r['items'][0]['bedrooms'],0)
        self.assertEqual(json.loads(self.get('/api/search?beds=3%2B')[1])['total'],1)
        self.assertEqual(json.loads(self.get('/api/search?q=nonexistent')[1])['total'],0)
    def test_property_predictions(self):
        status,b=self.get('/api/property?id=SYNTHETIC-1');r=json.loads(b)
        self.assertEqual(status,200);self.assertEqual(r['with_parking'],820);self.assertEqual(r['without_parking'],770)
        self.assertEqual(self.get('/api/property?id=missing')[0],404)
    def test_private_paths_and_host(self):
        self.assertEqual(self.get('/data/private/test.csv')[0],404)
        self.assertEqual(self.get('/../rent_app.py')[0],404)
        self.assertEqual(self.get('/api/meta','untrusted.example')[0],403)
    def test_assets_and_demo_label(self):
        for path in ['/','/app.js','/styles.css']:self.assertEqual(self.get(path)[0],200)
        r=json.loads(self.get('/api/meta')[1]);self.assertTrue(r['demo']);self.assertEqual(r['count'],4)

if __name__=='__main__':unittest.main()
