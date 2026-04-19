#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Загрузка данных в БД
ЗАПРАВКИ - ТОЛЬКО из Excel (амик_заправки.xlsx)
ОСТАТКИ ТОПЛИВА - из API
"""

import requests
import pandas as pd
import sqlite3
import os
import re
import webbrowser
import time
from datetime import datetime, timedelta

# ============================================================================
# НАСТРОЙКИ
# ============================================================================

API_BASE_URL = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN = "abvprom"
PASSWORD = "29328"
INPUT_FILE = r"C:\Users\snltv\Desktop\ii\putevoi list\CAN_пробег_датчики_06_02_2026.xlsx"
EXCEL_REFUELS = r"C:\Users\snltv\Desktop\ii\putevoi list\справочники\амик_заправки.xlsx"
DB_NAME = "abv_fuel_in_out_comsum.db"

# ============================================================================
# ФУНКЦИИ БД
# ============================================================================

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


# ============================================================================
# API ФУНКЦИИ
# ============================================================================

def get_sid():
    try:
        res = requests.get(f"{API_BASE_URL}/connect", 
                           params={'login': LOGIN, 'password': PASSWORD, 'lang': 'ru-ru', 'timezone': '3'},
                           timeout=15)
        return res.headers.get('sessionid') or res.json().get('sessionid')
    except: 
        return None


def get_tank_volume(oid, sid):
    try:
        res = requests.get(f"{API_BASE_URL}/objsensorslist", 
                          params={'oid': oid}, 
                          headers={'SessionId': sid}, 
                          timeout=15).json()
        for sensor in res.get('obj_sensors', []):
            name = sensor.get('name', '')
            volumes = re.findall(r'(\d{3,4})', name)
            if volumes: 
                return int(max(volumes, key=len))
    except: 
        pass
    return 600


# ============================================================================
# ЗАГРУЗКА ЗАПРАВОК ИЗ EXCEL
# ============================================================================

def load_refuels_from_excel():
    """
    Загрузка заправок ТОЛЬКО из Excel файла
    Returns: dict {(vehicle_name, date): volume}
    """
    
    print("\n" + "="*60)
    print("ЗАГРУЗКА ЗАПРАВОК ИЗ EXCEL")
    print("="*60)
    
    if not os.path.exists(EXCEL_REFUELS):
        print(f"⚠️ Файл {EXCEL_REFUELS} не найден!")
        print("⚠️ Все заправки будут = 0")
        return {}
    
    try:
        df = pd.read_excel(EXCEL_REFUELS)
        
        print(f"✓ Загружено {len(df)} строк из Excel")
        print(f"\nКолонки в файле:")
        for col in df.columns:
            print(f"  - {col}")
        
        # Автоматическое определение колонок
        vehicle_col = None
        date_col = None
        volume_col = None
        
        for col in df.columns:
            col_lower = str(col).lower()
            
            if not vehicle_col and any(kw in col_lower for kw in ['авто', 'машина', 'vehicle', 'номер']):
                vehicle_col = col
                print(f"\n✓ Номер авто: '{col}'")
            
            if not date_col and any(kw in col_lower for kw in ['дата', 'date', 'число']):
                date_col = col
                print(f"✓ Дата: '{col}'")
            
            if not volume_col and any(kw in col_lower for kw in ['объ', 'литр', 'volume', 'сумма', 'л']):
                volume_col = col
                print(f"✓ Объём: '{col}'")
        
        if not all([vehicle_col, date_col, volume_col]):
            print("\n❌ Не удалось определить необходимые колонки!")
            return {}
        
        # Создаём словарь заправок
        refuels_dict = {}
        errors = 0
        
        for idx, row in df.iterrows():
            try:
                vehicle = str(row[vehicle_col]).strip()
                date_val = row[date_col]
                volume = float(row[volume_col])
                
                # Парсим дату
                if isinstance(date_val, datetime):
                    date_str = date_val.strftime('%Y-%m-%d')
                elif isinstance(date_val, str):
                    date_str = pd.to_datetime(date_val).strftime('%Y-%m-%d')
                else:
                    date_str = pd.to_datetime(str(date_val)).strftime('%Y-%m-%d')
                
                key = (vehicle, date_str)
                
                # Если несколько заправок в день - суммируем
                if key in refuels_dict:
                    refuels_dict[key] += volume
                else:
                    refuels_dict[key] = volume
                
            except Exception as e:
                errors += 1
        
        print(f"\n✓ Обработано успешно: {len(refuels_dict)} уникальных (ТС, дата)")
        if errors > 0:
            print(f"⚠️ Ошибок обработки: {errors}")
        
        # Показываем примеры
        if refuels_dict:
            print(f"\nПримеры заправок:")
            for i, ((vehicle, date), volume) in enumerate(list(refuels_dict.items())[:5], 1):
                print(f"  {i}. {vehicle} | {date} | {volume} л")
        
        print("="*60 + "\n")
        
        return refuels_dict
    
    except Exception as e:
        print(f"❌ Ошибка чтения Excel: {e}")
        return {}


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("\n" + "="*70)
    print("ЗАГРУЗКА ДАННЫХ В БД")
    print("Заправки - из Excel | Остатки топлива - из API")
    print("="*70)
    
    # Инициализация БД
    init_db()
    
    # Авторизация API
    print("\n🔐 Авторизация в API...")
    sid = get_sid()
    if not sid: 
        print("❌ Ошибка авторизации")
        input("\nНажмите Enter...")
        return
    print("✓ Подключено к API")
    
    # Загрузка справочника ТС
    if not os.path.exists(INPUT_FILE): 
        print(f"\n❌ Файл {INPUT_FILE} не найден!")
        input("\nНажмите Enter...")
        return
    
    print(f"\n📂 Загрузка справочника ТС...")
    df_input = pd.read_excel(INPUT_FILE).dropna(subset=['ID объекта'])
    car_names = pd.Series(df_input['Номер авто'].values, 
                         index=df_input['ID объекта'].astype(int)).to_dict()
    ids_list = list(car_names.keys())
    print(f"✓ Загружено {len(ids_list)} ТС")
    
    # Получение объёмов баков
    print("\n📡 Опрос конфигурации баков...")
    tank_map = {}
    for oid in ids_list:
        tank_map[oid] = get_tank_volume(oid, sid)
        time.sleep(0.1)
    print("✓ Конфигурация получена")
    
    # НОВОЕ: Загрузка заправок из Excel
    excel_refuels = load_refuels_from_excel()
    
    # Ввод периода
    date_start_str = input("\n📅 Дата начала (ГГГГ-ММ-ДД): ").strip()
    date_end_str = input("📅 Дата конца  (ГГГГ-ММ-ДД): ").strip()
    
    start_dt = pd.to_datetime(date_start_str)
    end_dt = pd.to_datetime(date_end_str)
    
    print(f"\n{'='*70}")
    print(f"ОБРАБОТКА ПЕРИОДА: {date_start_str} — {date_end_str}")
    print(f"{'='*70}\n")
    
    # Обработка по дням
    curr = start_dt
    total_added = 0
    total_skipped = 0
    
    while curr <= end_dt:
        d_str = curr.strftime('%Y-%m-%d')
        print(f"📅 {d_str}:", end=" ")
        day_data = []
        
        for oid in ids_list:
            v_name = car_names.get(oid, "N/A")
            
            # Проверка: уже есть в БД?
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM abv_fuel_in_out_comsum WHERE obj_id = ? AND report_date = ?", 
                          (oid, d_str))
            already_exists = cursor.fetchone()
            conn.close()
            
            if already_exists:
                total_skipped += 1
                continue
            
            try:
                # Получаем ТОЛЬКО уровни топлива из API
                res = requests.get(f"{API_BASE_URL}/getobjectsfuelinfo", 
                                   params={
                                       'date_from': d_str + " 00:00:00", 
                                       'date_to': d_str + " 23:59:59", 
                                       'objuids': str(oid)
                                   },
                                   headers={'SessionId': sid}, timeout=20).json()
                
                t_start = 0
                t_end = 0
                
                if res and len(res) > 0:
                    obj = res[0]
                    
                    # Извлекаем ТОЛЬКО уровни начала/конца
                    if obj.get('sensors'):
                        for s in obj['sensors']:
                            name_lower = s.get('sensor_name', '').lower()
                            if any(w in name_lower for w in ["бак", "lls", "fuel", "датчик"]):
                                t_start += float(s.get('beginLevel', 0))
                                t_end += float(s.get('endLevel', 0))
                    else:
                        t_start = float(obj.get('beginLevel', 0))
                        t_end = float(obj.get('endLevel', 0))
                
                # НОВОЕ: Заправки ТОЛЬКО из Excel!
                excel_key = (v_name, d_str)
                refuels = excel_refuels.get(excel_key, 0.0)
                
                vol = tank_map.get(oid, 600)
                consumption = round((t_start + refuels) - t_end, 1)
                if consumption < 0: 
                    consumption = 0
                
                day_data.append((
                    oid, v_name, d_str, vol, 
                    round(t_start, 1), round(refuels, 1), 
                    round(t_end, 1), round(consumption, 1)
                ))
                
                total_added += 1
            
            except Exception as e:
                continue
            
            time.sleep(0.05)
        
        # Сохранение данных за день
        if day_data:
            save_to_db(day_data)
            print(f"✓ Добавлено: {len(day_data)} записей")
        else:
            print("⏭️  Пропущено")
        
        curr += timedelta(days=1)
    
    print(f"\n{'='*70}")
    print("ИТОГИ")
    print(f"{'='*70}")
    print(f"✅ Добавлено записей: {total_added}")
    print(f"⏭️  Пропущено (уже есть): {total_skipped}")
    print(f"{'='*70}\n")
    
    print(f"🚀 Готово! База данных: {DB_NAME}")
    
    # Генерация HTML-отчета
    if os.path.exists(DB_NAME):
        conn = sqlite3.connect(DB_NAME)
        df_final = pd.read_sql_query("SELECT * FROM abv_fuel_in_out_comsum ORDER BY report_date DESC LIMIT 100", conn)
        conn.close()
        
        df_final.to_html("Full_History_Report.html", index=False)
        print(f"📄 HTML отчёт: Full_History_Report.html")
        
        webbrowser.open("file://" + os.path.abspath("Full_History_Report.html"))
    
    input("\nНажмите Enter для выхода...")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⏹️  Прервано пользователем")
    except Exception as e:
        print(f"\n❌ Критическая ошибка: {e}")
        input("\nНажмите Enter...")
