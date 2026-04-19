import requests
import pandas as pd
import sqlite3
import webbrowser
import time
from datetime import timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

# --- НАСТРОЙКИ ---
API_URL = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN = "abvprom"
PASSWORD = "29328"
TARGET_FILE = r"c:/Users/snltv/Desktop/ii/putevoi list/CAN_пробег_датчики_06_02_2026.xlsx"
DB_NAME = "abv_fuel_in_out_comsum.db" 
PORT = 8080

# --- БД ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS abv_fuel_in_out_comsum (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            obj_id INTEGER,
            vehicle_name TEXT,
            report_date TEXT,
            begin_level REAL,
            refuels REAL,
            end_level REAL,
            consumption REAL,
            UNIQUE(obj_id, report_date)
        )
    ''')
    conn.commit()
    conn.close()

def save_to_db(data_list):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.executemany('''
        INSERT OR REPLACE INTO abv_fuel_in_out_comsum 
        (obj_id, vehicle_name, report_date, begin_level, refuels, end_level, consumption)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', data_list)
    conn.commit()
    conn.close()

# --- API ---
def get_sid():
    params = {'login': LOGIN, 'password': PASSWORD, 'timezone': '3', 'lang': 'ru-ru'}
    try:
        res = requests.get(f"{API_URL}/connect", params=params, timeout=15)
        return res.headers.get('sessionid') or res.headers.get('SessionId')
    except: return None

def get_fuel_data(sid, oid, d_from, d_to):
    """Получает данные, даже если не было заправок"""
    headers = {'SessionId': sid, 'Accept': 'application/json'}
    params = {'date_from': d_from, 'date_to': d_to, 'objuids': str(oid)}
    try:
        res = requests.get(f"{API_URL}/getobjectsfuelinfo", headers=headers, params=params, timeout=20)
        if res.status_code == 200:
            data = res.json()
            if not data: return None
            
            obj_data = data[0]
            # Если есть датчики — берем лучший
            if obj_data.get('sensors'):
                best = sorted(obj_data['sensors'], key=lambda x: float(x.get('summ_refuelings', 0)), reverse=True)[0]
                return {
                    'b': round(float(best.get('beginLevel', 0)), 1),
                    'r': round(float(best.get('summ_refuelings', 0)), 1),
                    'e': round(float(best.get('endLevel', 0)), 1)
                }
            # Если датчиков в списке нет (не было заправок), берем общие уровни объекта
            else:
                return {
                    'b': round(float(obj_data.get('beginLevel', 0)), 1),
                    'r': 0.0,
                    'e': round(float(obj_data.get('endLevel', 0)), 1)
                }
    except: return None
    return None

# --- SERVER ---
class WebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = urlparse(self.path).query
        params = parse_qs(query)
        
        try:
            df = pd.read_excel(TARGET_FILE).dropna(subset=['ID объекта'])
            df['ID объекта'] = df['ID объекта'].astype(int)
        except Exception as e:
            self.send_error(500, f"Excel error: {e}")
            return

        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()

        html = """<html><head><style>
            body { font-family: 'Segoe UI', sans-serif; margin: 40px; background: #f0f2f5; }
            .container { background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.08); max-width: 1100px; margin: auto; }
            table { width: 100%; border-collapse: collapse; margin-top: 20px; }
            th, td { border: 1px solid #ddd; padding: 10px; text-align: center; }
            th { background: #1a73e8; color: white; }
            .date-col { background: #f8f9fa; font-weight: bold; }
            .btn { background: #1a73e8; color: white; border: none; padding: 10px 20px; border-radius: 4px; cursor: pointer; font-weight: bold; }
        </style></head><body><div class='container'>
            <h2>⛽ Ежедневный отчет по топливу (Все дни)</h2>
            <form method="GET">
                <select name="oid"><option value="all">-- Все авто --</option>"""
        for _, row in df.iterrows():
            html += f'<option value="{row["ID объекта"]}">{row["Номер авто"]}</option>'
        html += """</select> <input type="date" name="df" required> <input type="date" name="dt" required>
                <button type="submit" class="btn">Сформировать</button></form>"""

        if 'df' in params and 'dt' in params:
            start_dt = pd.to_datetime(params['df'][0])
            end_dt = pd.to_datetime(params['dt'][0])
            sid = get_sid()
            
            if sid:
                selected = params['oid'][0]
                target_rows = df[df['ID объекта'] == int(selected)] if selected != 'all' else df
                db_data = []

                html += "<table><tr><th>Дата</th><th>Автомобиль</th><th>Начало</th><th>Заправки</th><th>Конец</th><th>Расход</th></tr>"

                curr = start_dt
                while curr <= end_dt:
                    d_str = curr.strftime('%Y-%m-%d')
                    print(f"📡 Обработка {d_str}...")
                    
                    for _, row in target_rows.iterrows():
                        oid = int(row['ID объекта'])
                        res = get_fuel_data(sid, oid, d_str + " 00:00:00", d_str + " 23:59:59")
                        
                        if res:
                            cons = round((res['b'] + res['r']) - res['e'], 1)
                            if cons < 0: cons = 0
                            
                            db_data.append((oid, str(row['Номер авто']), d_str, res['b'], res['r'], res['e'], cons))
                            html += f"<tr><td>{d_str}</td><td>{row['Номер авто']}</td><td>{res['b']}</td><td>{res['r']}</td><td>{res['e']}</td><td>{cons}</td></tr>"
                        else:
                            html += f"<tr><td>{d_str}</td><td>{row['Номер авто']}</td><td colspan='4'>Нет данных в GPS</td></tr>"
                    
                    curr += timedelta(days=1)
                    time.sleep(0.05)

                if db_data:
                    save_to_db(db_data)
                    html += f"<h4 style='color:green'>✅ Данные за период сохранены в {DB_NAME}</h4>"
                html += "</table>"

        html += "</div></body></html>"
        self.wfile.write(html.encode('utf-8'))

if __name__ == "__main__":
    init_db()
    print(f"🌍 Сервер запущен: http://localhost:{PORT}")
    webbrowser.open(f"http://localhost:{PORT}")
    HTTPServer(('localhost', PORT), WebHandler).serve_forever()