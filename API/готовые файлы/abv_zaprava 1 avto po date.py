#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ВЕБ-ИНТЕРФЕЙС ДЛЯ ОТЧЁТОВ ПО ЗАПРАВКАМ
Запускает локальный сервер с HTML формой
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
import pandas as pd
import json
import time
from urllib.parse import parse_qs, urlparse
import webbrowser
import threading

# ============================================================================
# НАСТРОЙКИ
# ============================================================================

API_URL = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN = "abvprom"
PASSWORD = "29328"
TARGET_FILE = "CAN_пробег_датчики_06_02_2026.xlsx"
PORT = 8080

# Глобальные переменные
vehicles_df = None
session_id = None

# ============================================================================
# ФУНКЦИИ API
# ============================================================================

def connect_to_api():
    """Подключение к API"""
    try:
        res = requests.get(f"{API_URL}/connect", 
                           params={'login': LOGIN, 'password': PASSWORD, 
                                   'lang': 'ru-ru', 'timezone': '3'},
                           timeout=10)
        return res.headers.get('sessionid')
    except:
        return None


def get_address(sid, lat, lon):
    """Получение адреса по координатам"""
    try:
        res = requests.get(f"{API_URL}/getaddress", 
                           headers={'SessionId': sid}, 
                           params={'lat': lat, 'lon': lon}, 
                           timeout=10)
        return res.text.strip().strip('"') if res.status_code == 200 else "Адрес не определен"
    except:
        return "Ошибка геокодера"


def get_fuelings(sid, oid, date_from, date_to):
    """Получение заправок"""
    results = []
    
    try:
        f_res = requests.get(
            f"{API_URL}/fuelings", 
            headers={'SessionId': sid}, 
            params={'oid': oid, 'from': date_from, 'to': date_to},
            timeout=30
        )
        
        if f_res.status_code != 200:
            return []
        
        data = f_res.json()
        
        if data.get('result') == 'Ok':
            events = data.get('fuelings', [])
            
            for event in events:
                if event.get('fuel_type') == 'fueling':
                    lat = event.get('lat')
                    lon = event.get('lon')
                    
                    address = get_address(sid, lat, lon)
                    
                    results.append({
                        'time': event.get('start_time'),
                        'volume': round(float(event.get('volume', 0)), 1),
                        'lat': lat,
                        'lon': lon,
                        'address': address
                    })
                    
                    time.sleep(0.1)
    
    except Exception as e:
        print(f"Ошибка получения заправок: {e}")
    
    return results


# ============================================================================
# HTML ГЕНЕРАЦИЯ
# ============================================================================

def generate_form_html():
    """Генерация HTML формы выбора"""
    
    # Создаём список ТС для select
    options_html = ""
    for i, row in vehicles_df.iterrows():
        oid = int(row['ID объекта'])
        vehicle = row.get('Номер авто', f'ID_{oid}')
        driver = row.get('ФИО', '')
        options_html += f'<option value="{oid}">{vehicle} - {driver}</option>\n'
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Отчёт по заправкам</title>
        <style>
            * {{
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }}
            
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 20px;
            }}
            
            .container {{
                max-width: 600px;
                width: 100%;
            }}
            
            .card {{
                background: white;
                border-radius: 20px;
                box-shadow: 0 20px 60px rgba(0,0,0,0.3);
                padding: 40px;
                animation: slideIn 0.5s ease;
            }}
            
            @keyframes slideIn {{
                from {{
                    opacity: 0;
                    transform: translateY(-30px);
                }}
                to {{
                    opacity: 1;
                    transform: translateY(0);
                }}
            }}
            
            .header {{
                text-align: center;
                margin-bottom: 30px;
            }}
            
            .icon {{
                font-size: 60px;
                margin-bottom: 15px;
            }}
            
            h1 {{
                color: #333;
                font-size: 28px;
                margin-bottom: 10px;
            }}
            
            .subtitle {{
                color: #666;
                font-size: 14px;
            }}
            
            .form-group {{
                margin-bottom: 25px;
            }}
            
            label {{
                display: block;
                color: #333;
                font-weight: 600;
                margin-bottom: 8px;
                font-size: 14px;
            }}
            
            select, input[type="datetime-local"] {{
                width: 100%;
                padding: 12px 15px;
                border: 2px solid #e0e0e0;
                border-radius: 10px;
                font-size: 14px;
                font-family: inherit;
                transition: all 0.3s;
                background: white;
            }}
            
            select:focus, input[type="datetime-local"]:focus {{
                outline: none;
                border-color: #667eea;
                box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
            }}
            
            select {{
                cursor: pointer;
            }}
            
            .btn {{
                width: 100%;
                padding: 15px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                border: none;
                border-radius: 10px;
                font-size: 16px;
                font-weight: 600;
                cursor: pointer;
                transition: all 0.3s;
                margin-top: 10px;
            }}
            
            .btn:hover {{
                transform: translateY(-2px);
                box-shadow: 0 10px 30px rgba(102, 126, 234, 0.4);
            }}
            
            .btn:active {{
                transform: translateY(0);
            }}
            
            .loading {{
                display: none;
                text-align: center;
                margin-top: 20px;
                color: #667eea;
            }}
            
            .spinner {{
                border: 3px solid #f3f3f3;
                border-top: 3px solid #667eea;
                border-radius: 50%;
                width: 40px;
                height: 40px;
                animation: spin 1s linear infinite;
                margin: 0 auto;
            }}
            
            @keyframes spin {{
                0% {{ transform: rotate(0deg); }}
                100% {{ transform: rotate(360deg); }}
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="card">
                <div class="header">
                    <div class="icon">⛽</div>
                    <h1>Отчёт по заправкам</h1>
                    <p class="subtitle">Выберите транспортное средство и период</p>
                </div>
                
                <form id="reportForm" action="/report" method="GET">
                    <div class="form-group">
                        <label for="vehicle">🚗 Транспортное средство</label>
                        <select id="vehicle" name="oid" required>
                            <option value="">-- Выберите ТС --</option>
                            {options_html}
                        </select>
                    </div>
                    
                    <div class="form-group">
                        <label for="dateFrom">📅 От (дата и время)</label>
                        <input type="datetime-local" id="dateFrom" name="date_from" required>
                    </div>
                    
                    <div class="form-group">
                        <label for="dateTo">📅 До (дата и время)</label>
                        <input type="datetime-local" id="dateTo" name="date_to" required>
                    </div>
                    
                    <button type="submit" class="btn">
                        🔍 Сформировать отчёт
                    </button>
                </form>
                
                <div class="loading" id="loading">
                    <div class="spinner"></div>
                    <p style="margin-top: 10px;">Загрузка данных...</p>
                </div>
            </div>
        </div>
        
        <script>
            // Установка значений по умолчанию
            const now = new Date();
            const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
            
            document.getElementById('dateTo').value = now.toISOString().slice(0, 16);
            document.getElementById('dateFrom').value = weekAgo.toISOString().slice(0, 16);
            
            // Обработка отправки формы
            document.getElementById('reportForm').addEventListener('submit', function() {{
                document.getElementById('loading').style.display = 'block';
            }});
        </script>
    </body>
    </html>
    """
    
    return html


def generate_report_html(vehicle_name, driver_name, period_start, period_end, fuelings):
    """Генерация HTML отчёта"""
    
    if not fuelings:
        total_volume = 0
        avg_volume = 0
        map_html = "<p style='text-align:center; color:#999; padding:50px;'>Заправок не найдено</p>"
    else:
        total_volume = sum(f['volume'] for f in fuelings)
        avg_volume = total_volume / len(fuelings)
        
        markers_js = []
        for i, f in enumerate(fuelings, 1):
            marker = f"""
            L.marker([{f['lat']}, {f['lon']}]).addTo(map)
                .bindPopup(`<b>Заправка #{i}</b><br>Объём: <b>{f['volume']} л</b><br>Время: {f['time']}<br>Адрес: {f['address']}`);
            """
            markers_js.append(marker)
        
        center_lat = fuelings[0]['lat']
        center_lon = fuelings[0]['lon']
        
        map_html = f"""
        <div id="map" style="height: 400px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);"></div>
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        <script>
            var map = L.map('map').setView([{center_lat}, {center_lon}], 10);
            L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
                attribution: '© OpenStreetMap'
            }}).addTo(map);
            {''.join(markers_js)}
        </script>
        """
    
    rows_html = ""
    for i, f in enumerate(fuelings, 1):
        maps_link = f"https://www.google.com/maps?q={f['lat']},{f['lon']}"
        rows_html += f"""
        <tr>
            <td style="text-align:center;">{i}</td>
            <td>{f['time']}</td>
            <td style="font-weight:bold; color:#28a745; font-size:16px;">{f['volume']} л</td>
            <td>{f['address']}</td>
            <td style="text-align:center;">
                <a href="{maps_link}" target="_blank" style="color:#1a73e8; text-decoration:none;">📍 Карта</a>
            </td>
        </tr>
        """
    
    if not rows_html:
        rows_html = "<tr><td colspan='5' style='text-align:center; color:#999; padding:30px;'>Заправок не найдено</td></tr>"
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Заправки - {vehicle_name}</title>
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ font-family: 'Segoe UI', sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; min-height: 100vh; }}
            .container {{ max-width: 1200px; margin: 0 auto; }}
            .card {{ background: white; border-radius: 15px; box-shadow: 0 10px 40px rgba(0,0,0,0.2); padding: 30px; margin-bottom: 20px; }}
            h1 {{ color: #333; font-size: 32px; margin-bottom: 10px; }}
            .vehicle-info {{ display: flex; gap: 30px; margin-top: 15px; flex-wrap: wrap; }}
            .info-item {{ display: flex; align-items: center; gap: 10px; color: #666; }}
            .info-label {{ font-weight: 600; color: #333; }}
            .period {{ background: #f8f9ff; padding: 15px 20px; border-radius: 10px; color: #666; margin-top: 15px; border-left: 4px solid #667eea; }}
            .stats {{ display: flex; gap: 20px; margin: 20px 0; flex-wrap: wrap; }}
            .stat-card {{ flex: 1; min-width: 200px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 10px; text-align: center; }}
            .stat-value {{ font-size: 36px; font-weight: bold; margin-bottom: 5px; }}
            .stat-label {{ font-size: 14px; opacity: 0.9; text-transform: uppercase; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            thead {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; }}
            th {{ padding: 15px 10px; text-align: left; font-weight: 600; text-transform: uppercase; font-size: 12px; }}
            td {{ padding: 15px 10px; border-bottom: 1px solid #f0f0f0; }}
            tr:hover {{ background: #f8f9ff; }}
            .btn {{ display: inline-block; padding: 12px 30px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; text-decoration: none; border-radius: 25px; font-weight: 600; margin: 10px 5px; border: none; cursor: pointer; }}
            .btn:hover {{ transform: translateY(-2px); box-shadow: 0 5px 20px rgba(102, 126, 234, 0.4); }}
            @media print {{ body {{ background: white; padding: 0; }} .no-print {{ display: none; }} .card {{ box-shadow: none; }} }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="card">
                <h1>⛽ Отчёт по заправкам</h1>
                <div class="vehicle-info">
                    <div class="info-item"><span class="info-label">🚗 Автомобиль:</span><span>{vehicle_name}</span></div>
                    <div class="info-item"><span class="info-label">👤 Водитель:</span><span>{driver_name}</span></div>
                </div>
                <div class="period">📅 Период: <strong>{period_start}</strong> — <strong>{period_end}</strong></div>
                <div class="stats">
                    <div class="stat-card"><div class="stat-value">{len(fuelings)}</div><div class="stat-label">Заправок</div></div>
                    <div class="stat-card"><div class="stat-value">{total_volume:.1f} л</div><div class="stat-label">Всего залито</div></div>
                    <div class="stat-card"><div class="stat-value">{avg_volume:.1f} л</div><div class="stat-label">Средний объём</div></div>
                </div>
            </div>
            <div class="card"><h2 style="margin-bottom: 20px; color: #333;">📍 Карта заправок</h2>{map_html}</div>
            <div class="card">
                <h2 style="margin-bottom: 20px; color: #333;">📋 Детали заправок</h2>
                <table>
                    <thead><tr><th style="width:50px;">#</th><th>Дата и время</th><th>Объём</th><th>Адрес</th><th style="width:100px; text-align:center;">Карта</th></tr></thead>
                    <tbody>{rows_html}</tbody>
                </table>
                <div class="no-print" style="margin-top: 20px; text-align: center;">
                    <button class="btn" onclick="window.print()">🖨️ Печать</button>
                    <a href="/" class="btn">◀️ Назад</a>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    
    return html


# ============================================================================
# HTTP СЕРВЕР
# ============================================================================

class RequestHandler(BaseHTTPRequestHandler):
    
    def log_message(self, format, *args):
        """Отключение логов сервера"""
        pass
    
    def do_GET(self):
        """Обработка GET запросов"""
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        
        if path == '/':
            # Главная страница - форма
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            
            html = generate_form_html()
            self.wfile.write(html.encode('utf-8'))
        
        elif path == '/report':
            # Генерация отчёта
            params = parse_qs(parsed_url.query)
            
            oid = int(params.get('oid', [0])[0])
            date_from = params.get('date_from', [''])[0].replace('T', ' ') + ':00'
            date_to = params.get('date_to', [''])[0].replace('T', ' ') + ':00'
            
            # Поиск ТС в DataFrame
            vehicle_row = vehicles_df[vehicles_df['ID объекта'] == oid].iloc[0]
            vehicle_name = vehicle_row.get('Номер авто', f'ID_{oid}')
            driver_name = vehicle_row.get('ФИО', 'Не указан')
            
            # Получение заправок
            fuelings = get_fuelings(session_id, oid, date_from, date_to)
            
            # Генерация HTML
            html = generate_report_html(vehicle_name, driver_name, date_from, date_to, fuelings)
            
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(html.encode('utf-8'))
        
        else:
            self.send_response(404)
            self.end_headers()


# ============================================================================
# MAIN
# ============================================================================

def main():
    global vehicles_df, session_id
    
    print("\n" + "="*70)
    print("⛽ ВЕБ-ИНТЕРФЕЙС ОТЧЁТОВ ПО ЗАПРАВКАМ")
    print("="*70)
    
    # Загрузка данных
    print("\n📂 Загрузка данных...")
    try:
        vehicles_df = pd.read_excel(TARGET_FILE)
        print(f"✓ Загружено {len(vehicles_df)} ТС")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        input("\nНажмите Enter...")
        return
    
    # Подключение к API
    print("\n🔗 Подключение к API...")
    session_id = connect_to_api()
    if not session_id:
        print("❌ Ошибка авторизации")
        input("\nНажмите Enter...")
        return
    print("✓ Подключено")
    
    # Запуск сервера
    print(f"\n🚀 Запуск веб-сервера на порту {PORT}...")
    
    server = HTTPServer(('localhost', PORT), RequestHandler)
    
    # Открытие браузера
    url = f"http://localhost:{PORT}"
    print(f"\n✅ Сервер запущен!")
    print(f"🌐 Откройте в браузере: {url}")
    print("\n💡 Нажмите Ctrl+C для остановки сервера\n")
    
    # Открываем браузер автоматически через 1 секунду
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\n⏹️  Сервер остановлен")


if __name__ == "__main__":
    main()
