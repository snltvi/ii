#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ВЕБ-ИНТЕРФЕЙС ДЛЯ ПУТЕВЫХ ЛИСТОВ
Выбор одного ТС или всех, период времени, HTML отчёт
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
        return res.headers.get('sessionid') or res.json().get('sessionid')
    except:
        return None


def get_address(sid, lat, lon):
    """Получение адреса по координатам"""
    try:
        res = requests.get(f"{API_URL}/getaddress", 
                           headers={'SessionId': sid}, 
                           params={'lat': lat, 'lon': lon}, 
                           timeout=10)
        return res.text.strip().strip('"')
    except:
        return "Не определен"


def get_waybill_data(sid, obj_ids_str, date_from, date_to):
    """
    Получение данных путевых листов через getobjectsreport
    
    Args:
        sid: SessionId
        obj_ids_str: ID объектов через ; (например "7281;7282")
        date_from: дата начала (YYYY-MM-DD)
        date_to: дата конца (YYYY-MM-DD)
    
    Returns:
        list: список путевых листов
    """
    params_list = "start_address;stop_address;start_can_dist;stop_can_dist;can_dist;odo_dist;start_move_time;stop_move_time;stop_coords;start_coords"
    
    payload = {
        'date_from': f"{date_from} 00:00:00",
        'date_to': f"{date_to} 23:59:59",
        'objuids': obj_ids_str,
        'split': 'none',
        'param': params_list
    }
    
    try:
        res = requests.get(
            f"{API_URL}/getobjectsreport",
            headers={'SessionId': sid},
            params=payload,
            timeout=60
        )
        
        if res.status_code != 200:
            return []
        
        report_data = res.json()
        results = []
        
        for obj_report in report_data:
            oid = obj_report.get('oid')
            v_name = obj_report.get('obj_name')
            
            periods = obj_report.get('periods', [])
            if not periods:
                continue
            
            # Преобразуем в словарь для удобства
            p = {item['name']: item['value'] for item in periods[0].get('prms', [])}
            
            # Адрес окончания (с fallback на координаты)
            addr_end = p.get('stop_address', 'Не определен')
            if addr_end == "Не определен" or not addr_end:
                coords = p.get('stop_coords')
                if coords and ';' in str(coords):
                    lat, lon = str(coords).split(';')
                    addr_end = get_address(sid, lat, lon)
            
            # Адрес начала (с fallback на координаты)
            addr_start = p.get('start_address', 'Не определен')
            if addr_start == "Не определен" or not addr_start:
                coords = p.get('start_coords')
                if coords and ';' in str(coords):
                    lat, lon = str(coords).split(';')
                    addr_start = get_address(sid, lat, lon)
            
            # Одометр и пробег
            can_start = float(p.get('start_can_dist', 0))
            can_end = float(p.get('stop_can_dist', 0))
            
            if can_start == 0 and can_end == 0:
                # Fallback на odo_dist
                dist_val = float(p.get('can_dist', 0)) or float(p.get('odo_dist', 0))
            else:
                dist_val = can_end - can_start if can_end > can_start else float(p.get('can_dist', 0))
            
            # Находим ФИО из DataFrame
            match = vehicles_df[vehicles_df['ID объекта'] == oid]
            driver = match.iloc[0]['ФИО'] if not match.empty else "—"
            
            results.append({
                'oid': oid,
                'driver': driver,
                'vehicle': v_name,
                'start_time': p.get('start_move_time', '—'),
                'start_address': addr_start,
                'start_odo': can_start,
                'end_time': p.get('stop_move_time', '—'),
                'end_address': addr_end,
                'end_odo': can_end,
                'mileage': round(dist_val, 2)
            })
        
        return results
    
    except Exception as e:
        print(f"Ошибка получения данных: {e}")
        return []


# ============================================================================
# HTML ГЕНЕРАЦИЯ
# ============================================================================

def generate_form_html():
    """Генерация HTML формы выбора"""
    
    # Создаём список ТС для select
    options_html = '<option value="ALL">🚛 ВСЕ ТРАНСПОРТНЫЕ СРЕДСТВА</option>\n'
    
    for i, row in vehicles_df.iterrows():
        oid = int(row['ID объекта'])
        vehicle = row.get('Номер авто', f'ID_{oid}')
        driver = row.get('ФИО', '')
        options_html += f'<option value="{oid}">{vehicle} — {driver}</option>\n'
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Путевые листы</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 20px;
            }}
            
            .container {{ max-width: 600px; width: 100%; }}
            
            .card {{
                background: white;
                border-radius: 20px;
                box-shadow: 0 20px 60px rgba(0,0,0,0.3);
                padding: 40px;
                animation: slideIn 0.5s ease;
            }}
            
            @keyframes slideIn {{
                from {{ opacity: 0; transform: translateY(-30px); }}
                to {{ opacity: 1; transform: translateY(0); }}
            }}
            
            .header {{
                text-align: center;
                margin-bottom: 30px;
                padding-bottom: 20px;
                border-bottom: 3px solid #667eea;
            }}
            
            .icon {{ font-size: 60px; margin-bottom: 15px; }}
            h1 {{ color: #333; font-size: 28px; margin-bottom: 10px; }}
            .subtitle {{ color: #666; font-size: 14px; }}
            
            .form-group {{ margin-bottom: 25px; }}
            
            label {{
                display: block;
                color: #333;
                font-weight: 600;
                margin-bottom: 8px;
                font-size: 14px;
            }}
            
            select, input[type="date"] {{
                width: 100%;
                padding: 12px 15px;
                border: 2px solid #e0e0e0;
                border-radius: 10px;
                font-size: 14px;
                font-family: inherit;
                transition: all 0.3s;
                background: white;
            }}
            
            select:focus, input[type="date"]:focus {{
                outline: none;
                border-color: #667eea;
                box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
            }}
            
            select {{
                cursor: pointer;
                appearance: none;
                background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%23333' d='M6 9L1 4h10z'/%3E%3C/svg%3E");
                background-repeat: no-repeat;
                background-position: right 15px center;
                padding-right: 40px;
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
            
            .btn:active {{ transform: translateY(0); }}
            
            .info-box {{
                background: #f8f9ff;
                padding: 15px;
                border-radius: 10px;
                margin-top: 20px;
                border-left: 4px solid #667eea;
                font-size: 13px;
                color: #666;
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
                    <div class="icon">📋</div>
                    <h1>Путевые листы</h1>
                    <p class="subtitle">Выберите транспорт и период</p>
                </div>
                
                <form id="reportForm" action="/report" method="GET">
                    <div class="form-group">
                        <label for="vehicle">🚗 Транспортное средство</label>
                        <select id="vehicle" name="oid" required>
                            {options_html}
                        </select>
                    </div>
                    
                    <div class="form-group">
                        <label for="dateFrom">📅 Дата начала</label>
                        <input type="date" id="dateFrom" name="date_from" required>
                    </div>
                    
                    <div class="form-group">
                        <label for="dateTo">📅 Дата окончания</label>
                        <input type="date" id="dateTo" name="date_to" required>
                    </div>
                    
                    <button type="submit" class="btn">
                        📊 Сформировать отчёт
                    </button>
                    
                    <div class="info-box">
                        💡 <strong>Совет:</strong> Выберите "ВСЕ ТС" для получения сводного отчёта по всему автопарку
                    </div>
                </form>
                
                <div class="loading" id="loading">
                    <div class="spinner"></div>
                    <p style="margin-top: 10px;">Формирование отчёта...</p>
                </div>
            </div>
        </div>
        
        <script>
            // Установка значений по умолчанию
            const now = new Date();
            const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
            
            document.getElementById('dateTo').value = now.toISOString().split('T')[0];
            document.getElementById('dateFrom').value = weekAgo.toISOString().split('T')[0];
            
            // Обработка отправки формы
            document.getElementById('reportForm').addEventListener('submit', function() {{
                document.getElementById('loading').style.display = 'block';
            }});
        </script>
    </body>
    </html>
    """
    
    return html


def generate_report_html(waybills, date_from, date_to, is_all=False):
    """Генерация HTML отчёта с путевыми листами"""
    
    if not waybills:
        content = "<p style='text-align:center; padding:50px; color:#999;'>📭 Данных не найдено</p>"
    else:
        rows_html = ""
        for i, wb in enumerate(waybills, 1):
            # Цвет для пробега
            mileage_color = "#28a745" if wb['mileage'] > 0 else "#999"
            
            rows_html += f"""
            <tr>
                <td style="text-align:center; font-weight:600;">{i}</td>
                <td><strong>{wb['driver']}</strong></td>
                <td>{wb['vehicle']}</td>
                <td style="font-size:12px;">{wb['start_time']}</td>
                <td style="font-size:12px;">{wb['start_address'][:40]}...</td>
                <td style="text-align:right;">{wb['start_odo']:.1f}</td>
                <td style="font-size:12px;">{wb['end_time']}</td>
                <td style="font-size:12px;">{wb['end_address'][:40]}...</td>
                <td style="text-align:right;">{wb['end_odo']:.1f}</td>
                <td style="text-align:right; font-weight:bold; color:{mileage_color}; font-size:16px;">{wb['mileage']:.1f}</td>
            </tr>
            """
        
        content = f"""
        <table>
            <thead>
                <tr>
                    <th style="width:40px;">#</th>
                    <th>Водитель</th>
                    <th>Автомобиль</th>
                    <th>Начало рейса</th>
                    <th>Адрес начала</th>
                    <th style="width:80px;">Одометр</th>
                    <th>Конец рейса</th>
                    <th>Адрес конца</th>
                    <th style="width:80px;">Одометр</th>
                    <th style="width:100px;">Пробег (км)</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>
        """
    
    # Статистика
    total_vehicles = len(waybills)
    total_mileage = sum(wb['mileage'] for wb in waybills)
    avg_mileage = total_mileage / total_vehicles if total_vehicles > 0 else 0
    max_mileage = max((wb['mileage'] for wb in waybills), default=0)
    
    title = "Сводный отчёт по автопарку" if is_all else f"Путевой лист — {waybills[0]['vehicle']}" if waybills else "Путевой лист"
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{title}</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ font-family: 'Segoe UI', sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; min-height: 100vh; }}
            .container {{ max-width: 1400px; margin: 0 auto; }}
            .card {{ background: white; border-radius: 15px; box-shadow: 0 10px 40px rgba(0,0,0,0.2); padding: 30px; margin-bottom: 20px; }}
            h1 {{ color: #333; font-size: 32px; margin-bottom: 20px; }}
            .period {{ background: #f8f9ff; padding: 15px 20px; border-radius: 10px; color: #666; margin-bottom: 20px; border-left: 4px solid #667eea; }}
            .stats {{ display: flex; gap: 20px; margin-bottom: 20px; flex-wrap: wrap; }}
            .stat-card {{ flex: 1; min-width: 200px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 10px; text-align: center; }}
            .stat-value {{ font-size: 36px; font-weight: bold; margin-bottom: 5px; }}
            .stat-label {{ font-size: 14px; opacity: 0.9; text-transform: uppercase; }}
            table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
            thead {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; }}
            th {{ padding: 12px 8px; text-align: left; font-weight: 600; text-transform: uppercase; font-size: 11px; }}
            td {{ padding: 12px 8px; border-bottom: 1px solid #f0f0f0; }}
            tr:hover {{ background: #f8f9ff; }}
            .btn {{ display: inline-block; padding: 12px 30px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; text-decoration: none; border-radius: 25px; font-weight: 600; margin: 10px 5px; border: none; cursor: pointer; }}
            .btn:hover {{ transform: translateY(-2px); box-shadow: 0 5px 20px rgba(102, 126, 234, 0.4); }}
            @media print {{ body {{ background: white; padding: 0; }} .no-print {{ display: none; }} .card {{ box-shadow: none; }} }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="card">
                <h1>📋 {title}</h1>
                <div class="period">📅 Период: <strong>{date_from}</strong> — <strong>{date_to}</strong></div>
                <div class="stats">
                    <div class="stat-card"><div class="stat-value">{total_vehicles}</div><div class="stat-label">Транспортных средств</div></div>
                    <div class="stat-card"><div class="stat-value">{total_mileage:.1f} км</div><div class="stat-label">Общий пробег</div></div>
                    <div class="stat-card"><div class="stat-value">{avg_mileage:.1f} км</div><div class="stat-label">Средний пробег</div></div>
                    <div class="stat-card"><div class="stat-value">{max_mileage:.1f} км</div><div class="stat-label">Максимальный пробег</div></div>
                </div>
            </div>
            
            <div class="card">
                {content}
                <div class="no-print" style="margin-top: 20px; text-align: center;">
                    <button class="btn" onclick="window.print()">🖨️ Печать</button>
                    <a href="/" class="btn">◀️ Назад</a>
                    <button class="btn" onclick="downloadExcel()">📥 Скачать Excel</button>
                </div>
            </div>
        </div>
        
        <script>
            function downloadExcel() {{
                // Конвертация таблицы в CSV
                const table = document.querySelector('table');
                if (!table) return;
                
                let csv = [];
                const rows = table.querySelectorAll('tr');
                
                for (let row of rows) {{
                    const cols = row.querySelectorAll('td, th');
                    const csvRow = [];
                    for (let col of cols) {{
                        csvRow.push('"' + col.innerText.replace(/"/g, '""') + '"');
                    }}
                    csv.push(csvRow.join(','));
                }}
                
                const csvContent = csv.join('\\n');
                const blob = new Blob([csvContent], {{ type: 'text/csv;charset=utf-8;' }});
                const link = document.createElement('a');
                const url = URL.createObjectURL(blob);
                link.setAttribute('href', url);
                link.setAttribute('download', 'Путевые_листы_{date_from}.csv');
                link.style.visibility = 'hidden';
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
            }}
        </script>
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
            
            oid_param = params.get('oid', [''])[0]
            date_from = params.get('date_from', [''])[0]
            date_to = params.get('date_to', [''])[0]
            
            # Определяем: все ТС или одно
            if oid_param == 'ALL':
                # Все ТС
                obj_ids_str = ";".join(vehicles_df['ID объекта'].astype(str).tolist())
                is_all = True
            else:
                # Одно ТС
                obj_ids_str = oid_param
                is_all = False
            
            # Получение данных
            waybills = get_waybill_data(session_id, obj_ids_str, date_from, date_to)
            
            # Генерация HTML
            html = generate_report_html(waybills, date_from, date_to, is_all)
            
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
    print("📋 ВЕБ-ИНТЕРФЕЙС ПУТЕВЫХ ЛИСТОВ")
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
