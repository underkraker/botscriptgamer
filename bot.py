import telebot
import sqlite3
import time
import threading
from flask import Flask, request, jsonify
from database import init_db, add_membership_key, redeem_membership, can_user_generate, generate_install_key, validate_and_burn_install_key, get_user

TOKEN = "TU_TOKEN_AQUI"
ADMIN_ID = 123456789  # EL ADMIN REEMPLAZA ESTO CON SU ID DE TELEGRAM

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# --- FLASK API ---
@app.route('/api/validar', methods=['GET'])
def validar_key():
    key = request.args.get('key')
    ip = request.remote_addr
    # validate key
    if not key:
        return jsonify({"status": "error", "msg": "No key provided"}), 400
        
    is_valid = validate_and_burn_install_key(key, ip)
    if is_valid:
        return jsonify({"status": "ok", "msg": "Key validada y consumida exitosamente"}), 200
    else:
        return jsonify({"status": "invalido", "msg": "Key invalida, expirada o ya usada"}), 403

# --- TELEGRAM BOT ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    if user_id == ADMIN_ID:
        bot.reply_to(message, "👑 Bienvenido Administrador. Eres el dueño del sistema.\n\nComandos Maestro:\n/crear_pase [dias] - Genera keys de membresía para revendedores.\n/key - Generar llave de instalación para ti mismo.")
        return
        
    user = get_user(user_id)
    if user and user['expiry_date'] > int(time.time()):
        bot.reply_to(message, "✅ ¡Estás autorizado!\nUsa /key para generar una llave de instalación (Válida por 4 horas).")
    else:
        bot.reply_to(message, "❌ No estás autorizado o tu membresía expiró.\nPara comprar un pase de acceso al Script, contacta a: @underkraker\n\nSi ya compraste un pase, actívalo con:\n/canjear [TU_CODIGO_AQUI]")

@bot.message_handler(commands=['crear_pase'])
def crear_pase(message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        dias = int(message.text.split()[1])
        key = add_membership_key(dias)
        bot.reply_to(message, f"🎟️ Pase de {dias} días creado exitosamente:\n\n`{key}`\n\nEnvíale este código al cliente.", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, "⚠️ Uso incorrecto. Ejemplo: /crear_pase 30")

@bot.message_handler(commands=['canjear'])
def canjear(message):
    try:
        key = message.text.split()[1]
        success, days = redeem_membership(message.from_user.id, message.from_user.username, key)
        if success:
            bot.reply_to(message, f"🎉 ¡Pago validado! Se han agregado {days} días a tu cuenta.\nUsa el comando /key para generar licencias de instalación en tus VPS.")
        else:
            bot.reply_to(message, "❌ Código inválido o ya fue usado por alguien más.")
    except Exception as e:
        bot.reply_to(message, "⚠️ Uso incorrecto. Ejemplo: /canjear VIP-ABCDE123")

@bot.message_handler(commands=['key'])
def generate_key(message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        if not can_user_generate(user_id):
            bot.reply_to(message, "❌ Tu membresía ha caducado o no tienes acceso. Contacta a @underkraker.")
            return

    new_key = generate_install_key(user_id)
    bot.reply_to(message, f"🔑 **TU KEY DE INSTALACIÓN:**\n\n`{new_key}`\n\n⚠️ *Válida por 4 horas. De 1 un solo uso.*", parse_mode="Markdown")

def run_flask():
    # Flask escucha peticiones del VPS en el puerto 5000
    app.run(host='0.0.0.0', port=5000)

if __name__ == '__main__':
    init_db()
    
    # Iniciar API web en un hilo secundario
    threading.Thread(target=run_flask, daemon=True).start()
    
    print("🚀 Bot Maestro y API de validación Iniciados correctamente...")
    # Iniciar Bot
    bot.infinity_polling()
