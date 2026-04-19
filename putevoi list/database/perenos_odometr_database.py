import requests
import pandas as pd
import os
import sqlite3
import calendar
from datetime import datetime

# --- НАЛАШТУВАННЯ ШЛЯХІВ ---
INPUT_PATH = r"C:\Users\snltv\Desktop\ii\putevoi list\справочники"
TARGET_FILE = os.path.join(INPUT_PATH, "CAN_пробег_датчики_06_02_2026.xlsx")
DB_NAME = "abvprom_od.db"

# --- НАЛАШТУВАННЯ API ---
API_URL = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN = "abvprom"
PASSWORD = "29328"

def get_sid():
    try:
        res = requests.get(f"{API_URL}/connect", 
                           params={'login': LOGIN, 'password': PASSWORD, 'lang': 'uk-ua', 'timezone': '3'},
                           timeout=10)
        return res.headers.get('sessionid') or res.json().get('sessionid')
    except:
        return None

def get_day_data(sid, oid, sid_param, date_str):
    """Запит сирих даних (objdata) для точного одометра"""
    params = {
        'oid': oid,
        'slist': f's{int(sid_param)}', 
        'from': f"{date_str} 00:00:00",
        'to': f"{date_str} 23:59:59"
    }
    try:
        res = requests.get(f"{API_URL}/objdata", headers={'SessionId': sid}, params=params, timeout=30)
        records = res.json().get('obj_data', {}).get('records', [])
        if not records: return None
        
        start_val = round(float(records[0][1]), 2)
        end_val = round(float(records[-1][1]), 2)
        return start_val, end_val, round(end_val - start_val, 2)
    except:
        return None

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS odometer_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            vehicle_number TEXT,
            driver_fio TEXT,
            odo_start REAL,
            odo_end REAL,
            daily_mileage REAL,
            sync_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(date, vehicle_number) 
        )
    ''')
    conn.commit()
    conn.close()

def load_month():
    print("🚀 СИНХРОНІЗАЦІЯ ДАНИХ ЗА МІСЯЦЬ")
    init_db()
    
    sid = get_sid()
    if not sid:
        print("❌ Помилка авторизації!"); return

    if not os.path.exists(TARGET_FILE):
        print(f"❌ Справочник не знайдено: {TARGET_FILE}"); return

    # Вибір періоду
    year = 2025 # Можна змінити на 2026 за потреби
    month = int(input("📅 Введіть номер місяця для завантаження (1-12): "))
    
    # Визначаємо кількість днів у місяці
    last_day = calendar.monthrange(year, month)[1]
    df_input = pd.read_excel(TARGET_FILE)
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    for day in range(1, last_day + 1):
        target_date = f"{year}-{month:02d}-{day:02d}"
        print(f"--- Обробка дати: {target_date} ---")
        
        for _, row in df_input.iterrows():
            oid = row['ID объекта']
            v_name = row['Номер авто']
            fio = row['ФИО']
            sid_p = row['SID']
            
            data = get_day_data(sid, oid, sid_p, target_date)
            
            if data:
                odo_s, odo_e, dist = data
                try:
                    cursor.execute('''
                        INSERT OR REPLACE INTO odometer_reports 
                        (date, vehicle_number, driver_fio, odo_start, odo_end, daily_mileage)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (target_date, v_name, fio, odo_s, odo_e, dist))
                    print(f"✅ {v_name}: {dist} км")
                except Exception as e:
                    print(f"❌ Помилка запису {v_name}: {e}")
            else:
                print(f"⚠️ {v_name}: немає даних")
        
        # Зберігаємо дані після кожного дня
        conn.commit()

    conn.close()
    print(f"\n🏁 Завантаження за {month:02d}.{year} завершено успішно!")

if __name__ == "__main__":
    load_month()