#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Путевой лист с веб-интерфейсом
- Поле для комментариев
- Все поля редактируемые в итоговом документе
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
import os
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs
import sqlite3

# ============================================================================
# НАСТРОЙКИ
# ============================================================================
API_URL = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN = "abvprom"
PASSWORD = "29328"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TARGET_FILE = os.path.join(SCRIPT_DIR, "справочники", "CAN_пробег_датчики_06_02_2026.xlsx")
DB_FILE = os.path.join(SCRIPT_DIR, "справочники", "abv_fuel_in_out_comsum-16-02-206.db")
PORT = 8080

# Глобальные переменные
vehicles_df = None

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
    """Надёжное получение координат"""
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
    
    # Fallback
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
    """
    УМНЫЙ ПОИСК по показанию одометра
    Ищет в указанную дату, если не находит - проверяет ±3 дня
    """
    print(f"\n🔍 Поиск: {target_odo} км на дату {date_str}")
    
    center_date = datetime.strptime(date_str, '%Y-%m-%d')
    
    # Стратегия: сначала указанная дата, потом соседние дни
    search_dates = [
        center_date,
        center_date - timedelta(days=1),
        center_date + timedelta(days=1),
        center_date - timedelta(days=2),
        center_date + timedelta(days=2),
        center_date - timedelta(days=3),
        center_date + timedelta(days=3),
    ]
    
    best_overall = None
    min_diff = float('inf')
    
    for check_date in search_dates:
        date_s = check_date.strftime('%Y-%m-%d')
        
        params = {'oid': oid, 'slist': f's{sid}', 
                 'from': f"{date_s} 00:00:00", 
                 'to': f"{date_s} 23:59:59"}
        
        try:
            res = requests.get(f"{API_URL}/objdata", 
                              headers={'SessionId': session_id}, 
                              params=params, timeout=20).json()
            records = res.get('obj_data', {}).get('records', [])
            
            valid_records = [r for r in records 
                            if len(r) > 1 and r[1] is not None and str(r[1]).strip() != '']
            
            if not valid_records:
                continue
            
            # Ищем ближайшее в этот день
            best_in_day = min(valid_records, key=lambda x: abs(float(x[1]) - float(target_odo)))
            found_odo = float(best_in_day[1])
            diff = abs(found_odo - float(target_odo))
            
            # ТОЧНОЕ совпадение (< 1 км)
            if diff < 1.0:
                print(f"   ✅ ТОЧНОЕ СОВПАДЕНИЕ {date_s}: {found_odo} км (разница: {diff:.2f} км)")
                
                lat, lon = get_coords_robust(session_id, oid, best_in_day[0], check_date)
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
                
                return {'dt': best_in_day[0], 'odo': found_odo, 'lat': lat, 'lon': lon, 'addr': addr}
            
            # Запоминаем лучший результат
            if diff < min_diff:
                min_diff = diff
                best_overall = (best_in_day, check_date, found_odo, diff)
        
        except:
            continue
    
    # Если точного не нашли - берём лучший
    if best_overall:
        best_match, check_date, found_odo, diff = best_overall
        date_found = check_date.strftime('%Y-%m-%d')
        
        print(f"   ✓ Найдено {date_found}: {found_odo} км (разница: {diff:.2f} км)")
        
        if date_found != date_str:
            print(f"   ⚠️ ВНИМАНИЕ: Показание в ДРУГОЙ день ({date_found} вместо {date_str})")
        
        if diff > 50:
            print(f"   ⚠️ ВНИМАНИЕ: Большая разница ({diff:.2f} км)")
        
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
        
        return {'dt': best_match[0], 'odo': found_odo, 'lat': lat, 'lon': lon, 'addr': addr}
    
    print("   ❌ Не найдено в пределах ±3 дней")
    return None


def get_fuel_level(session_id, oid, date_str):
    """Получение уровня топлива на дату из API"""
    print(f"   ⛽ Получение топлива за {date_str} из API...")
    
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


def get_refuels_from_db(oid, date_from, date_to):
    """Получение ТОЛЬКО ЗАПРАВОК из базы данных"""
    
    if not os.path.exists(DB_FILE):
        print(f"   ⚠️ База данных не найдена: {DB_FILE}")
        return None  # ← Вернём None чтобы понять что БД нет
    
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        query = """
            SELECT report_date, refuels
            FROM abv_fuel_in_out_comsum
            WHERE obj_id = ? AND report_date BETWEEN ? AND ?
            ORDER BY report_date
        """
        
        cursor.execute(query, (oid, date_from, date_to))
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            print(f"   ⚠️ Нет данных в БД для obj_id={oid}")
            return None  # ← Вернём None чтобы использовать API
        
        total_refuels = sum(row[1] for row in rows)
        print(f"   ✓ Из БД: {total_refuels} л")
        return round(total_refuels, 1)
    
    except Exception as e:
        print(f"   ⚠️ Ошибка чтения БД: {e}")
        return None


def get_fuelings_api(session_id, oid, date_from, date_to):
    """Получение заправок ИЗ API (fallback если нет БД)"""
    print(f"   ⛽ Получение заправок из API...")
    
    try:
        res = requests.get(f"{API_URL}/fuelings",
                          headers={'SessionId': session_id},
                          params={
                              'oid': oid,
                              'from': f"{date_from} 00:00:00",
                              'to': f"{date_to} 23:59:59"
                          }, timeout=20).json()
        
        if res.get('result') == 'Ok':
            total = 0
            count = 0
            
            for event in res.get('fuelings', []):
                if event.get('fuel_type') == 'fueling':
                    volume = float(event.get('volume', 0))
                    total += volume
                    count += 1
            
            print(f"      ✓ Из API: {count} заправок на {total:.1f} л")
            return round(total, 1)
        else:
            print(f"      ⚠️ API вернул: {res.get('result')}")
            return 0.0
    
    except Exception as e:
        print(f"      ❌ Ошибка API: {e}")
        return 0.0


def get_fuelings_api(session_id, oid, date_from, date_to):
    """Получение заправок ИЗ API (fallback если нет БД)"""
    print(f"   ⛽ Получение заправок за период {date_from} - {date_to} из API...")
    
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
        """Главная страница - форма"""
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
                input, select, textarea {{ width: 100%; padding: 12px; border: 2px solid #e0e0e0; border-radius: 6px; font-size: 14px; font-family: inherit; }}
                input:focus, select:focus, textarea:focus {{ outline: none; border-color: #667eea; }}
                textarea {{ resize: vertical; }}
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
                    
                    <label>📍 Остановки маршрута (необязательно):</label>
                    <select id="stops" multiple style="height: 120px;">
                        <optgroup label="🏭 Производственные объекты">
                            <option value="База АБВ ПРОМ (Одесса, ул. Промышленная, 15)">База АБВ ПРОМ</option>
                            <option value="Склад №1 (Киев, Столичное шоссе, 103)">Склад №1 Киев</option>
                            <option value="Склад №2 (Харьков, пр. Московский, 45)">Склад №2 Харьков</option>
                            <option value="Производство (Днепр, ул. Рабочая, 78)">Производство Днепр</option>
                        </optgroup>
                        <optgroup label="🏢 Клиенты">
                            <option value="ТОВ 'Будмеханізація' (Одесса, ул. Маршала Жукова, 5)">Будмеханізація</option>
                            <option value="ПП 'Техносервис' (Киев, Харьковское шоссе, 201)">Техносервис</option>
                            <option value="ТОВ 'Агротех' (Николаев, ул. Спортивная, 12)">Агротех</option>
                            <option value="ООО 'СтройДом' (Херсон, пр. Ушакова, 89)">СтройДом</option>
                        </optgroup>
                        <optgroup label="🏪 Точки обслуживания">
                            <option value="СТО 'Автомастер' (Одесса, ул. Балковская, 140)">СТО Автомастер</option>
                            <option value="Шиномонтаж 'Колесо' (Одесса, ул. Люстдорфская, 55)">Шиномонтаж</option>
                            <option value="АЗС ОККО (Одесса, ул. Новосельского, 90)">АЗС ОККО</option>
                            <option value="Мойка 'Чистота' (Одесса, пр. Добровольского, 120)">Автомойка</option>
                        </optgroup>
                        <optgroup label="🏙️ Города (основные направления)">
                            <option value="Киев">Киев</option>
                            <option value="Одесса">Одесса</option>
                            <option value="Харьков">Харьков</option>
                            <option value="Днепр">Днепр</option>
                            <option value="Николаев">Николаев</option>
                            <option value="Херсон">Херсон</option>
                            <option value="Житомир">Житомир</option>
                            <option value="Винница">Винница</option>
                        </optgroup>
                    </select>
                    <div class="hint">Удерживайте Ctrl (Cmd на Mac) для выбора нескольких пунктов</div>
                    <button type="button" onclick="addStopsToComment()" style="width: 100%; padding: 10px; margin-top: 5px; background: #28a745; color: white; border: none; border-radius: 6px; cursor: pointer; font-size: 13px;">
                        ➕ Добавить в комментарий
                    </button>
                    
                    <label>💬 Комментарий (маршрут):</label>
                    <textarea id="comment" name="comment" rows="5" placeholder="Маршрут будет добавлен сюда..."></textarea>
                    <div class="hint">Или введите комментарий вручную</div>
                    
                    <button type="submit">🔍 СФОРМИРОВАТЬ ПУТЕВОЙ ЛИСТ</button>
                </form>
            </div>
            <script>
                function addStopsToComment() {{
                    const select = document.getElementById('stops');
                    const comment = document.getElementById('comment');
                    const selected = Array.from(select.selectedOptions).map(opt => opt.value);
                    
                    if (selected.length === 0) {{
                        alert('Выберите хотя бы одну остановку!');
                        return;
                    }}
                    
                    // Формируем маршрут
                    let route = 'Маршрут:\\n';
                    selected.forEach((stop, idx) => {{
                        route += (idx + 1) + '. ' + stop + '\\n';
                    }});
                    
                    // Добавляем к существующему комментарию или создаём новый
                    if (comment.value.trim()) {{
                        comment.value += '\\n\\n' + route;
                    }} else {{
                        comment.value = route;
                    }}
                    
                    // Очищаем выбор
                    select.selectedIndex = -1;
                }}
            </script>
                </form>
            </div>
        </body>
        </html>
        """
        
        self.wfile.write(html.encode())

    def do_POST(self):
        """Обработка формы и генерация путевого листа"""
        content_length = int(self.headers['Content-Length'])
        data = parse_qs(self.rfile.read(content_length).decode())
        
        # Получаем данные формы
        car = vehicles_df.iloc[int(data['car_idx'][0])]
        date_1 = data['date_1'][0]
        odo_1 = data['odo_1'][0]
        date_2 = data['date_2'][0]
        odo_2 = data['odo_2'][0]
        comment = data.get('comment', [''])[0]  # Комментарий
        
        print(f"\n{'='*60}")
        print(f"ФОРМИРОВАНИЕ ПУТЕВОГО ЛИСТА")
        print(f"ТС: {car['Номер авто']} ({car['ФИО']})")
        print(f"{'='*60}")
        
        # Подключение к API
        sid_api = connect_to_api()
        if not sid_api:
            self.send_error("❌ Ошибка подключения к API")
            return
        
        # Поиск данных по одометру
        p1 = get_data_by_odo(sid_api, int(car['ID объекта']), int(car['SID']), odo_1, date_1)
        p2 = get_data_by_odo(sid_api, int(car['ID объекта']), int(car['SID']), odo_2, date_2)

        if not p1 or not p2:
            self.send_error("❌ Не удалось найти показания одометра")
            return
        
        # Получаем уровни топлива ИЗ API
        print(f"\n{'='*60}")
        print("ПОЛУЧЕНИЕ УРОВНЕЙ ТОПЛИВА ИЗ API")
        print(f"{'='*60}")
        
        fuel_1_start, fuel_1_end = get_fuel_level(sid_api, int(car['ID объекта']), date_1)
        fuel_2_start, fuel_2_end = get_fuel_level(sid_api, int(car['ID объекта']), date_2)
        
        fuel_start = fuel_1_start if fuel_1_start else 0
        fuel_end = fuel_2_end if fuel_2_end else 0
        
        # ГИБРИДНЫЙ ПОДХОД: Сначала пробуем БД, если нет - API
        print(f"\n{'='*60}")
        print("ПОЛУЧЕНИЕ ЗАПРАВОК")
        print(f"{'='*60}")
        
        fuelings = get_refuels_from_db(int(car['ID объекта']), date_1, date_2)
        
        if fuelings is None:
            # БД не дала результат - пробуем API
            print("   Используем API как fallback...")
            fuelings = get_fuelings_api(sid_api, int(car['ID объекта']), date_1, date_2)
        
        print(f"{'='*60}")
        
        # Расчёты
        days = (datetime.strptime(date_2, '%Y-%m-%d') - datetime.strptime(date_1, '%Y-%m-%d')).days + 1
        mileage = round(p2['odo'] - p1['odo'], 1)
        
        consumption = round(fuel_start + fuelings - fuel_end, 1)
        consumption_rate = round(consumption / mileage * 100, 2) if mileage > 0 else 0
        
        print(f"\n{'='*60}")
        print("ИТОГОВЫЕ РАСЧЁТЫ")
        print(f"{'='*60}")
        print(f"Дней в рейсе:     {days}")
        print(f"Пробег:           {mileage} км")
        print(f"Топливо начало:   {fuel_start} л")
        print(f"Заправлено:       {fuelings} л")
        print(f"Топливо конец:    {fuel_end} л")
        print(f"Расход:           {consumption} л ({consumption_rate} л/100км)")
        if comment:
            print(f"Комментарий:      {comment}")
        print(f"{'='*60}\n")
        
        # Генерация HTML с РЕДАКТИРУЕМЫМИ полями
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
                
                /* РЕДАКТИРУЕМЫЕ ПОЛЯ */
                .editable {{ 
                    border: 1px dashed #ccc; 
                    padding: 4px; 
                    min-width: 50px; 
                    display: inline-block;
                    cursor: text;
                }}
                .editable:focus {{
                    outline: 2px solid #667eea;
                    background: #f0f8ff;
                }}
                .editable:hover {{
                    background: #f9f9f9;
                }}
                
                .comment-box {{
                    border: 1px solid #ccc;
                    padding: 12px;
                    margin: 20px 0;
                    border-radius: 5px;
                    background: #f9f9f9;
                    min-height: 60px;
                }}
                .comment-box[contenteditable]:focus {{
                    outline: 2px solid #667eea;
                    background: white;
                }}
                
                button {{ padding: 12px 30px; margin: 10px 5px; cursor: pointer; border-radius: 5px; border: none; font-size: 14px; }}
                .print-btn {{ background: #28a745; color: white; }}
                .back-btn {{ background: #6c757d; color: white; }}
                .edit-hint {{ color: #999; font-size: 12px; margin-bottom: 10px; }}
                
                @media print {{ 
                    .buttons, .edit-hint {{ display: none; }} 
                    .editable {{ border: none; }}
                    .comment-box {{ border: 1px solid #ccc; background: white; }}
                }}
            </style>
        </head>
        <body>
            <div class="bill">
                <h1>ПУТЕВОЙ ЛИСТ</h1>
                
                <p class="edit-hint">💡 Подсказка: Кликните на любое значение чтобы отредактировать его</p>
                
                <div class="header">
                    <div><strong>ТС:</strong> <span class="editable" contenteditable="true">{car['Номер авто']}</span></div>
                    <div><strong>Водитель:</strong> <span class="editable" contenteditable="true">{car['ФИО']}</span></div>
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
                            <td><span class="editable" contenteditable="true">{p1['dt']}</span></td>
                            <td><span class="editable" contenteditable="true">{p2['dt']}</span></td>
                        </tr>
                        <tr>
                            <td><strong>Одометр</strong></td>
                            <td><span class="editable" contenteditable="true">{p1['odo']:.1f}</span> км</td>
                            <td><span class="editable" contenteditable="true">{p2['odo']:.1f}</span> км</td>
                        </tr>
                        <tr>
                            <td><strong>Координаты</strong></td>
                            <td><span class="editable" contenteditable="true">{p1.get('lat', 'N/A')}, {p1.get('lon', 'N/A')}</span></td>
                            <td><span class="editable" contenteditable="true">{p2.get('lat', 'N/A')}, {p2.get('lon', 'N/A')}</span></td>
                        </tr>
                        <tr>
                            <td><strong>Адрес</strong></td>
                            <td><span class="editable" contenteditable="true">{p1['addr']}</span></td>
                            <td><span class="editable" contenteditable="true">{p2['addr']}</span></td>
                        </tr>
                    </tbody>
                </table>
                
                <h3>Итоги:</h3>
                <table>
                    <tbody>
                        <tr class="highlight">
                            <td><strong>Количество дней</strong></td>
                            <td style="font-size: 18px;"><strong><span class="editable" contenteditable="true">{days}</span> дней</strong></td>
                        </tr>
                        <tr class="highlight">
                            <td><strong>Пробег</strong></td>
                            <td style="font-size: 18px; color: #28a745;"><strong><span class="editable" contenteditable="true">{mileage}</span> км</strong></td>
                        </tr>
                        <tr>
                            <td><strong>Топливо начало</strong></td>
                            <td><span class="editable" contenteditable="true">{fuel_start}</span> л</td>
                        </tr>
                        <tr>
                            <td><strong>Заправлено</strong></td>
                            <td style="color: #007bff; font-weight: bold;"><span class="editable" contenteditable="true">{fuelings}</span> л</td>
                        </tr>
                        <tr>
                            <td><strong>Топливо конец</strong></td>
                            <td><span class="editable" contenteditable="true">{fuel_end}</span> л</td>
                        </tr>
                        <tr class="highlight">
                            <td><strong>Расход топлива</strong></td>
                            <td style="font-size: 18px; color: #dc3545;"><strong><span class="editable" contenteditable="true">{consumption}</span> л</strong></td>
                        </tr>
                        <tr>
                            <td><strong>Расход на 100 км</strong></td>
                            <td><strong><span class="editable" contenteditable="true">{consumption_rate}</span> л/100км</strong></td>
                        </tr>
                    </tbody>
                </table>
                
                <h3>Комментарий:</h3>
                <div class="comment-box" contenteditable="true">{comment if comment else 'Добавьте комментарий здесь...'}</div>
                
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
        """Страница ошибки"""
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
    print("ПУТЕВОЙ ЛИСТ С РЕДАКТИРУЕМЫМИ ПОЛЯМИ")
    print("="*60)
    
    # Загрузка данных
    if not os.path.exists(TARGET_FILE):
        print(f"\n❌ Файл {TARGET_FILE} не найден!")
        input("\nНажмите Enter...")
        return
    
    vehicles_df = pd.read_excel(TARGET_FILE)
    print(f"\n✓ Загружено {len(vehicles_df)} ТС")
    
    # Запуск сервера
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
