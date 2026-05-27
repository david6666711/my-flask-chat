from flask import Flask, render_template, request, redirect, url_for, session
from flask_sock import Sock
import json
import threading
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'supersecretkey123'
sock = Sock(app)

messages = []
clients = set()
clients_lock = threading.Lock()

ADMIN_PASSWORD = 'admin123'  # Поменяй на свой пароль!

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
    for msg in messages[-50:]:
        try:
            ws.send(json.dumps(msg))
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
                messages.append(packet)
                broadcast(packet)
            except:
                pass
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
    return render_template('admin.html', messages=messages, clients=len(clients))

@app.route('/admin/clear', methods=['POST'])
def admin_clear():
    if not session.get('admin'):
        return redirect(url_for('admin'))
    messages.clear()
    broadcast({'system': 'Чат очищен администратором'})
    return redirect(url_for('admin'))

@app.route('/admin/delete/<int:idx>', methods=['POST'])
def admin_delete(idx):
    if not session.get('admin'):
        return redirect(url_for('admin'))
    if 0 <= idx < len(messages):
        messages.pop(idx)
    return redirect(url_for('admin'))

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin', None)
    return redirect(url_for('admin'))

if __name__ == '__main__':
    print("=" * 40)
    print("  Сервер запущен!")
    print("  Сайт:    http://localhost:5000")
    print("  Сеть:    http://192.168.10.133:5000")
    print("  Админка: http://localhost:5000/admin")
    print("=" * 40)
    app.run(host='0.0.0.0', port=5000, debug=False)
