import os
import time
import base64
import queue
import threading
import requests
from datetime import datetime
from flask import Flask, request, jsonify
from consulta import ejecutar_consulta_completa, inicializar_driver_global

app = Flask(__name__)

# ── Configuración ──────────────────────────────────────────
USUARIO_CV        = os.environ.get('CV_USUARIO', '').strip()
CONTRASENA_CV     = os.environ.get('CV_CONTRASENA', '').strip()
ULTRAMSG_INSTANCE = os.environ.get('ULTRAMSG_INSTANCE', '').strip()
ULTRAMSG_TOKEN    = os.environ.get('ULTRAMSG_TOKEN', '').strip()
GRUPO_AUTORIZADO  = '120363406557895449@g.us'
LIMITE_DIARIO     = 15

MIEMBROS = {
    '51982008561': 'Juan',
    '51935203969': 'Alf',
}

# ── Cola de consultas (1 a la vez) ─────────────────────────
cola = queue.Queue()
en_proceso = False
lock_proceso = threading.Lock()

# ── Conteo diario ──────────────────────────────────────────
conteo_diario = {}

def hoy():
    return datetime.now().strftime('%Y-%m-%d')

def conteo_hoy(numero):
    return conteo_diario.get(hoy(), {}).get(numero, 0)

def incrementar_conteo(numero):
    dia = hoy()
    if dia not in conteo_diario:
        conteo_diario[dia] = {}
    conteo_diario[dia][numero] = conteo_diario[dia].get(numero, 0) + 1

# ── UltraMsg ───────────────────────────────────────────────
def enviar_mensaje(to, mensaje):
    url = f'https://api.ultramsg.com/{ULTRAMSG_INSTANCE}/messages/chat'
    payload = {'token': ULTRAMSG_TOKEN, 'to': to, 'body': mensaje}
    try:
        r = requests.post(url, data=payload, timeout=15)
        print(f'✅ Mensaje enviado: {r.status_code}')
        return r.status_code == 200
    except Exception as e:
        print(f'❌ Error enviando mensaje: {e}')
        return False

def enviar_pdf(to, pdf_path, caption=''):
    url = f'https://api.ultramsg.com/{ULTRAMSG_INSTANCE}/messages/document'
    with open(pdf_path, 'rb') as f:
        b64 = base64.b64encode(f.read()).decode('utf-8')
    payload = {
        'token': ULTRAMSG_TOKEN,
        'to': to,
        'document': f'data:application/pdf;base64,{b64}',
        'filename': os.path.basename(pdf_path),
        'caption': caption,
    }
    try:
        r = requests.post(url, data=payload, timeout=60)
        print(f'✅ PDF enviado: {r.status_code}')
        return r.status_code == 200
    except Exception as e:
        print(f'❌ Error enviando PDF: {e}')
        return False

# ── Procesador de cola ─────────────────────────────────────
def procesar_cola():
    global en_proceso
    while True:
        try:
            item = cola.get(timeout=1)
        except queue.Empty:
            continue

        with lock_proceso:
            en_proceso = True

        grupo_id = item['grupo_id']
        numero   = item['numero']
        nombre   = item['nombre']
        placa    = item['placa']
        inicio   = time.time()

        try:
            pdf_path = ejecutar_consulta_completa(placa, USUARIO_CV, CONTRASENA_CV)
            elapsed  = int(time.time() - inicio)

            if pdf_path and os.path.exists(pdf_path):
                caption = f'📋 Reporte vehicular — *{placa}*\n👤 {nombre} | ⏱ {elapsed}s'
                enviar_pdf(grupo_id, pdf_path, caption)
                print(f'📊 Log: {nombre} | {placa} | PDF enviado | {elapsed}s')
                try:
                    os.remove(pdf_path)
                except Exception:
                    pass
            else:
                enviar_mensaje(grupo_id, f'⚠️ No se pudo generar reporte para *{placa}*.')
                print(f'📊 Log: {nombre} | {placa} | sin_pdf | {elapsed}s')
        except Exception as e:
            elapsed = int(time.time() - inicio)
            print(f'❌ Error procesando {placa}: {e}')
            enviar_mensaje(grupo_id, f'⚠️ Error al consultar *{placa}*.')
        finally:
            with lock_proceso:
                en_proceso = False
            cola.task_done()

# ── Webhook ────────────────────────────────────────────────
@app.route('/webhook', methods=['POST'])
def webhook():
    data     = request.json or {}
    grupo_id = data.get('from', '')
    numero   = data.get('author', '').replace('@c.us', '').replace('+', '')
    body     = (data.get('body') or '').strip().upper()
    tipo     = data.get('type', '')

    # DEBUG TEMPORAL
    print(f'📨 from=[{grupo_id}] author=[{numero}] type=[{tipo}] body=[{body}]')

    if grupo_id != GRUPO_AUTORIZADO:
        print(f'❌ Grupo no autorizado: [{grupo_id}] esperado: [{GRUPO_AUTORIZADO}]')
        return jsonify({'status': 'ignored'}), 200
    if tipo != 'chat':
        print(f'❌ Tipo ignorado: [{tipo}]')
        return jsonify({'status': 'ignored'}), 200
    if not body.startswith('CONSULTA'):
        print(f'❌ Body ignorado: [{body}]')
        return jsonify({'status': 'ignored'}), 200

    nombre = MIEMBROS.get(numero, numero)
    print(f'Mensaje de {numero}: {body}')

    partes = body.split()
    if len(partes) < 2:
        enviar_mensaje(grupo_id, '❌ Formato incorrecto. Usa: *CONSULTA ABC123*')
        return jsonify({'status': 'ok'}), 200

    placa = partes[1].strip().upper()
    if len(placa) < 5:
        enviar_mensaje(grupo_id, '❌ Placa inválida. Ejemplo: *CONSULTA ABC123*')
        return jsonify({'status': 'ok'}), 200

    if numero not in MIEMBROS:
        enviar_mensaje(grupo_id, '🚫 No tienes permiso para usar este bot.')
        return jsonify({'status': 'ok'}), 200

    if conteo_hoy(numero) >= LIMITE_DIARIO:
        enviar_mensaje(grupo_id, f'⚠️ {nombre}, alcanzaste el límite de {LIMITE_DIARIO} consultas diarias.')
        return jsonify({'status': 'ok'}), 200

    incrementar_conteo(numero)

    pos = cola.qsize() + (1 if en_proceso else 0)
    if pos == 0:
        enviar_mensaje(grupo_id, f'⏳ Consultando *{placa}*...\nEspera 2-3 minutos.')
    else:
        enviar_mensaje(grupo_id, f'📋 Placa *{placa}* añadida a la cola\n⏳ Posición #{pos + 1} — espera ~{(pos + 1) * 3} minutos')

    cola.put({
        'grupo_id': grupo_id,
        'numero':   numero,
        'nombre':   nombre,
        'placa':    placa,
    })

    return jsonify({'status': 'ok'}), 200

# ── Inicio ─────────────────────────────────────────────────
if __name__ == '__main__':
    print(f'🚀 Servidor iniciando en puerto 8080')
    print(f'📍 Grupo autorizado: {GRUPO_AUTORIZADO}')
    print(f'🌐 Iniciando en modo driver-por-consulta...')

    inicializar_driver_global()

    hilo = threading.Thread(target=procesar_cola, daemon=True)
    hilo.start()

    app.run(host='0.0.0.0', port=8080)
