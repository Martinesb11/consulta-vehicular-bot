import os, threading, requests
from flask import Flask, request, jsonify
from consulta import ejecutar_consulta_completa, pdf_a_base64

app = Flask(__name__)

# ─────────────────────────────────────────
# Configuración — se leen desde variables de entorno en Railway
# ─────────────────────────────────────────
USUARIO            = os.environ.get('CV_USUARIO', '')
CONTRASENA         = os.environ.get('CV_CONTRASENA', '')
ULTRAMSG_INSTANCE  = os.environ.get('ULTRAMSG_INSTANCE', '')
ULTRAMSG_TOKEN     = os.environ.get('ULTRAMSG_TOKEN', '')

# Números autorizados para usar el bot (separados por coma en la variable de entorno)
# Ejemplo: "51987654321,51912345678"
NUMEROS_AUTORIZADOS = [
    n.strip() for n in os.environ.get('NUMEROS_AUTORIZADOS', '').split(',') if n.strip()
]

# ─────────────────────────────────────────
# Envío de mensajes WhatsApp
# ─────────────────────────────────────────
def enviar_mensaje(numero, texto):
    try:
        requests.post(
            f'https://api.ultramsg.com/{ULTRAMSG_INSTANCE}/messages/chat',
            data={'token': ULTRAMSG_TOKEN, 'to': numero, 'body': texto},
            timeout=30
        )
    except Exception as e:
        print(f'Error enviando mensaje: {e}')

def enviar_pdf(numero, pdf_path, placa):
    try:
        pdf_b64 = pdf_a_base64(pdf_path)
        requests.post(
            f'https://api.ultramsg.com/{ULTRAMSG_INSTANCE}/messages/document',
            data={
                'token':    ULTRAMSG_TOKEN,
                'to':       numero,
                'document': f'data:application/pdf;base64,{pdf_b64}',
                'filename': f'Reporte_{placa}.pdf',
                'caption':  f'📄 Reporte vehicular — Placa {placa}'
            },
            timeout=60
        )
    except Exception as e:
        print(f'Error enviando PDF: {e}')

# ─────────────────────────────────────────
# Lógica del bot
# ─────────────────────────────────────────
def procesar_consulta(numero, placa):
    """Corre en hilo separado para no bloquear el webhook"""
    enviar_mensaje(numero, f'⏳ Consultando la placa *{placa}*...\nEsto puede tardar 2-3 minutos, espera por favor.')
    try:
        pdf_path = ejecutar_consulta_completa(placa, USUARIO, CONTRASENA)
        if pdf_path:
            enviar_mensaje(numero, f'✅ Reporte listo para la placa *{placa}*. Te lo envío ahora:')
            enviar_pdf(numero, pdf_path, placa)
            # Limpiar archivo temporal
            try: os.remove(pdf_path)
            except Exception: pass
        else:
            enviar_mensaje(numero, f'⚠️ No se pudo generar el reporte para la placa *{placa}*.\nVerifica que la placa sea correcta e intenta nuevamente.')
    except Exception as e:
        print(f'Error en consulta: {e}')
        enviar_mensaje(numero, f'❌ Ocurrió un error al consultar la placa *{placa}*.\nIntenta nuevamente en unos minutos.')

def manejar_comando(numero, mensaje):
    msg = mensaje.strip().upper()

    # ── CONSULTA ABC123 ──
    if msg.startswith('CONSULTA '):
        placa = msg.replace('CONSULTA ', '').strip()
        if len(placa) < 6 or len(placa) > 8:
            enviar_mensaje(numero, '⚠️ Formato incorrecto.\nEscribe: *CONSULTA ABC123*')
            return
        hilo = threading.Thread(target=procesar_consulta, args=(numero, placa), daemon=True)
        hilo.start()
        return

    # ── AYUDA ──
    if msg in ('AYUDA', 'HELP', 'HOLA', 'HI', 'START', 'INICIO'):
        enviar_mensaje(numero,
            '🤖 *Bot de Consulta Vehicular*\n\n'
            '📋 *Comandos disponibles:*\n\n'
            '🔍 *CONSULTA [PLACA]*\n'
            '   Ejemplo: CONSULTA ABC123\n'
            '   → Te envío el reporte PDF completo\n\n'
            '📊 *ESTADO*\n'
            '   → Ver si el bot está activo\n\n'
            '❓ *AYUDA*\n'
            '   → Ver esta lista de comandos\n\n'
            '_El reporte puede tardar 2-3 minutos en generarse._'
        )
        return

    # ── ESTADO ──
    if msg == 'ESTADO':
        autorizados = len(NUMEROS_AUTORIZADOS)
        enviar_mensaje(numero,
            '✅ *Bot activo y funcionando*\n\n'
            f'🔧 Instancia UltraMsg: {ULTRAMSG_INSTANCE}\n'
            f'👥 Números autorizados: {autorizados}\n\n'
            'Escribe *AYUDA* para ver los comandos disponibles.'
        )
        return

    # ── Comando no reconocido ──
    enviar_mensaje(numero,
        '❓ No entendí ese comando.\n\n'
        'Escribe *AYUDA* para ver los comandos disponibles.\n\n'
        'O consulta una placa así:\n*CONSULTA ABC123*'
    )

# ─────────────────────────────────────────
# Webhook — UltraMsg llama aquí
# ─────────────────────────────────────────
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json(force=True) or {}
        print(f'Webhook recibido: {data}')

        # Extraer datos del mensaje
        msg_data = data.get('data', {})
        mensaje  = (msg_data.get('body') or '').strip()
        numero   = (msg_data.get('from') or '').replace('@c.us', '').replace('+', '').strip()
        tipo     = msg_data.get('type', '')

        # Solo procesar mensajes de texto
        if tipo != 'chat' or not mensaje or not numero:
            return jsonify({'status': 'ignored'}), 200

        # Ignorar mensajes propios del bot
        from_me = msg_data.get('fromMe', False)
        if from_me:
            return jsonify({'status': 'own_message'}), 200

        print(f'Mensaje de {numero}: {mensaje}')

        # Verificar si el número está autorizado
        if NUMEROS_AUTORIZADOS and numero not in NUMEROS_AUTORIZADOS:
            enviar_mensaje(numero, '🚫 No tienes autorización para usar este servicio.')
            return jsonify({'status': 'unauthorized'}), 200

        # Procesar el comando en hilo separado
        hilo = threading.Thread(target=manejar_comando, args=(numero, mensaje), daemon=True)
        hilo.start()

        return jsonify({'status': 'ok'}), 200

    except Exception as e:
        print(f'Error en webhook: {e}')
        return jsonify({'status': 'error', 'detail': str(e)}), 500

# ─────────────────────────────────────────
# Health check — Railway lo usa para saber si el servidor está vivo
# ─────────────────────────────────────────
@app.route('/', methods=['GET'])
def health():
    return jsonify({'status': '🟢 Bot activo', 'instancia': ULTRAMSG_INSTANCE}), 200

# ─────────────────────────────────────────
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print(f'🚀 Servidor iniciando en puerto {port}')
    app.run(host='0.0.0.0', port=port, debug=False)
