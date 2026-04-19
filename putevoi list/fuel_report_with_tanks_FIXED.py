import requests
import pandas as pd
import os
import re
import sqlite3
import calendar
import webbrowser
from datetime import datetime

# =================================================================
# НАЛАШТУВАННЯ
# =================================================================
API_BASE_URL = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN = "abvprom"
PASSWORD = "29328"

# Вказуємо ваш прямий шлях до папки з довідниками
BASE_PATH = r"C:\Users\snltv\Desktop\ii\putevoi list\справочники"
INPUT_FILE = os.path.join(BASE_PATH, 'CAN_пробег_датчики_06_02_2026.xlsx')
DB_FILE = 'abvprm_fuel.db'

def get_sid():
    try:
        res = requests.get(f"{API_BASE_URL}/connect", 
                           params={'login': LOGIN, 'password': PASSWORD, 'lang': 'uk-ua', 'timezone': '3'},
                           timeout=10)
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
            UNIQUE(report_date, vehicle_number)
        )
    ''')
    conn.commit()
    conn.close()

def main():
    print("=" * 70)
    print("⛽ ЗАВАНТАЖЕННЯ ПАЛИВА З ПАПКИ: " + BASE_PATH)
    print("=" * 70)
    
    init_db()
    sid = get_sid()
    if not sid: 
        print("❌ Помилка авторизації"); return

    if not os.path.exists(INPUT_FILE):
        print(f"❌ Файл не знайдено: {INPUT_FILE}"); return

    df_input = pd.read_excel(INPUT_FILE)
    
    year = 2025 # Можна змінити на поточний
    m_input = input("📅 Введіть номер місяця для завантаження (1-12): ")
    month = int(m_input)
    
    last_day = calendar.monthrange(year, month)[1]
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    for day in range(1, last_day + 1):
        date_str = f"{year}-{month:02d}-{day:02d}"
        print(f"📅 Обробка {date_str}...", end=" ", flush=True)
        
        for _, row in df_input.iterrows():
            oid = int(row['ID объекта'])
            v_name = str(row['Номер авто'])
            fio = str(row['ФИО'])

            try:
                # 1. Запит загальної інфи (рівні палива)
                res_f = requests.get(f"{API_BASE_URL}/getobjectsfuelinfo", 
                                   params={'date_from': f"{date_str} 00:00:00", 'date_to': f"{date_str} 23:59:59", 'objuids': str(oid)},
                                   headers={'SessionId': sid}, timeout=20).json()
                
                # 2. Окремий запит на заправки (щоб не були 0)
                res_ref = requests.get(f"{API_BASE_URL}/fuelings",
                                     params={'oid': oid, 'from': f"{date_str} 00:00:00", 'to': f"{date_str} 23:59:59"},
                                     headers={'SessionId': sid}, timeout=20).json()

                f_ref = 0.0
                if res_ref.get('result') == 'Ok':
                    f_ref = sum(float(e.get('volume', 0)) for e in res_ref.get('fuelings', []) if e.get('fuel_type') == 'fueling')

                f_start, f_end = 0.0, 0.0
                if res_f and len(res_f) > 0:
                    sensors = res_f[0].get('sensors', [])
                    found = False
                    for s in sensors:
                        n = s['sensor_name'].lower()
                        if 'сумматор' in n or 'топливо' in n:
                            f_start, f_end = s.get('beginLevel', 0.0), s.get('endLevel', 0.0)
                            found = True; break
                    if not found:
                        for s in sensors:
                            if 'бак' in s['sensor_name'].lower():
                                f_start += s.get('beginLevel', 0.0)
                                f_end += s.get('endLevel', 0.0)

                cons = round((f_start - f_end + f_ref), 1)

                cursor.execute('''INSERT OR REPLACE INTO fuel_reports 
                    (report_date, vehicle_number, driver_fio, fuel_start, fuel_end, refills, consumption)
                    VALUES (?, ?, ?, ?, ?, ?, ?)''', 
                    (date_str, v_name, fio, round(f_start, 1), round(f_end, 1), round(f_ref, 1), cons))
            except: continue
        
        conn.commit()
        print("✅")

    conn.close()
    print(f"\n🏁 Дані збережені в {DB_FILE}")
    
    # Відкриваємо папку з результатом
    os.startfile(os.path.dirname(os.path.abspath(DB_FILE)))

if __name__ == "__main__":
    main()