import os, io, time, hashlib, base64, urllib.parse, random, string, hmac as _hmac
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests, face_recognition, numpy as np
from supabase import create_client

app = Flask(__name__)
CORS(app)

CK = os.environ.get('SMUG_CK', '68rkjJGRC2MKcDjBxj98gSJK85FMKG7v')
CS = os.environ.get('SMUG_CS', '9c3cH4rrkw58PZC7SzLM7sL7FgqPgNCbhbpF5dtvcJTZZ72FzPpW6gPZGwCrvxqf')
AT = os.environ.get('SMUG_AT', 'kt6n2JDdSz9rqhjcqNNGbDZZdJNHsmLj')
TS = os.environ.get('SMUG_TS', 'gT7t7Fg7C4gk22cr6XfxXbk4W4mKGDzZSTvXgZQ7qNSgf3fMF8mCF4T75Wv62mNg')
SB_URL = os.environ.get('SB_URL', 'https://svvtypqcwaxzbubuysmu.supabase.co')
SB_KEY = os.environ.get('SB_KEY', '')

sb = create_client(SB_URL, SB_KEY) if SB_KEY else None

def pct(s):
    return urllib.parse.quote(str(s), safe='')

def oauth_header(method, url, params={}):
    ts    = str(int(time.time()))
    nonce = ''.join(random.choices(string.ascii_lowercase + string.digits, k=32))
    op = {
        'oauth_consumer_key':     CK,
        'oauth_nonce':            nonce,
        'oauth_signature_method': 'HMAC-SHA1',
        'oauth_timestamp':        ts,
        'oauth_token':            AT,
        'oauth_version':          '1.0',
    }
    all_params = {**params, **op}
    param_str = '&'.join(f'{pct(k)}={pct(v)}' for k, v in sorted(all_params.items()))
    base = f'{method.upper()}&{pct(url)}&{pct(param_str)}'
    key  = f'{pct(CS)}&{pct(TS)}'.encode()
    sig  = base64.b64encode(_hmac.new(key, base.encode(), hashlib.sha1).digest()).decode()
    op['oauth_signature'] = sig
    return 'OAuth ' + ', '.join(f'{pct(k)}="{pct(v)}"' for k, v in sorted(op.items()))

def smug_get(path, params={}):
    url  = f'https://api.smugmug.com{path}'
    qs   = '&'.join(f'{k}={v}' for k, v in params.items())
    full = f'{url}?{qs}' if qs else url
    h    = oauth_header('GET', url, params)
    r    = requests.get(full, headers={'Accept': 'application/json', 'Authorization': h}, timeout=30)
    r.raise_for_status()
    return r.json()

def get_face_descriptor_from_url(img_url):
    try:
        r = requests.get(img_url, timeout=15)
        img = face_recognition.load_image_file(io.BytesIO(r.content))
        encs = face_recognition.face_encodings(img, num_jitters=1, model='small')
        if encs:
            return encs[0].tolist()
    except Exception as e:
        print(f'Sem rosto em {img_url}: {e}')
    return None

@app.route('/')
def health():
    return jsonify({'status': 'ok', 'service': 'Studio Pro Python Backend'})

@app.route('/processar-album', methods=['POST'])
def processar_album():
    data  = request.json
    key   = data.get('album_key')
    ev_id = data.get('evento_id')
    if not key:
        return jsonify({'erro': 'album_key obrigatorio'}), 400

    resultados = []
    start = 1
    total = 0

    while True:
        d    = smug_get(f'/api/v2/album/{key}!images', {'count': '100', 'start': str(start), '_verbosity': '1'})
        imgs = d.get('Response', {}).get('AlbumImage', [])
        if not imgs:
            break
        if not total:
            total = d.get('Response', {}).get('Pages', {}).get('Total', len(imgs))

        for img in imgs:
            img_key  = img.get('ImageKey')
            thumb    = img.get('ThumbnailUrl', '')
            web_uri  = img.get('WebUri', '')
            filename = img.get('FileName', '')
            desc = get_face_descriptor_from_url(thumb)
            if desc:
                row = {'evento_id': ev_id, 'album_key': key, 'image_key': img_key,
                       'filename': filename, 'thumb_url': thumb, 'web_url': web_uri, 'descriptor': desc}
                if sb:
                    sb.table('fotomatch_descritores').upsert(row, on_conflict='image_key').execute()
                resultados.append(img_key)

        start += len(imgs)
        if start > total:
            break

    return jsonify({'processadas': len(resultados), 'total': total})

@app.route('/buscar', methods=['POST'])
def buscar():
    data       = request.json
    desc_aluno = np.array(data.get('descriptor', []))
    album_key  = data.get('album_key')
    threshold  = float(data.get('threshold', 0.52))

    if desc_aluno.shape != (128,):
        return jsonify({'erro': 'descriptor invalido'}), 400
    if not album_key or not sb:
        return jsonify({'erro': 'album_key ou Supabase nao configurado'}), 400

    rows = sb.table('fotomatch_descritores').select('*').eq('album_key', album_key).execute().data
    if not rows:
        return jsonify({'erro': 'album nao processado ainda', 'fotos': []}), 404

    matched = []
    for row in rows:
        desc_foto = np.array(row['descriptor'])
        dist = float(np.linalg.norm(desc_aluno - desc_foto))
        if dist < threshold:
            matched.append({'image_key': row['image_key'], 'filename': row['filename'],
                           'thumb': row['thumb_url'], 'original': row['web_url'], 'distancia': round(dist, 4)})

    matched.sort(key=lambda x: x['distancia'])
    return jsonify({'fotos': matched, 'total': len(matched)})

@app.route('/descriptor', methods=['POST'])
def get_descriptor():
    data = request.json
    img_b64 = data.get('image')
    if not img_b64:
        return jsonify({'erro': 'image obrigatorio'}), 400
    try:
        img_bytes = base64.b64decode(img_b64.split(',')[-1])
        img = face_recognition.load_image_file(io.BytesIO(img_bytes))
        encs = face_recognition.face_encodings(img, num_jitters=1, model='small')
        if encs:
            return jsonify({'descriptor': encs[0].tolist()})
        return jsonify({'erro': 'Nenhum rosto detectado'}), 400
    except Exception as e:
        return jsonify({'erro': str(e)}), 400

@app.route('/status-album', methods=['GET'])
def status_album():
    key = request.args.get('key')
    if not key or not sb:
        return jsonify({'processadas': 0})
    count = sb.table('fotomatch_descritores').select('image_key', count='exact').eq('album_key', key).execute()
    return jsonify({'processadas': count.count or 0})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
