import os
import time
import threading
import requests
from flask import Flask, request, jsonify
from consulta import ejecutar_consulta_completa

app = Flask(__name__)

USUARIO_CV       = os.environ.get('CV_USUARIO', '')
CONTRASENA_CV    = os.environ.get('CV_CONTRASENA', '')
ULTRAMSG_INSTANCE = os.environ.get('ULTRAMSG_INSTANCE', '')
ULTRAMSG_TOKEN   = os.environ.get('ULTRAMSG_TOKEN', '')
GRUPO_AUTORIZADO = '120363406557895449@g.us'

def enviar_mensaje(destino, texto):
    try:
        requests.post(
            f'https://api.ultramsg.com/{ULTRAMSG_INSTANCE}/messages/chat',
            data={'token': ULTRAMSG_TOKEN, 'to': destino, 'body': texto},
            timeout=30
        )
        print(f'✅ Mensaje enviado a {destino}')
    except Exception as e:
        print(f'❌ Error enviando mensaje: {e}')

def enviar_pdf(destino, pdf_path, placa):
    try:
        # Verificar que el archivo existe
        if not os.path.exists(pdf_path):
            print(f'ERROR: Archivo no encontrado: {pdf_path}')
            return False
        
        # Obtener tamaño para debugging
        tamaño = os.path.getsize(pdf_path)
        print(f'Enviando PDF: {pdf_path} ({tamaño} bytes)')
        
        with open(pdf_path, 'rb') as f:
            files = {'document': (os.path.basename(pdf_path), f, 'application/pdf')}
            data  = {
                'token': ULTRAMSG_TOKEN, 
                'to': destino, 
                'caption': f'📄 Reporte vehicular - Placa {placa}'
            }
            r = requests.post(
                f'https://api.ultramsg.com/{ULTRAMSG_INSTANCE}/messages/document',
                data=data, 
                files=files, 
                timeout=120
            )
            print(f'Respuesta UltraMsg: {r.status_code} - {r.text}')
            return r.status_code in [200, 201]
    except Exception as e:
        print(f'❌ ERROR enviando PDF: {e}')
        import traceback
        traceback.print_exc()
        return False

def procesar_consulta(placa, destino):
    enviar_mensaje(destino, f'⏳ Consultando *{placa}*...\nEspera 2-3 minutos.')
    try:
        pdf_path = ejecutar_consulta_completa(placa, USUARIO_CV, CONTRASENA_CV)
        if pdf_path and os.path.exists(pdf_path):
            print(f'PDF generado en: {pdf_path}')
            # Esperar un poco antes de enviar
            time.sleep(2)
            # Enviar PDF
            if enviar_pdf(destino, pdf_path, placa):
                print(f'✅ PDF enviado exitosamente')
            else:
                enviar_mensaje(destino, f'❌ Error enviando el PDF para *{placa}*')
            # Limpiar
            try:
                os.remove(pdf_path)
            except:
                pass
        else:
            enviar_mensaje(destino, f'⚠️ No se pudo generar reporte para *{placa}*.')
    except Exception as e:
        print(f'❌ Error en procesar_consulta: {e}')
        import traceback
        traceback.print_exc()
        enviar_mensaje(destino, f'❌ Error al consultar *{placa}*.')

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json or {}
        msg_data = data.get('data', {})
        
        # Ignorar si no es del grupo autorizado
        if msg_data.get('from') != GRUPO_AUTORIZADO:
            print(f'Ignorado (no autorizado): {msg_data.get("from")}')
            return jsonify({'status': 'ignorado'}), 200
        
        # Ignorar mensajes propios
        if msg_data.get('fromMe'):
            return jsonify({'status': 'ignorado'}), 200
        
        body = (msg_data.get('body') or '').strip().upper()
        autor = msg_data.get('author', msg_data.get('from'))
        print(f'Mensaje de {autor}: {body}')
        
        if body.startswith('CONSULTA '):
            placa = body.replace('CONSULTA ', '').strip()
            if 6 <= len(placa) <= 8:
                hilo = threading.Thread(
                    target=procesar_consulta, 
                    args=(placa, GRUPO_AUTORIZADO), 
                    daemon=True
                )
                hilo.start()
            else:
                enviar_mensaje(GRUPO_AUTORIZADO, '⚠️ Formato: *CONSULTA ABC123*')
        
        return jsonify({'status': 'ok'}), 200
    
    except Exception as e:
        print(f'❌ Error en webhook: {e}')
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error'}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'grupo': GRUPO_AUTORIZADO}), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print(f'🚀 Servidor iniciando en puerto {port}')
    print(f'📍 Grupo autorizado: {GRUPO_AUTORIZADO}')
    app.run(host='0.0.0.0', port=port, debug=False)
