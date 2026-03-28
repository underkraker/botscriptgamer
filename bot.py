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
from database import init_db, can_user_generate, generate_install_key, validate_and_burn_install_key, add_membership_key, redeem_membership, get_user, get_active_vps_ips, get_expiring_users, add_vps, get_user_vps, get_vps_by_id, delete_vps
from config import TOKEN, ADMIN_ID, VERSION, INSTALL_CMD, API_KEY

VERSION = "v12.0 Tactical Master ⚔️"
bot = telebot.TeleBot(TOKEN, threaded=True, num_threads=20) # Multihilo nativo activado
app = Flask(__name__)

# --- CONFIGURACIÓN DE AISLAMIENTO TOTAL ---
executor = ThreadPoolExecutor(max_workers=60)
user_locks = {}
vip_cache = {}

def get_cached_vip(uid):
    now = time.time()
    if uid in vip_cache:
        val, ts = vip_cache[uid]
        if now - ts < 120: return val
    val = can_user_generate(uid) or uid == ADMIN_ID
    vip_cache[uid] = (val, now)
    return val

def is_locked(uid):
    now = time.time()
    if uid in user_locks and now - user_locks[uid] < 0.8: return True
    user_locks[uid] = now
    return False

# --- MEMORIA VOLATIL ---
temp_vps = {}
temp_creation = {}
temp_edit = {}

# --- API VALIDACIÓN ---
@app.route('/api/validar', methods=['GET'])
def validar_key():
    key = request.args.get('key'); ip = request.remote_addr
    is_valid, creator_id, install_id = validate_and_burn_install_key(key, ip)
    if is_valid:
        creator = get_user(creator_id); c_username = creator['username'] if creator else "Admin"
        msg = f"✅ KEY: {key} | IP: {ip} | DUEÑO: @{c_username}"
        try: bot.send_message(ADMIN_ID, f"📩 <b>INSTALL:</b>\n{msg}", parse_mode="HTML")
        except: pass
        return jsonify({"status": "success", "msg": "valid", "owner": c_username}), 200
    return jsonify({"status": "error", "msg": "invalid"}), 403

def run_flask(): 
    try: app.run(host='0.0.0.0', port=5000)
    except Exception as e: print(f"Flask Error: {e}")

# --- MOTORES SSH AISLADOS ---
def ssh_connect_client(vps):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        if vps['auth_type'] == 'key':
            key_file = io.StringIO(vps['vps_key_content'])
            try: pkey = paramiko.RSAKey.from_private_key(key_file)
            except: 
                key_file.seek(0); pkey = paramiko.Ed25519Key.from_private_key(key_file)
            ssh.connect(vps['vps_ip'], username=vps['vps_user'], pkey=pkey, timeout=6)
        else:
            ssh.connect(vps['vps_ip'], username=vps['vps_user'], password=vps['vps_pass'], timeout=6)
        return ssh
    except: return None

def ssh_execute_master(vps, cmd_list):
    ssh = ssh_connect_client(vps)
    if not ssh: return False, "", "TimeOut Connection (6s)"
    try:
        pre = "sudo " if vps['use_sudo'] else ""
        full_cmd = " && ".join([c if any(x in c for x in ["grep","echo","tee"]) or pre in c else f"{pre}{c}" for c in cmd_list])
        stdin, stdout, stderr = ssh.exec_command(full_cmd)
        out = stdout.read().decode(); err = stderr.read().decode(); ssh.close()
        return True, out, err
    except Exception as e: return False, "", str(e)

# --- MENÚS ULTRA-ESTABLES ---
def get_main_markup(uid):
    is_vip = get_cached_vip(uid)
    markup = InlineKeyboardMarkup()
    if is_vip:
        markup.row(InlineKeyboardButton("🖥️ GESTIONAR VPS", callback_data="vps_list"))
        markup.row(InlineKeyboardButton("🔑 KEY VPS", callback_data="btn_key"), InlineKeyboardButton("🛰️ MONITOR", callback_data="btn_monitor"))
    markup.row(InlineKeyboardButton("👤 MI PERFIL", callback_data="btn_perfil"), InlineKeyboardButton("📚 GUÍAS", callback_data="btn_guias"))
    markup.row(InlineKeyboardButton("🛠️ SOPORTE", callback_data="btn_soporte"))
    if uid == ADMIN_ID: markup.row(InlineKeyboardButton("🎟️ CREAR VIP", callback_data="btn_p_admin"))
    return markup

def send_main_menu(chat_id, message_id, uid, edit=True):
    # Función de envío aislada
    def task():
        markup = get_main_markup(uid)
        msg = f"<b>🔥 MAESTRO UNDERKRAKER v12 🔥</b>\n━━━━━━━━━━━━━━━━━━━━\nPanel de Control Táctico.\n🚀 Selecciona una opción:"
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

@bot.callback_query_handler(func=lambda call: True)
def callback_master(call):
    uid, data = call.from_user.id, call.data
    chat_id, msg_id = call.message.chat.id, call.message.message_id
    
    try: bot.answer_callback_query(call.id)
    except: pass

    if is_locked(uid): return

    # --- TODA LA LÓGICA PASA A HILOS SECUNDARIOS ---
    if data == "vps_list":
        def run():
            vlist = get_user_vps(uid)
            markup = InlineKeyboardMarkup()
            for v in vlist: markup.row(InlineKeyboardButton(f"🌐 {v['vps_name']}", callback_data=f"v_view_{v['id']}"))
            markup.row(InlineKeyboardButton("➕ AÑADIR", callback_data="v_add_template"), InlineKeyboardButton("🏠 INICIO", callback_data="back"))
            bot.edit_message_text("🖥️ <b>TUS SERVIDORES:</b>", chat_id, msg_id, reply_markup=markup, parse_mode="HTML")
        executor.submit(run)
    
    elif data.startswith("v_view_"):
        vid = data.split("_")[2]
        def run():
            v = get_vps_by_id(vid)
            if not v: return
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("➕ USER SSH", callback_data=f"v_cu_{vid}"), InlineKeyboardButton("👥 CLIENTES", callback_data=f"v_lu_{vid}"))
            markup.row(InlineKeyboardButton("🗑️ BORRAR", callback_data=f"v_del_{vid}"), InlineKeyboardButton("🏠 INICIO", callback_data="back"))
            bot.edit_message_text(f"🖥️ <b>VPS:</b> {v['vps_name']}\n🌐 <b>IP:</b> <code>{v['vps_ip']}</code>", chat_id, msg_id, reply_markup=markup, parse_mode="HTML")
        executor.submit(run)

    elif data.startswith("v_lu_"):
        vid = data.split("_")[2]; v = get_vps_by_id(vid)
        bot.edit_message_text("⏳ <b>Leyendo VPS...</b>", chat_id, msg_id, parse_mode="HTML")
        def run():
            ok, out, err = ssh_execute_master(v, ["ls /etc/gaming_vps/*.limit"])
            if ok:
                users = [f.split("/")[-1].replace(".limit", "") for f in out.split() if ".limit" in f]
                markup = InlineKeyboardMarkup()
                for u in users: markup.row(InlineKeyboardButton(f"👤 {u}", callback_data=f"u_opt_{vid}_{u}"))
                markup.row(InlineKeyboardButton("🏠 INICIO", callback_data="back"))
                bot.edit_message_text(f"👥 <b>CLIENTES:</b>", chat_id, msg_id, reply_markup=markup, parse_mode="HTML")
            else: bot.edit_message_text(f"⚠️ {err}", chat_id, msg_id, reply_markup=InlineKeyboardMarkup().row(InlineKeyboardButton("🏠 INICIO", callback_data="back")), parse_mode="HTML")
        executor.submit(run)

    elif data.startswith("u_opt_"):
        vid, user = data.split("_")[2:4]
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("🗑️ BORRAR", callback_data=f"u_del_{vid}_{user}"), InlineKeyboardButton("✏️ PASS", callback_data=f"u_edit_{vid}_{user}"))
        markup.row(InlineKeyboardButton("🏠 INICIO", callback_data="back"))
        bot.edit_message_text(f"👤 <b>CLIENTE:</b> <code>{user}</code>", chat_id, msg_id, reply_markup=markup, parse_mode="HTML")

    elif data.startswith("u_del_"):
        vid, user = data.split("_")[2:4]; v = get_vps_by_id(vid)
        bot.edit_message_text(f"⏳ <b>Borrando...</b>", chat_id, msg_id, parse_mode="HTML")
        def run():
            ssh_execute_master(v, [f"userdel -f {user}", f"rm -f /etc/gaming_vps/{user}.limit"])
            bot.edit_message_text(f"✅ Borrado.", chat_id, msg_id, parse_mode="HTML")
            bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=InlineKeyboardMarkup().row(InlineKeyboardButton("🏠 INICIO", callback_data="back")))
        executor.submit(run)

    elif data == "back": 
        send_main_menu(chat_id, msg_id, uid, edit=True)

    # --- RESTO DE BOTONES ---
    elif data == "btn_perfil":
        def run():
            user = get_user(uid)
            st = "👑 ADMIN" if uid == ADMIN_ID else ("🌟 VIP" if user else "👤 BASE")
            bot.send_message(chat_id, f"👤 <b>PERFIL:</b>\n📌 Status: {st}", parse_mode="HTML")
        executor.submit(run)

    elif data == "btn_key":
        def run():
            if get_cached_vip(uid):
                k, c = generate_install_key(uid)
                bot.send_message(chat_id, f"🗝️ <code>{k}</code>\n\n<code>{INSTALL_CMD}</code>", parse_mode="HTML")
        executor.submit(run)

    elif data.startswith("v_add_template"):
        markup = InlineKeyboardMarkup().row(InlineKeyboardButton("📂 AWS", callback_data="tpl_aws"), InlineKeyboardButton("📂 Oracle", callback_data="tpl_ora")).row(InlineKeyboardButton("📂 Root", callback_data="tpl_root"), InlineKeyboardButton("🏠 INICIO", callback_data="back"))
        bot.edit_message_text("🚀 <b>PLANTILLAS:</b>", chat_id, msg_id, reply_markup=markup, parse_mode="HTML")
    
    elif data.startswith("tpl_"):
        temp_vps[uid] = {"template": data.split("_")[1]}
        msg = bot.send_message(chat_id, "🏷️ <b>Nombre:</b>", parse_mode="HTML"); bot.register_next_step_handler(msg, v_step1_name)
    
    elif data.startswith("v_del_"):
        def run():
            delete_vps(data.split("_")[2], uid)
            send_main_menu(chat_id, msg_id, uid, edit=True)
        executor.submit(run)
    
    elif data.startswith("v_cu_"):
        temp_creation[uid] = {"vid": data.split("_")[2]}
        msg = bot.send_message(chat_id, "👤 <b>User SSH:</b>", parse_mode="HTML"); bot.register_next_step_handler(msg, cu_step1)

# --- STEPS (v12.0) ---
def cu_step1(m): temp_creation[m.from_user.id]["un"] = m.text; msg = bot.send_message(m.chat.id, "🔐 <b>Pass:</b>", parse_mode="HTML"); bot.register_next_step_handler(msg, cu_step2)
def cu_step2(m): temp_creation[m.from_user.id]["pw"] = m.text; msg = bot.send_message(m.chat.id, "📅 <b>Días:</b>", parse_mode="HTML"); bot.register_next_step_handler(msg, cu_step3)
def cu_step3(m): 
    try: temp_creation[m.from_user.id]["ds"] = int(m.text); msg = bot.send_message(m.chat.id, "🔄 <b>Límite:</b>", parse_mode="HTML"); bot.register_next_step_handler(msg, cu_final)
    except: bot.send_message(m.chat.id, "❌ Error número."); send_main_menu(m.chat.id, 0, m.from_user.id, edit=False)

def cu_final(m):
    uid, limit = m.from_user.id, m.text
    def run():
        try:
            lim = int(limit); data = temp_creation.get(uid); v = get_vps_by_id(data['vid'])
            if not v: return
            bot.send_message(m.chat.id, "⏳ <b>Configurando...</b>")
            cmds = [f"useradd -e $(date -d '{data['ds']} days' +%Y-%m-%d) -s /bin/false -M {data['un']}", f"echo '{data['un']}:{data['pw']}' | chpasswd", f"echo '{lim}' | tee /etc/gaming_vps/{data['un']}.limit", f"systemctl restart sshd 2>/dev/null", f"systemctl restart dropbear 2>/dev/null"]
            ssh_execute_master(v, cmds)
            bot.send_message(m.chat.id, f"✅ <b>CREADO:</b> <code>{data['un']}</code>", parse_mode="HTML")
        except: bot.send_message(m.chat.id, "❌")
    executor.submit(run)

def v_step1_name(m): temp_vps[m.from_user.id]["n"] = m.text; msg = bot.send_message(m.chat.id, "🌐 <b>IP:</b>", parse_mode="HTML"); bot.register_next_step_handler(msg, v_step2_ip)
def v_step2_ip(m):
    uid, tpl = m.from_user.id, temp_vps[m.from_user.id]["template"]; temp_vps[uid]["i"] = m.text
    if tpl in ["aws", "ora"]:
        temp_vps[uid]["u"], temp_vps[uid]["auth_type"] = "ubuntu", "key"
        bot.send_message(m.chat.id, "📂 <b>Sube llave .pem:</b>", parse_mode="HTML")
    elif tpl == "root":
        temp_vps[uid]["u"], temp_vps[uid]["auth_type"] = "root", "pass"
        msg = bot.send_message(m.chat.id, "🔑 <b>Pass Root:</b>", parse_mode="HTML"); bot.register_next_step_handler(msg, v_step_pass_direct)
    else:
        msg = bot.send_message(m.chat.id, "👤 <b>User:</b>", parse_mode="HTML"); bot.register_next_step_handler(msg, v_step_user_manual)

def v_step_pass_direct(m): 
    uid, d = m.from_user.id, temp_vps.get(m.from_user.id); add_vps(uid, d['n'], d['i'], d['u'], 'pass', m.text, 0)
    bot.send_message(m.chat.id, "✅ <b>VPS Registrada.</b>", parse_mode="HTML"); send_main_menu(m.chat.id, 0, uid, edit=False)

if __name__ == '__main__':
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()
    print(f"--- TACTICAL MASTER {VERSION} ACTIVO ---")
    while True:
        try: bot.polling(non_stop=True, interval=1, timeout=60)
        except: time.sleep(5)
