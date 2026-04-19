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
from urllib.parse import parse_qs, urlparse
import sqlite3
import json
import time as time_module

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


def get_actual_stops(session_id, oid, date_from, date_to):
    """
    УЛУЧШЕННОЕ: Получение остановок через анализ трека движения
    Определяем остановки где машина стояла > 5 минут
    """
    print(f"\n📍 Получение остановок за период {date_from} - {date_to}...")
    
    try:
        # Получаем трек движения за весь период
        params = {
            'oid': oid,
            'from': f"{date_from} 00:00:00",
            'to': f"{date_to} 23:59:59"
        }
        
        res = requests.get(f"{API_URL}/track",
                          headers={'SessionId': session_id},
                          params=params, timeout=30).json()
        
        track_points = res.get('track', [])
        
        if not track_points:
            print("   ⚠️ Нет данных трека")
            return []
        
        print(f"   Анализ {len(track_points)} точек трека...")
        
        # Алгоритм определения остановок
        stops_list = []
        current_stop = None
        STOP_THRESHOLD = 0.0005  # ~50 метров
        MIN_DURATION = 5  # минут
        
        for i, point in enumerate(track_points):
            lat = point.get('lat')
            lon = point.get('lon')
            speed = point.get('speed', 0)
            dt_str = point.get('dt')
            
            if not lat or not lon:
                continue
            
            dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
            
            # Если скорость близка к нулю - возможная остановка
            if speed < 5:  # < 5 км/ч
                if current_stop is None:
                    # Начало новой остановки
                    current_stop = {
                        'lat': lat,
                        'lon': lon,
                        'start_time': dt,
                        'end_time': dt
                    }
                else:
                    # Проверяем - это та же остановка или новая
                    lat_diff = abs(lat - current_stop['lat'])
                    lon_diff = abs(lon - current_stop['lon'])
                    
                    if lat_diff < STOP_THRESHOLD and lon_diff < STOP_THRESHOLD:
                        # Та же остановка - обновляем время конца
                        current_stop['end_time'] = dt
                    else:
                        # Новая остановка - сохраняем предыдущую
                        duration = (current_stop['end_time'] - current_stop['start_time']).total_seconds() / 60
                        
                        if duration >= MIN_DURATION:
                            # Получаем адрес
                            try:
                                addr_res = requests.get(f"{API_URL}/getaddress",
                                                       headers={'SessionId': session_id},
                                                       params={'lat': current_stop['lat'], 
                                                              'lon': current_stop['lon']},
                                                       timeout=10)
                                address = addr_res.text.strip().strip('"')
                                
                                stops_list.append({
                                    'lat': current_stop['lat'],
                                    'lon': current_stop['lon'],
                                    'duration': round(duration, 1),
                                    'address': address,
                                    'start_time': current_stop['start_time'].strftime('%Y-%m-%d %H:%M')
                                })
                            except:
                                pass
                        
                        # Начинаем новую остановку
                        current_stop = {
                            'lat': lat,
                            'lon': lon,
                            'start_time': dt,
                            'end_time': dt
                        }
            else:
                # Скорость > 5 км/ч - едет
                if current_stop:
                    # Сохраняем остановку если была
                    duration = (current_stop['end_time'] - current_stop['start_time']).total_seconds() / 60
                    
                    if duration >= MIN_DURATION:
                        try:
                            addr_res = requests.get(f"{API_URL}/getaddress",
                                                   headers={'SessionId': session_id},
                                                   params={'lat': current_stop['lat'], 
                                                          'lon': current_stop['lon']},
                                                   timeout=10)
                            address = addr_res.text.strip().strip('"')
                            
                            stops_list.append({
                                'lat': current_stop['lat'],
                                'lon': current_stop['lon'],
                                'duration': round(duration, 1),
                                'address': address,
                                'start_time': current_stop['start_time'].strftime('%Y-%m-%d %H:%M')
                            })
                        except:
                            pass
                    
                    current_stop = None
        
        # Обрабатываем последнюю остановку
        if current_stop:
            duration = (current_stop['end_time'] - current_stop['start_time']).total_seconds() / 60
            if duration >= MIN_DURATION:
                try:
                    addr_res = requests.get(f"{API_URL}/getaddress",
                                           headers={'SessionId': session_id},
                                           params={'lat': current_stop['lat'], 
                                                  'lon': current_stop['lon']},
                                           timeout=10)
                    address = addr_res.text.strip().strip('"')
                    
                    stops_list.append({
                        'lat': current_stop['lat'],
                        'lon': current_stop['lon'],
                        'duration': round(duration, 1),
                        'address': address,
                        'start_time': current_stop['start_time'].strftime('%Y-%m-%d %H:%M')
                    })
                except:
                    pass
        
        # Удаляем дубли по координатам
        unique_stops = []
        seen_coords = set()
        
        for stop in stops_list:
            coord_key = (round(stop['lat'], 4), round(stop['lon'], 4))
            if coord_key not in seen_coords:
                unique_stops.append(stop)
                seen_coords.add(coord_key)
        
        # Сортируем по длительности
        unique_stops.sort(key=lambda x: x['duration'], reverse=True)
        
        print(f"   ✓ Найдено остановок: {len(unique_stops)}")
        
        if unique_stops:
            print(f"\n   📋 Топ-5 остановок:")
            for i, stop in enumerate(unique_stops[:5], 1):
                print(f"      {i}. {stop['address']} ({stop['duration']} мин)")
        
        return unique_stops
    
    except Exception as e:
        print(f"   ❌ Ошибка получения остановок: {e}")
        import traceback
        traceback.print_exc()
        return []


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
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        
        # Новый endpoint для получения остановок
        if path == '/get_stops':
            params = parse_qs(parsed_url.query)
            car_idx = int(params['car_idx'][0])
            date_1 = params['date_1'][0]
            date_2 = params['date_2'][0]
            
            car = vehicles_df.iloc[car_idx]
            
            print(f"\n{'='*60}")
            print(f"ПОЛУЧЕНИЕ ОСТАНОВОК")
            print(f"ТС: {car['Номер авто']}")
            print(f"Период: {date_1} — {date_2}")
            print(f"{'='*60}")
            
            # Подключение к API
            sid = connect_to_api()
            if not sid:
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error": "API connection failed"}')
                return
            
            # Получаем остановки
            try:
                res = requests.get(f"{API_URL}/getobjectsreport",
                                  headers={'SessionId': sid},
                                  params={
                                      'date_from': f"{date_1} 00:00:00",
                                      'date_to': f"{date_2} 23:59:59",
                                      'objuids': str(int(car['ID объекта'])),
                                      'split': 'none',
                                      'param': 'stops'
                                  }, timeout=30).json()
                
                stops = []
                
                if res and len(res) > 0 and res[0].get('periods'):
                    for period in res[0]['periods']:
                        for prm in period.get('prms', []):
                            if prm.get('param') == 'stops':
                                # Парсим остановки
                                stops_data = prm.get('value', [])
                                
                                if isinstance(stops_data, list):
                                    for stop_info in stops_data:
                                        try:
                                            # Получаем координаты и время
                                            if isinstance(stop_info, dict):
                                                lat = stop_info.get('lat')
                                                lon = stop_info.get('lon')
                                                time_start = stop_info.get('time_from', '')
                                                duration = stop_info.get('duration', 0)
                                                
                                                # Фильтруем короткие остановки (< 5 минут)
                                                if duration < 300:
                                                    continue
                                                
                                                if lat and lon:
                                                    # Получаем адрес
                                                    addr_res = requests.get(f"{API_URL}/getaddress",
                                                                          headers={'SessionId': sid},
                                                                          params={'lat': lat, 'lon': lon},
                                                                          timeout=10)
                                                    address = addr_res.text.strip().strip('"')
                                                    
                                                    # Форматируем время
                                                    duration_min = int(duration / 60)
                                                    
                                                    stops.append({
                                                        'time': time_start[:16] if time_start else '',
                                                        'duration': f"{duration_min} мин",
                                                        'address': address,
                                                        'lat': lat,
                                                        'lon': lon
                                                    })
                                                    
                                                    time.sleep(0.1)  # Пауза между запросами адресов
                                        except:
                                            continue
                
                print(f"✓ Найдено остановок: {len(stops)}")
                print(f"{'='*60}\n")
                
                # Отправляем JSON
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.end_headers()
                
                import json
                self.wfile.write(json.dumps({'stops': stops}, ensure_ascii=False).encode('utf-8'))
                return
                
            except Exception as e:
                print(f"❌ Ошибка: {e}")
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
        
        # Главная страница
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
                    
                    <div id="stops-section" style="display: none;">
                        <label>📍 Остановки маршрута (где побывало ТС):</label>
                        <select id="stops" multiple style="height: 150px; width: 100%; padding: 8px; border: 2px solid #e0e0e0; border-radius: 6px; font-size: 14px;">
                            <option disabled>Загрузка остановок...</option>
                        </select>
                        <div class="hint">Удерживайте Ctrl (Cmd на Mac) для выбора нескольких остановок</div>
                        <button type="button" onclick="addStopsToComment()" style="width: 100%; padding: 10px; margin-top: 5px; background: #28a745; color: white; border: none; border-radius: 6px; cursor: pointer; font-size: 13px;">
                            ➕ Добавить выбранные остановки в маршрут
                        </button>
                    </div>
                    
                    <button type="button" onclick="loadStops()" style="width: 100%; padding: 12px; margin-top: 10px; background: #17a2b8; color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: 600;">
                        🔍 Загрузить остановки за период
                    </button>
                    
                    <label style="margin-top: 15px;">💬 Комментарий (маршрут):</label>
                    <textarea id="comment" name="comment" rows="5" placeholder="Маршрут будет добавлен сюда автоматически из остановок..."></textarea>
                    <div class="hint">Или введите комментарий вручную</div>
                    
                    <button type="submit">🔍 СФОРМИРОВАТЬ ПУТЕВОЙ ЛИСТ</button>
                </form>
            </div>
            <script>
                let loadedStops = [];
                
                async function loadStops() {{
                    const carIdx = document.querySelector('select[name="car_idx"]').value;
                    const date1 = document.querySelector('input[name="date_1"]').value;
                    const date2 = document.querySelector('input[name="date_2"]').value;
                    
                    if (!carIdx || !date1 || !date2) {{
                        alert('Пожалуйста, выберите ТС и укажите даты!');
                        return;
                    }}
                    
                    const btn = event.target;
                    btn.disabled = true;
                    btn.textContent = '⏳ Загрузка остановок...';
                    
                    try {{
                        const response = await fetch(`/get_stops?car_idx=${{carIdx}}&date_1=${{date1}}&date_2=${{date2}}`);
                        const data = await response.json();
                        
                        if (data.stops && data.stops.length > 0) {{
                            loadedStops = data.stops;
                            const select = document.getElementById('stops');
                            select.innerHTML = '';
                            
                            data.stops.forEach((stop, idx) => {{
                                const option = document.createElement('option');
                                option.value = stop.address;
                                option.textContent = `${{idx + 1}}. ${{stop.time}} - ${{stop.address}}`;
                                select.appendChild(option);
                            }});
                            
                            document.getElementById('stops-section').style.display = 'block';
                            btn.textContent = `✅ Загружено ${{data.stops.length}} остановок`;
                            btn.style.background = '#28a745';
                        }} else {{
                            alert('Остановки не найдены за указанный период');
                            btn.textContent = '🔍 Загрузить остановки за период';
                            btn.disabled = false;
                        }}
                    }} catch (error) {{
                        alert('Ошибка загрузки остановок: ' + error);
                        btn.textContent = '🔍 Загрузить остановки за период';
                        btn.disabled = false;
                    }}
                }}
                
                function addStopsToComment() {{
                    const select = document.getElementById('stops');
                    const comment = document.getElementById('comment');
                    const selected = Array.from(select.selectedOptions);
                    
                    if (selected.length === 0) {{
                        alert('Выберите хотя бы одну остановку!');
                        return;
                    }}
                    
                    // Формируем маршрут
                    let route = 'Маршрут:\\n';
                    selected.forEach((opt, idx) => {{
                        route += (idx + 1) + '. ' + opt.value + '\\n';
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
        
        # НОВОЕ: Получаем РЕАЛЬНЫЕ остановки за период
        actual_stops = get_actual_stops(sid_api, int(car['ID объекта']), date_1, date_2)
        
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
                
                {'<h3>📍 Остановки на маршруте:</h3>' if actual_stops else ''}
                {'<div style="background: #f0f8ff; padding: 15px; border-radius: 8px; margin: 20px 0;">' if actual_stops else ''}
                {'''<p style="color: #666; font-size: 13px; margin-bottom: 10px;">Выберите остановки для добавления в комментарий:</p>
                <div id="stops-list" style="max-height: 200px; overflow-y: auto; border: 1px solid #ddd; border-radius: 5px; padding: 10px; background: white;">''' if actual_stops else ''}
                {''.join([f'''
                    <label style="display: block; padding: 8px; margin: 3px 0; background: white; border-radius: 4px; cursor: pointer; transition: background 0.2s;" onmouseover="this.style.background='#f9f9f9'" onmouseout="this.style.background='white'">
                        <input type="checkbox" value="{stop['address']}" style="margin-right: 8px;">
                        <strong>{stop['address']}</strong>
                        <span style="color: #999; font-size: 12px; margin-left: 8px;">({stop['duration']} мин)</span>
                    </label>
                ''' for stop in actual_stops]) if actual_stops else ''}
                {'</div>' if actual_stops else ''}
                {'''<button onclick="addSelectedStops()" style="width: 100%; padding: 10px; margin-top: 10px; background: #28a745; color: white; border: none; border-radius: 5px; cursor: pointer; font-weight: bold;">
                    ➕ Добавить выбранные в комментарий
                </button>''' if actual_stops else ''}
                {'</div>' if actual_stops else ''}
                
                <script>
                function addSelectedStops() {{
                    const checkboxes = document.querySelectorAll('#stops-list input[type="checkbox"]:checked');
                    const comment = document.querySelector('.comment-box');
                    
                    if (checkboxes.length === 0) {{
                        alert('Выберите хотя бы одну остановку!');
                        return;
                    }}
                    
                    let stops = '\\nМаршрут:\\n';
                    checkboxes.forEach((cb, idx) => {{
                        stops += (idx + 1) + '. ' + cb.value + '\\n';
                        cb.checked = false;
                    }});
                    
                    const currentText = comment.textContent.trim();
                    if (currentText && currentText !== 'Добавьте комментарий здесь...') {{
                        comment.textContent = currentText + stops;
                    }} else {{
                        comment.textContent = stops.trim();
                    }}
                }}
                </script>
                
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