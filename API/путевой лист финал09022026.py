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
# ИСПРАВЛЕННАЯ ЛОГИКА ПОИСКА
# ============================================================================

def get_coords_robust(session_id, oid, time_str, check_date):
    dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
    time_windows = [2, 5, 10, 30]
    for window in time_windows:
        try:
            t_from = (dt - timedelta(minutes=window)).strftime('%Y-%m-%d %H:%M:%S')
            t_to = (dt + timedelta(minutes=window)).strftime('%Y-%m-%d %H:%M:%S')
            res = requests.get(f"{API_URL}/track", headers={'SessionId': session_id}, 
                               params={'oid': oid, 'from': t_from, 'to': t_to}, timeout=10).json()
            points = res.get('track', [])
            if points:
                best_p = min(points, key=lambda p: abs(datetime.strptime(p['dt'], '%Y-%m-%d %H:%M:%S') - dt))
                return best_p['lat'], best_p['lon']
        except: continue
    try:
        date_s = check_date.strftime('%Y-%m-%d')
        res = requests.get(f"{API_URL}/getobjectsreport", headers={'SessionId': session_id}, 
                           params={'date_from': f"{date_s} 00:00:00", 'date_to': f"{date_s} 23:59:59", 
                                   'objuids': str(oid), 'split': 'none', 'param': 'stop_coords'}).json()
        if res and res[0].get('periods'):
            val = res[0]['periods'][0]['prms'][0]['value']
            lat, lon = str(val).split(';')
            return float(lat), float(lon)
    except: pass
    return None, None

def get_data_by_odo(session_id, oid, sid, target_odo, date_str):
    print(f"\n🔍 Поиск: {target_odo} км на дату {date_str}")
    check_date = datetime.strptime(date_str, '%Y-%m-%d')
    params = {'oid': oid, 'slist': f's{sid}', 'from': f"{date_str} 00:00:00", 'to': f"{date_str} 23:59:59"}
    
    try:
        res = requests.get(f"{API_URL}/objdata", headers={'SessionId': session_id}, params=params, timeout=20).json()
        records = res.get('obj_data', {}).get('records', [])
        
        # КЛЮЧЕВОЕ ИСПРАВЛЕНИЕ: Фильтруем записи, где значение пустое или None
        valid_records = [r for r in records if len(r) > 1 and r[1] is not None and str(r[1]).strip() != '']
        
        if not valid_records: 
            print("   ❌ Нет валидных данных одометра за этот день")
            return None

        # Ищем ближайшее совпадение только среди валидных записей
        best_match = min(valid_records, key=lambda x: abs(float(x[1]) - float(target_odo)))
        found_odo = float(best_match[1])
        diff = abs(found_odo - float(target_odo))
        print(f"   📊 Найдено: {found_odo} км (разница: {diff:.2f} км)")

        if diff > 15:
            print(f"   ⚠️ Слишком большая разница ({diff:.2f} км)")
            return None

        lat, lon = get_coords_robust(session_id, oid, best_match[0], check_date)
        addr = "Адрес не определен"
        if lat:
            addr_res = requests.get(f"{API_URL}/getaddress", headers={'SessionId': session_id}, params={'lat': lat, 'lon': lon})
            addr = addr_res.text.strip().strip('"')

        return {'dt': best_match[0], 'odo': found_odo, 'addr': addr}
    except Exception as e:
        print(f"   ❌ Ошибка обработки: {e}")
        return None

# ============================================================================
# ВЕБ-СЕРВЕР (RequestHandler)
# ============================================================================

class WebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        options = "".join([f"<option value='{i}'>{row['Номер авто']} ({row['ФИО']})</option>" for i, row in vehicles_df.iterrows()])
        html = f"""
        <html><head><meta charset="UTF-8"><title>Путевой лист</title>
        <style>
            body {{ font-family: sans-serif; background: #f0f2f5; padding: 40px; }}
            .card {{ background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); max-width: 500px; margin: auto; }}
            input, select {{ width: 100%; padding: 12px; margin: 10px 0; border: 1px solid #ddd; border-radius: 6px; }}
            button {{ width: 100%; padding: 15px; background: #007bff; color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: bold; }}
        </style></head><body>
        <div class="card">
            <h2 style="text-align:center">Путевой Лист</h2>
            <form action="/generate" method="POST">
                <label>Автомобиль:</label><select name="car_idx">{options}</select>
                <label>Выезд (Дата и Одометр):</label>
                <input type="date" name="date_1" required><input type="number" step="0.1" name="odo_1" required>
                <label>Возврат (Дата и Одометр):</label>
                <input type="date" name="date_2" required><input type="number" step="0.1" name="odo_2" required>
                <button type="submit">СФОРМИРОВАТЬ</button>
            </form>
        </div></body></html>
        """
        self.wfile.write(html.encode())

    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        data = parse_qs(self.rfile.read(content_length).decode())
        car = vehicles_df.iloc[int(data['car_idx'][0])]
        sid_api = connect_to_api()
        
        p1 = get_data_by_odo(sid_api, int(car['ID объекта']), int(car['SID']), data['odo_1'][0], data['date_1'][0])
        p2 = get_data_by_odo(sid_api, int(car['ID объекта']), int(car['SID']), data['odo_2'][0], data['date_2'][0])

        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()

        if p1 and p2:
            res_html = f"""
            <html><head><meta charset="UTF-8"><style>
                body {{ font-family: serif; padding: 50px; }}
                .bill {{ border: 1px solid #000; padding: 30px; max-width: 800px; margin: auto; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
                th, td {{ border: 1px solid #000; padding: 10px; }}
            </style></head><body>
            <div class="bill">
                <h1 style="text-align:center">ПУТЕВОЙ ЛИСТ</h1>
                <p><b>ТС:</b> {car['Номер авто']} | <b>Водитель:</b> {car['ФИО']}</p>
                <table>
                    <tr><th>Этап</th><th>Дата/Время</th><th>Одометр</th><th>Адрес</th></tr>
                    <tr><td>Выезд</td><td>{p1['dt']}</td><td>{p1['odo']} км</td><td>{p1['addr']}</td></tr>
                    <tr><td>Возврат</td><td>{p2['dt']}</td><td>{p2['odo']} км</td><td>{p2['addr']}</td></tr>
                </table>
                <p style="text-align:right"><b>Итого: {round(p2['odo'] - p1['odo'], 1)} км</b></p>
                <button onclick="window.print()">Печать</button>
            </div></body></html>
            """
            self.wfile.write(res_html.encode())
        else:
            self.wfile.write("<h3>❌ Данные не найдены (проверьте консоль для деталей)</h3><button onclick='history.back()'>Назад</button>".encode())

def connect_to_api():
    try:
        res = requests.get(f"{API_URL}/connect", params={'login': LOGIN, 'password': PASSWORD, 'lang': 'ru-ru', 'timezone': '3'}, timeout=10)
        return res.headers.get('sessionid') or res.json().get('sessionid')
    except: return None

def main():
    global vehicles_df
    vehicles_df = pd.read_excel(TARGET_FILE)
    server = HTTPServer(('localhost', PORT), WebHandler)
    print(f"🚀 СЕРВЕР ЗАПУЩЕН: http://localhost:{PORT}")
    webbrowser.open(f"http://localhost:{PORT}")
    server.serve_forever()

if __name__ == "__main__":
    main()