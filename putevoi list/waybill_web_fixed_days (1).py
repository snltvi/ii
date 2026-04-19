#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Путевой лист с веб-интерфейсом
ИСПРАВЛЕНО: правильный подсчёт дней командировки
"""

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
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TARGET_FILE = os.path.join(SCRIPT_DIR, "CAN_пробег_датчики_06_02_2026.xlsx")
PORT = 8080

# ============================================================================
# API ФУНКЦИИ
# ============================================================================

def connect_to_api():
    try:
        res = requests.get(f"{API_URL}/connect", 
                          params={'login': LOGIN, 'password': PASSWORD, 
                                  'lang': 'ru-ru', 'timezone': '3'}, 
                          timeout=10)
        return res.headers.get('sessionid') or res.json().get('sessionid')
    except: 
        return None


def get_coords_robust(session_id, oid, time_str, check_date):
    """Надёжное получение координат с несколькими попытками"""
    dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
    time_windows = [2, 5, 10, 30]
    
    for window in time_windows:
        try:
            t_from = (dt - timedelta(minutes=window)).strftime('%Y-%m-%d %H:%M:%S')
            t_to = (dt + timedelta(minutes=window)).strftime('%Y-%m-%d %H:%M:%S')
            res = requests.get(f"{API_URL}/track", 
                              headers={'SessionId': session_id}, 
                              params={'oid': oid, 'from': t_from, 'to': t_to}, 
                              timeout=10).json()
            points = res.get('track', [])
            if points:
                best_p = min(points, key=lambda p: abs(datetime.strptime(p['dt'], '%Y-%m-%d %H:%M:%S') - dt))
                return best_p['lat'], best_p['lon']
        except: 
            continue
    
    # Fallback: пробуем через getobjectsreport
    try:
        date_s = check_date.strftime('%Y-%m-%d')
        res = requests.get(f"{API_URL}/getobjectsreport", 
                          headers={'SessionId': session_id}, 
                          params={'date_from': f"{date_s} 00:00:00", 
                                 'date_to': f"{date_s} 23:59:59", 
                                 'objuids': str(oid), 
                                 'split': 'none', 
                                 'param': 'stop_coords'}).json()
        if res and res[0].get('periods'):
            val = res[0]['periods'][0]['prms'][0]['value']
            lat, lon = str(val).split(';')
            return float(lat), float(lon)
    except: 
        pass
    
    return None, None


def get_data_by_odo(session_id, oid, sid, target_odo, date_str):
    """Поиск данных по показанию одометра"""
    print(f"\n🔍 Поиск: {target_odo} км на дату {date_str}")
    check_date = datetime.strptime(date_str, '%Y-%m-%d')
    params = {'oid': oid, 'slist': f's{sid}', 
             'from': f"{date_str} 00:00:00", 
             'to': f"{date_str} 23:59:59"}
    
    try:
        res = requests.get(f"{API_URL}/objdata", 
                          headers={'SessionId': session_id}, 
                          params=params, timeout=20).json()
        records = res.get('obj_data', {}).get('records', [])
        
        valid_records = [r for r in records 
                        if len(r) > 1 and r[1] is not None and str(r[1]).strip() != '']
        
        if not valid_records: 
            print("   ❌ Нет валидных данных одометра")
            return None

        best_match = min(valid_records, key=lambda x: abs(float(x[1]) - float(target_odo)))
        found_odo = float(best_match[1])
        diff = abs(found_odo - float(target_odo))
        print(f"   ✓ Найдено: {found_odo} км (разница: {diff:.2f} км)")

        if diff > 100:
            print(f"   ⚠️ Большая разница ({diff:.2f} км)")

        lat, lon = get_coords_robust(session_id, oid, best_match[0], check_date)
        addr = "Адрес не определен"
        
        if lat:
            try:
                addr_res = requests.get(f"{API_URL}/getaddress", 
                                       headers={'SessionId': session_id}, 
                                       params={'lat': lat, 'lon': lon}, 
                                       timeout=10)
                addr = addr_res.text.strip().strip('"')
            except:
                pass

        return {'dt': best_match[0], 'odo': found_odo, 'addr': addr}
    
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
        return None


def get_fuel_level(session_id, oid, date_str):
    """Получение уровня топлива на дату"""
    print(f"   ⛽ Получение топлива за {date_str}...")
    
    try:
        params = {
            'date_from': f"{date_str} 00:00:00",
            'date_to': f"{date_str} 23:59:59",
            'objuids': str(oid)
        }
        
        res = requests.get(f"{API_URL}/getobjectsfuelinfo", 
                          headers={'SessionId': session_id}, 
                          params=params, timeout=20).json()
        
        if res and len(res) > 0:
            obj_data = res[0]
            total_start = 0
            total_end = 0
            has_tanks = False
            
            for sensor in obj_data.get('sensors', []):
                sensor_name = sensor.get('sensor_name', '').lower()
                if any(kw in sensor_name for kw in ['бак', 'lls', 'fuel', 'tank']):
                    total_start += sensor.get('beginLevel', 0)
                    total_end += sensor.get('endLevel', 0)
                    has_tanks = True
            
            if has_tanks:
                print(f"      Начало дня: {total_start:.1f} л, Конец дня: {total_end:.1f} л")
                return round(total_start, 1), round(total_end, 1)
    
    except Exception as e:
        print(f"      ⚠️ Ошибка: {e}")
    
    return None, None


def get_fuelings(session_id, oid, date_from, date_to):
    """Получение заправок за период"""
    print(f"   ⛽ Получение заправок за период {date_from} - {date_to}...")
    
    try:
        params = {
            'oid': oid,
            'from': f"{date_from} 00:00:00",
            'to': f"{date_to} 23:59:59"
        }
        
        res = requests.get(f"{API_URL}/fuelings",
                          headers={'SessionId': session_id},
                          params=params, timeout=20).json()
        
        if res.get('result') == 'Ok':
            total = 0
            count = 0
            
            for event in res.get('fuelings', []):
                if event.get('fuel_type') == 'fueling':
                    volume = float(event.get('volume', 0))
                    total += volume
                    count += 1
            
            print(f"      Заправок: {count} шт на {total:.1f} л")
            return round(total, 1)
    
    except Exception as e:
        print(f"      ⚠️ Ошибка: {e}")
    
    return 0.0


# ============================================================================
# ВЕБ-СЕРВЕР
# ============================================================================

class WebHandler(BaseHTTPRequestHandler):
    
    def log_message(self, format, *args):
        pass
    
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        
        options = "".join([f"<option value='{i}'>{row['Номер авто']} ({row['ФИО']})</option>" 
                          for i, row in vehicles_df.iterrows()])
        
        html = f"""
        <html>
        <head>
            <meta charset="UTF-8">
            <title>Путевой лист</title>
            <style>
                body {{ font-family: sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 40px; min-height: 100vh; }}
                .card {{ background: white; padding: 30px; border-radius: 12px; box-shadow: 0 10px 40px rgba(0,0,0,0.2); max-width: 500px; margin: auto; }}
                h2 {{ text-align: center; color: #333; margin-bottom: 25px; }}
                label {{ display: block; margin-top: 15px; margin-bottom: 5px; color: #555; font-weight: 600; }}
                input, select {{ width: 100%; padding: 12px; border: 2px solid #e0e0e0; border-radius: 6px; font-size: 14px; }}
                input:focus, select:focus {{ outline: none; border-color: #667eea; }}
                button {{ width: 100%; padding: 15px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: bold; margin-top: 20px; }}
                button:hover {{ transform: translateY(-2px); }}
                .hint {{ font-size: 12px; color: #999; margin-top: 3px; }}
            </style>
        </head>
        <body>
            <div class="card">
                <h2>📋 Путевой Лист</h2>
                <form action="/generate" method="POST">
                    <label>🚗 Транспортное средство:</label>
                    <select name="car_idx" required>{options}</select>
                    
                    <label>📅 Дата начала рейса:</label>
                    <input type="date" name="date_1" required>
                    <div class="hint">Дата выезда</div>
                    
                    <label>📊 Одометр начала (км):</label>
                    <input type="number" step="0.1" name="odo_1" placeholder="Например: 862345" required>
                    
                    <label>📅 Дата окончания рейса:</label>
                    <input type="date" name="date_2" required>
                    <div class="hint">Дата возврата</div>
                    
                    <label>📊 Одометр окончания (км):</label>
                    <input type="number" step="0.1" name="odo_2" placeholder="Например: 862590" required>
                    
                    <button type="submit">🔍 СФОРМИРОВАТЬ ПУТЕВОЙ ЛИСТ</button>
                </form>
            </div>
        </body>
        </html>
        """
        
        self.wfile.write(html.encode())

    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        data = parse_qs(self.rfile.read(content_length).decode())
        
        car = vehicles_df.iloc[int(data['car_idx'][0])]
        date_1 = data['date_1'][0]
        odo_1 = data['odo_1'][0]
        date_2 = data['date_2'][0]
        odo_2 = data['odo_2'][0]
        
        print(f"\n{'='*60}")
        print(f"ФОРМИРОВАНИЕ ПУТЕВОГО ЛИСТА")
        print(f"ТС: {car['Номер авто']} ({car['ФИО']})")
        print(f"{'='*60}")
        
        sid_api = connect_to_api()
        if not sid_api:
            self.send_error("❌ Ошибка подключения к API")
            return
        
        p1 = get_data_by_odo(sid_api, int(car['ID объекта']), int(car['SID']), odo_1, date_1)
        p2 = get_data_by_odo(sid_api, int(car['ID объекта']), int(car['SID']), odo_2, date_2)

        if not p1 or not p2:
            self.send_error("❌ Не удалось найти показания одометра")
            return
        
        print(f"\n{'='*60}")
        print("ПОЛУЧЕНИЕ ДАННЫХ ПО ТОПЛИВУ")
        print(f"{'='*60}")
        
        fuel_1_start, fuel_1_end = get_fuel_level(sid_api, int(car['ID объекта']), date_1)
        fuel_2_start, fuel_2_end = get_fuel_level(sid_api, int(car['ID объекта']), date_2)
        
        fuel_start = fuel_1_start if fuel_1_start else 0
        fuel_end = fuel_2_end if fuel_2_end else 0
        
        fuelings = get_fuelings(sid_api, int(car['ID объекта']), date_1, date_2)
        
        # ИСПРАВЛЕНО: +1 чтобы включить оба дня
        days = (datetime.strptime(date_2, '%Y-%m-%d') - datetime.strptime(date_1, '%Y-%m-%d')).days + 1
        mileage = round(p2['odo'] - p1['odo'], 1)
        
        consumption = round(fuel_start + fuelings - fuel_end, 1)
        consumption_rate = round(consumption / mileage * 100, 2) if mileage > 0 else 0
        
        print(f"\n{'='*60}")
        print("ИТОГОВЫЕ РАСЧЁТЫ")
        print(f"{'='*60}")
        print(f"Дней в рейсе:     {days} (с {date_1} по {date_2} включительно)")
        print(f"Пробег:           {mileage} км")
        print(f"Топливо начало:   {fuel_start} л")
        print(f"Заправлено:       {fuelings} л")
        print(f"Топливо конец:    {fuel_end} л")
        print(f"Расход:           {consumption} л ({consumption_rate} л/100км)")
        print(f"{'='*60}\n")
        
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()

        html = f"""
        <html>
        <head>
            <meta charset="UTF-8">
            <title>Путевой лист - {car['Номер авто']}</title>
            <style>
                body {{ font-family: serif; padding: 30px; max-width: 900px; margin: auto; }}
                .bill {{ border: 3px solid #000; padding: 40px; background: #fff; }}
                h1 {{ text-align: center; margin-bottom: 20px; }}
                .header {{ display: flex; justify-content: space-between; margin-bottom: 20px; padding-bottom: 10px; border-bottom: 2px solid #000; }}
                table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
                th, td {{ border: 1px solid #000; padding: 12px; }}
                th {{ background: #f0f0f0; font-weight: bold; }}
                .highlight {{ background: #fffacd; font-weight: bold; }}
                button {{ padding: 12px 30px; margin: 10px 5px; cursor: pointer; border-radius: 5px; border: none; font-size: 14px; }}
                .print-btn {{ background: #28a745; color: white; }}
                .back-btn {{ background: #6c757d; color: white; }}
                @media print {{ .buttons {{ display: none; }} }}
            </style>
        </head>
        <body>
            <div class="bill">
                <h1>ПУТЕВОЙ ЛИСТ</h1>
                
                <div class="header">
                    <div><strong>ТС:</strong> {car['Номер авто']}</div>
                    <div><strong>Водитель:</strong> {car['ФИО']}</div>
                </div>
                
                <h3>Данные рейса:</h3>
                <table>
                    <thead>
                        <tr>
                            <th>Параметр</th>
                            <th>Выезд</th>
                            <th>Возврат</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr>
                            <td><strong>Дата и время</strong></td>
                            <td>{p1['dt']}</td>
                            <td>{p2['dt']}</td>
                        </tr>
                        <tr>
                            <td><strong>Одометр</strong></td>
                            <td>{p1['odo']:.1f} км</td>
                            <td>{p2['odo']:.1f} км</td>
                        </tr>
                        <tr>
                            <td><strong>Адрес</strong></td>
                            <td>{p1['addr']}</td>
                            <td>{p2['addr']}</td>
                        </tr>
                    </tbody>
                </table>
                
                <h3>Итоги:</h3>
                <table>
                    <tbody>
                        <tr class="highlight">
                            <td><strong>Количество дней</strong></td>
                            <td style="font-size: 18px;"><strong>{days} дней</strong></td>
                        </tr>
                        <tr class="highlight">
                            <td><strong>Пробег</strong></td>
                            <td style="font-size: 18px; color: #28a745;"><strong>{mileage} км</strong></td>
                        </tr>
                        <tr>
                            <td><strong>Топливо начало</strong></td>
                            <td>{fuel_start} л</td>
                        </tr>
                        <tr>
                            <td><strong>Заправлено</strong></td>
                            <td style="color: #007bff; font-weight: bold;">{fuelings} л</td>
                        </tr>
                        <tr>
                            <td><strong>Топливо конец</strong></td>
                            <td>{fuel_end} л</td>
                        </tr>
                        <tr class="highlight">
                            <td><strong>Расход топлива</strong></td>
                            <td style="font-size: 18px; color: #dc3545;"><strong>{consumption} л</strong></td>
                        </tr>
                        <tr>
                            <td><strong>Расход на 100 км</strong></td>
                            <td><strong>{consumption_rate} л/100км</strong></td>
                        </tr>
                    </tbody>
                </table>
                
                <div class="buttons" style="text-align: center; margin-top: 30px;">
                    <button class="print-btn" onclick="window.print()">🖨️ Печать</button>
                    <button class="back-btn" onclick="history.back()">◀️ Назад</button>
                </div>
            </div>
        </body>
        </html>
        """
        
        self.wfile.write(html.encode())
    
    def send_error(self, message):
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        
        html = f"""
        <html>
        <head><meta charset="UTF-8"></head>
        <body style="font-family: sans-serif; padding: 40px; text-align: center;">
            <h3 style="color: red;">{message}</h3>
            <p>Проверьте консоль для подробностей</p>
            <button onclick="history.back()" style="padding: 12px 30px; background: #6c757d; color: white; border: none; border-radius: 5px; cursor: pointer;">
                ◀️ Назад
            </button>
        </body>
        </html>
        """
        
        self.wfile.write(html.encode())


# ============================================================================
# MAIN
# ============================================================================

def main():
    global vehicles_df
    
    print("\n" + "="*60)
    print("ПУТЕВОЙ ЛИСТ - ИСПРАВЛЕННАЯ ВЕРСИЯ")
    print("="*60)
    
    if not os.path.exists(TARGET_FILE):
        print(f"\n❌ Файл {TARGET_FILE} не найден!")
        return
    
    vehicles_df = pd.read_excel(TARGET_FILE)
    print(f"\n✓ Загружено {len(vehicles_df)} ТС")
    
    server = HTTPServer(('localhost', PORT), WebHandler)
    print(f"\n🚀 Сервер запущен: http://localhost:{PORT}")
    print("\n💡 Нажмите Ctrl+C для остановки\n")
    
    webbrowser.open(f"http://localhost:{PORT}")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\n⏹️  Сервер остановлен")


if __name__ == "__main__":
    main()
