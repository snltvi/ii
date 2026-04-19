import sqlite3
import pandas as pd
import requests
import os
import re
import calendar
from datetime import datetime

# =================================================================
# 1. НАСТРОЙКИ ПУТЕЙ
# =================================================================
BASE_PATH = r"C:\Users\snltv\Desktop\ii\putevoi list"
INPUT_FOLDER = os.path.join(BASE_PATH, "справочники")
DB_FOLDER = os.path.join(BASE_PATH, "dbf")
DB_PATH = os.path.join(DB_FOLDER, "data_for_way_list.db")

# Файлы-справочники
FILE_FLEET_EXCEL = os.path.join(INPUT_FOLDER, 'CAN_пробег_датчики_06_02_2026.xlsx')
FILE_AMIK_TRANSACTIONS = os.path.join(BASE_PATH, 'отчет по транзакциям.xlsx')
FILE_FLEET_AMIK = os.path.join(BASE_PATH, 'Cцепка_водитель-авто-прицеп_на_20_01_2026_с_ID_объектов.xlsx')

# API Mobiteam
API_BASE_URL = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN = "abvprom"
PASSWORD = "29328"

# Создание папки для БД, если её нет
if not os.path.exists(DB_FOLDER):
    os.makedirs(DB_FOLDER)

# =================================================================
# 2. ТЕХНИЧЕСКИЕ ФУНКЦИИ
# =================================================================

def get_sid():
    url = f"{API_BASE_URL}/connect"
    params = {'login': LOGIN, 'password': PASSWORD, 'lang': 'uk-ua', 'timezone': '3'}
    try:
        res = requests.get(url, params=params, timeout=20)
        return res.headers.get('sessionid') or res.json().get('sessionid')
    except:
        return None

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Таблица Топлива (GPS)
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
    # Таблица Одометра (GPS)
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
    # Таблица Амик создастся автоматически через pandas (to_sql)
    conn.commit()
    conn.close()

# =================================================================
# 3. БЛОК 1: ДАННЫЕ ИЗ API (ТОПЛИВО + ОДОМЕТР)
# =================================================================

def sync_api_data(year, month):
    sid = get_sid()
    if not sid:
        print("❌ Ошибка авторизации в Mobiteam!"); return

    df_input = pd.read_excel(FILE_FLEET_EXCEL)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    last_day = calendar.monthrange(year, month)[1]
    print(f"🚀 Синхронизация API за {month:02d}.{year}")

    for day in range(1, last_day + 1):
        date_str = f"{year}-{month:02d}-{day:02d}"
        print(f"📅 Дата: {date_str}", end=" | ", flush=True)
        count = 0
        
        for _, row in df_input.iterrows():
            oid = int(row['ID объекта'])
            v_name = str(row['Номер авто'])
            fio = str(row['ФИО'])
            sid_p = row.get('SID') 

            try:
                # --- ТОПЛИВО (Логика из perenos_toplivo) ---
                res_f = requests.get(f"{API_BASE_URL}/getobjectsfuelinfo", 
                                   params={'date_from': f"{date_str} 00:00:00", 'date_to': f"{date_str} 23:59:59", 'objuids': str(oid)},
                                   headers={'SessionId': sid}, timeout=30).json()
                
                f_start, f_end, f_ref = 0.0, 0.0, 0.0
                if res_f and len(res_f) > 0:
                    sensors = res_f[0].get('sensors', [])
                    summ_found = False
                    for s in sensors:
                        n = s['sensor_name'].lower()
                        if 'сумматор' in n or 'топливо' in n:
                            f_start, f_end = s.get('beginLevel', 0.0), s.get('endLevel', 0.0)
                            f_ref = s.get('refillsSum', 0.0) or 0.0
                            summ_found = True; break
                    if not summ_found:
                        for s in sensors:
                            if 'бак' in s['sensor_name'].lower():
                                f_start += s.get('beginLevel', 0.0)
                                f_end += s.get('endLevel', 0.0)
                                f_ref += (s.get('refillsSum', 0.0) or 0.0)
                    cons = round((f_start - f_end + f_ref), 1)
                    cursor.execute('INSERT OR REPLACE INTO fuel_reports (report_date, vehicle_number, driver_fio, fuel_start, fuel_end, refills, consumption) VALUES (?,?,?,?,?,?,?)',
                                   (date_str, v_name, fio, round(f_start, 1), round(f_end, 1), round(f_ref, 1), cons))

                # --- ОДОМЕТР (Логика из perenos_odometr) ---
                if not pd.isna(sid_p):
                    p_odo = {'oid': oid, 'slist': f's{int(sid_p)}', 'from': f"{date_str} 00:00:00", 'to': f"{date_str} 23:59:59"}
                    res_o = requests.get(f"{API_BASE_URL}/objdata", headers={'SessionId': sid}, params=p_odo, timeout=30).json()
                    recs = res_o.get('obj_data', {}).get('records', [])
                    if recs:
                        o_start, o_end = round(float(recs[0][1]), 2), round(float(recs[-1][1]), 2)
                        cursor.execute('INSERT OR REPLACE INTO odometer_reports (date, vehicle_number, driver_fio, odo_start, odo_end, daily_mileage) VALUES (?,?,?,?,?,?)',
                                       (date_str, v_name, fio, o_start, o_end, round(o_end - o_start, 2)))
                count += 1
            except: continue
        
        conn.commit()
        print(f"OK (обработано {count})")
    conn.close()

# =================================================================
# 4. БЛОК 2: АМИК (ЛОГИКА ИЗ amik_zapravka)
# =================================================================

def sync_amik_data():
    print("⛽ Обработка транзакций Амик...")
    if not os.path.exists(FILE_FLEET_AMIK) or not os.path.exists(FILE_AMIK_TRANSACTIONS):
        print("⚠️ Файлы Амик не найдены в корневой папке, пропускаю."); return

    df_fleet = pd.read_excel(FILE_FLEET_AMIK)
    df_transactions = pd.read_excel(FILE_AMIK_TRANSACTIONS)

    def get_clean_key(value):
        if pd.isna(value): return None
        match = re.search(r'(\d{4})$', str(value).replace('.0', '').strip())
        return match.group(1) if match else None

    df_transactions['key_card'] = df_transactions['Номер топливной карты'].apply(get_clean_key)
    df_fleet['key_card'] = df_fleet['Карта Амик'].apply(get_clean_key)

    fleet_lookup = df_fleet[['key_card', 'ID объекта', 'Номер авто', 'ФИО', 'Номер прицепа']].copy()
    fleet_lookup = fleet_lookup.dropna(subset=['key_card']).drop_duplicates(subset=['key_card'])

    final_df = pd.merge(df_transactions, fleet_lookup, on='key_card', how='left')
    if 'Дата' in final_df.columns:
        final_df['Дата'] = pd.to_datetime(final_df['Дата'], dayfirst=True, errors='coerce')

    try:
        conn = sqlite3.connect(DB_PATH)
        # Перезаписываем таблицу Амик свежими данными
        final_df.drop(columns=['key_card']).to_sql('amik_refills', conn, if_exists='replace', index=False)
        conn.close()
        print(f"✅ Данные Амик обновлены (Записей: {len(final_df)})")
    except Exception as e:
        print(f"❌ Ошибка Амик: {e}")

# =================================================================
# 5. ЗАПУСК
# =================================================================

if __name__ == "__main__":
    init_db()
    
    print("-" * 50)
    print("СИНХРОНИЗАЦИЯ ДАННЫХ В ЕДИНУЮ БАЗУ")
    print("-" * 50)
    
    m_input = input("📅 Введите номер месяца (1-12) или 0 для пропуска API: ")
    
    if m_input != "0":
        # Можно добавить выбор года, если нужно, пока 2025
        sync_api_data(2025, int(m_input))
    
    sync_amik_data()
    
    print(f"\n✨ ГОТОВО! База данных находится здесь:\n{DB_PATH}")
    input("\nНажмите Enter для выхода...")