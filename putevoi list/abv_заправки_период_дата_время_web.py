#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ВЕБ-ОТЧЁТ ПО ЗАПРАВКАМ ЗА ПЕРИОД
С детальной статистикой и картой
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
import pandas as pd
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
TARGET_FILE = r"c:/Users/snltv/Desktop/ii/putevoi list/CAN_пробег_датчики_06_02_2026.xlsx"
PORT = 8080

# Глобальные переменные
vehicles_df = None
session_id = None

# ============================================================================
# API ФУНКЦИИ
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
    """Получение заправок за период"""
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
    
    options_html = '<option value="all">📊 ВСЕ АВТОМОБИЛИ (сводный отчёт)</option>\n'
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
        <title>Отчёт по заправкам за период</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ font-family: 'Segoe UI', sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px; }}
            .container {{ max-width: 600px; width: 100%; }}
            .card {{ background: white; border-radius: 20px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); padding: 40px; animation: slideIn 0.5s ease; }}
            @keyframes slideIn {{ from {{ opacity: 0; transform: translateY(-30px); }} to {{ opacity: 1; transform: translateY(0); }} }}
            .header {{ text-align: center; margin-bottom: 30px; }}
            .icon {{ font-size: 60px; margin-bottom: 15px; }}
            h1 {{ color: #333; font-size: 28px; margin-bottom: 10px; }}
            .subtitle {{ color: #666; font-size: 14px; }}
            .form-group {{ margin-bottom: 25px; }}
            label {{ display: block; color: #333; font-weight: 600; margin-bottom: 8px; font-size: 14px; }}
            select, input[type="datetime-local"] {{ width: 100%; padding: 12px 15px; border: 2px solid #e0e0e0; border-radius: 10px; font-size: 14px; font-family: inherit; transition: all 0.3s; background: white; }}
            select:focus, input[type="datetime-local"]:focus {{ outline: none; border-color: #667eea; box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1); }}
            .btn {{ width: 100%; padding: 15px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border: none; border-radius: 10px; font-size: 16px; font-weight: 600; cursor: pointer; transition: all 0.3s; margin-top: 10px; }}
            .btn:hover {{ transform: translateY(-2px); box-shadow: 0 10px 30px rgba(102, 126, 234, 0.4); }}
            .loading {{ display: none; text-align: center; margin-top: 20px; color: #667eea; }}
            .spinner {{ border: 3px solid #f3f3f3; border-top: 3px solid #667eea; border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; margin: 0 auto; }}
            @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="card">
                <div class="header">
                    <div class="icon">⛽</div>
                    <h1>Отчёт по заправкам за период</h1>
                    <p class="subtitle">Выберите ТС и укажите период анализа</p>
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
                        <label for="dateFrom">📅 Начало периода</label>
                        <input type="datetime-local" id="dateFrom" name="date_from" required>
                    </div>
                    <div class="form-group">
                        <label for="dateTo">📅 Конец периода</label>
                        <input type="datetime-local" id="dateTo" name="date_to" required>
                    </div>
                    <button type="submit" class="btn">🔍 Сформировать отчёт</button>
                </form>
                <div class="loading" id="loading">
                    <div class="spinner"></div>
                    <p style="margin-top: 10px;">Загрузка данных...</p>
                </div>
            </div>
        </div>
        <script>
            const now = new Date();
            const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
            document.getElementById('dateTo').value = now.toISOString().slice(0, 16);
            document.getElementById('dateFrom').value = weekAgo.toISOString().slice(0, 16);
            document.getElementById('reportForm').addEventListener('submit', function() {{
                document.getElementById('loading').style.display = 'block';
            }});
        </script>
    </body>
    </html>
    """
    
    return html


def generate_summary_report_html(period_start, period_end, all_results):
    """Генерация сводного отчёта по всем ТС"""
    
    if not all_results:
        return "<p style='text-align:center; padding:50px; color:#999;'>Нет данных за указанный период</p>"
    
    # Общая статистика
    total_vehicles = len(all_results)
    total_fuelings = sum(len(r['fuelings']) for r in all_results)
    total_volume = sum(sum(f['volume'] for f in r['fuelings']) for r in all_results)
    avg_volume = total_volume / total_fuelings if total_fuelings > 0 else 0
    estimated_cost = total_volume * 50
    
    # Таблица по ТС
    rows_html = ""
    for i, result in enumerate(all_results, 1):
        vehicle_name = result['vehicle']
        driver_name = result['driver']
        fuelings = result['fuelings']
        
        count = len(fuelings)
        volume = sum(f['volume'] for f in fuelings)
        avg = volume / count if count > 0 else 0
        
        if count == 0:
            status_badge = '<span style="color:#999;">Нет заправок</span>'
        else:
            status_badge = f'<span style="color:#28a745; font-weight:bold;">✓ {count} заправок</span>'
        
        rows_html += f"""
        <tr>
            <td style="text-align:center; font-weight:bold; color:#667eea;">{i}</td>
            <td><strong>{vehicle_name}</strong></td>
            <td>{driver_name}</td>
            <td style="text-align:center; font-size:16px; font-weight:bold;">{count}</td>
            <td style="text-align:right; color:#28a745; font-weight:bold; font-size:16px;">{volume:.1f} л</td>
            <td style="text-align:right;">{avg:.1f} л</td>
            <td>{status_badge}</td>
        </tr>
        """
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Сводный отчёт по всем ТС</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ font-family: 'Segoe UI', sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; min-height: 100vh; }}
            .container {{ max-width: 1400px; margin: 0 auto; }}
            .card {{ background: white; border-radius: 15px; box-shadow: 0 10px 40px rgba(0,0,0,0.2); padding: 30px; margin-bottom: 20px; }}
            h1 {{ color: #333; font-size: 32px; margin-bottom: 10px; }}
            h2 {{ color: #333; font-size: 24px; margin-bottom: 20px; }}
            .period {{ background: #f8f9ff; padding: 15px 20px; border-radius: 10px; color: #666; margin: 15px 0; border-left: 4px solid #667eea; }}
            
            .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 15px; margin: 25px 0; }}
            .stat-card {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 12px; text-align: center; transition: transform 0.3s; }}
            .stat-card:hover {{ transform: translateY(-5px); }}
            .stat-card.highlight {{ background: linear-gradient(135deg, #28a745 0%, #20c997 100%); }}
            .stat-card.info {{ background: linear-gradient(135deg, #17a2b8 0%, #138496 100%); }}
            .stat-value {{ font-size: 36px; font-weight: bold; margin-bottom: 8px; text-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            .stat-label {{ font-size: 13px; opacity: 0.95; text-transform: uppercase; letter-spacing: 0.5px; }}
            
            .summary-box {{ background: linear-gradient(135deg, #e8f5e9 0%, #c8e6c9 100%); padding: 30px; border-radius: 12px; margin: 25px 0; border-left: 6px solid #28a745; }}
            .summary-title {{ font-size: 22px; font-weight: bold; color: #1b5e20; margin-bottom: 25px; text-align: center; }}
            .summary-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 20px; }}
            .summary-item {{ text-align: center; padding: 20px; background: white; border-radius: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
            .summary-value {{ font-size: 32px; font-weight: bold; color: #28a745; margin-bottom: 10px; }}
            .summary-label {{ font-size: 13px; color: #666; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600; }}
            
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            thead {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; }}
            th {{ padding: 16px 12px; text-align: left; font-weight: 600; text-transform: uppercase; font-size: 12px; letter-spacing: 0.5px; }}
            td {{ padding: 16px 12px; border-bottom: 1px solid #f0f0f0; }}
            tr:hover {{ background: #f8f9ff; }}
            
            .btn {{ display: inline-block; padding: 14px 35px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; text-decoration: none; border-radius: 25px; font-weight: 600; margin: 10px 5px; border: none; cursor: pointer; transition: all 0.3s; font-size: 15px; }}
            .btn:hover {{ transform: translateY(-2px); box-shadow: 0 8px 25px rgba(102, 126, 234, 0.4); }}
            
            @media print {{ body {{ background: white; padding: 0; }} .no-print {{ display: none; }} .card {{ box-shadow: none; }} }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="card">
                <h1>📊 Сводный отчёт по заправкам всех ТС</h1>
                <div class="period">📅 Период анализа: <strong>{period_start}</strong> — <strong>{period_end}</strong></div>
                
                <div class="stats">
                    <div class="stat-card info">
                        <div class="stat-value">{total_vehicles}</div>
                        <div class="stat-label">Транспортных средств</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value">{total_fuelings}</div>
                        <div class="stat-label">Всего заправок</div>
                    </div>
                    <div class="stat-card highlight">
                        <div class="stat-value">{total_volume:.1f} л</div>
                        <div class="stat-label">Общий объём</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value">{avg_volume:.1f} л</div>
                        <div class="stat-label">Средний объём</div>
                    </div>
                </div>
                
                <div class="summary-box">
                    <div class="summary-title">💰 Итоговая сводка по парку за период</div>
                    <div class="summary-grid">
                        <div class="summary-item">
                            <div class="summary-value">{total_vehicles}</div>
                            <div class="summary-label">ТС в парке</div>
                        </div>
                        <div class="summary-item">
                            <div class="summary-value">{total_fuelings}</div>
                            <div class="summary-label">Заправок</div>
                        </div>
                        <div class="summary-item">
                            <div class="summary-value">{total_volume:.1f} л</div>
                            <div class="summary-label">Топлива</div>
                        </div>
                        <div class="summary-item">
                            <div class="summary-value">~{estimated_cost:,.0f} ₴</div>
                            <div class="summary-label">Стоимость*</div>
                        </div>
                    </div>
                    <p style="margin-top: 20px; font-size: 11px; color: #666; text-align: center;">* Приблизительная стоимость по 50 грн/л</p>
                </div>
            </div>
            
            <div class="card">
                <h2>🚗 Детализация по каждому транспортному средству</h2>
                <table>
                    <thead>
                        <tr>
                            <th style="width:50px; text-align:center;">#</th>
                            <th>Автомобиль</th>
                            <th>Водитель</th>
                            <th style="width:100px; text-align:center;">Заправок</th>
                            <th style="width:120px; text-align:right;">Объём</th>
                            <th style="width:120px; text-align:right;">В среднем</th>
                            <th style="width:150px;">Статус</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows_html}
                    </tbody>
                    <tfoot>
                        <tr style="background:#f8f9fa; font-weight:bold; border-top:3px solid #667eea;">
                            <td colspan="3" style="text-align:right; padding:16px;">ИТОГО:</td>
                            <td style="text-align:center; font-size:18px; color:#667eea;">{total_fuelings}</td>
                            <td style="text-align:right; font-size:18px; color:#28a745;">{total_volume:.1f} л</td>
                            <td style="text-align:right; font-size:16px;">{avg_volume:.1f} л</td>
                            <td></td>
                        </tr>
                    </tfoot>
                </table>
                
                <div class="no-print" style="margin-top: 25px; text-align: center;">
                    <button class="btn" onclick="window.print()">🖨️ Печать отчёта</button>
                    <a href="/" class="btn">◀️ Новый отчёт</a>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    
    return html


def generate_report_html(vehicle_name, driver_name, period_start, period_end, fuelings):
    """Генерация HTML отчёта с расширенной статистикой"""
    
    if not fuelings:
        total_volume = 0
        estimated_cost = 0
        map_html = "<p style='text-align:center; color:#999; padding:50px;'>За указанный период заправок не найдено</p>"
    else:
        total_volume = sum(f['volume'] for f in fuelings)
        estimated_cost = total_volume * 50  # 50 грн за литр
        
        markers_js = []
        for i, f in enumerate(fuelings, 1):
            marker = f"""
            L.marker([{f['lat']}, {f['lon']}]).addTo(map)
                .bindPopup(`<b>Заправка #{i}</b><br>Объём: <b>{f['volume']} л</b><br>Время: {f['time']}<br>Адрес: {f['address']}`);
            """
            markers_js.append(marker)
        
        center_lat = sum(f['lat'] for f in fuelings) / len(fuelings)
        center_lon = sum(f['lon'] for f in fuelings) / len(fuelings)
        
        map_html = f"""
        <div id="map" style="height: 450px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);"></div>
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
            <td style="text-align:center; font-weight: bold; color: #667eea;">{i}</td>
            <td>{f['time']}</td>
            <td style="font-weight:bold; color:#28a745; font-size:16px;">{f['volume']} л</td>
            <td>{f['address']}</td>
            <td style="text-align:center;">
                <a href="{maps_link}" target="_blank" style="color:#1a73e8; text-decoration:none; font-weight: 600;">📍 Карта</a>
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
        <title>Заправки за период - {vehicle_name}</title>
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ font-family: 'Segoe UI', sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; min-height: 100vh; }}
            .container {{ max-width: 1200px; margin: 0 auto; }}
            .card {{ background: white; border-radius: 15px; box-shadow: 0 10px 40px rgba(0,0,0,0.2); padding: 30px; margin-bottom: 20px; }}
            h1 {{ color: #333; font-size: 32px; margin-bottom: 10px; }}
            h2 {{ color: #333; font-size: 24px; margin-bottom: 20px; }}
            .vehicle-info {{ display: flex; gap: 30px; margin-top: 15px; flex-wrap: wrap; }}
            .info-item {{ display: flex; align-items: center; gap: 10px; color: #666; }}
            .info-label {{ font-weight: 600; color: #333; }}
            .period {{ background: #f8f9ff; padding: 15px 20px; border-radius: 10px; color: #666; margin-top: 15px; border-left: 4px solid #667eea; }}
            
            /* УЛУЧШЕННАЯ СТАТИСТИКА */
            .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 15px; margin: 25px 0; }}
            .stat-card {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 12px; text-align: center; transition: transform 0.3s; }}
            .stat-card:hover {{ transform: translateY(-5px); }}
            .stat-card.highlight {{ background: linear-gradient(135deg, #28a745 0%, #20c997 100%); }}
            .stat-card.warning {{ background: linear-gradient(135deg, #ffc107 0%, #ff9800 100%); }}
            .stat-value {{ font-size: 36px; font-weight: bold; margin-bottom: 8px; text-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            .stat-label {{ font-size: 13px; opacity: 0.95; text-transform: uppercase; letter-spacing: 0.5px; }}
            
            /* ИТОГОВЫЙ БЛОК */
            .summary-box {{ background: linear-gradient(135deg, #e8f5e9 0%, #c8e6c9 100%); padding: 25px; border-radius: 12px; margin: 25px 0; border-left: 6px solid #28a745; }}
            .summary-title {{ font-size: 20px; font-weight: bold; color: #1b5e20; margin-bottom: 20px; text-align: center; }}
            .summary-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 20px; }}
            .summary-item {{ text-align: center; padding: 15px; background: white; border-radius: 10px; }}
            .summary-value {{ font-size: 28px; font-weight: bold; color: #28a745; margin-bottom: 8px; }}
            .summary-label {{ font-size: 12px; color: #666; text-transform: uppercase; letter-spacing: 0.5px; }}
            
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            thead {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; }}
            th {{ padding: 16px 12px; text-align: left; font-weight: 600; text-transform: uppercase; font-size: 12px; letter-spacing: 0.5px; }}
            td {{ padding: 16px 12px; border-bottom: 1px solid #f0f0f0; }}
            tr:hover {{ background: #f8f9ff; }}
            
            .btn {{ display: inline-block; padding: 14px 35px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; text-decoration: none; border-radius: 25px; font-weight: 600; margin: 10px 5px; border: none; cursor: pointer; transition: all 0.3s; font-size: 15px; }}
            .btn:hover {{ transform: translateY(-2px); box-shadow: 0 8px 25px rgba(102, 126, 234, 0.4); }}
            
            @media print {{ body {{ background: white; padding: 0; }} .no-print {{ display: none; }} .card {{ box-shadow: none; }} }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="card">
                <h1>⛽ Отчёт по заправкам за период</h1>
                <div class="vehicle-info">
                    <div class="info-item"><span class="info-label">🚗 Автомобиль:</span><span>{vehicle_name}</span></div>
                    <div class="info-item"><span class="info-label">👤 Водитель:</span><span>{driver_name}</span></div>
                </div>
                <div class="period">📅 Период анализа: <strong>{period_start}</strong> — <strong>{period_end}</strong></div>
                
                <div class="stats">
                    <div class="stat-card">
                        <div class="stat-value">{len(fuelings)}</div>
                        <div class="stat-label">Всего заправок</div>
                    </div>
                    <div class="stat-card highlight">
                        <div class="stat-value">{total_volume:.1f} л</div>
                        <div class="stat-label">Заправлено топлива</div>
                    </div>
                </div>
                
                {f'''
                <div class="summary-box">
                    <div class="summary-title">📊 Итоговая сводка за период</div>
                    <div class="summary-grid">
                        <div class="summary-item">
                            <div class="summary-value">{len(fuelings)}</div>
                            <div class="summary-label">Количество заправок</div>
                        </div>
                        <div class="summary-item">
                            <div class="summary-value">{total_volume:.1f} л</div>
                            <div class="summary-label">Всего заправлено</div>
                        </div>
                        <div class="summary-item">
                            <div class="summary-value">~{estimated_cost:,.0f} ₴</div>
                            <div class="summary-label">Примерная стоимость*</div>
                        </div>
                    </div>
                    <p style="margin-top: 18px; font-size: 11px; color: #666; text-align: center;">* Расчёт по 50 грн/л</p>
                </div>
                ''' if fuelings else ''}
            </div>
            
            <div class="card">
                <h2>📍 Карта всех заправок за период</h2>
                {map_html}
            </div>
            
            <div class="card">
                <h2>📋 Детальный список всех заправок</h2>
                <table>
                    <thead>
                        <tr>
                            <th style="width:60px; text-align:center;">#</th>
                            <th style="width:180px;">Дата и время</th>
                            <th style="width:120px;">Объём</th>
                            <th>Адрес заправки</th>
                            <th style="width:100px; text-align:center;">Карта</th>
                        </tr>
                    </thead>
                    <tbody>{rows_html}</tbody>
                </table>
                
                <div class="no-print" style="margin-top: 25px; text-align: center;">
                    <button class="btn" onclick="window.print()">🖨️ Печать отчёта</button>
                    <a href="/" class="btn">◀️ Новый отчёт</a>
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
        """Отключение логов"""
        pass
    
    def do_GET(self):
        """Обработка GET запросов"""
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        
        if path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            
            html = generate_form_html()
            self.wfile.write(html.encode('utf-8'))
        
        elif path == '/report':
            params = parse_qs(parsed_url.query)
            
            oid_param = params.get('oid', [''])[0]
            date_from = params.get('date_from', [''])[0].replace('T', ' ') + ':00'
            date_to = params.get('date_to', [''])[0].replace('T', ' ') + ':00'
            
            # Проверка: все ТС или одно
            if oid_param == 'all':
                # СВОДНЫЙ ОТЧЁТ ПО ВСЕМ ТС
                print(f"\n{'='*60}")
                print(f"📊 Формирование СВОДНОГО отчёта по всем ТС")
                print(f"   Период: {date_from} — {date_to}")
                print(f"{'='*60}")
                
                all_results = []
                
                for idx, row in vehicles_df.iterrows():
                    oid = int(row['ID объекта'])
                    vehicle_name = row.get('Номер авто', f'ID_{oid}')
                    driver_name = row.get('ФИО', 'Не указан')
                    
                    print(f"  {idx+1}. {vehicle_name}...", end=' ', flush=True)
                    
                    fuelings = get_fuelings(session_id, oid, date_from, date_to)
                    
                    if fuelings:
                        total = sum(f['volume'] for f in fuelings)
                        print(f"✓ {len(fuelings)} заправок, {total:.1f} л")
                    else:
                        print("Нет данных")
                    
                    all_results.append({
                        'vehicle': vehicle_name,
                        'driver': driver_name,
                        'fuelings': fuelings
                    })
                
                total_fuelings = sum(len(r['fuelings']) for r in all_results)
                total_volume = sum(sum(f['volume'] for f in r['fuelings']) for r in all_results)
                
                print(f"\n{'='*60}")
                print(f"✓ Обработано ТС: {len(all_results)}")
                print(f"✓ Всего заправок: {total_fuelings}")
                print(f"✓ Общий объём: {total_volume:.1f} л")
                print(f"{'='*60}\n")
                
                # Генерация сводного отчёта
                html = generate_summary_report_html(date_from, date_to, all_results)
            
            else:
                # ОТЧЁТ ПО ОДНОМУ ТС
                oid = int(oid_param)
                
                # Поиск ТС
                vehicle_row = vehicles_df[vehicles_df['ID объекта'] == oid].iloc[0]
                vehicle_name = vehicle_row.get('Номер авто', f'ID_{oid}')
                driver_name = vehicle_row.get('ФИО', 'Не указан')
                
                print(f"\n{'='*60}")
                print(f"📊 Формирование отчёта")
                print(f"   ТС: {vehicle_name}")
                print(f"   Период: {date_from} — {date_to}")
                print(f"{'='*60}")
                
                # Получение заправок
                fuelings = get_fuelings(session_id, oid, date_from, date_to)
                
                print(f"✓ Найдено заправок: {len(fuelings)}")
                if fuelings:
                    total = sum(f['volume'] for f in fuelings)
                    print(f"✓ Общий объём: {total:.1f} л")
                print(f"{'='*60}\n")
                
                # Генерация отчёта по одному ТС
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
    print("⛽ ВЕБ-ОТЧЁТ ПО ЗАПРАВКАМ ЗА ПЕРИОД")
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
    
    url = f"http://localhost:{PORT}"
    print(f"\n✅ Сервер запущен!")
    print(f"🌐 Откройте в браузере: {url}")
    print("\n💡 Нажмите Ctrl+C для остановки\n")
    
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\n⏹️  Сервер остановлен")


if __name__ == "__main__":
    main()
