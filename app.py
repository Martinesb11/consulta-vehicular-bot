import os, threading, requests
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
    except Exception as e:
        print(f'Error enviando: {e}')

def enviar_pdf(destino, pdf_path, placa):
    try:
        with open(pdf_path, 'rb') as f:
            files = {'document': (f'Reporte_{placa}.pdf', f, 'application/pdf')}
            data  = {'token': ULTRAMSG_TOKEN, 'to': destino, 'caption': f'📄 Placa {placa}'}
            requests.post(
                f'https://api.ultramsg.com/{ULTRAMSG_INSTANCE}/messages/document',
                data=data, files=files, timeout=60
            )
    except Exception as e:
        print(f'Error enviando PDF: {e}')

def procesar_consulta(placa, destino):
    enviar_mensaje(destino, f'⏳ Consultando *{placa}*...\nEspera 2-3 minutos.')
    try:
        pdf_path = ejecutar_consulta_completa(placa, USUARIO_CV, CONTRASENA_CV)
        if pdf_path and os.path.exists(pdf_path):
            enviar_pdf(destino, pdf_path, placa)
            try:
                os.remove(pdf_path)
            except:
                pass
        else:
            enviar_mensaje(destino, f'⚠️ No se pudo generar reporte para *{placa}*.')
    except Exception as e:
        print(f'Error: {e}')
        enviar_mensaje(destino, f'❌ Error al consultar *{placa}*. Intenta después.')

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json or {}
    msg_data = data.get('data', {})
    
    # Ignorar si no es del grupo autorizado
    if msg_data.get('from') != GRUPO_AUTORIZADO:
        return jsonify({'status': 'ignorado'}), 200
    
    # Ignorar mensajes propios
    if msg_data.get('fromMe'):
        return jsonify({'status': 'ignorado'}), 200
    
    body = (msg_data.get('body') or '').strip().upper()
    
    if body.startswith('CONSULTA '):
        placa = body.replace('CONSULTA ', '').strip()
        if 6 <= len(placa) <= 8:
            hilo = threading.Thread(target=procesar_consulta, args=(placa, GRUPO_AUTORIZADO), daemon=True)
            hilo.start()
        else:
            enviar_mensaje(GRUPO_AUTORIZADO, '⚠️ Formato: *CONSULTA ABC123*')
    
    return jsonify({'status': 'ok'}), 200

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'}), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print(f'🚀 Puerto {port}')
    app.run(host='0.0.0.0', port=port, debug=False)
