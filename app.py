import os
import time
import base64
import queue
import threading
import requests
from datetime import datetime
from flask import Flask, request, jsonify
from consulta import ejecutar_consulta_completa

app = Flask(__name__)

# ── Configuración ──────────────────────────────────────────
USUARIO_CV        = os.environ.get('CV_USUARIO', '')
CONTRASENA_CV     = os.environ.get('CV_CONTRASENA', '')
ULTRAMSG_INSTANCE = os.environ.get('ULTRAMSG_INSTANCE', '')
ULTRAMSG_TOKEN    = os.environ.get('ULTRAMSG_TOKEN', '')
GRUPO_AUTORIZADO  = '120363406557895449@g.us'
LIMITE_DIARIO     = 15

# ⚠️ ACTUALIZA CON TUS NÚMEROS
MIEMBROS = {
    '51982008561': 'Juan',
    '51935203969': 'Alf',
    # '51999999999': 'Nombre',
}

# ── Cola de consultas (1 a la vez) ─────────────────────────
cola = queue.Queue()

def worker():
    while True:
        placa, destino, autor = cola.get()
        try:
            procesar_consulta(placa, destino, autor)
        except Exception as e:
            print(f'❌ Error en worker: {e}')
        finally:
            cola.task_done()

hilo_worker = threading.Thread(target=worker, daemon=True)
hilo_worker.start()

# ── Límite diario por usuario ──────────────────────────────
# { 'numero': {'fecha': 'YYYY-MM-DD', 'count': N} }
contadores = {}
lock_contadores = threading.Lock()

def verificar_limite(numero):
    """Retorna True si puede consultar, False si alcanzó el límite"""
    hoy = datetime.now().strftime('%Y-%m-%d')
    with lock_contadores:
        datos = contadores.get(numero, {'fecha': hoy, 'count': 0})
        # Resetear si es un nuevo día
        if datos['fecha'] != hoy:
            datos = {'fecha': hoy, 'count': 0}
        if datos['count'] >= LIMITE_DIARIO:
            return False
        datos['count'] += 1
        contadores[numero] = datos
        return True

def consultas_restantes(numero):
    hoy = datetime.now().strftime('%Y-%m-%d')
    with lock_contadores:
        datos = contadores.get(numero, {'fecha': hoy, 'count': 0})
        if datos['fecha'] != hoy:
            return LIMITE_DIARIO
        return max(0, LIMITE_DIARIO - datos['count'])

# ── Anti-duplicados (caché 24h) ────────────────────────────
# { 'PLACA': {'timestamp': float, 'pdf_b64': str, 'fecha': str} }
cache_pdfs = {}
lock_cache = threading.Lock()
CACHE_HORAS = 24

def obtener_cache(placa):
    """Retorna pdf_b64 si está en caché y no expiró, sino None"""
    with lock_cache:
        dato = cache_pdfs.get(placa)
        if not dato:
            return None
        horas_pasadas = (time.time() - dato['timestamp']) / 3600
        if horas_pasadas > CACHE_HORAS:
            del cache_pdfs[placa]
            return None
        return dato

def guardar_cache(placa, pdf_b64):
    with lock_cache:
        cache_pdfs[placa] = {
            'timestamp': time.time(),
            'pdf_b64':   pdf_b64,
            'fecha':     datetime.now().strftime('%d/%m/%Y %I:%M %p')
        }
        print(f'💾 Caché guardado para {placa}')

# ── Log de uso ─────────────────────────────────────────────
def registrar_log(numero, placa, resultado, segundos):
    nombre = MIEMBROS.get(numero, numero)
    ahora  = datetime.now()
    linea  = f"{ahora.strftime('%Y-%m-%d')},{ahora.strftime('%H:%M:%S')},{numero},{nombre},{placa},{resultado},{segundos}\n"
    try:
        with open('log_consultas.csv', 'a') as f:
            f.write(linea)
        print(f'📊 Log: {nombre} | {placa} | {resultado} | {segundos}s')
    except Exception as e:
        print(f'Error en log: {e}')

# ── Envío de mensajes ──────────────────────────────────────
def enviar_mensaje(destino, texto):
    try:
        r = requests.post(
            f'https://api.ultramsg.com/{ULTRAMSG_INSTANCE}/messages/chat',
            data={'token': ULTRAMSG_TOKEN, 'to': destino, 'body': texto},
            timeout=30
        )
        print(f'✅ Mensaje enviado: {r.status_code}')
    except Exception as e:
        print(f'❌ Error enviando mensaje: {e}')

def enviar_pdf_b64(destino, pdf_b64, placa, autor_numero, desde_cache=False):
    try:
        nombre_autor = MIEMBROS.get(autor_numero, autor_numero)
        ahora        = datetime.now().strftime('%d/%m/%Y %I:%M %p')
        cache_tag    = '\n⚡ _Resultado en caché_' if desde_cache else ''
        r = requests.post(
            f'https://api.ultramsg.com/{ULTRAMSG_INSTANCE}/messages/document',
            data={
                'token':    ULTRAMSG_TOKEN,
                'to':       destino,
                'document': f'data:application/pdf;base64,{pdf_b64}',
                'filename': f'Reporte_{placa}.pdf',
                'caption':  f'📄 Reporte vehicular - Placa {placa}\n🙋 Solicitado por: {nombre_autor}\n📅 {ahora}{cache_tag}'
            },
            timeout=120
        )
        print(f'Respuesta UltraMsg: {r.status_code} - {r.text}')
        return r.status_code in [200, 201]
    except Exception as e:
        print(f'❌ ERROR enviando PDF: {e}')
        import traceback
        traceback.print_exc()
        return False

# ── Procesar consulta ──────────────────────────────────────
def procesar_consulta(placa, destino, autor):
    inicio = time.time()

    # Verificar caché primero
    cached = obtener_cache(placa)
    if cached:
        print(f'⚡ Placa {placa} encontrada en caché')
        if enviar_pdf_b64(destino, cached['pdf_b64'], placa, autor, desde_cache=True):
            registrar_log(autor, placa, 'cache_hit', 0)
        else:
            enviar_mensaje(destino, f'❌ Error enviando PDF para *{placa}*')
        return

    # Consulta completa
    try:
        pdf_path = ejecutar_consulta_completa(placa, USUARIO_CV, CONTRASENA_CV)
        segundos = int(time.time() - inicio)
        if pdf_path and os.path.exists(pdf_path):
            print(f'PDF generado en: {pdf_path}')
            time.sleep(2)
            with open(pdf_path, 'rb') as f:
                pdf_b64 = base64.b64encode(f.read()).decode('utf-8')
            # Guardar en caché
            guardar_cache(placa, pdf_b64)
            # Enviar
            if enviar_pdf_b64(destino, pdf_b64, placa, autor):
                print(f'✅ PDF enviado exitosamente')
                registrar_log(autor, placa, 'exitoso', segundos)
            else:
                enviar_mensaje(destino, f'❌ Error enviando PDF para *{placa}*')
                registrar_log(autor, placa, 'error_envio', segundos)
            try:
                os.remove(pdf_path)
            except:
                pass
        else:
            enviar_mensaje(destino, f'⚠️ No se pudo generar reporte para *{placa}*.')
            registrar_log(autor, placa, 'sin_pdf', segundos)
    except Exception as e:
        segundos = int(time.time() - inicio)
        print(f'❌ Error en procesar_consulta: {e}')
        import traceback
        traceback.print_exc()
        enviar_mensaje(destino, f'❌ Error al consultar *{placa}*.')
        registrar_log(autor, placa, 'excepcion', segundos)

# ── Webhook ────────────────────────────────────────────────
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data     = request.json or {}
        msg_data = data.get('data', {})

        # Solo del grupo autorizado
        if msg_data.get('from') != GRUPO_AUTORIZADO:
            print(f'Ignorado (no autorizado): {msg_data.get("from")}')
            return jsonify({'status': 'ignorado'}), 200

        # Ignorar mensajes propios
        if msg_data.get('fromMe'):
            return jsonify({'status': 'ignorado'}), 200

        body  = (msg_data.get('body') or '').strip().upper()
        autor = (msg_data.get('author') or msg_data.get('from', '')).replace('@c.us', '').replace('+', '').strip()
        print(f'Mensaje de {autor}: {body}')

        if body.startswith('CONSULTA '):
            placa = body.replace('CONSULTA ', '').strip()
            if 6 <= len(placa) <= 8:
                # Verificar límite diario
                if not verificar_limite(autor):
                    restantes = consultas_restantes(autor)
                    nombre = MIEMBROS.get(autor, autor)
                    enviar_mensaje(GRUPO_AUTORIZADO,
                        f'🚫 *{nombre}* alcanzaste el límite de {LIMITE_DIARIO} consultas por hoy.\n'
                        f'🔄 Tu contador se resetea a medianoche.'
                    )
                    return jsonify({'status': 'limite_alcanzado'}), 200

                # Agregar a cola
                posicion = cola.qsize() + 1
                if posicion > 1:
                    tiempo_est = posicion * 5
                    enviar_mensaje(GRUPO_AUTORIZADO,
                        f'📋 Placa *{placa}* añadida a la cola\n'
                        f'⏳ Posición #{posicion} — espera ~{tiempo_est} minutos'
                    )
                else:
                    # Verificar caché antes de avisar tiempo de espera
                    cached = obtener_cache(placa)
                    if cached:
                        enviar_mensaje(GRUPO_AUTORIZADO,
                            f'⚡ Placa *{placa}* encontrada en caché, enviando ahora...'
                        )
                    else:
                        enviar_mensaje(GRUPO_AUTORIZADO,
                            f'⏳ Consultando *{placa}*...\nEspera 2-3 minutos.'
                        )
                cola.put((placa, GRUPO_AUTORIZADO, autor))
            else:
                enviar_mensaje(GRUPO_AUTORIZADO, '⚠️ Formato: *CONSULTA ABC123*')

        return jsonify({'status': 'ok'}), 200

    except Exception as e:
        print(f'❌ Error en webhook: {e}')
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error'}), 500

# ── Health check ───────────────────────────────────────────
@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status':          'ok',
        'grupo':           GRUPO_AUTORIZADO,
        'cola_pendientes': cola.qsize(),
        'cache_placas':    list(cache_pdfs.keys())
    }), 200

# ── Inicio ─────────────────────────────────────────────────
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print(f'🚀 Servidor iniciando en puerto {port}')
    print(f'📍 Grupo autorizado: {GRUPO_AUTORIZADO}')
    app.run(host='0.0.0.0', port=port, debug=False)
