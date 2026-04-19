import requests
import pandas as pd
from datetime import datetime, timedelta
import os, webbrowser, time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs

# --- НАСТРОЙКИ ---
API_URL = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN, PASSWORD = "abvprom", "29328"
TARGET_FILE = "CAN_пробег_датчики_06_02_2026.xlsx"
PORT = 8080

# --- ЛОГИКА API ---
def connect_with_retry():
    """Попытка входа (3 раза)"""
    for i in range(3):
        try:
            r = requests.get(f"{API_URL}/connect", 
                             params={'login': LOGIN, 'password': PASSWORD, 'timezone': '3'}, 
                             timeout=15)
            if r.status_code == 200:
                sid = r.headers.get('sessionid') or r.json().get('sessionid')
                if sid: return sid
        except: time.sleep(1); continue
    return None

def get_api(sid, endp, pars):
    """Общая функция для запросов к API"""
    try:
        headers = {'SessionId': sid}
        r = requests.get(f"{API_URL}/{endp}", headers=headers, params=pars, timeout=20)
        return r.json() if r.status_code == 200 else {}
    except: return {}

def find_data(sid, oid, sid_val, odo_target, date_str, mode="start"):
    """
    mode="start": берет начало дня, если одометр не указан
    mode="end": берет конец дня, если одометр не указан
    """
    p = {'oid': oid, 'slist': f's{int(float(sid_val))}', 'from': f"{date_str} 00:00:00", 'to': f"{date_str} 23:59:59"}
    res = get_api(sid, "objdata", p)
    recs = res.get('obj_data', {}).get('records', [])
    
    if not recs or not isinstance(recs, list): return None, None
    
    # Фильтруем только записи с числами
    valid = [r for r in recs if len(r) > 1 and str(r[1]).replace('.','',1).isdigit()]
    if not valid: return None, None
    
    # Если одометр НЕ введен
    if not odo_target or str(odo_target).strip() == "":
        best = valid[0] if mode == "start" else valid[-1]
    else:
        # Если одометр ВВЕДЕН - ищем ближайшее значение
        best = min(valid, key=lambda x: abs(float(x[1]) - float(odo_target)))
        
    return best[0], float(best[1])

def get_extra(sid, oid, t):
    fuel, addr = 0.0, "Не визначено"
    if not t: return fuel, addr
    
    # Топливо
    res_f = get_api(sid, "objdata", {'oid': oid, 'from': t, 'to': t})
    rec = res_f.get('obj_data', {}).get('records', [])
    if rec and len(rec[0]) > 2: 
        try: fuel = round(float(rec[0][2]), 1)
        except: fuel = 0.0
    
    # Адрес
    dt = datetime.strptime(t, '%Y-%m-%d %H:%M:%S')
    tr = get_api(sid, "track", {'oid': oid, 'from': (dt-timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S'), 'to': (dt+timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')})
    pts = tr.get('track', [])
    if pts:
        try:
            headers = {'SessionId': sid}
            a = requests.get(f"{API_URL}/getaddress", headers=headers, params={'lat': pts[0]['lat'], 'lon': pts[0]['lon']}, timeout=10)
            addr = a.text.strip().strip('"')
        except: pass
    return fuel, addr

# --- СЕРВЕР ---
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        opts = "".join([f"<option value='{i}'>{r['Номер авто']} ({r['ФИО']})</option>" for i, r in v_df.iterrows()])
        html = f"""<html><head><meta charset="UTF-8"><style>
            body{{font-family:sans-serif;padding:40px;background:#f4f7f9}}
            .card{{background:#fff;padding:25px;border-radius:10px;width:400px;margin:auto;box-shadow:0 2px 15px rgba(0,0,0,0.1)}}
            input,select,button{{width:100%;margin:10px 0;padding:12px;border:1px solid #ccc;border-radius:5px;box-sizing:border-box}}
            button{{background:#007bff;color:#fff;border:none;font-weight:bold;cursor:pointer}}
            label{{font-size:13px;font-weight:bold;color:#555}}
        </style></head><body><div class="card">
            <h2 style="text-align:center">Путевой Лист</h2>
            <form action="/gen" method="POST">
                <label>Автомобіль:</label>
                <select name="idx">{opts}</select>
                <label>Виїзд:</label>
                <input type="date" name="d1" required>
                <input type="number" step="0.1" name="o1" placeholder="Одометр старт (пусто = початок дня)">
                <label>Повернення:</label>
                <input type="date" name="d2" required>
                <input type="number" step="0.1" name="o2" placeholder="Одометр фініш (пусто = кінець дня)">
                <button type="submit">Сформировать</button>
            </form>
        </div></body></html>"""
        self.wfile.write(html.encode('utf-8'))

    def do_POST(self):
        try:
            length = int(self.headers['Content-Length'])
            post_data = parse_qs(self.rfile.read(length).decode('utf-8'))
            car = v_df.iloc[int(post_data['idx'][0])]
            
            sid = connect_with_retry()
            if not sid:
                self.send_error_page("Ошибка API: Не удалось войти в Mobiteam. Проверьте логин/пароль.")
                return

            # Получаем значения одометра (могут быть пустыми)
            o1_val = post_data.get('o1', [''])[0]
            o2_val = post_data.get('o2', [''])[0]

            t1, od1 = find_data(sid, car['ID объекта'], car['SID'], o1_val, post_data['d1'][0], "start")
            t2, od2 = find_data(sid, car['ID объекта'], car['SID'], o2_val, post_data['d2'][0], "end")

            if od1 is None or od2 is None:
                self.send_error_page("Данные за этот период не найдены. Машина могла не выезжать.")
                return

            f1, a1 = get_extra(sid, car['ID объекта'], t1)
            f2, a2 = get_extra(sid, car['ID объекта'], t2)
            
            dist = round(od2 - od1, 1)
            spent = round(f1 - f2, 1)
            rate = round(spent/dist*100, 2) if dist > 0 else 0

            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            
            res_html = f"""<html><head><meta charset="UTF-8"><style>
                body{{font-family:serif;padding:30px}}
                .box{{border:2px solid #000;padding:25px;width:190mm;margin:auto}}
                table{{width:100%;border-collapse:collapse;margin:20px 0}}
                td,th{{border:1px solid #000;padding:10px;text-align:left}}
                button{{padding:10px 20px;cursor:pointer}}
            </style></head><body><div class="box">
                <h3 style="text-align:center">ПОДОРОЖНІЙ ЛИСТ</h3>
                <p><b>Авто:</b> {car['Номер авто']} | <b>Водій:</b> {car['ФИО']}</p>
                <table>
                    <tr><th>Параметр</th><th>Выезд</th><th>Возврат</th></tr>
                    <tr><td>Время</td><td>{t1}</td><td>{t2}</td></tr>
                    <tr><td>Одометр</td><td>{od1} км</td><td>{od2} км</td></tr>
                    <tr><td>Топливо</td><td>{f1} л</td><td>{f2} л</td></tr>
                    <tr><td>Адрес</td><td>{a1}</td><td>{a2}</td></tr>
                </table>
                <p><b>Пробег:</b> {dist} км | <b>Расход:</b> {spent} л ({rate} л/100км)</p>
                <button onclick="window.print()">Печать</button>
                <button onclick="history.back()">Назад</button>
            </div></body></html>"""
            self.wfile.write(res_html.encode('utf-8'))
        except Exception as e:
            self.send_error_page(f"Системная ошибка: {e}")

    def send_error_page(self, msg):
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(f"<h3>❌ {msg}</h3><button onclick='history.back()'>Назад</button>".encode('utf-8'))

def main():
    global v_df
    if not os.path.exists(TARGET_FILE):
        print(f"Файл {TARGET_FILE} не найден!")
        return
    v_df = pd.read_excel(TARGET_FILE)
    print(f"✅ Сервер запущен: http://localhost:{PORT}")
    webbrowser.open(f"http://localhost:{PORT}")
    HTTPServer(('localhost', PORT), Handler).serve_forever()

if __name__ == "__main__": main()