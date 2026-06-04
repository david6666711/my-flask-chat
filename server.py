from flask import Flask, render_template, request, redirect, url_for, session, Response, jsonify
from flask_sock import Sock
from flask_sqlalchemy import SQLAlchemy
import json
import threading
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'supersecretkey123'

app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///local_chat.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
sock = Sock(app)

# username -> websocket
clients = {}
clients_lock = threading.Lock()

ADMIN_PASSWORD = 'admin123'

# --- МОДЕЛИ ---

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), nullable=False)
    message = db.Column(db.Text, nullable=True)
    image = db.Column(db.Text, nullable=True)
    time = db.Column(db.String(10), nullable=False)

class BannedUser(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    reason = db.Column(db.String(200), nullable=True)
    banned_at = db.Column(db.String(20), nullable=False)

with app.app_context():
    db.create_all()

# --- УТИЛИТЫ ---

def is_banned(username):
    return BannedUser.query.filter_by(username=username).first() is not None

def broadcast(data, exclude=None):
    dead = []
    with clients_lock:
        for uname, ws in clients.items():
            if uname == exclude:
                continue
            try:
                ws.send(json.dumps(data))
            except:
                dead.append(uname)
        for u in dead:
            clients.pop(u, None)

def online_list():
    with clients_lock:
        return list(clients.keys())

# --- WEBSOCKET ---

@sock.route('/ws')
def chat(ws):
    username = None
    try:
        # Первый пакет — приветствие с именем
        raw = ws.receive()
        if raw is None:
            return
        init = json.loads(raw)
        username = init.get('username', 'Аноним')[:20]

        # Проверка бана
        if is_banned(username):
            ws.send(json.dumps({'system': '🚫 Вы заблокированы администратором'}))
            return

        with clients_lock:
            clients[username] = ws

        # Отправить последние 50 сообщений
        db_messages = Message.query.order_by(Message.id.desc()).limit(50).all()
        for msg in reversed(db_messages):
            try:
                ws.send(json.dumps({
                    'username': msg.username,
                    'message': msg.message,
                    'image': msg.image,
                    'time': msg.time
                }))
            except:
                break

        # Уведомить всех о входе
        broadcast({'system': f'👤 {username} вошёл в чат'}, exclude=username)
        # Обновить список онлайн
        broadcast({'online': online_list()})

        while True:
            data = ws.receive()
            if data is None:
                break
            if is_banned(username):
                ws.send(json.dumps({'system': '🚫 Вы заблокированы'}))
                break
            try:
                packet = json.loads(data)
                packet['username'] = username
                packet['time'] = datetime.now().strftime('%H:%M')
                new_msg = Message(
                    username=username,
                    message=packet.get('message', ''),
                    image=packet.get('image', None),
                    time=packet['time']
                )
                db.session.add(new_msg)
                db.session.commit()
                broadcast(packet)
            except Exception as e:
                print(f"Ошибка: {e}")

    finally:
        if username:
            with clients_lock:
                clients.pop(username, None)
            broadcast({'system': f'👤 {username} покинул чат'})
            broadcast({'online': online_list()})

# --- ОСНОВНЫЕ МАРШРУТЫ ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/sitemap.xml')
def sitemap():
    xml = '''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://my-flask-chat-wxxd.onrender.com/</loc>
  <changefreq>daily</changefreq><priority>1.0</priority></url>
</urlset>'''
    return Response(xml, mimetype='application/xml')

@app.route('/robots.txt')
def robots():
    return Response('User-agent: *\nAllow: /\nSitemap: https://my-flask-chat-wxxd.onrender.com/sitemap.xml', mimetype='text/plain')

# --- АДМИНКА ---

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['admin'] = True
            return redirect(url_for('admin'))
        return render_template('admin_login.html', error='Неверный пароль')
    if not session.get('admin'):
        return render_template('admin_login.html', error=None)
    messages_list = Message.query.order_by(Message.id.desc()).all()
    banned_list = BannedUser.query.all()
    return render_template('admin.html',
        messages=messages_list,
        banned=banned_list,
        online=online_list(),
        online_count=len(online_list())
    )

@app.route('/admin/delete/<int:idx>', methods=['POST'])
def admin_delete(idx):
    if not session.get('admin'): return redirect(url_for('admin'))
    msg = Message.query.get(idx)
    if msg:
        db.session.delete(msg)
        db.session.commit()
    return redirect(url_for('admin'))

@app.route('/admin/clear', methods=['POST'])
def admin_clear():
    if not session.get('admin'): return redirect(url_for('admin'))
    db.session.query(Message).delete()
    db.session.commit()
    broadcast({'system': '🗑 Чат очищен администратором'})
    return redirect(url_for('admin'))

@app.route('/admin/ban/<username>', methods=['POST'])
def admin_ban(username):
    if not session.get('admin'): return redirect(url_for('admin'))
    reason = request.form.get('reason', 'Нарушение правил')
    if not is_banned(username):
        db.session.add(BannedUser(
            username=username,
            reason=reason,
            banned_at=datetime.now().strftime('%d.%m.%Y %H:%M')
        ))
        db.session.commit()
    # Кикнуть если онлайн
    with clients_lock:
        ws = clients.get(username)
    if ws:
        try:
            ws.send(json.dumps({'system': f'🚫 Вы заблокированы. Причина: {reason}'}))
        except:
            pass
    broadcast({'system': f'🚫 {username} заблокирован администратором'})
    return redirect(url_for('admin'))

@app.route('/admin/unban/<username>', methods=['POST'])
def admin_unban(username):
    if not session.get('admin'): return redirect(url_for('admin'))
    BannedUser.query.filter_by(username=username).delete()
    db.session.commit()
    return redirect(url_for('admin'))

@app.route('/admin/kick/<username>', methods=['POST'])
def admin_kick(username):
    if not session.get('admin'): return redirect(url_for('admin'))
    with clients_lock:
        ws = clients.get(username)
    if ws:
        try:
            ws.send(json.dumps({'system': '⚠️ Вас кикнул администратор'}))
        except:
            pass
    broadcast({'system': f'⚠️ {username} кикнут администратором'})
    return redirect(url_for('admin'))

@app.route('/admin/announce', methods=['POST'])
def admin_announce():
    if not session.get('admin'): return redirect(url_for('admin'))
    text = request.form.get('text', '').strip()
    if text:
        broadcast({'system': f'📢 {text}'})
    return redirect(url_for('admin'))

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin', None)
    return redirect(url_for('admin'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
