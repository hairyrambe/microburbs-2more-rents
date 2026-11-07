"""2more local rent explorer. Standard-library only; never uploads input data."""
import argparse
import hashlib
import csv
import json
import math
import threading
import re
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent

def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

def numeric(v):
    try:
        n=float(v)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):return None

def load_data(root=ROOT, demo=False):
    if demo:
        rows=[]
        for i,(suburb,beds,baths,yes,no) in enumerate([('Demo Harbour',1,1,820,770),('Demo Harbour',2,2,1100,1040),('Demo Gardens',0,1,590,560),('Demo Gardens',3,2,1450,1400)]):
            rows.append(dict(gnaf_id=f'SYNTHETIC-{i+1}',address=f'FICTIONAL FLAT {i+1}, 10 EXAMPLE LANE',suburb=suburb,bedrooms=beds,bathrooms=baths,floor_level=i+1,car_space=None,with_parking=yes,without_parking=no))
        return rows, 'Synthetic demonstration — no supplied records', True
    inputs=root/'data/private/rents-input-flats-city-of-sydney.csv'
    if not inputs.exists():inputs=root/'data/rents-input-flats-city-of-sydney.csv'
    if not inputs.exists():raise ValueError('Missing rents-input-flats-city-of-sydney.csv. Put the supplied file in data/ (or data/private/) next to this script.')
    candidates=[root/'rents_2more.csv',root/'outputs/improved/rents_2more.csv',root/'outputs/improved/rents_your-team.csv']
    predictions=next((p for p in candidates if p.exists()),None)
    if not predictions:raise ValueError('No improved predictions found. Keep rents_2more.csv in this folder or outputs/improved, or run the improved model first.')
    rents=read_csv(predictions)
    by_id={r['gnaf_id']:r for r in rents}
    if len(by_id)!=len(rents):raise ValueError('Duplicate IDs in prediction CSV')
    source=read_csv(inputs)
    if len({r['gnaf_id'] for r in source})!=len(source) or set(by_id)!={r['gnaf_id'] for r in source}:
        raise ValueError('Input and prediction IDs do not match exactly')
    rows=[]
    for r in source:
        p=by_id[r['gnaf_id']]
        yes,no=numeric(p['rent_with_car_space']),numeric(p['rent_without_car_space'])
        if yes is None or no is None or min(yes,no)<=0:raise ValueError('Invalid prediction in CSV')
        rows.append(dict(gnaf_id=r['gnaf_id'], address=r['address'], suburb=r['suburb'],
                         bedrooms=numeric(r['bedrooms']),bathrooms=numeric(r['bathrooms']),
                         floor_level=numeric(r.get('floor_level')),car_space=numeric(r.get('car_space')),
                         with_parking=yes,without_parking=no))
    return rows, str(predictions.relative_to(root)), False

def search_rows(ordered, search_keys, query, page_size=20):
    tokens=query.get('q',[''])[0].casefold().split()
    suburb=query.get('suburb',[''])[0]
    beds=query.get('beds',[''])[0]
    try:
        page=max(1,int(query.get('page',['1'])[0]))
    except ValueError:
        page=1
    matches=[]
    for r in ordered:
        if suburb and r['suburb']!=suburb:continue
        n=r['bedrooms']
        if beds:
            if n is None:continue
            if beds=='3+':
                if n<3:continue
            elif n!=numeric(beds):continue
        if all(t in search_keys[r['gnaf_id']] for t in tokens):matches.append(r)
    pages=max(1,math.ceil(len(matches)/page_size))
    page=min(page,pages)
    start=(page-1)*page_size
    fields=('gnaf_id','address','suburb','bedrooms','bathrooms')
    return dict(total=len(matches),page=page,pages=pages,
                start=start+1 if matches else 0,end=min(start+page_size,len(matches)),
                items=[{k:r[k] for k in fields} for r in matches[start:start+page_size]])

def natural_key(text):
    return tuple((0,int(piece)) if piece.isdigit() else (1,piece.casefold())
                 for piece in re.split(r'(\d+)',text))

def verified_metrics(root, source, demo=False):
    try:
        manifest=json.loads((root/'history_manifest.json').read_text())
        check=json.loads((root/'history_check.json').read_text())
        predictions=root/('rents_2more.csv' if demo else source)
        digest=hashlib.sha256(predictions.read_bytes()).hexdigest()
        if digest != manifest['prediction_sha256'] or check['iterations'] != manifest['iterations']:
            return None
        return check
    except (OSError,ValueError,KeyError):
        return None

def make_handler(rows, source, demo):
    metrics=verified_metrics(ROOT,source,demo)
    index={r['gnaf_id']:r for r in rows}
    ordered=sorted(rows,key=lambda r:(r['suburb'],natural_key(r['address'])))
    search_keys={r['gnaf_id']:f"{r['address']} {r['suburb']} {r['gnaf_id']}".casefold() for r in rows}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,payload,status=200,content_type='application/json; charset=utf-8'):
            data=json.dumps(payload,allow_nan=False).encode() if content_type.startswith('application/json') else payload
            self.send_response(status)
            self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            style_policy = "'self' 'unsafe-inline'" if urlparse(self.path).path == '/report' else "'self'"
            self.send_header('Content-Security-Policy',f"default-src 'self'; script-src 'self'; style-src {style_policy}; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
            self.end_headers();self.wfile.write(data)
        def do_GET(self):
            if self.headers.get('Host','').split(':')[0] not in ('127.0.0.1','localhost'):
                return self.send({'error':'Local access only'},403)
            url=urlparse(self.path);q=parse_qs(url.query)
            if url.path=='/api/meta':
                return self.send(dict(count=len(rows),suburbs=sorted({r['suburb'] for r in rows}),source=source,demo=demo,metrics=metrics,report_available=(ROOT/'report.html').is_file()))
            if url.path=='/api/search':
                return self.send(search_rows(ordered,search_keys,q))
            if url.path=='/api/property':
                r=index.get(q.get('id',[''])[0])
                return self.send(r if r else {'error':'Flat not found'},200 if r else 404)
            assets={'/':('index.html','text/html; charset=utf-8'),'/styles.css':('styles.css','text/css; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8')}
            if url.path=='/report' and (ROOT/'report.html').is_file():
                return self.send((ROOT/'report.html').read_bytes(),content_type='text/html; charset=utf-8')
            if url.path in assets:
                name,kind=assets[url.path]
                return self.send((ROOT/'app_ui'/name).read_bytes(),content_type=kind)
            self.send({'error':'Not found'},404)
    return Handler

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port',type=int,default=8765)
    p.add_argument('--demo',action='store_true',help='Use fictional examples for a public demo recording')
    p.add_argument('--no-browser',action='store_true')
    args=p.parse_args()
    try:
        rows,source,demo=load_data(demo=args.demo)
        server=ThreadingHTTPServer(('127.0.0.1',args.port),make_handler(rows,source,demo))
    except (ValueError,OSError,KeyError) as e:
        print(f'Could not start: {e}',flush=True)
        raise SystemExit(1)
    url=f'http://127.0.0.1:{args.port}'
    print(f'2more is ready: {url}\nLoaded {len(rows):,} flats. Source: {source}\nKeep this window open. Press Ctrl+C to stop.',flush=True)
    if not args.no_browser:threading.Timer(.6,lambda:webbrowser.open(url)).start()
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=='__main__':main()
