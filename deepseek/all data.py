#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
РАСЧЕТ СУТОЧНОГО ПРОБЕГА - ФИНАЛЬНАЯ ВЕРСИЯ
Использует только рабочий endpoint /objdata
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
import os
import sys

# ============================================================================
# КОНСТАНТЫ
# ============================================================================

API_URL = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN = "abvprom"
PASSWORD = "29328"
TARGET_FILE = "CAN_пробег_датчики_06_02_2026.xlsx"

# ============================================================================
# ФУНКЦИИ API (ТОЛЬКО РАБОЧИЕ)
# ============================================================================

def connect_to_api():
    """Подключение к API - endpoint /connect работает"""
    try:
        response = requests.get(
            f"{API_URL}/connect",
            params={'login': LOGIN, 'password': PASSWORD, 'lang': 'ru-ru', 'timezone': '3'},
            timeout=10
        )
        
        if response.status_code == 200:
            session_id = response.headers.get('sessionid')
            if session_id:
                return session_id
        
        print(f"❌ Ошибка подключения: {response.status_code}")
        return None
        
    except Exception as e:
        print(f"❌ Ошибка подключения: {e}")
        return None

def get_can_data(session_id, oid, sid, date_from, date_to):
    """
    Получение данных CAN датчика - ЕДИНСТВЕННЫЙ РАБОЧИЙ ENDPOINT /objdata
    
    Args:
        session_id: SessionId из подключения
        oid: ID объекта
        sid: ID датчика CAN (SID)
        date_from: начало периода (YYYY-MM-DD HH:MM:SS)
        date_to: конец периода (YYYY-MM-DD HH:MM:SS)
    
    Returns:
        dict: {'result': 'Ok'/'Error', 'records': [], 'error': сообщение}
    """
    try:
        url = f"{API_URL}/objdata"
        params = {
            'oid': oid,
            'slist': f's{sid}',  # Префикс 's' перед SID
            'from': date_from,
            'to': date_to,
            'compress': 'true'  # Сжатие для ускорения
        }
        headers = {'SessionId': session_id}
        
        response = requests.get(url, headers=headers, params=params, timeout=30)
        
        if response.status_code == 200:
            try:
                data = response.json()
                return data
            except:
                return {'result': 'Error', 'error': 'Не JSON ответ'}
        else:
            return {'result': 'Error', 'error': f'HTTP {response.status_code}'}
            
    except requests.exceptions.Timeout:
        return {'result': 'Error', 'error': 'Таймаут'}
    except Exception as e:
        return {'result': 'Error', 'error': str(e)[:100]}

def calculate_mileage_from_records(records):
    """
    Расчет пробега из записей одометра
    
    Args:
        records: список записей [['время', 'значение'], ...]
    
    Returns:
        dict: {'start': начало, 'end': конец, 'mileage': пробег, 'status': статус}
    """
    if not records:
        return {'start': None, 'end': None, 'mileage': 0, 'status': 'Нет данных', 'records': 0}
    
    # Фильтруем валидные значения
    valid_values = []
    for rec in records:
        if len(rec) >= 2 and rec[1] is not None:
            try:
                val = float(str(rec[1]).strip())
                if val >= 0:  # Одометр не может быть отрицательным
                    valid_values.append(val)
            except:
                continue
    
    if len(valid_values) < 2:
        return {'start': None, 'end': None, 'mileage': 0, 'status': 'Мало данных', 'records': len(valid_values)}
    
    # Берем первое и последнее значение
    start_odo = valid_values[0]
    end_odo = valid_values[-1]
    mileage = end_odo - start_odo
    
    # Анализируем качество данных
    records_count = len(valid_values)
    
    if mileage < 0:
        # Пробуем найти максимальную разницу
        if len(valid_values) > 2:
            actual_mileage = max(valid_values) - min(valid_values)
            if actual_mileage >= 0:
                mileage = actual_mileage
                status = 'Проверить (корр.)'
            else:
                mileage = 0
                status = 'Ошибка данных'
        else:
            mileage = 0
            status = 'Ошибка данных'
    elif mileage > 2000:
        status = 'Проверить (>2000км)'
    elif mileage == 0:
        if records_count > 10:
            status = 'Нулевой пробег'
        else:
            status = 'Мало данных'
    else:
        status = 'OK'
    
    return {
        'start': start_odo,
        'end': end_odo,
        'mileage': mileage,
        'status': status,
        'records': records_count
    }

# ============================================================================
# ОСНОВНЫЕ ФУНКЦИИ
# ============================================================================

def read_excel_file():
    """Чтение Excel файла с проверками"""
    if not os.path.exists(TARGET_FILE):
        print(f"❌ Файл не найден: {TARGET_FILE}")
        print(f"📁 Текущая папка: {os.getcwd()}")
        return None
    
    try:
        df = pd.read_excel(TARGET_FILE)
        print(f"✓ Файл прочитан: {TARGET_FILE}")
        print(f"📊 Записей: {len(df)}")
        return df
    except Exception as e:
        print(f"❌ Ошибка чтения файла: {e}")
        return None

def check_data_quality(df):
    """Проверка качества данных в файле"""
    print("\n🔍 ПРОВЕРКА ДАННЫХ В ФАЙЛЕ:")
    print("-" * 70)
    
    # Проверяем колонки
    required_cols = ['ID объекта', 'SID']
    missing_cols = [col for col in required_cols if col not in df.columns]
    
    if missing_cols:
        print(f"❌ Отсутствуют колонки: {missing_cols}")
        print(f"   Найденные колонки: {list(df.columns)}")
        return False
    
    print("✓ Обязательные колонки присутствуют")
    
    # Проверяем SID
    problems = []
    for idx, row in df.iterrows():
        oid = row['ID объекта']
        sid = row['SID']
        
        if pd.isna(sid):
            problems.append(f"Строка {idx+1}: ID {oid} - SID пустой")
        elif sid == 0:
            problems.append(f"Строка {idx+1}: ID {oid} - SID=0 (некорректно)")
        elif isinstance(sid, (int, float)) and sid < 10000:
            problems.append(f"Строка {idx+1}: ID {oid} - SID={sid} (слишком маленький)")
    
    if problems:
        print(f"⚠ Найдено проблем с SID: {len(problems)}")
        for problem in problems[:5]:  # Показываем первые 5
            print(f"  {problem}")
        if len(problems) > 5:
            print(f"  ... и еще {len(problems)-5} проблем")
        
        print("\n💡 Для объекта 8743 должен быть SID=129259")
        print("   Исправьте SID в файле Excel и перезапустите скрипт")
        return False
    
    print("✓ SID корректны")
    return True

def show_vehicle_list(df):
    """Показать список транспортных средств"""
    print("\n🚗 СПИСОК ТРАНСПОРТНЫХ СРЕДСТВ:")
    print("-" * 80)
    print(f"{'№':>3} {'ФИО':<25} {'Авто':<12} {'ID':>8} {'SID':>10}")
    print("-" * 80)
    
    for idx, row in df.iterrows():
        driver = str(row.get('ФИО', row.get('Карта Амик', f'ID_{row["ID объекта"]}')))[:24]
        vehicle = str(row.get('Номер авто', row.get('Сокар', '')))[:10]
        oid = row['ID объекта']
        sid = row['SID']
        
        print(f"{idx+1:3d}. {driver:<25} {vehicle:<12} {oid:>8} {sid:>10}")
    
    print("-" * 80)

def process_vehicles(session_id, df, date_str):
    """Обработка всех транспортных средств"""
    print(f"\n📅 РАСЧЕТ ПРОБЕГА ЗА {date_str}")
    print("=" * 70)
    
    results = []
    total = len(df)
    
    for idx, row in df.iterrows():
        # Прогресс
        percent = (idx + 1) / total * 100
        print(f"\r🔄 Обработка: {idx+1}/{total} ({percent:.1f}%)", end='', flush=True)
        
        try:
            oid = int(row['ID объекта'])
            sid = int(row['SID'])
            driver = str(row.get('ФИО', '')).strip() or f'ID_{oid}'
            vehicle = str(row.get('Номер авто', '')).strip() or ''
            trailer = str(row.get('Номер прицепа', '')).strip() or ''
            
            # Проверка SID
            if sid == 0 or pd.isna(sid):
                results.append(create_error_result(idx, row, 'SID=0 (некорректно)'))
                continue
            
            # Получение данных
            date_from = f"{date_str} 00:00:00"
            date_to = f"{date_str} 23:59:59"
            
            data = get_can_data(session_id, oid, sid, date_from, date_to)
            
            if data.get('result') == 'Ok':
                records = data.get('obj_data', {}).get('records', [])
                mileage_data = calculate_mileage_from_records(records)
                
                results.append({
                    '№': idx + 1,
                    'ФИО': driver,
                    'Номер авто': vehicle,
                    'Номер прицепа': trailer,
                    'ID объекта': oid,
                    'SID': sid,
                    'Одометр начало (км)': round(mileage_data['start'], 2) if mileage_data['start'] else '',
                    'Одометр конец (км)': round(mileage_data['end'], 2) if mileage_data['end'] else '',
                    'Пробег (км)': round(mileage_data['mileage'], 2),
                    'Записей': mileage_data['records'],
                    'Статус': mileage_data['status']
                })
            else:
                results.append(create_error_result(idx, row, f"API: {data.get('error', 'Неизвестно')}"))
                
        except Exception as e:
            results.append(create_error_result(idx, row, f"Ошибка: {str(e)[:30]}"))
    
    print("\n\n✅ РАСЧЕТ ЗАВЕРШЕН!")
    return pd.DataFrame(results)

def create_error_result(idx, row, error_msg):
    """Создание записи об ошибке"""
    return {
        '№': idx + 1,
        'ФИО': str(row.get('ФИО', '')),
        'Номер авто': str(row.get('Номер авто', '')),
        'Номер прицепа': str(row.get('Номер прицепа', '')),
        'ID объекта': int(row['ID объекта']) if 'ID объекта' in row else 0,
        'SID': int(row['SID']) if 'SID' in row else 0,
        'Одометр начало (км)': '',
        'Одометр конец (км)': '',
        'Пробег (км)': 0,
        'Записей': 0,
        'Статус': error_msg
    }

def save_results(results_df, date_str):
    """Сохранение результатов"""
    output_file = f"Пробег_{date_str}.xlsx"
    
    try:
        results_df.to_excel(output_file, index=False)
        print(f"\n💾 Результаты сохранены в: {output_file}")
        print(f"📂 Полный путь: {os.path.join(os.getcwd(), output_file)}")
        return output_file
    except Exception as e:
        print(f"❌ Ошибка сохранения Excel: {e}")
        
        # Пробуем CSV
        try:
            csv_file = f"Пробег_{date_str}.csv"
            results_df.to_csv(csv_file, index=False, encoding='utf-8-sig')
            print(f"✓ Результаты сохранены в CSV: {csv_file}")
            return csv_file
        except:
            print("❌ Не удалось сохранить результаты!")
            return None

def show_statistics(results_df):
    """Показать статистику расчета"""
    print("\n📊 СТАТИСТИКА РАСЧЕТА:")
    print("=" * 70)
    
    total = len(results_df)
    
    # Группируем по статусам
    status_counts = results_df['Статус'].value_counts()
    
    print(f"Всего транспортных средств: {total}")
    print("\nРаспределение по статусам:")
    
    for status, count in status_counts.items():
        percentage = count / total * 100
        
        if status == 'OK':
            icon = '✓'
        elif 'Проверить' in status:
            icon = '⚠'
        elif 'Ошибка' in status or 'SID=0' in status:
            icon = '✗'
        elif 'Нет данных' in status or 'Мало данных' in status:
            icon = '📭'
        elif 'Нулевой пробег' in status:
            icon = '0️⃣'
        else:
            icon = '❓'
        
        print(f"  {icon} {status:<25} {count:>3} ({percentage:.1f}%)")
    
    # Общий пробег
    total_mileage = results_df['Пробег (км)'].sum()
    avg_mileage = results_df['Пробег (км)'].mean() if total > 0 else 0
    
    print(f"\n🛣️  Общий суточный пробег: {total_mileage:,.1f} км")
    print(f"📈 Средний пробег на ТС: {avg_mileage:,.1f} км")
    
    # Топ-5 по пробегу
    top5 = results_df.nlargest(5, 'Пробег (км)')
    if len(top5) > 0:
        print(f"\n🏆 ТОП-5 ПО ПРОБЕГУ:")
        for i, (_, row) in enumerate(top5.iterrows(), 1):
            driver = row['ФИО'][:20] if len(row['ФИО']) > 20 else row['ФИО']
            print(f"  {i}. {driver:<20} {row['Пробег (км)']:>7.1f} км")

# ============================================================================
# ГЛАВНАЯ ФУНКЦИЯ
# ============================================================================

def main():
    print("=" * 70)
    print("РАСЧЕТ СУТОЧНОГО ПРОБЕГА - MOBITEAM API")
    print("=" * 70)
    
    # 1. Чтение файла
    df = read_excel_file()
    if df is None:
        input("\nНажмите Enter для выхода...")
        return
    
    # 2. Проверка данных
    if not check_data_quality(df):
        input("\nНажмите Enter для выхода...")
        return
    
    # 3. Показать список ТС
    show_vehicle_list(df)
    
    # 4. Подключение к API
    print("\n🔗 Подключение к Mobiteam API...")
    session_id = connect_to_api()
    
    if not session_id:
        print("❌ Не удалось подключиться к API")
        input("\nНажмите Enter для выхода...")
        return
    
    print("✓ Подключение успешно")
    
    # 5. Выбор даты
    print("\n📅 ВЫБОР ДАТЫ РАСЧЕТА")
    print("Формат: ГГГГ-ММ-ДД")
    
    date_input = input("Введите дату или нажмите Enter для вчерашней: ").strip()
    
    if date_input:
        try:
            target_date = datetime.strptime(date_input, '%Y-%m-%d')
        except:
            print("❌ Неверный формат даты!")
            input("\nНажмите Enter для выхода...")
            return
    else:
        target_date = datetime.now() - timedelta(days=1)
        print(f"✓ Используем вчерашнюю дату: {target_date.strftime('%d.%m.%Y')}")
    
    date_str = target_date.strftime('%Y-%m-%d')
    
    # 6. Расчет пробега
    results_df = process_vehicles(session_id, df, date_str)
    
    if results_df.empty:
        print("❌ Нет результатов для сохранения")
        input("\nНажмите Enter для выхода...")
        return
    
    # 7. Сохранение результатов
    saved_file = save_results(results_df, date_str)
    
    # 8. Статистика
    show_statistics(results_df)
    
    # 9. Завершение
    print("\n" + "=" * 70)
    print("✅ РАБОТА ЗАВЕРШЕНА УСПЕШНО!")
    print("=" * 70)
    
    if saved_file and os.path.exists(saved_file):
        open_file = input("\nОткрыть файл с результатами? (y/N): ").strip().lower()
        if open_file == 'y':
            try:
                os.startfile(saved_file)
                print("Файл открывается...")
            except:
                print(f"Откройте файл вручную: {saved_file}")
    
    input("\nНажмите Enter для выхода...")

# ============================================================================
# ЗАПУСК
# ============================================================================

if __name__ == "__main__":
    try:
        # Проверка зависимостей
        import pandas as pd
        import requests
        
        # Запуск
        main()
        
    except ImportError as e:
        print(f"❌ Отсутствуют необходимые библиотеки: {e}")
        print("\nУстановите командой:")
        print("pip install pandas requests openpyxl")
        input("\nНажмите Enter для выхода...")
    except KeyboardInterrupt:
        print("\n\n⏹️  Прервано пользователем")
    except Exception as e:
        print(f"\n❌ Непредвиденная ошибка: {e}")
        input("\nНажмите Enter для выхода...")
        