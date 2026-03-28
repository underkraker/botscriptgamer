import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from flask import Flask, request, jsonify
import threading
import time
import uuid
import os
import io
import paramiko
import subprocess
import html
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from database import init_db, can_user_generate, generate_install_key, validate_and_burn_install_key, add_membership_key, redeem_membership, get_user, get_active_vps_ips, get_expiring_users, create_ticket, add_vps, get_user_vps, get_vps_by_id, delete_vps
from config import TOKEN, ADMIN_ID, VERSION, INSTALL_CMD, API_KEY

VERSION = "v10.2 Master Shield Edition 🔐"
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# --- CONFIGURACIÓN DE CONCURRENCIA ---
executor = ThreadPoolExecutor(max_workers=30)
user_locks = {} # Prevención de duplicados (Debounce)

def is_locked(uid, duration=4):
    now = time.time()
    if uid in user_locks and now - user_locks[uid] < duration: return True
    user_locks[uid] = now
    return False

# --- MEMORIA VOLATIL ---
temp_vps = {}
temp_creation = {}
temp_edit = {}
temp_admin = {}

# --- API VALIDACIÓN ---
@app.route('/api/validar', methods=['GET'])
def validar_key():
    key = request.args.get('key'); ip = request.remote_addr
    is_valid, creator_id, install_id = validate_and_burn_install_key(key, ip)
    if is_valid:
        creator = get_user(creator_id); c_username = creator['username'] if creator else "Admin"
        uid = str(uuid.uuid4()); ahora = datetime.now().strftime("%H:%M:%S")
        msg = (
            "=======================================\n"
            "========📩 🅼🅴🅽🆂🅰🅹🅴 🆁🅴🅲🅸🅱🅸🅳🅾 📩========\n"
            "=======================================\n"
            f"<code>{key}</code>\n"
            "============= ☝️ ✅ ☝ ==============\n"
            f"🌐 IP: {ip}\n"
            "=======================================\n"
            f"📦 UUID: {uid}\n"
            f"👤 DUEÑO: @{c_username}\n"
            "=======================================\n"
            f"⏰ HORA: {ahora} <-> 📑 INSTALL N° {install_id}\n"
            "======================================="
        )
        try: bot.send_message(ADMIN_ID, msg, parse_mode="HTML")
        except: pass
        return jsonify({"status": "success", "msg": "valid", "owner": c_username}), 200
    return jsonify({"status": "error", "msg": "invalid"}), 403

def run_flask(): 
    try: app.run(host='0.0.0.0', port=5000)
    except Exception as e: print(f"Flask Error: {e}")

# --- SSH ENGINE ---
def ssh_connect_client(vps):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    if vps['auth_type'] == 'key':
        key_file = io.StringIO(vps['vps_key_content'])
        try: pkey = paramiko.RSAKey.from_private_key(key_file)
        except: 
            key_file.seek(0); pkey = paramiko.Ed25519Key.from_private_key(key_file)
        ssh.connect(vps['vps_ip'], username=vps['vps_user'], pkey=pkey, timeout=12)
    else:
        ssh.connect(vps['vps_ip'], username=vps['vps_user'], password=vps['vps_pass'], timeout=12)
    return ssh

def ssh_execute_master(vps, cmd_list):
    try:
        ssh = ssh_connect_client(vps); pre = "sudo " if vps['use_sudo'] else ""
        full_cmd = " && ".join([c if any(x in c for x in ["grep","echo","tee"]) or pre in c else f"{pre}{c}" for c in cmd_list])
        stdin, stdout, stderr = ssh.exec_command(full_cmd)
        out = stdout.read().decode(); err = stderr.read().decode(); ssh.close()
        return True, out, err
    except Exception as e: return False, "", str(e)

# --- BOT HELPERS (NUEVOS) ---
def get_main_markup(uid):
    is_vip = can_user_generate(uid) or uid == ADMIN_ID
    markup = InlineKeyboardMarkup()
    if is_vip:
        markup.row(InlineKeyboardButton("🖥️ GESTIONAR VPS", callback_data="vps_list"))
        markup.row(InlineKeyboardButton("🔑 KEY VPS", callback_data="btn_key"), InlineKeyboardButton("🛰️ MONITOR", callback_data="btn_monitor"))
    markup.row(InlineKeyboardButton("👤 MI PERFIL", callback_data="btn_perfil"))
    markup.row(InlineKeyboardButton("📚 GUÍAS", callback_data="btn_guias"), InlineKeyboardButton("🛠️ SOPORTE", callback_data="btn_soporte"))
    if uid == ADMIN_ID: markup.row(InlineKeyboardButton("🎟️ CREAR MEMBRESIA VIP", callback_data="btn_p_admin"))
    return markup

def send_main_menu(message, uid, edit=False):
    markup = get_main_markup(uid)
    msg = (
        "<b>🔥 MAESTRO UNDERKRAKER 🔥</b>\n"
        f"🚀 Version: <code>{VERSION}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Bienvenido al Centro de Mando Gamer Master.\n"
        "Gestiona tus servidores y licencias con un click."
    )
    if edit:
        try: bot.edit_message_text(msg, message.chat.id, message.message_id, reply_markup=markup, parse_mode="HTML")
        except: bot.send_message(message.chat.id, msg, reply_markup=markup, parse_mode="HTML")
    else:
        bot.send_message(message.chat.id, msg, reply_markup=markup, parse_mode="HTML")

# --- BOT HANDLERS ---
@bot.message_handler(commands=['start', 'menu'])
@bot.message_handler(func=lambda m: m.text and m.text.lower() in [".menu", ".start"])
def cmd_start(message):
    send_main_menu(message, message.from_user.id)

@bot.message_handler(commands=['canjear'])
def cnj(message):
    try:
        parts = message.text.split()
        if len(parts) < 2: return bot.reply_to(message, "❌ Uso: <code>/canjear CLAVE-AQUI</code>", parse_mode="HTML")
        key = parts[1]
        ok, duration = redeem_membership(message.from_user.id, message.from_user.username, key)
        if ok: bot.reply_to(message, f"✅ <b>Felicidades!</b>\nHas canjeado un pase VIP de <b>{duration} días</b>.", parse_mode="HTML")
        else: bot.reply_to(message, "❌ Key inválida o ya canjeada.")
    except Exception as e: bot.reply_to(message, f"❌ Error: {str(e)}")

@bot.callback_query_handler(func=lambda call: True)
def callback_master(call):
    uid = call.from_user.id; data = call.data
    chat_id = call.message.chat.id; msg_id = call.message.message_id
    
    # Respuesta inmediata para UX
    try: bot.answer_callback_query(call.id)
    except: pass

    # 📋 MODULO VPS
    if data == "vps_list":
        vps_list = get_user_vps(uid)
        markup = InlineKeyboardMarkup()
        for v in vps_list: markup.row(InlineKeyboardButton(f"🌐 {v['vps_name']} ({v['vps_ip']})", callback_data=f"v_view_{v['id']}"))
        markup.row(InlineKeyboardButton("➕ AÑADIR VPS", callback_data="v_add_template"), InlineKeyboardButton("🔙 REGRESAR", callback_data="back"))
        bot.edit_message_text("🖥️ <b>TUS SERVIDORES:</b>", chat_id, msg_id, reply_markup=markup, parse_mode="HTML")
    
    elif data.startswith("v_view_"):
        vid = data.split("_")[2]; v = get_vps_by_id(vid)
        if not v: return bot.send_message(chat_id, "❌ VPS no encontrada.")
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("➕ CREAR USER SSH", callback_data=f"v_cu_{vid}"))
        markup.row(InlineKeyboardButton("👥 GESTIONAR USERS", callback_data=f"v_lu_{vid}"))
        markup.row(InlineKeyboardButton("🗑️ BORRAR VPS", callback_data=f"v_del_{vid}"), InlineKeyboardButton("🔙 VOLVER", callback_data="vps_list"))
        at = "Llave (.pem)" if v['auth_type'] == 'key' else "Pass"
        text = f"🖥️ <b>VPS:</b> {v['vps_name']}\n🌐 <b>IP:</b> <code>{v['vps_ip']}</code>\n👤: <code>{v['vps_user']}</code>\n🔐: <code>{at}</code>"
        bot.edit_message_text(text, chat_id, msg_id, reply_markup=markup, parse_mode="HTML")

    elif data.startswith("v_lu_"):
        if is_locked(uid): return
        vid = data.split("_")[2]; v = get_vps_by_id(vid)
        info = bot.send_message(chat_id, "⏳ <b>Consultando usuarios en el VPS...</b>", parse_mode="HTML")
        def run_lu():
            try:
                ok, out, err = ssh_execute_master(v, ["ls /etc/gaming_vps/*.limit"])
                if ok:
                    users = [f.split("/")[-1].replace(".limit", "") for f in out.split() if ".limit" in f]
                    markup = InlineKeyboardMarkup()
                    for u in users: markup.row(InlineKeyboardButton(f"👤 {u}", callback_data=f"u_opt_{vid}_{u}"))
                    markup.row(InlineKeyboardButton("🔙 VOLVER", callback_data=f"v_view_{vid}"))
                    bot.edit_message_text(f"👥 <b>CLIENTES EN {v['vps_name']}:</b>", chat_id, info.message_id, reply_markup=markup, parse_mode="HTML")
                else: 
                    bot.edit_message_text(f"❌ Error SSH: <code>{html.escape(err)}</code>", chat_id, info.message_id, parse_mode="HTML")
            except Exception as e:
                bot.send_message(chat_id, f"⚠️ Error inesperado: {str(e)}")
        executor.submit(run_lu)

    elif data.startswith("u_opt_"):
        parts = data.split("_"); vid = parts[2]; user = parts[3]
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("🗑️ BORRAR", callback_data=f"u_del_{vid}_{user}"), InlineKeyboardButton("✏️ EDITAR PASS", callback_data=f"u_edit_{vid}_{user}"))
        markup.row(InlineKeyboardButton("🔙 VOLVER", callback_data=f"v_lu_{vid}"))
        bot.edit_message_text(f"👤 <b>GESTIÓN DE USUARIO:</b> <code>{user}</code>\n¿Qué deseas hacer?", chat_id, msg_id, reply_markup=markup, parse_mode="HTML")

    elif data.startswith("u_del_"):
        if is_locked(uid): return
        parts = data.split("_"); vid = parts[2]; user = parts[3]; v = get_vps_by_id(vid)
        info = bot.send_message(chat_id, f"⏳ <b>Borrando a {user}...</b>", parse_mode="HTML")
        def run_del():
            try:
                ok, out, err = ssh_execute_master(v, [f"userdel -f {user}", f"rm -f /etc/gaming_vps/{user}.limit"])
                bot.edit_message_text(f"✅ Usuario <code>{user}</code> eliminado con éxito.", chat_id, info.message_id, parse_mode="HTML")
                # Botón para volver
                markup = InlineKeyboardMarkup().row(InlineKeyboardButton("🔙 VOLVER A LISTA", callback_data=f"v_lu_{vid}"))
                bot.edit_message_reply_markup(chat_id, info.message_id, reply_markup=markup)
            except Exception as e:
                bot.send_message(chat_id, f"❌ Error en borrado: {str(e)}")
        executor.submit(run_del)

    elif data == "btn_perfil":
        user = get_user(uid)
        if uid == ADMIN_ID: status = "👑 <b>MAESTRO / ADMIN</b>"; exp = "♾️ Inmortal"
        elif user:
            status = "🌟 <b>VIP / MIEMBRO</b>"
            exp = datetime.fromtimestamp(user['expiry_date']).strftime("%d/%m/%Y %H:%M")
        else: status = "👤 <b>USUARIO BASE</b>"; exp = "❌ Sin Membresía"
        bot.send_message(chat_id, f"👤 <b>TU PERFIL:</b>\n📌 Status: {status}\n📅 Expiración: <code>{exp}</code>", parse_mode="HTML")

    elif data == "btn_key":
        if can_user_generate(uid) or uid == ADMIN_ID:
            k, c = generate_install_key(uid)
            u_name = html.escape(call.from_user.username or "Usuario")
            msg = (
                "••••••••••••••••••••••••••••••••••••••••••••••••••••••••••\n"
                f"KEY {{ {c} }} DE @{u_name} con ID: {uid}\n"
                "⚠️ VENCE EN 4 HORAS O AL SER USADA ⚠️\n"
                "••••••••••••••••••••••••••••••••••••••••••••••••••••••••••\n"
                f"🛡️ SloganKEY 🛡️ : Klk {u_name}\n"
                "••••••••••••••••••••••••••••••••••••••••••••••••••••••••••\n"
                f"🗝️ <code>{k}</code> 🗝️\n"
                "•••••••••••••\n"
                f"🛡️ 𝙸𝚗𝚜𝚝𝚊𝚕𝚊𝚍𝚘𝚛 𝙾𝚏𝚒𝚌𝚒𝚊𝚕 {VERSION} 🔐\n"
                "••••••••••••••••••••••••••••••••••••••••••••••••••••••••••\n"
                f"<code>{INSTALL_CMD}</code>\n"
                "••••••••••••••••••••••••••••••••••••••••••••••••••••••••••\n"
                "𝙍𝙚𝙘𝙤𝙢𝙚𝙣𝙙𝙖𝙙𝙤 𝙐𝙗𝙪𝙣𝙩𝙪 20.04 LTS\n"
                "🧬🧬 S.O Ubuntu 18.04 a 24.04 X64 🧬🧬\n"
                "Debian 8 a 12 (x64)\n"
                "🪦 ACCESOS OFICIALES CON @underkraker\n"
                "••••••••••••••••••••••••••••••••••••••••••••••••••••••••••"
            )
            bot.send_message(chat_id, msg, parse_mode="HTML")
        else: bot.send_message(chat_id, "❌ No tienes permiso VIP.")

    elif data == "btn_monitor":
        vips = get_active_vps_ips(); msg = "🛰️ <b>IPS ACTIVAS:</b>\n"
        if not vips: msg += "⚠️ Ninguna IP registrada."
        else:
            for v in vips: msg += f"• <code>{v['ip']}</code> (@{html.escape(v['username'])})\n"
        bot.send_message(chat_id, msg, parse_mode="HTML")

    elif data == "btn_guias":
        bot.send_message(chat_id, "📚 <b>CENTRO DE AYUDA:</b>\n• Usa <code>/canjear CLAVE</code> para ser VIP.\n• Registra tu VPS con IP y Pass/Key.\n• Crea usuarios SSH ilimitados.", parse_mode="HTML")

    elif data == "btn_soporte":
        bot.send_message(chat_id, "🛠️ <b>SOPORTE TÉCNICO:</b>\nContáctame en @underkraker para reportar fallos o comprar membresías.")

    elif data == "btn_p_admin":
        if uid == ADMIN_ID:
            msg = bot.send_message(chat_id, "🎟️ <b>ADMIN:</b> Escribe la duración en días para la nueva llave VIP (ej: 30):", parse_mode="HTML")
            bot.register_next_step_handler(msg, step_p_admin_1)

    elif data == "v_add_template":
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("📂 AWS", callback_data="tpl_aws"), InlineKeyboardButton("📂 Oracle", callback_data="tpl_ora"))
        markup.row(InlineKeyboardButton("📂 Root", callback_data="tpl_root"), InlineKeyboardButton("⚙️ Manual", callback_data="tpl_man"))
        bot.edit_message_text("🚀 <b>PLANTILLAS:</b>", chat_id, msg_id, reply_markup=markup, parse_mode="HTML")
    
    elif data.startswith("tpl_"):
        temp_vps[uid] = {"template": data.split("_")[1]}
        msg = bot.send_message(chat_id, "🏷️ <b>Nombre VPS:</b>", parse_mode="HTML"); bot.register_next_step_handler(msg, v_step1_name)
    
    elif data.startswith("v_del_"):
        delete_vps(data.split("_")[2], uid)
        bot.send_message(chat_id, "✅ VPS eliminada con éxito.")
        send_main_menu(call.message, uid, edit=True)
    
    elif data == "back": 
        send_main_menu(call.message, uid, edit=True)
    
    elif data.startswith("v_cu_"):
        temp_creation[uid] = {"vid": data.split("_")[2]}
        msg = bot.send_message(chat_id, "👤 <b>Nombre de usuario SSH:</b>", parse_mode="HTML"); bot.register_next_step_handler(msg, cu_step1)

# --- STEPS (HARDENED) ---
def step_p_admin_1(m):
    try:
        duration = int(m.text); key = add_membership_key(duration)
        bot.send_message(m.chat.id, f"✅ <b>PASE VIP CREADO:</b>\n🔑 <code>{key}</code>\n⏳ Duración: {duration} días.\nCanjear con: <code>/canjear {key}</code>", parse_mode="HTML")
    except: bot.send_message(m.chat.id, "❌ Duración inválida.")

def cu_step1(m): temp_creation[m.from_user.id]["un"] = m.text; msg = bot.send_message(m.chat.id, "🔐 <b>Contraseña para el usuario:</b>", parse_mode="HTML"); bot.register_next_step_handler(msg, cu_step2)
def cu_step2(m): temp_creation[m.from_user.id]["pw"] = m.text; msg = bot.send_message(m.chat.id, "📅 <b>Días de duración:</b>", parse_mode="HTML"); bot.register_next_step_handler(msg, cu_step3)
def cu_step3(m): 
    try:
        temp_creation[m.from_user.id]["ds"] = int(m.text)
        msg = bot.send_message(m.chat.id, "🔄 <b>Límite de conexiones simultáneas:</b>", parse_mode="HTML")
        bot.register_next_step_handler(msg, cu_final)
    except: bot.send_message(m.chat.id, "❌ Error: Debe ser un número."); send_main_menu(m, m.from_user.id)

def cu_final(m):
    uid = m.from_user.id
    if is_locked(uid): return
    try:
        limit = int(m.text); data = temp_creation.get(uid)
        if not data: return
        v = get_vps_by_id(data['vid']); pre = "sudo " if v['use_sudo'] else ""
        info = bot.send_message(m.chat.id, "⏳ <b>Configurando usuario en la VPS remota...</b>", parse_mode="HTML")
        
        def run_cu():
            try:
                cmds = [
                    f"grep -q '/bin/false' /etc/shells || echo '/bin/false' | {pre}tee -a /etc/shells",
                    f"useradd -e $(date -d '{data['ds']} days' +%Y-%m-%d) -s /bin/false -M {data['un']}",
                    f"echo '{data['un']}:{data['pw']}' | chpasswd",
                    f"mkdir -p /etc/gaming_vps",
                    f"echo '{limit}' | tee /etc/gaming_vps/{data['un']}.limit",
                    f"sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/g' /etc/ssh/sshd_config",
                    f"systemctl restart sshd 2>/dev/null", f"systemctl restart dropbear 2>/dev/null"
                ]
                ok, out, err = ssh_execute_master(v, cmds)
                if ok: 
                    bot.edit_message_text(f"✅ <b>CLIENTE CREADO!</b>\nUser: <code>{data['un']}</code>\nPass: <code>{data['pw']}</code>\nLímite: <code>{limit}</code>", m.chat.id, info.message_id, parse_mode="HTML")
                else: 
                    bot.edit_message_text(f"❌ Error crítico en VPS: <code>{html.escape(err)}</code>", m.chat.id, info.message_id, parse_mode="HTML")
            except Exception as ex:
                bot.send_message(m.chat.id, f"⚠️ Error en ejecución SSH: {str(ex)}")
        executor.submit(run_cu)
    except: bot.send_message(m.chat.id, "❌ Límite inválido."); send_main_menu(m, uid)

def v_step1_name(m): temp_vps[m.from_user.id]["n"] = m.text; msg = bot.send_message(m.chat.id, "🌐 <b>IP del VPS:</b>", parse_mode="HTML"); bot.register_next_step_handler(msg, v_step2_ip)
def v_step2_ip(m):
    uid = m.from_user.id; temp_vps[uid]["i"] = m.text; tpl = temp_vps[uid]["template"]
    if tpl in ["aws", "ora"]:
        temp_vps[uid]["u"] = "ubuntu"; temp_vps[uid]["auth_type"] = "key"
        bot.send_message(m.chat.id, "📂 <b>Por favor, sube el archivo .pem (Llave SSH):</b>", parse_mode="HTML")
    elif tpl == "root":
        temp_vps[uid]["u"] = "root"; temp_vps[uid]["auth_type"] = "pass"
        msg = bot.send_message(m.chat.id, "🔑 <b>Contraseña Root:</b>", parse_mode="HTML"); bot.register_next_step_handler(msg, v_step_pass_direct)
    else:
        msg = bot.send_message(m.chat.id, "👤 <b>Nombre de usuario SSH:</b>", parse_mode="HTML"); bot.register_next_step_handler(msg, v_step_user_manual)

def v_step_user_manual(m): temp_vps[m.from_user.id]["u"] = m.text; msg = bot.send_message(m.chat.id, "🔑 <b>Contraseña SSH:</b>", parse_mode="HTML"); bot.register_next_step_handler(msg, v_step_pass_direct)

@bot.message_handler(content_types=['document'])
def handle_ssh_final(message):
    uid = message.from_user.id
    if uid in temp_vps and temp_vps[uid].get("auth_type") == "key":
        try:
            f = bot.download_file(bot.get_file(message.document.file_id).file_path)
            temp_vps[uid]["val"] = f.decode('utf-8')
            sudo_val = 1 if temp_vps[uid].get("template") in ["aws", "ora"] else 0
            add_vps(uid, temp_vps[uid]['n'], temp_vps[uid]['i'], temp_vps[uid]['u'], 'key', temp_vps[uid]['val'], sudo_val)
            bot.send_message(message.chat.id, "✅ <b>VPS Registrada correctamente.</b>", parse_mode="HTML")
            send_main_menu(message, uid)
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ Error leyendo archivo: {str(e)}")

def v_step_pass_direct(m): 
    uid = m.from_user.id; d = temp_vps.get(uid)
    if not d: return
    try:
        add_vps(uid, d['n'], d['i'], d['u'], 'pass', m.text, 0)
        bot.send_message(m.chat.id, "✅ <b>VPS Registrada correctamente con contraseña.</b>", parse_mode="HTML")
        send_main_menu(m, uid)
    except Exception as e: bot.send_message(m.chat.id, f"❌ Error DB: {str(e)}")

# --- COMANDO .CMD (HARDENED) ---
@bot.message_handler(func=lambda m: m.text and m.text.startswith(".cmd"))
def handle_cmd_raw(m):
    uid = m.from_user.id
    if uid != ADMIN_ID: return bot.reply_to(m, "🚫 <b>Acceso denegado.</b>", parse_mode="HTML")
    cmd = m.text[5:].strip()
    if not cmd: return bot.reply_to(m, "🔑 <b>Uso:</b> <code>.cmd COMANDO</code>", parse_mode="HTML")
    def run_raw():
        try:
            p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, err = p.communicate()
            res = (out.decode() + err.decode()).strip()
            if not res: res = "✅ Ejecución exitosa (sin salida)."
            if len(res) > 3800:
                f = io.BytesIO(res.encode()); f.name = "output.txt"
                bot.send_document(m.chat.id, f, caption="📄 Salida completa.")
            else: bot.reply_to(m, f"💻 <b>SHELL:</b>\n<pre>{html.escape(res)}</pre>", parse_mode="HTML")
        except Exception as e: bot.reply_to(m, f"❌ Error: {str(e)}")
    executor.submit(run_raw)

if __name__ == '__main__':
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()
    print(f"--- BOT GAMER MASTER {VERSION} INICIADO ---")
    
    while True:
        try:
            bot.polling(non_stop=True, interval=1, timeout=40)
        except Exception as e:
            print(f"Polling Crash Recovery: {e}")
            time.sleep(5)
