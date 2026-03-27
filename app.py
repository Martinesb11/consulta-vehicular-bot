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

# ⚠️ ACTUALIZA CON TUS NÚMEROS (sin + ni espacios)
MIEMBROS = {
    '51982008561': 'Juan',
    '51935203969': 'Admin',
    # '51999999999': 'Nombre',  ← agrega más aquí
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

def enviar_pdf(destino, pdf_path, placa, autor_numero):
    try:
        if not os.path.exists(pdf_path):
            print(f'ERROR: Archivo no encontrado: {pdf_path}')
            return False
        tamaño = os.path.getsize(pdf_path)
        print(f'Enviando PDF: {pdf_path} ({tamaño} bytes)')
        with open(pdf_path, 'rb') as f:
            pdf_b64 = base64.b64encode(f.read()).decode('utf-8')
        nombre_autor = MIEMBROS.get(autor_numero, autor_numero)
        ahora = datetime.now().strftime('%d/%m/%Y %I:%M %p')
        r = requests.post(
            f'https://api.ultramsg.com/{ULTRAMSG_INSTANCE}/messages/document',
            data={
                'token':    ULTRAMSG_TOKEN,
                'to':       destino,
                'document': f'data:application/pdf;base64,{pdf_b64}',
                'filename': f'Reporte_{placa}.pdf',
                'caption':  f'📄 Reporte vehicular - Placa {placa}\n🙋 Solicitado por: {nombre_autor}\n📅 {ahora}'
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
    try:
        pdf_path = ejecutar_consulta_completa(placa, USUARIO_CV, CONTRASENA_CV)
        segundos = int(time.time() - inicio)
        if pdf_path and os.path.exists(pdf_path):
            print(f'PDF generado en: {pdf_path}')
            time.sleep(2)
            if enviar_pdf(destino, pdf_path, placa, autor):
                print(f'✅ PDF enviado exitosamente')
                registrar_log(autor, placa, 'exitoso', segundos)
            else:
                enviar_mensaje(destino, f'❌ Error enviando el PDF para *{placa}*')
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
                posicion = cola.qsize() + 1
                if posicion > 1:
                    tiempo_est = posicion * 5
                    enviar_mensaje(GRUPO_AUTORIZADO,
                        f'📋 Placa *{placa}* añadida a la cola\n'
                        f'⏳ Posición #{posicion} — espera ~{tiempo_est} minutos'
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
        'status': 'ok',
        'grupo': GRUPO_AUTORIZADO,
        'cola_pendientes': cola.qsize()
    }), 200

# ── Inicio ─────────────────────────────────────────────────
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print(f'🚀 Servidor iniciando en puerto {port}')
    print(f'📍 Grupo autorizado: {GRUPO_AUTORIZADO}')
    app.run(host='0.0.0.0', port=port, debug=False)
