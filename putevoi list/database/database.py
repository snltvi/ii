import sqlite3
import pandas as pd
import requests
import os
import calendar
from datetime import datetime

# =================================================================
# НАЛАШТУВАННЯ
# =================================================================
API_BASE_URL = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN = "abvprom"
PASSWORD = "29328"

# Шлях до папки з довідниками
BASE_PATH = r"C:\Users\snltv\Desktop\ii\putevoi list\справочники"
INPUT_FILE = os.path.join(BASE_PATH, 'CAN_пробег_датчики_06_02_2026.xlsx')
DB_FILE = 'abvprm_fuel.db'

def get_sid():
    url = f"{API_BASE_URL}/connect"
    params = {'login': LOGIN, 'password': PASSWORD, 'lang': 'uk-ua', 'timezone': '3'}
    try:
        res = requests.get(url, params=params, timeout=20)
        return res.headers.get('sessionid') or res.json().get('sessionid')
    except:
        return None

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS fuel_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_date TEXT,
            vehicle_number TEXT,
            driver_fio TEXT,
            fuel_start REAL,
            fuel_end REAL,
            refills REAL,
            consumption REAL,
            sync_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(report_date, vehicle_number)
        )
    ''')
    conn.commit()
    conn.close()

def load_month_fuel(year, month):
    init_db()
    sid = get_sid()
    if not sid:
        print("❌ Помилка авторизації!"); return

    if not os.path.exists(INPUT_FILE):
        print(f"❌ Файл не знайдено за шляхом: {INPUT_FILE}"); return

    # Читаємо довідник (Excel)
    df_input = pd.read_excel(INPUT_FILE)
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    last_day = calendar.monthrange(year, month)[1]
    print(f"🚀 Завантаження палива за {month:02d}.{year}")

    for day in range(1, last_day + 1):
        date_str = f"{year}-{month:02d}-{day:02d}"
        print(f"📅 {date_str}:", end=" ", flush=True)
        added_in_day = 0
        
        for _, row in df_input.iterrows():
            oid = int(row['ID объекта'])
            v_name = str(row['Номер авто'])
            fio = str(row['ФИО'])

            try:
                # Запит даних про паливо через API
                url_f = f"{API_BASE_URL}/getobjectsfuelinfo"
                params_f = {
                    'date_from': f"{date_str} 00:00:00", 
                    'date_to': f"{date_str} 23:59:59", 
                    'objuids': str(oid)
                }
                res_f = requests.get(url_f, params=params_f, headers={'SessionId': sid}, timeout=30).json()
                
                f_start, f_end, f_ref = 0.0, 0.0, 0.0
                
                if res_f and len(res_f) > 0:
                    sensors = res_f[0].get('sensors', [])
                    summ_found = False
                    
                    # Пріоритет: Суматор або датчик з назвою "Топливо"
                    for s in sensors:
                        n = s['sensor_name'].lower()
                        if 'сумматор' in n or 'топливо' in n:
                            f_start = s.get('beginLevel', 0.0)
                            f_end = s.get('endLevel', 0.0)
                            f_ref = s.get('refillsSum', 0.0) or 0.0
                            summ_found = True
                            break
                    
                    # Якщо суматор не знайдено, підсумовуємо всі "Баки"
                    if not summ_found:
                        for s in sensors:
                            if 'бак' in s['sensor_name'].lower():
                                f_start += s.get('beginLevel', 0.0)
                                f_end += s.get('endLevel', 0.0)
                                f_ref += (s.get('refillsSum', 0.0) or 0.0)

                    # Розрахунок витрати
                    cons = round((f_start - f_end + f_ref), 1)

                    cursor.execute('''INSERT OR REPLACE INTO fuel_reports 
                        (report_date, vehicle_number, driver_fio, fuel_start, fuel_end, refills, consumption)
                        VALUES (?, ?, ?, ?, ?, ?, ?)''', 
                        (date_str, v_name, fio, round(f_start, 1), round(f_end, 1), round(f_ref, 1), cons))
                    added_in_day += 1
            except Exception:
                continue
        
        conn.commit()
        print(f"✅ Оброблено авто: {added_in_day}")

    conn.close()
    print(f"\n🏁 Синхронізацію завершено. База: {DB_FILE}")

if __name__ == "__main__":
    m = input("Введіть номер місяця (1-12): ")
    try:
        load_month_fuel(2025, int(m))
    except ValueError:
        print("Помилка: введіть число.")