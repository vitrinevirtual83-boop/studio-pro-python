# Studio Pro — Backend Python

Servidor Flask com reconhecimento facial para o Studio Pro.

## Deploy no Render.com (GRÁTIS)

### Passo 1 — GitHub
1. Crie conta em https://github.com
2. Crie repositório público: "studio-pro-python"  
3. Faça upload dos 3 arquivos: app.py, requirements.txt, README.md

### Passo 2 — Render
1. Crie conta em https://render.com (pode usar o GitHub)
2. New + → Web Service → conecte o repositório
3. Configure:
   - Name: studio-pro-python
   - Runtime: Python 3
   - Build Command: pip install -r requirements.txt
   - Start Command: gunicorn app:app
   - Plan: Free

### Passo 3 — Variáveis de ambiente no Render
Em Environment → Add Environment Variable:
- SB_KEY = [sua anon key do Supabase]
- SB_URL = https://svvtypqcwaxzbubuysmu.supabase.co

### Passo 4
Após deploy copie a URL e me passe para integrar no Studio Pro.

## Endpoints
- GET  /                     — health check
- POST /processar-album      — processa fotos (fotógrafo)
- POST /buscar               — busca por rosto (aluno)
- GET  /status-album?key=    — status do processamento
