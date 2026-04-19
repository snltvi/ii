#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Расчет суточного пробега через API Mobiteam
ГИБРИДНЫЙ МЕТОД: пробует getobjectsreport, при неудаче - objdata
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
import sys
import os

# ============================================================================
# КОНСТАНТЫ
# ============================================================================

API_BASE_URL = "https://gps.mobiteam.com.ua/api/integration/v1"

# Credentials для автоматического получения SessionId
LOGIN = "abvprom"
PASSWORD = "29328"

# Поиск входного файла с датчиками
EXCEL_FILES = ['CAN_пробег_датчики_06_02_2026.xlsx', 'Датчики_CAN_пробег.xlsx']


# ============================================================================
# ФУНКЦИИ API
# ============================================================================

def connect_to_api():
    """Подключение к API и получение SessionId"""
    url = f"{API_BASE_URL}/connect"
    params = {
        'login': LOGIN,
        'password': PASSWORD,
        'lang': 'ru-ru',
        'timezone': '+2'
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        
        session_id = response.headers.get('sessionid')
        
        if not session_id:
            raise Exception("SessionId не найден в ответе API")
        
        return session_id
        
    except Exception as e:
        print(f"✗ Ошибка подключения к API: {e}")
        sys.exit(1)


def get_mileage_from_report(session_id, oid, date_from_utc, date_to_utc):
    """
    МЕТОД 1: Получение пробега через getobjectsreport
    Быстрее, но может не работать для всех объектов
    
    Returns:
        tuple: (odo_start, odo_end, mileage) или (None, None, None)
    """
    url = f"{API_BASE_URL}/getobjectsreport"
    
    params = {
        'date_from': date_from_utc.strftime('%Y-%m-%d %H:%M:%S'),
        'date_to': date_to_utc.strftime('%Y-%m-%d %H:%M:%S'),
        'objuids': str(oid),
        'split': 'none',
        'param': 'start_can_dist;stop_can_dist;can_dist'
    }
    
    headers = {'SessionId': session_id}
    
    try:
        response = requests.get(url, params=params, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        if not data or len(data) == 0:
            return None, None, None
        
        obj_data = data[0]
        periods = obj_data.get('periods', [])
        
        if len(periods) == 0:
            return None, None, None
        
        period = periods[0]
        prms = period.get('prms', [])
        
        # Ищем нужные параметры
        start_can_dist = None
        stop_can_dist = None
        can_dist = None
        
        for prm in prms:
            name = prm.get('name')
            value = prm.get('value')
            
            if name == 'start_can_dist' and value:
                start_can_dist = float(value)
            elif name == 'stop_can_dist' and value:
                stop_can_dist = float(value)
            elif name == 'can_dist' and value:
                can_dist = float(value)
        
        # Проверяем что хотя бы can_dist есть
        if can_dist is not None and can_dist > 0:
            return start_can_dist, stop_can_dist, can_dist
        
        return None, None, None
        
    except Exception as e:
        return None, None, None


def get_mileage_from_objdata(session_id, oid, sensor_id, date_from_str, date_to_str):
    """
    МЕТОД 2: Получение пробега через objdata (прямой запрос датчика)
    Медленнее, но надёжнее
    
    Returns:
        tuple: (odo_start, odo_end, mileage) или (None, None, None)
    """
    url = f"{API_BASE_URL}/objdata"
    
    params = {
        'oid': oid,
        'slist': f's{sensor_id}',
        'from': date_from_str,
        'to': date_to_str
    }
    
    headers = {'SessionId': session_id}
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        if data.get('result') != 'Ok':
            return None, None, None
        
        records = data.get('obj_data', {}).get('records', [])
        
        if not records:
            return None, None, None
        
        # records = [[time, value], [time, value], ...]
        valid_records = [rec for rec in records if len(rec) >= 2 and rec[1] and str(rec[1]).strip()]
        
        if not valid_records:
            return None, None, None
        
        value_start = float(valid_records[0][1])
        value_end = float(valid_records[-1][1])
        mileage = value_end - value_start
        
        return value_start, value_end, mileage
        
    except Exception as e:
        return None, None, None


def get_mileage_hybrid(session_id, oid, sensor_id, target_date):
    """
    ГИБРИДНЫЙ метод: пробует getobjectsreport, если не работает - objdata
    
    Returns:
        tuple: (odo_start, odo_end, mileage, method_used) или (None, None, None, None)
    """
    # Подготовка времени для обоих методов
    date_from_local = target_date.replace(hour=0, minute=0, second=0)
    date_to_local = target_date.replace(hour=23, minute=59, second=59)
    date_from_utc = date_from_local - timedelta(hours=2)
    date_to_utc = date_to_local - timedelta(hours=2)
    
    date_str = target_date.strftime('%Y-%m-%d')
    date_from_str = f"{date_str} 00:00:00"
    date_to_str = f"{date_str} 23:59:00"
    
    # МЕТОД 1: getobjectsreport (быстрый)
    odo_start, odo_end, mileage = get_mileage_from_report(session_id, oid, date_from_utc, date_to_utc)
    
    if mileage is not None:
        return odo_start, odo_end, mileage, 'report'
    
    # МЕТОД 2: objdata (надёжный, но требует SID)
    if sensor_id:
        odo_start, odo_end, mileage = get_mileage_from_objdata(
            session_id, oid, sensor_id, date_from_str, date_to_str
        )
        
        if mileage is not None:
            return odo_start, odo_end, mileage, 'objdata'
    
    return None, None, None, None


# ============================================================================
# РАСЧЕТ ПРОБЕГА
# ============================================================================

def calculate_mileage(session_id, vehicles_df, target_date):
    """Расчет пробега для всех автомобилей"""
    
    print(f"\n{'='*60}")
    print(f"ЗАПРОС ДАННЫХ ЗА {target_date.strftime('%d.%m.%Y')}")
    print(f"{'='*60}\n")
    
    results = []
    method_stats = {'report': 0, 'objdata': 0, 'failed': 0}
    
    for idx, row in vehicles_df.iterrows():
        oid = int(row['ID объекта'])
        sensor_id = int(row['SID']) if 'SID' in row and pd.notna(row['SID']) else None
        driver = row.get('ФИО', '')
        vehicle_number = row.get('Номер авто', '')
        trailer_number = row.get('Номер прицепа', '')
        
        print(f"  {idx+1}. {driver} ({vehicle_number})...", end=' ')
        
        try:
            odo_start, odo_end, mileage, method = get_mileage_hybrid(
                session_id, oid, sensor_id, target_date
            )
            
            if mileage is None:
                print("НЕТ ДАННЫХ")
                method_stats['failed'] += 1
                results.append({
                    'ФИО': driver,
                    'Номер авто': vehicle_number,
                    'Номер прицепа': trailer_number,
                    'ID объекта': oid,
                    'Одометр начало (км)': None,
                    'Одометр конец (км)': None,
                    'Пробег (км)': 0.0,
                    'Метод': None,
                    'Статус': 'Нет данных'
                })
                continue
            
            method_stats[method] += 1
            
            # Проверка на адекватность
            if mileage < 0 or mileage > 2000:
                print(f"⚠️ {mileage:.2f} км [{method}]")
                status = 'Проверить'
            else:
                print(f"✓ {mileage:.2f} км [{method}]")
                status = 'OK'
            
            results.append({
                'ФИО': driver,
                'Номер авто': vehicle_number,
                'Номер прицепа': trailer_number,
                'ID объекта': oid,
                'Одометр начало (км)': round(odo_start, 2) if odo_start else None,
                'Одометр конец (км)': round(odo_end, 2) if odo_end else None,
                'Пробег (км)': round(mileage, 2),
                'Метод': method,
                'Статус': status
            })
            
        except Exception as e:
            print(f"ОШИБКА: {e}")
            method_stats['failed'] += 1
            results.append({
                'ФИО': driver,
                'Номер авто': vehicle_number,
                'Номер прицепа': trailer_number,
                'ID объекта': oid,
                'Одометр начало (км)': None,
                'Одометр конец (км)': None,
                'Пробег (км)': 0.0,
                'Метод': None,
                'Статус': f'Ошибка: {str(e)[:50]}'
            })
    
    print(f"\n📊 МЕТОДЫ:")
    print(f"  getobjectsreport: {method_stats['report']}")
    print(f"  objdata: {method_stats['objdata']}")
    print(f"  Не найдено: {method_stats['failed']}")
    
    return pd.DataFrame(results)


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("\n" + "="*60)
    print("РАСЧЁТ СУТОЧНОГО ПРОБЕГА - Mobiteam API")
    print("ГИБРИДНЫЙ МЕТОД (report + objdata)")
    print("="*60)
    
    # Проверка наличия Excel файла
    excel_file = None
    for filename in EXCEL_FILES:
        if os.path.exists(filename):
            excel_file = filename
            break
    
    if not excel_file:
        print("\n✗ Excel файл не найден!")
        print(f"\nОжидаемые имена: {', '.join(EXCEL_FILES)}")
        sys.exit(1)
    
    # Ввод даты
    target_date_str = input("\nВведите дату (YYYY-MM-DD), например 2026-02-05: ").strip()
    
    try:
        target_date = datetime.strptime(target_date_str, '%Y-%m-%d')
    except ValueError:
        print("✗ Ошибка: неверный формат даты. Используйте YYYY-MM-DD")
        sys.exit(1)
    
    # Подключение к API
    print("\nПодключение к API...", end=' ')
    session_id = connect_to_api()
    print("✓ SessionId получен")
    
    # Загрузка Excel файла
    try:
        vehicles_df = pd.read_excel(excel_file)
        print(f"✓ Загружено {len(vehicles_df)} записей из {excel_file}")
        
        # ID объекта обязательно, SID опционально
        if 'ID объекта' not in vehicles_df.columns:
            print(f"✗ ОШИБКА: Отсутствует колонка 'ID объекта'")
            sys.exit(1)
        
        has_sid = 'SID' in vehicles_df.columns
        if not has_sid:
            print("⚠️  Колонка SID не найдена - будет использоваться только метод getobjectsreport")
        
        results_df = calculate_mileage(session_id, vehicles_df, target_date)
        output_file = f"Пробег_{target_date.strftime('%Y-%m-%d')}.xlsx"
        
    except Exception as e:
        print(f"✗ Ошибка чтения файла: {e}")
        sys.exit(1)
    
    # Сохранение результатов
    print(f"\n{'='*60}")
    print(f"СОХРАНЕНИЕ: {output_file}")
    print(f"{'='*60}\n")
    
    try:
        results_df.to_excel(output_file, index=False)
        print(f"✓ Результаты сохранены в {output_file}")
        print(f"\n📊 СТАТИСТИКА:")
        print(f"  Всего записей: {len(results_df)}")
        print(f"  Успешно: {len(results_df[results_df['Статус'] == 'OK'])}")
        print(f"  Нет данных: {len(results_df[results_df['Статус'] == 'Нет данных'])}")
        print(f"  Общий пробег: {results_df['Пробег (км)'].sum():.2f} км")
        print(f"  Макс. пробег: {results_df['Пробег (км)'].max():.2f} км")
        print(f"  Средний: {results_df['Пробег (км)'].mean():.2f} км")
        
    except Exception as e:
        print(f"✗ Ошибка сохранения: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
