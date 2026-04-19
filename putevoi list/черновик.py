#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
import pandas as pd
from urllib.parse import parse_qs, urlparse
import webbrowser
import threading
import sys

# ============================================================================
# НАЛАШТУВАННЯ
# ============================================================================
API_URL = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN = "abvprom"
PASSWORD = "29328"
TARGET_FILE = "CAN_пробег_датчики_06_02_2026.xlsx"
PORT = 8080

vehicles_df = None
session_id = None

# ============================================================================
# ЛОГІКА API
# ============================================================================

def connect_to_api():
    try:
        res = requests.get(f"{API_URL}/connect", 
                           params={'login': LOGIN, 'password': PASSWORD, 'lang': 'ru-ru', 'timezone': '2'},
                           timeout=15)
        return res.headers.get('sessionid') or res.json().get('sessionid')
    except: return None

def get_waybill_data(sid, obj_ids_str, date_from, date_to):
    params_list = "start_address;stop_address;start_can_dist;stop_can_dist;can_dist;odo_dist;start_move_time;stop_move_time;first_msg_time"
    payload = {
        'date_from': f"{date_from} 00:00:00",
        'date_to': f"{date_to} 23:59:59",
        'objuids': obj_ids_str,
        'split': 'none', 
        'param': params_list
    }
    
    try:
        res = requests.get(f"{API_URL}/getobjectsreport", headers={'SessionId': sid}, params=payload, timeout=60)
        if res.status_code != 200: return []
        
        report_data = res.json()
        results = []
        vehicles_info = {str(int(row['ID объекта'])): row for _, row in vehicles_df.iterrows()}

        for obj_report in report_data:
            oid = str(obj_report.get('oid'))
            v_name = obj_report.get('obj_name')
            periods = obj_report.get('periods', [])
            info = vehicles_info.get(oid, {})
            
            if not periods or not periods[0].get('prms'):
                results.append({
                    'driver': info.get('ФИО', '—'), 'vehicle': v_name,
                    'start_time': '—', 'start_address': '—', 'start_odo': 0.0,
                    'end_time': '—', 'end_address': '—', 'end_odo': 0.0, 'mileage': 0.0
                })
                continue
            
            p = {item['name']: item['value'] for item in periods[0].get('prms', [])}
            mileage = float(p.get('can_dist', 0)) or float(p.get('odo_dist', 0))
            
            raw_start = p.get('start_move_time', '')
            raw_stop  = p.get('stop_move_time', '')

            if mileage > 0.1:
                # ---- СТАРТ ----
                # Якщо дата в raw_start відрізняється від date_from — авто вже
                # рухалось до початку доби (транзит), показуємо 00:00:00.
                # Те саме якщо час рівно 00:00 (API «зарізав» початок).
                # ---- СТАРТ ----
                first_msg = p.get('first_msg_time', '')
                if raw_start:
                    time_only = raw_start.split(' ')[1] if ' ' in raw_start else raw_start
                    msg_time_only = first_msg.split(' ')[1] if ' ' in first_msg else first_msg
                    # Транзит: час старту збігається з першим повідомленням доби
                    # АБО час старту рівно 00:00
                    if time_only.startswith("00:00") or (msg_time_only and time_only == msg_time_only):
                        display_start = f"{date_from} 00:00:00"
                    else:
                        display_start = raw_start
                else:
                    display_start = f"{date_from} 00:00:00"

                # ---- ФІНІШ ----
                # Якщо час зупинки 23:58–23:59 — авто рухалось до кінця доби,
                # показуємо 23:59:59. Якщо stop порожній — теж кінець доби.
                if raw_stop:
                    time_only_stop = raw_stop.split(' ')[1] if ' ' in raw_stop else raw_stop
                    if time_only_stop.startswith("23:59") or time_only_stop.startswith("23:58"):
                        display_stop = f"{date_to} 23:59:59"
                    else:
                        display_stop = raw_stop
                else:
                    display_stop = f"{date_to} 23:59:59"

                s_addr = p.get('start_address') or "Початок маршруту"
                e_addr = p.get('stop_address') or "Кінець маршруту"
            else:
                display_start, display_stop = "—", "—"
                s_addr, e_addr = "Стоянка", "Стоянка"

            results.append({
                'driver': info.get('ФИО', '—'),
                'vehicle': v_name,
                'start_time': display_start,
                'start_address': s_addr,
                'start_odo': float(p.get('start_can_dist', 0)),
                'end_time': display_stop,
                'end_address': e_addr,
                'end_odo': float(p.get('stop_can_dist', 0)),
                'mileage': round(mileage, 2)
            })
        return results
    except Exception as e:
        print(f"Помилка API: {e}")
        return []

# ============================================================================
# ВЕБ-ІНТЕРФЕЙС
# ============================================================================

def generate_form_html():
    options = "".join([f"<option value='{int(r['ID объекта'])}'>{r.get('Номер авто')} - {r.get('ФИО')}</option>" for _, r in vehicles_df.iterrows()])
    return f"""
    <html><head><meta charset='UTF-8'><title>Шляхові листи DAF</title>
    <style>
        body {{ font-family: sans-serif; background: #1a1a2e; display: flex; justify-content: center; padding-top: 50px; color: #fff; }}
        .card {{ background: white; padding: 30px; border-radius: 12px; width: 450px; color: #333; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }}
        h2 {{ text-align: center; color: #16213e; border-bottom: 2px solid #e94560; padding-bottom: 10px; }}
        select, input {{ width: 100%; padding: 12px; margin: 10px 0; border: 1px solid #ddd; border-radius: 6px; font-size: 14px; }}
        button {{ width: 100%; padding: 14px; background: #e94560; color: white; border: none; border-radius: 6px; font-weight: bold; cursor: pointer; font-size: 16px; margin-top: 15px; }}
        button:hover {{ background: #ff4d6d; }}
    </style></head>
    <body>
        <div class="card">
            <h2>Генератор путівок</h2>
            <form action='/report'>
                <label>Виберіть автомобіль:</label>
                <select name='oid'><option value='ALL'>🚛 ВСІ АВТОМОБІЛІ</option>{options}</select>
                <label>Дата звіту:</label>
                <input type='date' name='date_from' id='d' required>
                <input type='hidden' name='date_to' id='dt'>
                <button type='submit'>СФОРМУВАТИ ЗВІТ</button>
            </form>
        </div>
        <script>
            const yest = new Date(Date.now()-86400000).toISOString().split('T')[0];
            document.getElementById('d').value = yest;
            document.getElementById('dt').value = yest;
            document.querySelector('form').onsubmit = () => {{
                document.getElementById('dt').value = document.getElementById('d').value;
            }};
        </script>
    </body></html>
    """

def generate_report_html(data, date):
    rows = ""
    for i, d in enumerate(data):
        t_start = d['start_time'].split(' ')[1] if ' ' in d['start_time'] else d['start_time']
        t_end   = d['end_time'].split(' ')[1]   if ' ' in d['end_time']   else d['end_time']
        row_style = "style='background:#fff;'" if d['mileage'] > 0 else "style='background:#f2f2f2; color:#aaa;'"
        
        rows += f"""<tr {row_style}>
            <td style='text-align:center;'>{i+1}</td>
            <td><b>{d['driver']}</b></td>
            <td>{d['vehicle']}</td>
            <td style='color:#e94560; font-weight:bold;'>{t_start}</td>
            <td style='font-size:10px; line-height:1.1;'>{d['start_address']}</td>
            <td>{d['start_odo']:.1f}</td>
            <td style='color:#e94560; font-weight:bold;'>{t_end}</td>
            <td style='font-size:10px; line-height:1.1;'>{d['end_address']}</td>
            <td>{d['end_odo']:.1f}</td>
            <td style='background:#fff0f3;'><b>{d['mileage']:.1f}</b></td>
        </tr>"""
        
    return f"""
    <html><head><meta charset='UTF-8'><style>
        table {{ width: 100%; border-collapse: collapse; font-family: sans-serif; }}
        th {{ background: #16213e; color: white; padding: 10px; font-size: 11px; border: 1px solid #333; }}
        td {{ padding: 6px; border: 1px solid #ddd; font-size: 11px; }}
        h3 {{ font-family: sans-serif; color: #16213e; }}
        @media print {{ .no-print {{ display: none; }} }}
    </style></head>
    <body>
        <h3>Звіт по роботі автотранспорту за {date}</h3>
        <table>
            <thead><tr>
                <th>№</th><th>Водій</th><th>Автомобіль</th><th>Старт</th><th>Адреса (Початок)</th><th>Одометр П</th>
                <th>Фініш</th><th>Адреса (Кінець)</th><th>Одометр К</th><th>КМ</th>
            </tr></thead>
            <tbody>{rows}</tbody>
        </table>
        <div class="no-print" style="margin-top:20px;">
            <button onclick="window.print()" style="padding:10px 20px; cursor:pointer;">Друк</button>
            <a href="/" style="margin-left:20px; text-decoration:none; color:#e94560; font-weight:bold;">Назад</a>
        </div>
    </body></html>
    """

# ============================================================================
# ЗАПУСК
# ============================================================================

class WebHandler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        u = urlparse(self.path); p = parse_qs(u.query)
        if u.path == '/':
            self.send_response(200); self.send_header('Content-type','text/html; charset=utf-8'); self.end_headers()
            self.wfile.write(generate_form_html().encode())
        elif u.path == '/report':
            df = p.get('date_from',[''])[0]
            oid = p.get('oid',['ALL'])[0]
            ids = ";".join(vehicles_df['ID объекта'].astype(str)) if oid == 'ALL' else oid
            data = get_waybill_data(session_id, ids, df, df)
            self.send_response(200); self.send_header('Content-type','text/html; charset=utf-8'); self.end_headers()
            self.wfile.write(generate_report_html(data, df).encode())

def main():
    global vehicles_df, session_id
    try:
        print("Завантаження Excel...")
        vehicles_df = pd.read_excel(TARGET_FILE)
        print("Авторизація в Mobiteam...")
        session_id = connect_to_api()
        if not session_id:
            print("❌ ПОМИЛКА: Не вдалося увійти в систему GPS!"); return
        
        server = HTTPServer(('localhost', PORT), WebHandler)
        print(f"✅ ПРОГРАМА ЗАПУЩЕНА: http://localhost:{PORT}")
        webbrowser.open(f"http://localhost:{PORT}")
        server.serve_forever()
    except Exception as e:
        print(f"❌ КРИТИЧНА ПОМИЛКА: {e}")
        input("Натисніть Enter для виходу...")

if __name__ == "__main__":
    main()
