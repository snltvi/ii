import sqlite3
import pandas as pd
import requests
import os
from datetime import datetime, timedelta
import calendar

# =================================================================
# НАСТРОЙКИ
# =================================================================
API_BASE_URL = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN = "abvprom"
PASSWORD = "29328"
INPUT_FILE = 'CAN_пробег_датчики_06_02_2026.xlsx' 
DB_FILE = 'fleet_monitoring.db'               

# Ключевые слова для поиска датчиков (из твоего файла инвентаризации)
FUEL_KEYS = ['lls', 'бак', 'fuel level', 'топливо', 'сумматор', 'датчик уровня']
MILEAGE_KEYS = ['абсолютный пробег', 'накопленного пробега', 'ус пробег', 'total mileage']

def get_sid():
    """ Авторизация в Mobiteam """
    url = f"{API_BASE_URL}/connect"
    params = {'login': LOGIN, 'password': PASSWORD, 'lang': 'ru-ru', 'timezone': '2'}
    try:
        res = requests.get(url, params=params, timeout=20)
        return res.headers.get('sessionid')
    except Exception as e:
        print(f"❌ Ошибка авторизации: {e}")
        return None

def load_month_data(year, month):
    """ Загрузка данных за конкретный месяц """
    print(f"\n🚀 Начинаем загрузку за {calendar.month_name[month]} {year} года...")
    
    if not os.path.exists(INPUT_FILE):
        print(f"❌ Файл {INPUT_FILE} не найден!")
        return

    # Подключаемся к базе и создаем таблицу (на случай если файл удален)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS fleet_economy (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_date TEXT,
            object_id INTEGER,
            vehicle_name TEXT,
            mileage_total REAL,
            fuel_start REAL,
            fuel_end REAL,
            refills REAL,
            consumption REAL,
            sync_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()

    # Берем список машин из твоего Excel
    df_input = pd.read_excel(INPUT_FILE)
    unique_ids = [int(x) for x in df_input['ID объекта'].dropna().unique()]
    
    # Определяем диапазон дат в месяце
    last_day = calendar.monthrange(year, month)[1]
    
    sid = get_sid()
    if not sid: return

    for day in range(1, last_day + 1):
        date_str = f"{year}-{month:02d}-{day:02d}"
        
        # Пропускаем, если данные за этот день уже есть в базе
        cursor.execute("SELECT object_id FROM fleet_economy WHERE report_date = ? AND vehicle_name != 'НЕТ ДАННЫХ'", (date_str,))
        existing_ids = [row[0] for row in cursor.fetchall()]
        missing_ids = [oid for oid in unique_ids if oid not in existing_ids]
        
        if not missing_ids:
            continue

        print(f"📅 {date_str}: Догрузка {len(missing_ids)} машин...", end=" ", flush=True)
        
        added_count = 0
        for oid in missing_ids:
            try:
                url = f"{API_BASE_URL}/getobjectsfuelinfo"
                params = {
                    'date_from': f"{date_str} 00:00:00", 
                    'date_to': f"{date_str} 23:59:59", 
                    'objuids': str(oid)
                }
                res = requests.get(url, params=params, headers={'SessionId': sid}, timeout=45).json()
                
                if res:
                    for obj in res:
                        f_start, f_end, f_refills = 0, 0, 0
                        max_odo = 0
                        
                        sensors = obj.get('sensors', [])
                        for s in sensors:
                            name = s['sensor_name'].lower()
                            # 1. Считаем топливо (если датчик подходит под ключи)
                            if any(key in name for key in FUEL_KEYS):
                                f_start += s.get('beginLevel', 0)
                                f_end += s.get('endLevel', 0)
                                f_refills += s.get('refillsSum', 0)
                            # 2. Считаем пробег/одометр
                            if any(key in name for key in MILEAGE_KEYS):
                                val = s.get('endLevel', 0)
                                if val > max_odo: max_odo = val

                        # Smart Logic: если в баке прибавилось, но сервер не пометил как заправку
                        if f_refills < (f_end - f_start) and (f_end - f_start) > 10:
                            f_refills = f_end - f_start
                            
                        # Если нашли датчик одометра — берем его, иначе берем пробег за день от API
                        final_mileage = max_odo if max_odo > 0 else obj.get('mileage', 0)

                        cursor.execute('''INSERT OR REPLACE INTO fleet_economy 
                            (report_date, object_id, vehicle_name, mileage_total, fuel_start, fuel_end, refills, consumption)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', 
                            (date_str, obj.get('object_id'), obj.get('object_name'), round(final_mileage, 1), 
                             round(f_start, 1), round(f_end, 1), round(f_refills, 1), round((f_start-f_end+f_refills), 1)))
                        added_count += 1
                else:
                    # Пометка, что за этот день данных нет физически
                    cursor.execute("INSERT INTO fleet_economy (report_date, object_id, vehicle_name) VALUES (?, ?, ?)", 
                                 (date_str, oid, 'НЕТ ДАННЫХ'))
                
                conn.commit()
            except:
                continue
        
        print(f"✅ ({added_count} догружено)")

    conn.close()
    print(f"\n🏁 Загрузка за {calendar.month_name[month]} завершена!")

# =================================================================
# ЗАПУСК С ВЫБОРОМ МЕСЯЦА
# =================================================================
if __name__ == "__main__":
    print("--- ЗАГРУЗКА ДАННЫХ ПО МЕСЯЦАМ (2025 год) ---")
    m = input("Введите номер месяца (1-12): ")
    try:
        month_num = int(m)
        if 1 <= month_num <= 12:
            load_month_data(2025, month_num)
        else:
            print("❌ Неверный номер месяца.")
    except ValueError:
        print("❌ Введите число от 1 до 12.")