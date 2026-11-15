import os, sqlite3, hashlib
from datetime import datetime, timezone
from flask import Flask, request, render_template, jsonify
import requests

app = Flask(__name__)
DB = os.environ.get("DATABASE_PATH", "visits.db")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
PUBLIC_URL = os.environ.get("PUBLIC_URL", "")

def db():
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS visits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        ip_masked TEXT,
        user_agent TEXT,
        consent INTEGER NOT NULL
    )""")
    return con

def mask_ip(ip):
    if not ip:
        return "не определён"
    parts = ip.split(".")
    if len(parts) == 4:
        return ".".join(parts[:3] + ["x"])
    if ":" in ip:
        return ip.split(":")[0] + ":…"
    return "скрыт"

def telegram(message):
    if BOT_TOKEN and CHAT_ID:
        try:
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": CHAT_ID, "text": message},
                timeout=8
            )
        except requests.RequestException:
            pass

@app.route("/")
def home():
    return """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Добро пожаловать</title>
</head>
<body style="background:#101116;color:white;font-family:Arial;text-align:center;padding:50px">
<h1>Добро пожаловать!</h1>
<p>Для отправки технической статистики посещения необходимо ваше согласие.</p>
<button onclick="sendConsent()">Согласиться и продолжить</button>
<button onclick="document.getElementById('status').innerText='Вы продолжили без аналитики'">Продолжить без аналитики</button>
<p id="status"></p>
<script>
async function sendConsent(){
 const r=await fetch('/visit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({consent:true})});
 const d=await r.json();
 document.getElementById('status').innerText=d.ok?'Спасибо!':'Ошибка отправки';
}
</script>
</body>
</html>
"""

@app.route("/visit", methods=["POST"])
def visit():
    data = request.get_json(silent=True) or {}
    if data.get("consent") is not True:
        return jsonify({"ok": False, "error": "consent_required"}), 400

    ip = request.headers.get("CF-Connecting-IP") or request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr
    ua = request.headers.get("User-Agent", "не определён")[:350]
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    masked = mask_ip(ip)

    con = db()
    con.execute(
        "INSERT INTO visits (created_at, ip_masked, user_agent, consent) VALUES (?, ?, ?, 1)",
        (now, masked, ua)
    )
    total = con.execute("SELECT COUNT(*) FROM visits").fetchone()[0]
    con.commit()
    con.close()

    # Геолокация намеренно не запрашивается у внешнего сервиса.
    # По IP можно определить лишь приблизительный регион, и только при отдельном
    # прозрачном подключении геосервиса с учётом его условий и уведомления посетителя.
    message = (
        "🔔 Новый согласившийся посетитель\n"
        f"🕒 Время: {now}\n"
        f"🌐 IP (маскирован): {masked}\n"
        f"📱 Браузер/устройство: {ua}\n"
        f"🔢 Всего переходов с согласием: {total}"
    )
    telegram(message)
    return jsonify({"ok": True, "total": total})

@app.route("/stats")
def stats():
    # Простая статистика доступна только по секретному ключу в переменной окружения.
    key = os.environ.get("STATS_KEY", "")
    if not key or request.args.get("key") != key:
        return "Forbidden", 403
    con = db()
    rows = con.execute(
        "SELECT created_at, ip_masked, user_agent FROM visits ORDER BY id DESC LIMIT 100"
    ).fetchall()
    total = con.execute("SELECT COUNT(*) FROM visits").fetchone()[0]
    con.close()
    return jsonify({"total": total, "recent_visits": [
        {"time": r[0], "ip_masked": r[1], "user_agent": r[2]} for r in rows
    ]})

@app.get("/health")
def health():
    return {"status": "ok"}

if __name__ == "__main__":
    from waitress import serve
    serve(app, host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
