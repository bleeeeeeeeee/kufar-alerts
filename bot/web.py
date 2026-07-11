from flask import Flask
import threading

app = Flask(__name__)

@app.route('/')
def health():
    return "Bot is running!", 200

@app.route('/health')
def health_check():
    return "OK", 200

def start_web():
    # Запускаем Flask-сервер на порту 10000
    app.run(host='0.0.0.0', port=10000, debug=False, use_reloader=False)

def run_web_in_thread():
    thread = threading.Thread(target=start_web, daemon=True)
    thread.start()