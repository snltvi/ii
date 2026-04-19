import requests
import pandas as pd
import os
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
import time

# --- НАСТРОЙКИ ---
API_URL = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN = "abvprom"
PASSWORD = "29328"
TARGET_FILE = r"c:/Users/snltv/Desktop/ii/putevoi list/CAN_пробег_датчики_06_02_2026.xlsx"
PORT = 8080

def get_sid():
    headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
    params = {'login': LOGIN, 'password': PASSWORD, 'timezone': '3', 'lang': 'ru-ru'}
    try:
        res = requests.get(f"{API_URL}/connect", params=params, headers=headers, timeout=15)
        return res.headers.get('sessionid') or res.headers.get('SessionId')
    except: return None

def get_single_fuel_data(sid, oid, d_from, d_to):
    """Запрос данных по одной машине с защитой от таймаута"""
    headers = {'SessionId': sid, 'Accept': 'application/json'}
    params = {'date_from': d_from, 'date_to': d_to, 'objuids': str(oid)}
    try:
        # Увеличиваем таймаут и пробуем получить данные для одной машины
        res = requests.get(f"{API_URL}/getobjectsfuelinfo", headers=headers, params=params, timeout=20)
        if res.status_code == 200:
            data = res.json()
            return data[0]['sensors'] if data and 'sensors' in data[0] else []
    except:
        return []
    return []

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

        html = f"""
        <html><head><style>
            body {{ font-family: 'Segoe UI', sans-serif; margin: 40px; background: #f0f2f5; }}
            .container {{ background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.08); max-width: 1100px; margin: auto; }}
            .controls {{ margin: 20px 0; padding: 20px; background: #f8f9fa; border-radius: 8px; border: 1px solid #eef0f2; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 25px; background: white; }}
            th, td {{ border: 1px solid #dee2e6; padding: 12px; text-align: center; }}
            th {{ background-color: #1a73e8; color: white; }}
            tr:nth-child(even) {{ background-color: #f8f9fa; }}
            .val-refuel {{ color: #28a745; font-weight: bold; }}
            .val-cons {{ background: #fff3cd; font-weight: bold; color: #856404; }}
            select, input, button {{ padding: 10px; border: 1px solid #dadce0; border-radius: 4px; }}
            button {{ background: #1a73e8; color: white; border: none; font-weight: bold; cursor: pointer; }}
            .loader {{ color: #666; font-style: italic; margin-bottom: 10px; }}
        </style></head><body><div class="container">
            <h2>⛽ Топливный отчет (Пообъектный опрос)</h2>
            <div class="controls">
                <form method="GET">
                    <select name="oid"><option value="all">-- Все автомобили --</option>"""
        for _, row in df.iterrows():
            html += f'<option value="{row["ID объекта"]}">{row["Номер авто"]}</option>'
        html += """</select>
                    <input type="date" name="df" required>
                    <input type="date" name="dt" required>
                    <button type="submit">Сформировать</button>
                </form></div>"""

        if 'df' in params and 'dt' in params:
            d_from, d_to = params['df'][0] + " 00:00:00", params['dt'][0] + " 23:59:59"
            sid = get_sid()
            
            if sid:
                selected = params['oid'][0]
                target_rows = df[df['ID объекта'] == int(selected)] if selected != 'all' else df
                
                html += f"<h4>Период: {params['df'][0]} — {params['dt'][0]}</h4>"
                html += "<table><tr><th>Автомобиль</th><th>Начало, л</th><th>Заправки, л</th><th>Конец, л</th><th>РАСХОД, л</th></tr>"

                print(f"📡 Начинаю поочередный опрос {len(target_rows)} машин...")
                
                for _, row in target_rows.iterrows():
                    oid = int(row['ID объекта'])
                    sensors = get_single_fuel_data(sid, oid, d_from, d_to)
                    
                    if sensors:
                        # Берем датчик с макс. заправкой (обычно это основной)
                        best = sorted(sensors, key=lambda x: float(x.get('summ_refuelings', 0)), reverse=True)[0]
                        
                        b, r, e = float(best.get('beginLevel', 0)), float(best.get('summ_refuelings', 0)), float(best.get('endLevel', 0))
                        cons = round((b + r) - e, 1)

                        html += f"<tr><td style='text-align:left;'>{row['Номер авто']}</td><td>{round(b,1)}</td>"
                        html += f"<td class='val-refuel'>{round(r,1)}</td><td>{round(e,1)}</td>"
                        html += f"<td class='val-cons'>{max(0, cons)}</td></tr>"
                        print(f"✅ {row['Номер авто']} - Готово")
                    else:
                        html += f"<tr><td style='text-align:left;'>{row['Номер авто']}</td><td colspan='4'>Нет данных датчиков</td></tr>"
                        print(f"⚠️ {row['Номер авто']} - Нет данных")
                    
                    time.sleep(0.1) # Пауза для стабильности
                html += "</table>"
            else:
                html += "<p style='color:red'>Ошибка авторизации!</p>"

        html += "</div></body></html>"
        self.wfile.write(html.encode('utf-8'))

if __name__ == "__main__":
    server = HTTPServer(('localhost', PORT), WebHandler)
    print(f"🌍 Сервер запущен: http://localhost:{PORT}")
    webbrowser.open(f"http://localhost:{PORT}")
    server.serve_forever()