import os, io, time, hashlib, base64, urllib.parse, random, string, hmac as _hmac
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests, numpy as np, cv2
from PIL import Image
from supabase import create_client
import mediapipe as mp

app = Flask(__name__)
CORS(app)

CK = os.environ.get('SMUG_CK', '68rkjJGRC2MKcDjBxj98gSJK85FMKG7v')
CS = os.environ.get('SMUG_CS', '9c3cH4rrkw58PZC7SzLM7sL7FgqPgNCbhbpF5dtvcJTZZ72FzPpW6gPZGwCrvxqf')
AT = os.environ.get('SMUG_AT', 'kt6n2JDdSz9rqhjcqNNGbDZZdJNHsmLj')
TS = os.environ.get('SMUG_TS', 'gT7t7Fg7C4gk22cr6XfxXbk4W4mKGDzZSTvXgZQ7qNSgf3fMF8mCF4T75Wv62mNg')
SB_URL = os.environ.get('SB_URL', 'https://svvtypqcwaxzbubuysmu.supabase.co')
SB_KEY = os.environ.get('SB_KEY', '')

sb = create_client(SB_URL, SB_KEY) if SB_KEY else None

# MediaPipe Face Mesh - retorna 468 pontos por rosto que usamos como descritor
mp_face_mesh = mp.solutions.face_mesh
face_mesh = mp_face_mesh.FaceMesh(static_image_mode=True, max_num_faces=5,
                                    refine_landmarks=False, min_detection_confidence=0.5)

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

def landmarks_to_descriptor(landmarks, img_shape):
    """Converte 468 landmarks 3D em um vetor descritor normalizado."""
    h, w = img_shape[:2]
    pts = np.array([[lm.x*w, lm.y*h, lm.z*w] for lm in landmarks.landmark])
    # Centraliza no centroid
    pts -= pts.mean(axis=0)
    # Normaliza pela escala (distância média ao centro)
    scale = np.linalg.norm(pts, axis=1).mean()
    if scale > 0:
        pts /= scale
    return pts.flatten().tolist()  # 468*3 = 1404 dimensões

def extract_descriptors_from_image(img_bytes):
    """Extrai descritores faciais de uma imagem (bytes)."""
    try:
        img = np.array(Image.open(io.BytesIO(img_bytes)).convert('RGB'))
        results = face_mesh.process(img)
        if not results.multi_face_landmarks:
            return []
        return [landmarks_to_descriptor(lms, img.shape) for lms in results.multi_face_landmarks]
    except Exception as e:
        print(f'Erro: {e}')
        return []

@app.route('/')
def health():
    return jsonify({'status': 'ok', 'service': 'Studio Pro Python Backend (MediaPipe)'})

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
            try:
                r = requests.get(thumb, timeout=15)
                descs = extract_descriptors_from_image(r.content)
                for i, desc in enumerate(descs):
                    row = {'evento_id': ev_id, 'album_key': key,
                           'image_key': f'{img_key}_{i}' if i else img_key,
                           'filename': filename, 'thumb_url': thumb, 'web_url': web_uri,
                           'descriptor': desc}
                    if sb:
                        sb.table('fotomatch_descritores').upsert(row, on_conflict='image_key').execute()
                if descs:
                    resultados.append(img_key)
            except Exception as e:
                print(f'Erro em {img_key}: {e}')

        start += len(imgs)
        if start > total:
            break

    return jsonify({'processadas': len(resultados), 'total': total})

@app.route('/descriptor', methods=['POST'])
def get_descriptor():
    """Aluno envia foto base64 → retorna descritor."""
    data = request.json
    img_b64 = data.get('image')
    if not img_b64:
        return jsonify({'erro': 'image obrigatorio'}), 400
    try:
        img_bytes = base64.b64decode(img_b64.split(',')[-1])
        descs = extract_descriptors_from_image(img_bytes)
        if descs:
            return jsonify({'descriptor': descs[0]})
        return jsonify({'erro': 'Nenhum rosto detectado'}), 400
    except Exception as e:
        return jsonify({'erro': str(e)}), 400

@app.route('/buscar', methods=['POST'])
def buscar():
    data       = request.json
    desc_aluno = np.array(data.get('descriptor', []))
    album_key  = data.get('album_key')
    threshold  = float(data.get('threshold', 0.6))

    if not album_key or not sb:
        return jsonify({'erro': 'album_key ou Supabase nao configurado'}), 400

    rows = sb.table('fotomatch_descritores').select('*').eq('album_key', album_key).execute().data
    if not rows:
        return jsonify({'erro': 'album nao processado ainda', 'fotos': []}), 404

    matched = []
    seen = set()
    for row in rows:
        desc_foto = np.array(row['descriptor'])
        # Cosine similarity
        cos = np.dot(desc_aluno, desc_foto) / (np.linalg.norm(desc_aluno) * np.linalg.norm(desc_foto) + 1e-9)
        dist = 1 - cos
        if dist < threshold:
            key_orig = row['image_key'].split('_')[0]
            if key_orig in seen:
                continue
            seen.add(key_orig)
            matched.append({'image_key': key_orig, 'filename': row['filename'],
                           'thumb': row['thumb_url'], 'original': row['web_url'],
                           'distancia': round(float(dist), 4)})

    matched.sort(key=lambda x: x['distancia'])
    return jsonify({'fotos': matched, 'total': len(matched)})

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
