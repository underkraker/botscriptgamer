import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from flask import Flask, request, jsonify
import threading
import time
import uuid
import os
import io
import subprocess
import html
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from database import init_db, can_user_generate, generate_install_key, validate_and_burn_install_key, add_membership_key, redeem_membership, get_user, get_active_vps_ips
from config import TOKEN, ADMIN_ID, VERSION, INSTALL_CMD, API_KEY

VERSION = "v13.0 Lite Shield 🛡️"
bot = telebot.TeleBot(TOKEN, threaded=True, num_threads=15)
app = Flask(__name__)

# --- CONFIGURACIÓN LITE (v13.0) ---
executor = ThreadPoolExecutor(max_workers=30)
user_locks = {}
vip_cache = {}

def get_cached_vip(uid):
    now = time.time()
    if uid in vip_cache:
        val, ts = vip_cache[uid]
        if now - ts < 180: return val # Cache de 3 minutos para máxima estabilidad
    val = can_user_generate(uid) or uid == ADMIN_ID
    vip_cache[uid] = (val, now)
    return val

def is_locked(uid, duration=0.5):
    now = time.time()
    if uid in user_locks and now - user_locks[uid] < duration:
        print(f"⚠️ [ANTI-SPAM] {uid} bloqueado por 0.5s")
        return True
    user_locks[uid] = now
    return False

# --- API VALIDACIÓN (Solo para Instalador) ---
@app.route('/api/validar', methods=['GET'])
def validar_key():
    key = request.args.get('key')
    # Detectar IP real si hay proxy (Nginx/Cloudflare)
    ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
    
    is_valid, creator_id, install_id = validate_and_burn_install_key(key, ip)
    if is_valid:
        creator = get_user(creator_id)
        c_username = creator['username'] if creator else "Admin"
        try:
            bot.send_message(ADMIN_ID, f"✅ <b>NUEVA INSTALACIÓN:</b>\nKey: <code>{key}</code>\nIP: {ip}\nDueño: @{c_username}", parse_mode="HTML")
        except Exception as e:
            print(f"Error enviando notificación al admin: {e}")
        return jsonify({"status": "success", "msg": "valid", "owner": c_username}), 200
    return jsonify({"status": "error", "msg": "invalid"}), 403

def run_flask(): 
    try: app.run(host='0.0.0.0', port=5000)
    except: pass

# --- SISTEMA DE MENÚS LITE ---
def get_main_markup(uid):
    is_vip = get_cached_vip(uid)
    markup = InlineKeyboardMarkup()
    if is_vip:
        markup.row(InlineKeyboardButton("🔑 GENERAR KEY VPS", callback_data="btn_key"))
        markup.row(InlineKeyboardButton("🛰️ MONITOR GLOBAL", callback_data="btn_monitor"))
    markup.row(InlineKeyboardButton("👤 MI PERFIL", callback_data="btn_perfil"), InlineKeyboardButton("📚 GUÍAS", callback_data="btn_guias"))
    markup.row(InlineKeyboardButton("🛠️ SOPORTE TÉCNICO", callback_data="btn_soporte"))
    if uid == ADMIN_ID: markup.row(InlineKeyboardButton("🎟️ CREAR VIP KEY", callback_data="btn_p_admin"))
    return markup

def send_main_menu(chat_id, message_id, uid, edit=True):
    def task():
        markup = get_main_markup(uid)
        msg = (
            f"<b>🔥 MAESTRO UNDERKRAKER {VERSION} 🔥</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Sistema de Generación de Licencias VPS.\n"
            "<b>0% LAG | 100% ESTABILIDAD</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Selecciona una opción:"
        )
        if edit:
            try: bot.edit_message_text(msg, chat_id, message_id, reply_markup=markup, parse_mode="HTML")
            except: bot.send_message(chat_id, msg, reply_markup=markup, parse_mode="HTML")
        else:
            bot.send_message(chat_id, msg, reply_markup=markup, parse_mode="HTML")
    executor.submit(task)

# --- BOT HANDLERS ---
@bot.message_handler(commands=['start', 'menu'])
def cmd_start(message):
    send_main_menu(message.chat.id, message.message_id, message.from_user.id, edit=False)

@bot.message_handler(commands=['canjear'])
def cnj(message):
    try:
        parts = message.text.split()
        if len(parts) < 2: return bot.reply_to(message, "❌ Uso: <code>/canjear CLAVE</code>", parse_mode="HTML")
        ok, duration = redeem_membership(message.from_user.id, message.from_user.username, parts[1])
        if ok: 
            vip_cache.pop(message.from_user.id, None)
            bot.reply_to(message, f"✅ <b>Felicidades!</b>\nHas canjeado un pase VIP de <b>{duration} días</b>.", parse_mode="HTML")
        else: bot.reply_to(message, "❌ Clave inválida.")
    except: bot.reply_to(message, "❌ Error.")

@bot.callback_query_handler(func=lambda call: True)
def callback_master(call):
    uid, data = call.from_user.id, call.data
    chat_id, msg_id = call.message.chat.id, call.message.message_id
    
    print(f"📥 [BOT] Clic de {uid} (@{call.from_user.username}): {data}")
    
    try: bot.answer_callback_query(call.id)
    except Exception as e: print(f"❌ Error answer_callback: {e}")

    if is_locked(uid): return

    if data == "btn_perfil":
        def run():
            try:
                user = get_user(uid)
                st = "👑 ADMIN" if uid == ADMIN_ID else ("🌟 VIP" if user else "👤 BASE")
                exp = "♾️" if uid == ADMIN_ID else (datetime.fromtimestamp(user['expiry_date']).strftime("%d/%m/%Y") if user else "❌")
                bot.send_message(chat_id, f"👤 <b>PERFIL:</b>\n📌 Status: {st}\n📅 Vence: <code>{exp}</code>", parse_mode="HTML")
            except Exception as e:
                print(f"❌ [ERROR] Fallo en btn_perfil para {uid}: {e}")
        executor.submit(run)

    elif data == "btn_key":
        def run():
            try:
                if get_cached_vip(uid):
                    k, c = generate_install_key(uid)
                    u_name = html.escape(call.from_user.username or "Usuario")
                    # Escapamos el comando para que no rompa el HTML de Telegram
                    safe_cmd = html.escape(INSTALL_CMD)
                    msg = (
                        "•••••••••••••••••••••••••••••••••••••••••••••••••••••••••\n"
                        f"KEY {{ {c} }} DE @{u_name} con ID: {uid}\n"
                        "⚠️ VENCE EN 4 HORAS O AL SER USADA ⚠️\n"
                        "••••••••••••••••••••••••••••••••••••••••••••••••••••••••\n"
                        f"🛡️ SloganKEY 🛡️ : Klk {u_name}\n"
                        "••••••••••••••••••••••••••••••••••••••••••••••••••••••••\n"
                        f"🗝️ <code>{k}</code> 🗝️\n"
                        "•••••••••••••\n"
                        f"🛡️ 𝙸𝚗𝚜𝚝𝚊𝚕𝚊𝚍𝚘𝚛 𝙾𝚏𝚒𝚌𝚒𝚊𝚕 {VERSION} 🔐\n"
                        "••••••••••••••••••••••••••••••••••••••••••••••••••••••••\n"
                        f"<code>{safe_cmd}</code>\n"
                        "••••••••••••••••••••••••••••••••••••••••••••••••••••••••\n"
                        "𝙍𝙚𝙘𝙤𝙢𝙚𝙣𝙙𝙖𝙙𝙤 𝙐𝙗𝙪𝙣𝙩𝙪 20.04 LTS\n"
                        "🧬🧬 S.O Ubuntu 18.04 a 24.04 X64 🧬🧬\n"
                        "Debian 8 a 12 (x64)\n"
                        "🪦 ACCESOS OFICIALES CON @underkraker\n"
                        "••••••••••••••••••••••••••••••••••••••••••••••••••••••••"
                    )
                    bot.send_message(chat_id, msg, parse_mode="HTML")
                    print(f"✅ [BOT] Key {k} enviada a {uid}")
                else:
                    print(f"❌ [BOT] {uid} no tiene permisos VIP para generar keys.")
            except Exception as e:
                print(f"❌ [ERROR] Fallo en btn_key para {uid}: {e}")
        executor.submit(run)

    elif data == "btn_monitor":
        def run():
            vips = get_active_vps_ips()
            msg = "🛰️ <b>IPS ACTIVAS CON SCRIPT:</b>\n" + ("⚠️ Ninguna activa." if not vips else "".join([f"• <code>{v['ip']}</code> (@{v['username']})\n" for v in vips]))
            bot.send_message(chat_id, msg, parse_mode="HTML")
        executor.submit(run)

    elif data == "btn_guias":
        bot.send_message(chat_id, "📚 <b>GUÍAS RÁPIDAS:</b>\n1. Consigue una VIP KEY con @underkraker.\n2. Usa <code>/canjear</code>.\n3. Genera tu instalador y pégalo en tu VPS Ubuntu.", parse_mode="HTML")

    elif data == "btn_soporte":
        bot.send_message(chat_id, "🛠️ <b>SOPORTE:</b> @underkraker")

    elif data == "btn_p_admin":
        if uid == ADMIN_ID:
            msg = bot.send_message(chat_id, "🎟️ <b>Días VIP (Num):</b>", parse_mode="HTML")
            bot.register_next_step_handler(msg, step_p_admin_1)

    elif data == "back":
        send_main_menu(chat_id, msg_id, uid, edit=True)

def step_p_admin_1(m):
    try:
        duration = int(m.text); key = add_membership_key(duration)
        bot.send_message(m.chat.id, f"✅ <b>PASE VIP CREADO:</b>\n🔑 <code>{key}</code>\n⏳ Duración: {duration} días.\nCanjear con: <code>/canjear {key}</code>", parse_mode="HTML")
    except: bot.send_message(m.chat.id, "❌ Error.")

@bot.message_handler(func=lambda m: m.text and m.text.startswith(".cmd"))
def handle_cmd_raw(m):
    if m.from_user.id != ADMIN_ID: return
    cmd = m.text[5:].strip()
    def run():
        p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = p.communicate(); res = (out.decode() + err.decode()).strip() or "✅"
        bot.reply_to(m, f"<code>{html.escape(res[:3800])}</code>", parse_mode="HTML")
    executor.submit(run)

if __name__ == '__main__':
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()
    print(f"--- BOT LITE SHIELD {VERSION} ACTIVO ---")
    while True:
        try:
            bot.polling(non_stop=True, interval=1, timeout=65)
        except Exception as e:
            print(f"❌ Error en Polling: {e}")
            time.sleep(5)
