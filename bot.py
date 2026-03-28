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

VERSION = "v10.5 Hyper-Sonic Edition ⚡"
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# --- CONFIGURACIÓN DE ALTO RENDIMIENTO ---
executor = ThreadPoolExecutor(max_workers=50) # Aumentado para ráfagas
user_locks = {}

def is_locked(uid, duration=1.5): # Reducido a lo mínimo necesario
    now = time.time()
    if uid in user_locks and now - user_locks[uid] < duration:
        return True
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

# --- MOTORES SSH OPTIMIZADOS ---
def ssh_connect_client(vps):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    # Timeout reducido a 7s para no esperar demasiado ante VPS caídos
    if vps['auth_type'] == 'key':
        key_file = io.StringIO(vps['vps_key_content'])
        try: pkey = paramiko.RSAKey.from_private_key(key_file)
        except: 
            key_file.seek(0); pkey = paramiko.Ed25519Key.from_private_key(key_file)
        ssh.connect(vps['vps_ip'], username=vps['vps_user'], pkey=pkey, timeout=7)
    else:
        ssh.connect(vps['vps_ip'], username=vps['vps_user'], password=vps['vps_pass'], timeout=7)
    return ssh

def ssh_execute_master(vps, cmd_list):
    try:
        ssh = ssh_connect_client(vps); pre = "sudo " if vps['use_sudo'] else ""
        full_cmd = " && ".join([c if any(x in c for x in ["grep","echo","tee"]) or pre in c else f"{pre}{c}" for c in cmd_list])
        stdin, stdout, stderr = ssh.exec_command(full_cmd)
        out = stdout.read().decode(); err = stderr.read().decode(); ssh.close()
        return True, out, err
    except Exception as e: return False, "", str(e)

# --- SISTEMA DE MENÚS ULTRA-RÁPIDOS ---
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
    def async_menu():
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
    executor.submit(async_menu)

# --- BOT HANDLERS ---
@bot.message_handler(commands=['start', 'menu'])
@bot.message_handler(func=lambda m: m.text and m.text.lower() in [".menu", ".start"])
def cmd_start(message):
    send_main_menu(message, message.from_user.id)

@bot.message_handler(commands=['canjear'])
def cnj(message):
    def async_cnj():
        try:
            parts = message.text.split()
            if len(parts) < 2: return bot.reply_to(message, "❌ Uso: <code>/canjear CLAVE-AQUI</code>", parse_mode="HTML")
            key = parts[1]
            ok, duration = redeem_membership(message.from_user.id, message.from_user.username, key)
            if ok: bot.reply_to(message, f"✅ <b>Felicidades!</b>\nHas canjeado un pase VIP de <b>{duration} días</b>.", parse_mode="HTML")
            else: bot.reply_to(message, "❌ Key inválida o ya canjeada.")
        except Exception as e: bot.reply_to(message, f"❌ Error: {str(e)}")
    executor.submit(async_cnj)

@bot.callback_query_handler(func=lambda call: True)
def callback_master(call):
    uid = call.from_user.id; data = call.data
    chat_id = call.message.chat.id; msg_id = call.message.message_id
    
    try: bot.answer_callback_query(call.id)
    except: pass

    if is_locked(uid): return

    # 📋 MODULO VPS
    if data == "vps_list":
        def run_list():
            vps_list = get_user_vps(uid)
            markup = InlineKeyboardMarkup()
            for v in vps_list: markup.row(InlineKeyboardButton(f"🌐 {v['vps_name']} ({v['vps_ip']})", callback_data=f"v_view_{v['id']}"))
            markup.row(InlineKeyboardButton("➕ AÑADIR VPS", callback_data="v_add_template"), InlineKeyboardButton("🔙 REGRESAR", callback_data="back"))
            bot.edit_message_text("🖥️ <b>TUS SERVIDORES:</b>", chat_id, msg_id, reply_markup=markup, parse_mode="HTML")
        executor.submit(run_list)
    
    elif data.startswith("v_view_"):
        vid = data.split("_")[2]
        def run_view():
            v = get_vps_by_id(vid)
            if not v: return bot.send_message(chat_id, "❌ VPS no encontrada.")
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("➕ CREAR USER SSH", callback_data=f"v_cu_{vid}"))
            markup.row(InlineKeyboardButton("👥 GESTIONAR USERS", callback_data=f"v_lu_{vid}"))
            markup.row(InlineKeyboardButton("🗑️ BORRAR VPS", callback_data=f"v_del_{vid}"), InlineKeyboardButton("🔙 VOLVER", callback_data="vps_list"))
            at = "Llave (.pem)" if v['auth_type'] == 'key' else "Pass"
            text = f"🖥️ <b>VPS:</b> {v['vps_name']}\n🌐 <b>IP:</b> <code>{v['vps_ip']}</code>\n👤: <code>{v['vps_user']}</code>\n🔐: <code>{at}</code>"
            bot.edit_message_text(text, chat_id, msg_id, reply_markup=markup, parse_mode="HTML")
        executor.submit(run_view)

    elif data.startswith("v_lu_"):
        vid = data.split("_")[2]; v = get_vps_by_id(vid)
        bot.edit_message_text("⏳ <b>Consultando usuarios...</b>", chat_id, msg_id, parse_mode="HTML")
        def run_lu():
            try:
                ok, out, err = ssh_execute_master(v, ["ls /etc/gaming_vps/*.limit"])
                if ok:
                    users = [f.split("/")[-1].replace(".limit", "") for f in out.split() if ".limit" in f]
                    markup = InlineKeyboardMarkup()
                    for u in users: markup.row(InlineKeyboardButton(f"👤 {u}", callback_data=f"u_opt_{vid}_{u}"))
                    markup.row(InlineKeyboardButton("🔙 VOLVER", callback_data=f"v_view_{vid}"))
                    bot.edit_message_text(f"👥 <b>CLIENTES EN {v['vps_name']}:</b>", chat_id, msg_id, reply_markup=markup, parse_mode="HTML")
                else: bot.edit_message_text(f"❌ Error SSH: <code>{html.escape(err)}</code>", chat_id, msg_id, parse_mode="HTML")
            except Exception as e: bot.send_message(chat_id, f"⚠️ Error fatal: {str(e)}")
        executor.submit(run_lu)

    elif data.startswith("u_opt_"):
        parts = data.split("_"); vid = parts[2]; user = parts[3]
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("🗑️ BORRAR", callback_data=f"u_del_{vid}_{user}"), InlineKeyboardButton("✏️ EDITAR PASS", callback_data=f"u_edit_{vid}_{user}"))
        markup.row(InlineKeyboardButton("🔙 VOLVER", callback_data=f"v_lu_{vid}"))
        bot.edit_message_text(f"👤 <b>GESTIÓN DE USUARIO:</b> <code>{user}</code>\n¿Qué deseas hacer?", chat_id, msg_id, reply_markup=markup, parse_mode="HTML")

    elif data.startswith("u_del_"):
        parts = data.split("_"); vid = parts[2]; user = parts[3]; v = get_vps_by_id(vid)
        bot.edit_message_text(f"⏳ <b>Eliminando a {user}...</b>", chat_id, msg_id, parse_mode="HTML")
        def run_del():
            try:
                ok, out, err = ssh_execute_master(v, [f"userdel -f {user}", f"rm -f /etc/gaming_vps/{user}.limit"])
                bot.edit_message_text(f"✅ Usuario <code>{user}</code> eliminado con éxito.", chat_id, msg_id, parse_mode="HTML")
                bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=InlineKeyboardMarkup().row(InlineKeyboardButton("🔙 VOLVER", callback_data=f"v_lu_{vid}")))
            except Exception as e: bot.send_message(chat_id, f"❌ Error: {str(e)}")
        executor.submit(run_del)

    elif data.startswith("u_edit_"):
        parts = data.split("_"); vid = parts[2]; user = parts[3]
        temp_edit[uid] = {"vid": vid, "un": user}
        msg = bot.send_message(chat_id, f"✏️ <b>Nueva contraseña para {user}:</b>", parse_mode="HTML")
        bot.register_next_step_handler(msg, u_edit_final)

    elif data == "btn_perfil":
        def run_perfil():
            user = get_user(uid)
            status = "👑 <b>MAESTRO / ADMIN</b>" if uid == ADMIN_ID else ("🌟 <b>VIP / MIEMBRO</b>" if user else "👤 <b>USUARIO BASE</b>")
            exp = "♾️ Inmortal" if uid == ADMIN_ID else (datetime.fromtimestamp(user['expiry_date']).strftime("%d/%m/%Y %H:%M") if user else "❌ Sin Membresía")
            bot.send_message(chat_id, f"👤 <b>TU PERFIL:</b>\n📌 Status: {status}\n📅 Expiración: <code>{exp}</code>", parse_mode="HTML")
        executor.submit(run_perfil)

    elif data == "btn_key":
        def run_key():
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
        executor.submit(run_key)

    elif data == "btn_monitor":
        def run_mon():
            vips = get_active_vps_ips()
            msg = "🛰️ <b>IPS ACTIVAS:</b>\n" + ("⚠️ Ninguna IP registrada." if not vips else "".join([f"• <code>{v['ip']}</code> (@{html.escape(v['username'])})\n" for v in vips]))
            bot.send_message(chat_id, msg, parse_mode="HTML")
        executor.submit(run_mon)

    elif data == "btn_guias":
        bot.send_message(chat_id, "📚 <b>CENTRO DE AYUDA:</b>\n• Usa <code>/canjear CLAVE</code> para ser VIP.\n• Registra tu VPS con IP y Pass/Key.\n• Crea usuarios SSH ilimitados.", parse_mode="HTML")

    elif data == "btn_soporte":
        bot.send_message(chat_id, "🛠️ <b>SOPORTE TÉCNICO:</b>\nContáctame en @underkraker para comprar membresías.")

    elif data == "btn_p_admin":
        if uid == ADMIN_ID:
            msg = bot.send_message(chat_id, "🎟️ <b>ADMIN:</b> Duración VIP (días):", parse_mode="HTML")
            bot.register_next_step_handler(msg, step_p_admin_1)

    elif data == "v_add_template":
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("📂 AWS", callback_data="tpl_aws"), InlineKeyboardButton("📂 Oracle", callback_data="tpl_ora"))
        markup.row(InlineKeyboardButton("📂 Root", callback_data="tpl_root"), InlineKeyboardButton("⚙️ Manual", callback_data="tpl_man"))
        bot.edit_message_text("🚀 <b>PLANTILLAS:</b>", chat_id, msg_id, reply_markup=markup, parse_mode="HTML")
    
    elif data.startswith("tpl_"):
        temp_vps[uid] = {"template": data.split("_")[1]}
        msg = bot.send_message(chat_id, "🏷️ <b>Nombre para este VPS:</b>", parse_mode="HTML"); bot.register_next_step_handler(msg, v_step1_name)
    
    elif data.startswith("v_del_"):
        delete_vps(data.split("_")[2], uid)
        bot.send_message(chat_id, "✅ VPS eliminada."); send_main_menu(call.message, uid, edit=True)
    
    elif data == "back": send_main_menu(call.message, uid, edit=True)
    
    elif data.startswith("v_cu_"):
        temp_creation[uid] = {"vid": data.split("_")[2]}
        msg = bot.send_message(chat_id, "👤 <b>User SSH:</b>", parse_mode="HTML"); bot.register_next_step_handler(msg, cu_step1)

# --- STEPS (OPTIMIZADOS) ---
def u_edit_final(m):
    uid = m.from_user.id; data = temp_edit.get(uid); pw = m.text
    if not data: return
    def run_edit():
        v = get_vps_by_id(data['vid'])
        bot.send_message(m.chat.id, f"⏳ <b>Cambiando contraseña de {data['un']}...</b>", parse_mode="HTML")
        ok, out, err = ssh_execute_master(v, [f"echo '{data['un']}:{pw}' | chpasswd"])
        if ok: bot.send_message(m.chat.id, f"✅ Contraseña de <code>{data['un']}</code> actualizada.", parse_mode="HTML")
        else: bot.send_message(m.chat.id, f"❌ Error: {err}")
    executor.submit(run_edit)

def step_p_admin_1(m):
    try:
        duration = int(m.text); key = add_membership_key(duration)
        bot.send_message(m.chat.id, f"✅ <b>KEY VIP:</b> <code>{key}</code>", parse_mode="HTML")
    except: bot.send_message(m.chat.id, "❌ Valor inválido.")

def cu_step1(m): temp_creation[m.from_user.id]["un"] = m.text; msg = bot.send_message(m.chat.id, "🔐 <b>Pass:</b>", parse_mode="HTML"); bot.register_next_step_handler(msg, cu_step2)
def cu_step2(m): temp_creation[m.from_user.id]["pw"] = m.text; msg = bot.send_message(m.chat.id, "📅 <b>Días:</b>", parse_mode="HTML"); bot.register_next_step_handler(msg, cu_step3)
def cu_step3(m): 
    try:
        temp_creation[m.from_user.id]["ds"] = int(m.text)
        msg = bot.send_message(m.chat.id, "🔄 <b>Límite:</b>", parse_mode="HTML"); bot.register_next_step_handler(msg, cu_final)
    except: bot.send_message(m.chat.id, "❌ Error número."); send_main_menu(m, m.from_user.id)

def cu_final(m):
    uid = m.from_user.id; limit = m.text
    def async_cu():
        try:
            lim = int(limit); data = temp_creation.get(uid); v = get_vps_by_id(data['vid'])
            if not v: return
            pre = "sudo " if v['use_sudo'] else ""
            bot.send_message(m.chat.id, "⏳ <b>Configurando en VPS remota...</b>", parse_mode="HTML")
            cmds = [
                f"grep -q '/bin/false' /etc/shells || echo '/bin/false' | {pre}tee -a /etc/shells",
                f"useradd -e $(date -d '{data['ds']} days' +%Y-%m-%d) -s /bin/false -M {data['un']}",
                f"echo '{data['un']}:{data['pw']}' | chpasswd",
                f"mkdir -p /etc/gaming_vps",
                f"echo '{lim}' | tee /etc/gaming_vps/{data['un']}.limit",
                f"systemctl restart sshd 2>/dev/null", f"systemctl restart dropbear 2>/dev/null"
            ]
            ok, out, err = ssh_execute_master(v, cmds)
            if ok: bot.send_message(m.chat.id, f"✅ <b>CREADO:</b> <code>{data['un']}</code>", parse_mode="HTML")
            else: bot.send_message(m.chat.id, f"❌ Error: {err}")
        except: bot.send_message(m.chat.id, "❌ Error en límite.")
    executor.submit(async_cu)

def v_step1_name(m): temp_vps[m.from_user.id]["n"] = m.text; msg = bot.send_message(m.chat.id, "🌐 <b>IP:</b>", parse_mode="HTML"); bot.register_next_step_handler(msg, v_step2_ip)
def v_step2_ip(m):
    uid = m.from_user.id; temp_vps[uid]["i"] = m.text; tpl = temp_vps[uid]["template"]
    if tpl in ["aws", "ora"]:
        temp_vps[uid]["u"] = "ubuntu"; temp_vps[uid]["auth_type"] = "key"
        bot.send_message(m.chat.id, "📂 <b>Sube llave .pem:</b>", parse_mode="HTML")
    elif tpl == "root":
        temp_vps[uid]["u"] = "root"; temp_vps[uid]["auth_type"] = "pass"
        msg = bot.send_message(m.chat.id, "🔑 <b>Pass Root:</b>", parse_mode="HTML"); bot.register_next_step_handler(msg, v_step_pass_direct)
    else:
        msg = bot.send_message(m.chat.id, "👤 <b>User:</b>", parse_mode="HTML"); bot.register_next_step_handler(msg, v_step_user_manual)

def v_step_user_manual(m): temp_vps[m.from_user.id]["u"] = m.text; msg = bot.send_message(m.chat.id, "🔑 <b>Pass:</b>", parse_mode="HTML"); bot.register_next_step_handler(msg, v_step_pass_direct)

@bot.message_handler(content_types=['document'])
def handle_ssh_final(message):
    uid = message.from_user.id
    if uid in temp_vps and temp_vps[uid].get("auth_type") == "key":
        try:
            f = bot.download_file(bot.get_file(message.document.file_id).file_path)
            temp_vps[uid]["val"] = f.decode('utf-8')
            sudo_val = 1 if temp_vps[uid].get("template") in ["aws", "ora"] else 0
            add_vps(uid, temp_vps[uid]['n'], temp_vps[uid]['i'], temp_vps[uid]['u'], 'key', temp_vps[uid]['val'], sudo_val)
            bot.send_message(message.chat.id, "✅ <b>VPS Registrada.</b>", parse_mode="HTML"); send_main_menu(message, uid)
        except Exception as e: bot.send_message(message.chat.id, f"❌ Error: {e}")

def v_step_pass_direct(m): 
    uid = m.from_user.id; d = temp_vps.get(uid); add_vps(uid, d['n'], d['i'], d['u'], 'pass', m.text, 0)
    bot.send_message(m.chat.id, "✅ <b>VPS Registrada.</b>", parse_mode="HTML"); send_main_menu(m, uid)

@bot.message_handler(func=lambda m: m.text and m.text.startswith(".cmd"))
def handle_cmd_raw(m):
    if m.from_user.id != ADMIN_ID: return
    cmd = m.text[5:].strip()
    def run_cmd():
        try:
            p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, err = p.communicate(); res = (out.decode() + err.decode()).strip() or "✅ OK"
            if len(res) > 3800:
                f = io.BytesIO(res.encode()); f.name = "out.txt"
                bot.send_document(m.chat.id, f)
            else: bot.reply_to(m, f"<code>{html.escape(res)}</code>", parse_mode="HTML")
        except Exception as e: bot.reply_to(m, str(e))
    executor.submit(run_cmd)

if __name__ == '__main__':
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()
    print(f"--- HYPER-SONIC {VERSION} ACTIVO ---")
    while True:
        try: bot.polling(non_stop=True, interval=1, timeout=50)
        except Exception as e: print(f"Crash: {e}"); time.sleep(5)
