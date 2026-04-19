#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Импорт заправок из Excel в базу данных
С привязкой к автомобилям
"""

import pandas as pd
import sqlite3
import os
from datetime import datetime

# ============================================================================
# НАСТРОЙКИ
# ============================================================================

EXCEL_FILE = r"C:\Users\snltv\Desktop\ii\putevoi list\справочники\амик_заправки.xlsx"
VEHICLES_FILE = r"C:\Users\snltv\Desktop\ii\putevoi list\CAN_пробег_датчики_06_02_2026.xlsx"
DB_FILE = "abv_fuel_in_out_comsum.db"

# ============================================================================
# ФУНКЦИИ
# ============================================================================

def init_refuelings_table():
    """Создание таблицы заправок"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS refuelings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            obj_id INTEGER,
            vehicle_name TEXT,
            refuel_date TEXT,
            refuel_time TEXT,
            volume REAL,
            location TEXT,
            notes TEXT,
            imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(obj_id, refuel_date, refuel_time, volume)
        )
    ''')
    
    conn.commit()
    conn.close()


def load_vehicles_mapping():
    """Загрузка справочника ТС"""
    print("📂 Загрузка справочника ТС...")
    
    if not os.path.exists(VEHICLES_FILE):
        print(f"❌ Файл {VEHICLES_FILE} не найден!")
        return None
    
    try:
        df = pd.read_excel(VEHICLES_FILE)
        
        # Создаём словарь: Номер авто -> ID объекта
        mapping = {}
        for _, row in df.iterrows():
            vehicle_num = str(row['Номер авто']).strip()
            obj_id = int(row['ID объекта'])
            mapping[vehicle_num] = obj_id
        
        print(f"✓ Загружено {len(mapping)} ТС")
        return mapping
    
    except Exception as e:
        print(f"❌ Ошибка загрузки справочника: {e}")
        return None


def import_refuelings_from_excel(vehicles_mapping):
    """Импорт заправок из Excel"""
    
    print(f"\n📂 Загрузка заправок из Excel...")
    
    if not os.path.exists(EXCEL_FILE):
        print(f"❌ Файл {EXCEL_FILE} не найден!")
        return
    
    try:
        # Читаем Excel
        df = pd.read_excel(EXCEL_FILE)
        
        print(f"✓ Загружено {len(df)} записей из Excel")
        print(f"\n📋 Колонки в файле:")
        for i, col in enumerate(df.columns, 1):
            print(f"   {i}. {col}")
        
        # Определяем колонки (подстроить под ваш файл!)
        # Предполагаемые колонки:
        # - Дата или Дата/Время
        # - Номер авто или Автомобиль
        # - Объём или Литры
        # - Адрес или Место (опционально)
        
        print("\n🔍 Определение колонок...")
        
        # Ищем колонку с номером авто
        vehicle_col = None
        for col in df.columns:
            if any(keyword in str(col).lower() for keyword in ['авто', 'машина', 'vehicle', 'номер']):
                vehicle_col = col
                print(f"   ✓ Номер авто: {col}")
                break
        
        # Ищем колонку с датой
        date_col = None
        for col in df.columns:
            if any(keyword in str(col).lower() for keyword in ['дата', 'date', 'время', 'time']):
                date_col = col
                print(f"   ✓ Дата: {col}")
                break
        
        # Ищем колонку с объёмом
        volume_col = None
        for col in df.columns:
            if any(keyword in str(col).lower() for keyword in ['объ', 'литр', 'volume', 'л', 'л.']):
                volume_col = col
                print(f"   ✓ Объём: {col}")
                break
        
        # Ищем колонку с адресом (опционально)
        location_col = None
        for col in df.columns:
            if any(keyword in str(col).lower() for keyword in ['адрес', 'место', 'location', 'address']):
                location_col = col
                print(f"   ✓ Адрес: {col}")
                break
        
        if not vehicle_col or not date_col or not volume_col:
            print("\n❌ Не удалось определить необходимые колонки!")
            print("Пожалуйста, проверьте структуру файла.")
            return
        
        # Импорт данных
        print(f"\n{'='*60}")
        print("ИМПОРТ ЗАПРАВОК В БАЗУ ДАННЫХ")
        print(f"{'='*60}\n")
        
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        success_count = 0
        skip_count = 0
        error_count = 0
        
        for idx, row in df.iterrows():
            try:
                # Получаем номер авто
                vehicle_num = str(row[vehicle_col]).strip()
                
                # Находим ID объекта
                obj_id = vehicles_mapping.get(vehicle_num)
                
                if not obj_id:
                    print(f"  ⚠️ Строка {idx+1}: ТС '{vehicle_num}' не найдено в справочнике")
                    skip_count += 1
                    continue
                
                # Получаем дату и время
                date_value = row[date_col]
                
                if pd.isna(date_value):
                    print(f"  ⚠️ Строка {idx+1}: Пустая дата")
                    skip_count += 1
                    continue
                
                # Обработка даты
                if isinstance(date_value, datetime):
                    refuel_date = date_value.strftime('%Y-%m-%d')
                    refuel_time = date_value.strftime('%H:%M:%S')
                elif isinstance(date_value, str):
                    # Пытаемся распарсить строку
                    try:
                        dt = pd.to_datetime(date_value)
                        refuel_date = dt.strftime('%Y-%m-%d')
                        refuel_time = dt.strftime('%H:%M:%S')
                    except:
                        refuel_date = date_value
                        refuel_time = "00:00:00"
                else:
                    refuel_date = str(date_value)
                    refuel_time = "00:00:00"
                
                # Получаем объём
                volume = float(row[volume_col])
                
                # Получаем адрес (если есть)
                location = ""
                if location_col and location_col in row:
                    location = str(row[location_col]) if not pd.isna(row[location_col]) else ""
                
                # Вставка в БД
                cursor.execute('''
                    INSERT OR IGNORE INTO refuelings 
                    (obj_id, vehicle_name, refuel_date, refuel_time, volume, location, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    obj_id,
                    vehicle_num,
                    refuel_date,
                    refuel_time,
                    round(volume, 1),
                    location,
                    f"Импорт из Excel строка {idx+1}"
                ))
                
                if cursor.rowcount > 0:
                    print(f"  ✓ {vehicle_num} | {refuel_date} {refuel_time} | {volume} л")
                    success_count += 1
                else:
                    skip_count += 1
                
            except Exception as e:
                print(f"  ❌ Строка {idx+1}: Ошибка - {e}")
                error_count += 1
        
        conn.commit()
        conn.close()
        
        print(f"\n{'='*60}")
        print("ИТОГИ ИМПОРТА")
        print(f"{'='*60}")
        print(f"  ✅ Успешно добавлено: {success_count}")
        print(f"  ⏭️  Пропущено (дубли):  {skip_count}")
        print(f"  ❌ Ошибок:             {error_count}")
        print(f"{'='*60}\n")
        
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")


def update_main_table_with_refuelings():
    """
    Обновление главной таблицы abv_fuel_in_out_comsum
    Добавление заправок из таблицы refuelings
    """
    
    print(f"\n{'='*60}")
    print("ОБНОВЛЕНИЕ ГЛАВНОЙ ТАБЛИЦЫ ЗАПРАВКАМИ")
    print(f"{'='*60}\n")
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Получаем все записи из главной таблицы
    cursor.execute("SELECT obj_id, report_date, refuels FROM abv_fuel_in_out_comsum")
    main_records = cursor.fetchall()
    
    updated_count = 0
    
    for obj_id, report_date, current_refuels in main_records:
        # Суммируем заправки из таблицы refuelings за этот день
        cursor.execute('''
            SELECT SUM(volume) 
            FROM refuelings 
            WHERE obj_id = ? AND refuel_date = ?
        ''', (obj_id, report_date))
        
        result = cursor.fetchone()
        excel_refuels = result[0] if result[0] else 0.0
        
        if excel_refuels > 0:
            # Обновляем заправки в главной таблице
            cursor.execute('''
                UPDATE abv_fuel_in_out_comsum 
                SET refuels = ? 
                WHERE obj_id = ? AND report_date = ?
            ''', (round(excel_refuels, 1), obj_id, report_date))
            
            if cursor.rowcount > 0:
                print(f"  ✓ {obj_id} | {report_date} | Заправки: {excel_refuels} л")
                updated_count += 1
    
    conn.commit()
    conn.close()
    
    print(f"\n{'='*60}")
    print(f"✓ Обновлено записей: {updated_count}")
    print(f"{'='*60}\n")


def show_statistics():
    """Показать статистику по импорту"""
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Статистика по заправкам
    cursor.execute('''
        SELECT 
            vehicle_name,
            COUNT(*) as refuel_count,
            SUM(volume) as total_volume,
            MIN(refuel_date) as first_date,
            MAX(refuel_date) as last_date
        FROM refuelings
        GROUP BY vehicle_name
        ORDER BY total_volume DESC
    ''')
    
    stats = cursor.fetchall()
    conn.close()
    
    if stats:
        print(f"\n{'='*60}")
        print("СТАТИСТИКА ПО ЗАПРАВКАМ")
        print(f"{'='*60}\n")
        
        for vehicle, count, volume, first, last in stats:
            print(f"  {vehicle}:")
            print(f"    Заправок: {count}")
            print(f"    Объём:    {volume:.1f} л")
            print(f"    Период:   {first} — {last}")
            print()


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("\n" + "="*60)
    print("ИМПОРТ ЗАПРАВОК ИЗ EXCEL В БАЗУ ДАННЫХ")
    print("="*60)
    
    # Инициализация БД
    init_refuelings_table()
    
    # Загрузка справочника ТС
    vehicles_mapping = load_vehicles_mapping()
    
    if not vehicles_mapping:
        return
    
    # Импорт заправок
    import_refuelings_from_excel(vehicles_mapping)
    
    # Обновление главной таблицы (опционально)
    update_choice = input("\n❓ Обновить главную таблицу заправками из Excel? (y/n): ").strip().lower()
    if update_choice == 'y':
        update_main_table_with_refuelings()
    
    # Статистика
    show_statistics()
    
    print("\n✅ Импорт завершён!")
    input("\nНажмите Enter для выхода...")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⏹️  Прервано пользователем")
    except Exception as e:
        print(f"\n❌ Критическая ошибка: {e}")
        input("\nНажмите Enter...")
