import requests
import pandas as pd
from datetime import datetime, timedelta
import os
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs

# ============================================================================
# НАСТРОЙКИ
# ============================================================================
API_URL = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN = "abvprom"
PASSWORD = "29328"
TARGET_FILE = "CAN_пробег_датчики_06_02_2026.xlsx"
PORT = 8080

# ============================================================================
# ЛОГИКА API
# ============================================================================

def connect_to_api():
    try:
        res = requests.get(f"{API_URL}/connect", 
                           params={'login': LOGIN, 'password': PASSWORD, 'timezone': '3'}, timeout=10)
        return res.headers.get('sessionid') or res.json().get('sessionid')
    except Exception as e:
        print(f"❌ Ошибка подключения: {e}")
        return None

def get_fuel_level(sid, oid, time_str):
    """Берет уровень топлива на конкретную секунду"""
    try:
        # Запрашиваем данные всех датчиков на конкретное время
        res = requests.get(f"{API_URL}/objdata", headers={'SessionId': sid}, 
                           params={'oid': oid, 'from': time_str, 'to': time_str}).json()
        records = res.get('obj_data', {}).get('records', [])
        if records:
            # Обычно топливо в CAN-данных идет 3-м или 4-м параметром (индекс 2 или 3)
            # Если в записи есть значение, возвращаем его
            val = records[0][2] if len(records[0]) > 2 else 0
            return float(val) if val else 0
    except: pass
    return 0

def get_total_fuelings(sid, oid, d1, d2):
    """Сумма всех заправок за период"""
    try:
        res = requests.get(f"{API_URL}/getobjectsreport", headers={'SessionId': sid}, 
                           params={'date_from': f"{d1} 00:00:00", 'date_to': f"{d2} 23:59:59", 
                                   'objuids': str(oid), 'split': 'none', 'param': 'fuelings'}).json()
        total = 0
        if res and res[0].get('periods'):
            for p in res[0]['periods']:
                total += float(p['prms'][0]['value'])
        return total
    except: return 0

def find_odo_and_time(sid, oid, sensor_id, target_odo, date_str):
    """Находит ближайшую запись по одометру и возвращает время"""
    params = {'oid': oid, 'slist': f's{sensor_id}', 'from': f"{date_str} 00:00:00", 'to': f"{date_str} 23:59:59"}
    try:
        res = requests.get(f"{API_URL}/objdata", headers={'SessionId': sid}, params=params).json()
        records = res.get('obj_data', {}).get('records', [])
        # Фильтруем пустые строки
        valid = [r for r in records if len(r) > 1 and str(r[1]).strip() != '']
        if not valid: return None, None
        
        best = min(valid, key=lambda x: abs(float(x[1]) - float(target_odo)))
        return best[0], float(best[1])
    except: return None, None

# ============================================================================
# ВЕБ-ИНТЕРФЕЙС
# ============================================================================

class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        
        options = "".join([f"<option value='{i}'>{row['Номер авто']} ({row['ФИО']})</option>" for i, row in vehicles_df.iterrows()])
        
        html = f"""
        <html><head><meta charset="UTF-8"><style>
            body {{ font-family: 'Segoe UI', sans-serif; background: #eef2f3; display: flex; justify-content: center; padding-top: 50px; }}
            .card {{ background: white; padding: 30px; border-radius: 15px; box-shadow: 0 8px 20px rgba(0,0,0,0.1); width: 450px; }}
            h2 {{ text-align: center; color: #333; margin-bottom: 20px; }}
            label {{ font-size: 13px; color: #666; font-weight: bold; }}
            input, select {{ width: 100%; padding: 12px; margin: 8px 0 18px; border: 1px solid #ddd; border-radius: 8px; box-sizing: border-box; }}
            button {{ width: 100%; padding: 15px; background: #007bff; color: white; border: none; border-radius: 8px; font-size: 16px; cursor: pointer; transition: 0.3s; }}
            button:hover {{ background: #0056b3; }}
        </style></head><body>
        <div class="card">
            <h2>Путевой лист + ГСМ</h2>
            <form action="/generate" method="POST">
                <label>Выберите ТС:</label>
                <select name="car_idx">{options}</select>
                <div style="background: #f9f9f9; padding: 15px; border-radius: 8px; margin-bottom: 15px;">
                    <label>ВЫЕЗД:</label>
                    <input type="date" name="d1" required>
                    <input type="number" step="0.1" name="o1" placeholder="Показания одометра" required>
                </div>
                <div style="background: #f9f9f9; padding: 15px; border-radius: 8px; margin-bottom: 15px;">
                    <label>ВОЗВРАТ:</label>
                    <input type="date" name="d2" required>
                    <input type="number" step="0.1" name="o2" placeholder="Показания одометра" required>
                </div>
                <button type="submit">Сформировать отчет</button>
            </form>
        </div></body></html>
        """
        self.wfile.write(html.encode())

    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = parse_qs(self.rfile.read(content_length).decode())
        
        car = vehicles_df.iloc[int(post_data['car_idx'][0])]
        sid = connect_to_api()
        
        # Данные по одометру и времени
        t1, odo1 = find_odo_and_time(sid, car['ID объекта'], car['SID'], post_data['o1'][0], post_data['d1'][0])
        t2, odo2 = find_odo_and_time(sid, car['ID объекта'], car['SID'], post_data['o2'][0], post_data['d2'][0])

        if not t1 or not t2:
            self.send_response(200); self.end_headers()
            self.wfile.write("<h3>❌ Ошибка: Данные одометра не найдены в системе за этот период.</h3>".encode()); return

        # Данные по топливу
        f1 = get_fuel_level(sid, car['ID объекта'], t1)
        f2 = get_fuel_level(sid, car['ID объекта'], t2)
        fuelings = get_total_fuelings(sid, car['ID объекта'], post_data['d1'][0], post_data['d2'][0])

        # Расчеты
        dist = round(odo2 - odo1, 1)
        spent = round((f1 + fuelings) - f2, 1)
        rate = round((spent / dist * 100), 2) if dist > 0 else 0

        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()

        res_html = f"""
        <html><head><meta charset="UTF-8"><style>
            body {{ font-family: serif; padding: 40px; }}
            .sheet {{ border: 2px solid #000; padding: 25px; max-width: 850px; margin: auto; }}
            table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
            th, td {{ border: 1px solid #000; padding: 10px; text-align: left; }}
            .total-box {{ background: #f2f2f2; font-weight: bold; }}
            @media print {{ .no-print {{ display: none; }} }}
        </style></head><body>
        <div class="sheet">
            <h2 style="text-align:center">ПОДОРОЖНІЙ ЛИСТ</h2>
            <p><b>Автомобіль:</b> {car['Номер авто']} &nbsp;&nbsp;&nbsp; <b>Водій:</b> {car['ФИО']}</p>
            
            <table>
                <tr style="background:#eee"><th>Параметр</th><th>Початок (Виїзд)</th><th>Кінець (Повернення)</th></tr>
                <tr><td>Дата та час</td><td>{t1}</td><td>{t2}</td></tr>
                <tr><td>Показники одометра</td><td>{odo1} км</td><td>{odo2} км</td></tr>
                <tr><td>Рівень палива в баку</td><td>{f1} л</td><td>{f2} л</td></tr>
            </table>

            <table>
                <tr class="total-box">
                    <td>ПРОБІГ: {dist} км</td>
                    <td>ЗАПРАВЛЕНО: {fuelings} л</td>
                    <td>ВИТРАТА: {spent} л</td>
                    <td>СЕР. ВИТРАТА: {rate} л/100км</td>
                </tr>
            </table>
            
            <p style="margin-top:40px">Диспетчер: __________________ &nbsp;&nbsp;&nbsp;&nbsp;&nbsp; Водій: __________________</p>
            <div class="no-print" style="text-align:center; margin-top:20px;">
                <button onclick="window.print()" style="padding:10px 20px; background:green; color:white; border:none; cursor:pointer">ДРУКУВАТИ</button>
            </div>
        </div></body></html>
        """
        self.wfile.write(res_html.encode())

# ============================================================================
# ЗАПУСК
# ============================================================================

def main():
    global vehicles_df
    if not os.path.exists(TARGET_FILE):
        print(f"❌ Файл {TARGET_FILE} не найден!"); return
    
    vehicles_df = pd.read_excel(TARGET_FILE)
    print(f"✅ Данные загружены. Запуск сервера на http://localhost:{PORT}")
    
    webbrowser.open(f"http://localhost:{PORT}")
    try:
        HTTPServer(('localhost', PORT), RequestHandler).serve_forever()
    except KeyboardInterrupt:
        print("\nСервер остановлен.")

if __name__ == "__main__":
    main()