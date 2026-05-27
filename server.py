import os
import json
import threading
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session
from flask_sock import Sock

app = Flask(__name__)
# Секретный ключ нужен для работы сессий (входа в админку)
app.secret_key = os.environ.get('SECRET_KEY', 'supersecretkey123')
sock = Sock(app)

messages = []
clients = set()
clients_lock = threading.Lock()

ADMIN_PASSWORD = 'admin123'  # Поменяй на свой надежный пароль!

def broadcast(data):
    """Рассылка сообщения абсолютно всем активным пользователям чата"""
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
    """Обработчик WebSocket-соединения чата"""
    with clients_lock:
        clients.add(ws)
    
    # При входе нового пользователя отправляем ему историю (последние 50 сообщений)
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
                # Сервер сам ставит точное время отправки сообщения
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
    """Главная страница чата"""
    return render_template('index.html')

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    """Панель администратора"""
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['admin'] = True
            return redirect(url_for('admin'))
        return render_template('admin_login.html', error='Неверный пароль')
    if not session.get('admin'):
        return render_template('admin_login.html', error=None)
    
    # Передаем сообщения инвертированными или списком с индексами для удаления
    return render_template('admin.html', messages=messages, clients=len(clients))

@app.route('/admin/clear', methods=['POST'])
def admin_clear():
    """Полная очистка истории чата"""
    if not session.get('admin'):
        return redirect(url_for('admin'))
    messages.clear()
    # Отправляем сигнал фронтенду мгновенно очистить экраны пользователей
    broadcast({'system': 'Чат очищен администратором'})
    return redirect(url_for('admin'))

@app.route('/admin/delete/<int:idx>', methods=['POST'])
def admin_delete(idx):
    """Удаление одного конкретного сообщения по его индексу"""
    if not session.get('admin'):
        return redirect(url_for('admin'))
    if 0 <= idx < len(messages):
        messages.pop(idx)
    return redirect(url_for('admin'))

@app.route('/admin/logout')
def admin_logout():
    """Выход из панели администратора"""
    session.pop('admin', None)
    return redirect(url_for('admin'))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Сервер запускается на порту {port}...")
    app.run(host='0.0.0.0', port=port, debug=False)
