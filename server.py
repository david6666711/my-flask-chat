from flask import Flask, render_template, request, redirect, url_for, session
from flask_sock import Sock
from flask_sqlalchemy import SQLAlchemy
from cryptography.fernet import Fernet
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

clients = set()
clients_lock = threading.Lock()

ADMIN_PASSWORD = 'admin123'

# Шифрование
ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY')
fernet = Fernet(ENCRYPTION_KEY.encode()) if ENCRYPTION_KEY else None

def encrypt(text):
    if not text or not fernet:
        return text
    return fernet.encrypt(text.encode()).decode()

def decrypt(text):
    if not text or not fernet:
        return text
    try:
        return fernet.decrypt(text.encode()).decode()
    except:
        return text  # старые незашифрованные сообщения вернём как есть

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), nullable=False)
    message = db.Column(db.Text, nullable=True)
    image = db.Column(db.Text, nullable=True)
    time = db.Column(db.String(10), nullable=False)

with app.app_context():
    db.create_all()

def broadcast(data):
    dead = set()
    with clients_lock:
        for client in clients:
            try:
                client.send(json.dumps(data))
            except:
                dead.add(client)
    for d in dead:
        clients.discard(d)

@sock.route('/ws')
def chat(ws):
    with clients_lock:
        clients.add(ws)

    db_messages = Message.query.order_by(Message.id.desc()).limit(50).all()
    for msg in reversed(db_messages):
        packet = {
            'username': msg.username,
            'message': decrypt(msg.message),
            'image': msg.image,
            'time': msg.time
        }
        try:
            ws.send(json.dumps(packet))
        except:
            break

    try:
        while True:
            data = ws.receive()
            if data is None:
                break
            try:
                packet = json.loads(data)
                packet['time'] = datetime.now().strftime('%H:%M')

                new_msg = Message(
                    username=packet.get('username', 'Аноним'),
                    message=encrypt(packet.get('message', '')),
                    image=packet.get('image', None),
                    time=packet['time']
                )
                db.session.add(new_msg)
                db.session.commit()

                broadcast(packet)
            except Exception as e:
                print(f"Ошибка сохранения: {e}")
    finally:
        with clients_lock:
            clients.discard(ws)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['admin'] = True
            return redirect(url_for('admin'))
        return render_template('admin_login.html', error='Неверный пароль')

    if not session.get('admin'):
        return render_template('admin_login.html', error=None)

    messages_list = Message.query.all()
    # Расшифровываем для отображения в админке
    for msg in messages_list:
        msg.message = decrypt(msg.message)

    return render_template('admin.html', messages=messages_list, clients=len(clients))

@app.route('/admin/clear', methods=['POST'])
def admin_clear():
    if not session.get('admin'):
        return redirect(url_for('admin'))
    db.session.query(Message).delete()
    db.session.commit()
    broadcast({'system': 'Чат очищен администратором'})
    return redirect(url_for('admin'))

@app.route('/admin/delete/<int:idx>', methods=['POST'])
def admin_delete(idx):
    if not session.get('admin'):
        return redirect(url_for('admin'))
    msg_to_delete = Message.query.get(idx)
    if msg_to_delete:
        db.session.delete(msg_to_delete)
        db.session.commit()
    return redirect(url_for('admin'))

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin', None)
    return redirect(url_for('admin'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
