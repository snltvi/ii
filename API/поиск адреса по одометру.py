#!/usr/bin/env python34
# -*- coding: utf-8 -*-
"""
ПОИСК ПО ПОКАЗАНИЮ ОДОМЕТРА
Находит: дату, время, координаты, адрес по показанию одометра CAN
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
import os

# ============================================================================
# НАСТРОЙКИ
# ============================================================================

API_URL = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN = "abvprom"
PASSWORD = "29328"

TARGET_FILE = "CAN_пробег_датчики_06_02_2026.xlsx"
TIME_OFFSET = 3  # UTC+3

# ============================================================================
# ФУНКЦИИ API
# ============================================================================

def connect_to_api():
    """Подключение к API и получение SessionId"""
    try:
        res = requests.get(f"{API_URL}/connect", 
                           params={'login': LOGIN, 'password': PASSWORD, 
                                   'lang': 'ru-ru', 'timezone': str(TIME_OFFSET)},
                           timeout=10)
        return res.headers.get('sessionid') or res.json().get('sessionid')
    except Exception as e:
        print(f"❌ Ошибка подключения: {e}")
        return None


def get_address(session_id, lat, lon):
    """Получение адреса по координатам"""
    try:
        res = requests.get(f"{API_URL}/getaddress", 
                           headers={'SessionId': session_id}, 
                           params={'lat': lat, 'lon': lon}, 
                           timeout=10)
        if res.status_code == 200:
            return res.text.strip().strip('"')
    except:
        pass
    return "Адрес не определен"


def search_by_odometer(session_id, oid, sid, target_odo, search_start_date, search_days=30):
    """
    Поиск точки по показанию одометра
    
    Args:
        session_id: SessionId
        oid: ID объекта
        sid: ID датчика CAN одометра
        target_odo: искомое показание одометра (км)
        search_start_date: дата начала поиска (datetime)
        search_days: сколько дней искать назад
    
    Returns:
        dict: информация о найденной точке или None
    """
    print(f"\n🔍 Поиск показания одометра: {target_odo} км")
    print(f"   Период поиска: {search_days} дней назад от {search_start_date.strftime('%d.%m.%Y')}")
    
    # Поиск по дням (от новых к старым)
    for day_offset in range(search_days):
        check_date = search_start_date - timedelta(days=day_offset)
        date_str = check_date.strftime('%Y-%m-%d')
        
        print(f"\r   Проверка: {check_date.strftime('%d.%m.%Y')}...", end='', flush=True)
        
        try:
            # Запрос данных одометра за весь день
            url = f"{API_URL}/objdata"
            params = {
                'oid': oid,
                'slist': f's{sid}',
                'from': f"{date_str} 00:00:00",
                'to': f"{date_str} 23:59:59"
            }
            headers = {'SessionId': session_id}
            
            res = requests.get(url, headers=headers, params=params, timeout=30)
            data = res.json()
            
            if data.get('result') != 'Ok':
                continue
            
            records = data.get('obj_data', {}).get('records', [])
            
            if not records:
                continue
            
            # Ищем ближайшее значение к target_odo
            # records = [[time, value], [time, value], ...]
            best_match = None
            min_diff = float('inf')
            
            for record in records:
                if len(record) < 2 or not record[1]:
                    continue
                
                try:
                    time_str = record[0]
                    odo_value = float(record[1])
                    
                    # Разница между текущим и искомым одометром
                    diff = abs(odo_value - target_odo)
                    
                    # Если это самое близкое совпадение
                    if diff < min_diff:
                        min_diff = diff
                        best_match = {
                            'time': time_str,
                            'odometer': odo_value,
                            'diff': diff
                        }
                    
                    # Если нашли точное совпадение (разница < 0.1 км)
                    if diff < 0.1:
                        break
                
                except:
                    continue
            
            # Если нашли достаточно близкое совпадение (в пределах 5 км)
            if best_match and best_match['diff'] < 5.0:
                print(f"\n   ✓ Найдено на {check_date.strftime('%d.%m.%Y')}! Разница: {best_match['diff']:.2f} км")
                print(f"   Получение координат...")
                
                # Получаем координаты в это время
                coords = get_coords_at_time(session_id, oid, best_match['time'])
                
                # Если координаты не найдены через track, пробуем через getobjectsreport
                if not coords:
                    print(f"   Пробуем альтернативный метод...")
                    coords = get_coords_from_report(session_id, oid, check_date)
                
                if coords:
                    lat, lon = coords
                    print(f"   ✓ Координаты: {lat:.6f}, {lon:.6f}")
                    print(f"   Определение адреса...")
                    address = get_address(session_id, lat, lon)
                    
                    # Парсим время
                    dt = datetime.strptime(best_match['time'], '%Y-%m-%d %H:%M:%S')
                    
                    # ВАЖНО: Возвращаем результат сразу!
                    return {
                        'datetime': dt,
                        'odometer': best_match['odometer'],
                        'latitude': lat,
                        'longitude': lon,
                        'address': address,
                        'diff': best_match['diff']
                    }
                else:
                    print(f"   ⚠️  Координаты не найдены, продолжаем поиск...")
                    # Если нет координат, продолжаем искать дальше
                    continue
        
        except Exception as e:
            continue
    
    print(f"\n   ✗ Показание {target_odo} км не найдено за {search_days} дней")
    return None


def get_coords_at_time(session_id, oid, time_str):
    """
    Получение координат в указанное время
    Пробует разные временные окна для надёжности
    
    Returns:
        tuple: (lat, lon) или None
    """
    # Пробуем разные временные окна (2мин, 5мин, 10мин, 30мин)
    time_windows = [2, 5, 10, 30]
    
    for window in time_windows:
        try:
            dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
            time_from = (dt - timedelta(minutes=window)).strftime('%Y-%m-%d %H:%M:%S')
            time_to = (dt + timedelta(minutes=window)).strftime('%Y-%m-%d %H:%M:%S')
            
            url = f"{API_URL}/track"
            params = {
                'oid': oid,
                'from': time_from,
                'to': time_to
            }
            headers = {'SessionId': session_id}
            
            res = requests.get(url, headers=headers, params=params, timeout=15)
            data = res.json()
            
            if data.get('result') == 'Ok':
                points = data.get('track', [])
                if points and len(points) > 0:
                    # Ищем точку, ближайшую ко времени
                    target_time = dt
                    best_point = None
                    min_time_diff = timedelta(days=999)
                    
                    for point in points:
                        point_time_str = point.get('dt')
                        if point_time_str:
                            try:
                                point_time = datetime.strptime(point_time_str, '%Y-%m-%d %H:%M:%S')
                                time_diff = abs(point_time - target_time)
                                
                                if time_diff < min_time_diff:
                                    min_time_diff = time_diff
                                    best_point = point
                            except:
                                continue
                    
                    if best_point:
                        lat = best_point.get('lat')
                        lon = best_point.get('lon')
                        if lat and lon:
                            return (lat, lon)
        except:
            continue
    
    return None


def get_coords_from_report(session_id, oid, check_date):
    """
    Альтернативный метод: получение координат через getobjectsreport
    
    Returns:
        tuple: (lat, lon) или None
    """
    try:
        date_str = check_date.strftime('%Y-%m-%d')
        
        url = f"{API_URL}/getobjectsreport"
        params = {
            'date_from': f"{date_str} 00:00:00",
            'date_to': f"{date_str} 23:59:59",
            'objuids': str(oid),
            'split': 'none',
            'param': 'stop_coords'
        }
        headers = {'SessionId': session_id}
        
        res = requests.get(url, headers=headers, params=params, timeout=15)
        data = res.json()
        
        if data and len(data) > 0:
            periods = data[0].get('periods', [])
            if periods and len(periods) > 0:
                prms = periods[0].get('prms', [])
                for prm in prms:
                    if prm.get('name') == 'stop_coords':
                        coords_str = prm.get('value')
                        if coords_str and ';' in str(coords_str):
                            try:
                                lat, lon = str(coords_str).split(';')
                                return (float(lat), float(lon))
                            except:
                                pass
    except:
        pass
    return None


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("\n" + "="*70)
    print("🔍 ПОИСК ПО ПОКАЗАНИЮ ОДОМЕТРА")
    print("="*70)
    
    # 1. Проверка файла
    if not os.path.exists(TARGET_FILE):
        print(f"\n❌ Файл {TARGET_FILE} не найден!")
        input("\nНажмите Enter для выхода...")
        return
    
    # 2. Загрузка данных ТС
    try:
        df = pd.read_excel(TARGET_FILE)
        print(f"\n✓ Загружено {len(df)} транспортных средств")
    except Exception as e:
        print(f"\n❌ Ошибка чтения файла: {e}")
        input("\nНажмите Enter для выхода...")
        return
    
    # Проверка колонок
    required = ['ID объекта', 'SID']
    missing = [col for col in required if col not in df.columns]
    if missing:
        print(f"❌ Отсутствуют колонки: {missing}")
        input("\nНажмите Enter для выхода...")
        return
    
    # 3. Подключение к API
    print("\n🔗 Подключение к API...")
    session_id = connect_to_api()
    if not session_id:
        input("\nНажмите Enter для выхода...")
        return
    print("✓ Подключено")
    
    # 4. Выбор ТС
    print("\n" + "-"*70)
    print("ВЫБОР ТРАНСПОРТНОГО СРЕДСТВА")
    print("-"*70)
    
    for i, row in df.iterrows():
        vehicle = row.get('Номер авто', f'ID_{row["ID объекта"]}')
        driver = row.get('ФИО', '')
        print(f"{i+1:2d}. {vehicle:15} - {driver}")
    
    print("-"*70)
    
    try:
        choice = int(input("\nВыберите номер ТС: ").strip())
        if choice < 1 or choice > len(df):
            print("❌ Неверный номер!")
            input("\nНажмите Enter для выхода...")
            return
    except:
        print("❌ Неверный ввод!")
        input("\nНажмите Enter для выхода...")
        return
    
    selected_row = df.iloc[choice - 1]
    oid = int(selected_row['ID объекта'])
    sid = int(selected_row['SID'])
    vehicle_name = selected_row.get('Номер авто', f'ID_{oid}')
    driver_name = selected_row.get('ФИО', '')
    
    print(f"\n✓ Выбрано: {vehicle_name} ({driver_name})")
    
    # 5. Ввод показания одометра
    print("\n" + "-"*70)
    print("ПАРАМЕТРЫ ПОИСКА")
    print("-"*70)
    
    try:
        target_odo = float(input("\nПоказание одометра (км): ").strip())
    except:
        print("❌ Неверное значение одометра!")
        input("\nНажмите Enter для выхода...")
        return
    
    # Дата начала поиска (по умолчанию - сегодня)
    print("\nДата начала поиска (по умолчанию - сегодня)")
    print("Формат: ГГГГ-ММ-ДД или Enter для сегодня")
    
    search_date_str = input("Дата начала поиска: ").strip()
    
    if search_date_str:
        try:
            search_start_date = datetime.strptime(search_date_str, '%Y-%m-%d')
        except:
            print("❌ Неверный формат даты!")
            input("\nНажмите Enter для выхода...")
            return
    else:
        search_start_date = datetime.now()
        print(f"✓ Используется сегодняшняя дата: {search_start_date.strftime('%d.%m.%Y')}")
    
    # Период поиска
    try:
        search_days_str = input("\nСколько дней искать назад (по умолчанию 30): ").strip()
        search_days = int(search_days_str) if search_days_str else 30
    except:
        search_days = 30
    
    # 6. Поиск
    print("\n" + "="*70)
    print(f"🚗 {vehicle_name} ({driver_name})")
    print("="*70)
    
    result = search_by_odometer(session_id, oid, sid, target_odo, search_start_date, search_days)
    
    # 7. Результаты
    if result:
        print("\n" + "="*70)
        print("✅ РЕЗУЛЬТАТ ПОИСКА")
        print("="*70)
        print(f"\n🔢 Показание одометра: {result['odometer']:.2f} км")
        print(f"   (разница с искомым: {result['diff']:.2f} км)")
        print(f"\n📅 Дата и время: {result['datetime'].strftime('%d.%m.%Y %H:%M:%S')}")
        print(f"\n📍 Координаты: {result['latitude']:.6f}, {result['longitude']:.6f}")
        print(f"\n🏠 Адрес:")
        print(f"   {result['address']}")
        
        # Ссылка на Google Maps
        maps_url = f"https://www.google.com/maps?q={result['latitude']},{result['longitude']}"
        print(f"\n🗺️  Google Maps: {maps_url}")
        
        # Сохранение в Excel
        save_choice = input("\n💾 Сохранить результат в Excel? (y/n): ").strip().lower()
        
        if save_choice == 'y':
            results_df = pd.DataFrame([{
                'ФИО': driver_name,
                'Номер авто': vehicle_name,
                'ID объекта': oid,
                'Искомый одометр (км)': target_odo,
                'Найденный одометр (км)': result['odometer'],
                'Разница (км)': result['diff'],
                'Дата': result['datetime'].strftime('%d.%m.%Y'),
                'Время': result['datetime'].strftime('%H:%M:%S'),
                'Широта': result['latitude'],
                'Долгота': result['longitude'],
                'Адрес': result['address'],
                'Google Maps': maps_url
            }])
            
            output_file = f"Поиск_одометр_{target_odo:.0f}км_{vehicle_name.replace(' ', '_')}.xlsx"
            
            try:
                results_df.to_excel(output_file, index=False)
                print(f"\n✓ Результат сохранен: {output_file}")
                
                # Попытка открыть файл
                try:
                    os.startfile(output_file)
                except:
                    pass
            except Exception as e:
                print(f"\n❌ Ошибка сохранения: {e}")
    
    else:
        print("\n" + "="*70)
        print("❌ ПОКАЗАНИЕ НЕ НАЙДЕНО")
        print("="*70)
        print("\n💡 Попробуйте:")
        print("   - Увеличить период поиска")
        print("   - Проверить правильность показания одометра")
        print("   - Убедиться, что машина использовалась в этот период")
    
    input("\n\nНажмите Enter для выхода...")


if __name__ == "__main__":
    main()
