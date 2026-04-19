import requests
import pandas as pd
import sqlite3
import os
import re
import webbrowser
import time
from datetime import timedelta

# --- НАСТРОЙКИ ---
API_BASE_URL = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN = "abvprom"
PASSWORD = "29328"
INPUT_FILE = r"c:/Users/snltv/Desktop/ii/putevoi list/CAN_пробег_датчики_06_02_2026.xlsx"
DB_NAME = "abv_fuel_in_out_comsum.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS abv_fuel_in_out_comsum (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            obj_id INTEGER,
            vehicle_name TEXT,
            report_date TEXT,
            tank_volume INTEGER,
            begin_level REAL,
            refuels REAL,
            end_level REAL,
            consumption REAL,
            UNIQUE(obj_id, report_date)
        )
    ''')
    conn.commit()
    conn.close()

def save_to_db(data_list):
    if not data_list: return
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.executemany('''
        INSERT OR REPLACE INTO abv_fuel_in_out_comsum 
        (obj_id, vehicle_name, report_date, tank_volume, begin_level, refuels, end_level, consumption)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', data_list)
    conn.commit()
    conn.close()

def get_sid():
    try:
        res = requests.get(f"{API_BASE_URL}/connect", 
                           params={'login': LOGIN, 'password': PASSWORD, 'lang': 'ru-ru', 'timezone': '3'},
                           timeout=15)
        return res.headers.get('sessionid') or res.json().get('sessionid')
    except: return None

def get_tank_volume(oid, sid):
    try:
        res = requests.get(f"{API_BASE_URL}/objsensorslist", params={'oid': oid}, headers={'SessionId': sid}, timeout=15).json()
        for sensor in res.get('obj_sensors', []):
            name = sensor.get('name', '')
            volumes = re.findall(r'(\d{3,4})', name)
            if volumes: return int(max(volumes, key=len))
    except: pass
    return 600

def main():
    init_db()
    sid = get_sid()
    if not sid: print("❌ Ошибка авторизации"); return
    if not os.path.exists(INPUT_FILE): print(f"❌ Нет файла {INPUT_FILE}"); return

    df_input = pd.read_excel(INPUT_FILE).dropna(subset=['ID объекта'])
    # Создаем словарь ID -> Номер авто для быстрого поиска
    car_names = pd.Series(df_input['Номер авто'].values, index=df_input['ID объекта'].astype(int)).to_dict()
    ids_list = list(car_names.keys())

    print("📡 Опрос конфигурации баков (один раз)...")
    tank_map = {}
    for oid in ids_list:
        tank_map[oid] = get_tank_volume(oid, sid)
        time.sleep(0.1)

    date_start_str = input("📅 Дата начала (ГГГГ-ММ-ДД): ").strip()
    date_end_str = input("📅 Дата конца  (ГГГГ-ММ-ДД): ").strip()
    
    start_dt = pd.to_datetime(date_start_str)
    end_dt = pd.to_datetime(date_end_str)

    curr = start_dt
    while curr <= end_dt:
        d_str = curr.strftime('%Y-%m-%d')
        print(f"\n--- 📅 Обработка даты: {d_str} ---")
        day_data = []
        
        for oid in ids_list:
            v_name = car_names.get(oid, "N/A")
            print(f"📡 Запрос: {v_name} (ID: {oid})... ", end="", flush=True)
            
            try:
                # Запрашиваем данные ТОЛЬКО для одного ID
                res = requests.get(f"{API_BASE_URL}/getobjectsfuelinfo", 
                                   params={
                                       'date_from': d_str + " 00:00:00", 
                                       'date_to': d_str + " 23:59:59", 
                                       'objuids': str(oid)
                                   },
                                   headers={'SessionId': sid}, timeout=20).json()
                
                if res and len(res) > 0:
                    obj = res[0]
                    t_start = 0
                    t_end = 0
                    refuels = 0
                    
                    if obj.get('sensors'):
                        for s in obj['sensors']:
                            if any(w in s.get('sensor_name', '').lower() for w in ["бак", "lls", "fuel", "датчик"]):
                                t_start += float(s.get('beginLevel', 0))
                                t_end += float(s.get('endLevel', 0))
                                refuels += float(s.get('summ_refuelings', 0))
                    else:
                        t_start = float(obj.get('beginLevel', 0))
                        t_end = float(obj.get('endLevel', 0))

                    vol = tank_map.get(oid, 600)
                    consumption = round((t_start + refuels) - t_end, 1)
                    if consumption < 0: consumption = 0

                    day_data.append((
                        oid, v_name, d_str, vol, 
                        round(t_start, 1), round(refuels, 1), 
                        round(t_end, 1), round(consumption, 1)
                    ))
                    print("✅")
                else:
                    print("⚠️ Нет данных")
            
            except Exception as e:
                print(f"❌ Ошибка: {e}")

            time.sleep(0.1) # Короткая пауза между машинами
        
        # Сохраняем данные за целый день сразу
        if day_data:
            save_to_db(day_data)
            print(f"💾 День {d_str} сохранен в базу.")

        curr += timedelta(days=1)

    print(f"\n🚀 Готово! Проверьте файл {DB_NAME}")
    
    # Генерация HTML-отчета
    if os.path.exists(DB_NAME):
        conn = sqlite3.connect(DB_NAME)
        df_final = pd.read_sql_query("SELECT * FROM abv_fuel_in_out_comsum ORDER BY report_date DESC", conn)
        conn.close()
        df_final.to_html("Full_History_Report.html", index=False)
        webbrowser.open("file://" + os.path.abspath("Full_History_Report.html"))

if __name__ == "__main__":
    main()