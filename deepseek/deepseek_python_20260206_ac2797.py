#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ПРОСТОЙ РАСЧЕТ ПРОБЕГА из Excel файла (.xls) в той же папке
Поддерживает форматы: .xls, .xlsx
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
import os
import glob

# Конфигурация
API_URL = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN = "abvprom"
PASSWORD = "29328"

def find_excel_files():
    """Найти Excel файлы (.xls и .xlsx) в текущей папке"""
    print("\n📁 Поиск Excel файлов в текущей папке...")
    print(f"Текущая папка: {os.getcwd()}")
    
    # Ищем все Excel файлы
    excel_files = []
    
    # Форматы для поиска
    extensions = ['*.xls', '*.xlsx', '*.xlsm', '*.xlsb']
    
    for ext in extensions:
        files = glob.glob(ext)
        for file in files:
            if os.path.isfile(file):
                excel_files.append(file)
    
    # Убираем дубликаты и сортируем
    excel_files = list(set(excel_files))
    excel_files.sort()
    
    return excel_files

def read_excel_file(filepath):
    """Чтение Excel файла с поддержкой .xls и .xlsx"""
    try:
        # Пробуем разные движки для чтения
        try:
            # Сначала пробуем openpyxl для .xlsx
            df = pd.read_excel(filepath, engine='openpyxl')
        except:
            try:
                # Пробуем xlrd для .xls (старый формат)
                df = pd.read_excel(filepath, engine='xlrd')
            except:
                try:
                    # Пробуем без указания движка (автовыбор)
                    df = pd.read_excel(filepath)
                except Exception as e:
                    print(f"❌ Не удалось прочитать файл: {e}")
                    return None
        
        return df
    except Exception as e:
        print(f"❌ Ошибка чтения файла {filepath}: {e}")
        return None

def save_to_excel(results_df, filename):
    """Сохранение в Excel (.xls или .xlsx)"""
    try:
        if filename.endswith('.xls'):
            # Для .xls используем xlwt
            try:
                results_df.to_excel(filename, index=False, engine='xlwt')
                print(f"✓ Сохранено в .xls (старый формат)")
            except:
                # Если xlwt не установлен, сохраняем как .xlsx
                new_filename = filename.replace('.xls', '.xlsx')
                results_df.to_excel(new_filename, index=False, engine='openpyxl')
                print(f"✓ Сохранено в .xlsx (новый формат)")
                return new_filename
        else:
            # Для .xlsx используем openpyxl
            results_df.to_excel(filename, index=False, engine='openpyxl')
            print(f"✓ Сохранено в .xlsx")
        
        return filename
    except Exception as e:
        print(f"❌ Ошибка сохранения: {e}")
        
        # Пробуем сохранить как CSV если Excel не получается
        try:
            csv_name = filename.replace('.xls', '.csv').replace('.xlsx', '.csv')
            results_df.to_csv(csv_name, index=False, encoding='utf-8-sig')
            print(f"✓ Данные сохранены в CSV: {csv_name}")
            return csv_name
        except:
            print("❌ Не удалось сохранить даже в CSV")
            return None

def get_odometer_data(session_id, oid, sid, date_str):
    """Получение данных одометра за день"""
    try:
        url = f"{API_URL}/objdata"
        params = {
            'oid': oid,
            'slist': f's{sid}',
            'from': f"{date_str} 00:00:00",
            'to': f"{date_str} 23:59:59",
            'compress': 'true'
        }
        headers = {'SessionId': session_id}
        
        response = requests.get(url, headers=headers, params=params, timeout=30)
        data = response.json()
        
        if data.get('result') != 'Ok':
            return None, None, None, 0, "Ошибка API"
        
        records = data.get('obj_data', {}).get('records', [])
        
        if not records:
            return None, None, None, 0, "Нет записей"
        
        # Ищем все валидные значения
        values = []
        for rec in records:
            if len(rec) > 1 and rec[1] is not None:
                try:
                    val = float(rec[1])
                    if val >= 0:  # Только положительные значения
                        values.append(val)
                except:
                    continue
        
        if len(values) < 2:
            return None, None, None, len(values), "Мало данных"
        
        # Берем первое и последнее значение
        start_odo = values[0]
        end_odo = values[-1]
        mileage = end_odo - start_odo
        
        # Проверки на корректность
        if mileage < 0:
            # Если пробег отрицательный, пробуем найти максимальную разницу
            if len(values) > 2:
                mileage = max(values) - min(values)
                if mileage < 0:
                    mileage = 0
            else:
                mileage = 0
        
        return start_odo, end_odo, mileage, len(values), "OK"
        
    except Exception as e:
        return None, None, None, 0, f"Ошибка: {str(e)[:50]}"

def main():
    print("=" * 70)
    print("РАСЧЕТ ПРОБЕГА ИЗ EXCEL ФАЙЛА (.xls или .xlsx)")
    print("=" * 70)
    
    # 1. Найти Excel файлы
    excel_files = find_excel_files()
    
    if not excel_files:
        print("\n❌ Excel файлы не найдены в текущей папке!")
        print("\n💡 Положите Excel файл (.xls или .xlsx) в папку:")
        print(f"   {os.getcwd()}")
        print("\nФайл должен содержать колонки: 'ID объекта' и 'SID'")
        input("\nНажмите Enter для выхода...")
        return
    
    print(f"\nНайдено файлов: {len(excel_files)}")
    for i, file in enumerate(excel_files, 1):
        size_kb = os.path.getsize(file) / 1024
        print(f"{i:2d}. {os.path.basename(file):30} ({size_kb:.1f} KB)")
    
    # 2. Выбрать файл
    if len(excel_files) == 1:
        excel_file = excel_files[0]
        print(f"\n✓ Используем единственный файл: {os.path.basename(excel_file)}")
    else:
        while True:
            try:
                choice = input(f"\nВыберите файл (1-{len(excel_files)}): ").strip()
                
                if not choice:
                    # По умолчанию первый файл
                    excel_file = excel_files[0]
                    print(f"✓ Используем файл по умолчанию: {os.path.basename(excel_file)}")
                    break
                
                if choice.isdigit():
                    idx = int(choice) - 1
                    if 0 <= idx < len(excel_files):
                        excel_file = excel_files[idx]
                        print(f"✓ Выбран файл: {os.path.basename(excel_file)}")
                        break
                    else:
                        print(f"❌ Введите число от 1 до {len(excel_files)}")
                else:
                    # Если ввели путь к файлу
                    if os.path.exists(choice):
                        excel_file = choice
                        print(f"✓ Выбран файл: {os.path.basename(excel_file)}")
                        break
                    else:
                        print("❌ Файл не найден. Попробуйте еще раз.")
            except:
                print("❌ Ошибка выбора файла")
    
    # 3. Прочитать файл
    print(f"\n📊 Чтение файла '{os.path.basename(excel_file)}'...")
    df = read_excel_file(excel_file)
    
    if df is None:
        input("\nНажмите Enter для выхода...")
        return
    
    print(f"✓ Прочитано строк: {len(df)}")
    print(f"✓ Колонки в файле: {list(df.columns)}")
    
    # 4. Проверить обязательные колонки
    required = ['ID объекта', 'SID']
    missing = [col for col in required if col not in df.columns]
    
    if missing:
        print(f"\n❌ Ошибка: отсутствуют обязательные колонки: {missing}")
        print("Файл должен содержать колонки: 'ID объекта' и 'SID'")
        input("\nНажмите Enter для выхода...")
        return
    
    # 5. Показать пример данных
    print("\n📋 Пример данных (первые 3 записи):")
    print("-" * 60)
    print(f"{'№':>3} {'ID':>6} {'SID':>8} {'ФИО':<20} {'Авто':<10}")
    print("-" * 60)
    for i, row in df.head(3).iterrows():
        oid = row['ID объекта']
        sid = row['SID']
        name = str(row.get('ФИО', 'Не указано'))[:18]
        vehicle = str(row.get('Номер авто', 'Не указан'))[:8]
        print(f"{i+1:3d} {oid:6d} {sid:8d} {name:<20} {vehicle:<10}")
    print("-" * 60)
    
    # 6. Подключиться к API
    print("\n🔗 Подключение к Mobiteam API...")
    try:
        response = requests.get(
            f"{API_URL}/connect",
            params={'login': LOGIN, 'password': PASSWORD, 'lang': 'ru-ru', 'timezone': '3'},
            timeout=10
        )
        
        if response.status_code != 200:
            print(f"❌ Ошибка API: {response.status_code}")
            input("\nНажмите Enter для выхода...")
            return
        
        session_id = response.headers.get('sessionid')
        if not session_id:
            print("❌ Не получен session_id")
            input("\nНажмите Enter для выхода...")
            return
        
        print(f"✓ Подключено! SessionId: {session_id[:15]}...")
        
    except Exception as e:
        print(f"❌ Ошибка подключения: {e}")
        input("\nНажмите Enter для выхода...")
        return
    
    # 7. Выбрать дату
    print("\n📅 Выбор даты для расчета")
    date_input = input("Введите дату (ГГГГ-ММ-ДД) или нажмите Enter для вчера: ").strip()
    
    if date_input:
        try:
            target_date = datetime.strptime(date_input, '%Y-%m-%d')
        except:
            print("❌ Неверный формат даты. Используйте ГГГГ-ММ-ДД")
            input("\nНажмите Enter для выхода...")
            return
    else:
        target_date = datetime.now() - timedelta(days=1)
        print(f"✓ Используем вчерашнюю дату: {target_date.strftime('%d.%m.%Y')}")
    
    date_str = target_date.strftime('%Y-%m-%d')
    
    # 8. Рассчитать пробег
    print(f"\n🚗 Расчет пробега за {target_date.strftime('%d.%m.%Y')}...")
    print("-" * 70)
    
    results = []
    total_rows = len(df)
    
    for idx, row in df.iterrows():
        # Показать прогресс
        if idx % 5 == 0 or idx == total_rows - 1:
            percent = (idx + 1) / total_rows * 100
            print(f"\rОбработка: {idx+1}/{total_rows} ({percent:.1f}%)", end='', flush=True)
        
        try:
            oid = int(row['ID объекта'])
            sid = int(row['SID'])
            driver = str(row.get('ФИО', ''))
            vehicle = str(row.get('Номер авто', ''))
            trailer = str(row.get('Номер прицепа', ''))
            
            # Получить данные одометра
            start_odo, end_odo, mileage, records_count, status_msg = get_odometer_data(
                session_id, oid, sid, date_str
            )
            
            # Определить статус для отчета
            if status_msg == "OK":
                if 0 <= mileage <= 2000:
                    status = "OK"
                else:
                    status = "Проверить"
            else:
                status = status_msg
            
            results.append({
                '№': idx + 1,
                'ФИО': driver,
                'Номер авто': vehicle,
                'Номер прицепа': trailer,
                'ID объекта': oid,
                'SID': sid,
                'Одометр начало (км)': round(start_odo, 2) if start_odo is not None else '',
                'Одометр конец (км)': round(end_odo, 2) if end_odo is not None else '',
                'Пробег (км)': round(mileage, 2) if mileage is not None else 0,
                'Записей': records_count,
                'Статус': status,
                'Дата': date_str
            })
            
        except Exception as e:
            print(f"\n⚠ Ошибка в строке {idx+1}: {str(e)[:50]}")
            results.append({
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
                'Статус': f'Ошибка: {str(e)[:30]}',
                'Дата': date_str
            })
    
    print("\n\n✅ Расчет завершен!")
    
    # 9. Сохранить результаты
    results_df = pd.DataFrame(results)
    
    # Предлагаем выбрать формат сохранения
    print("\n💾 Сохранение результатов")
    print("1. Сохранить как .xls (старый формат Excel 97-2003)")
    print("2. Сохранить как .xlsx (новый формат Excel)")
    print("3. Сохранить как .csv (текстовый формат)")
    
    format_choice = input("\nВыберите формат (1-3, по умолчанию 2): ").strip()
    
    if format_choice == '1':
        output_file = f"Пробег_{date_str}.xls"
    elif format_choice == '3':
        output_file = f"Пробег_{date_str}.csv"
    else:
        output_file = f"Пробег_{date_str}.xlsx"
    
    saved_file = save_to_excel(results_df, output_file)
    
    if saved_file:
        print(f"\n✓ Файл сохранен: {saved_file}")
        print(f"  Полный путь: {os.path.join(os.getcwd(), saved_file)}")
        
        # Статистика
        print("\n📊 Статистика:")
        print(f"  Всего ТС: {len(results_df)}")
        
        ok_count = len(results_df[results_df['Статус'] == 'OK'])
        check_count = len(results_df[results_df['Статус'] == 'Проверить'])
        error_count = len(results_df[results_df['Статус'].str.contains('Ошибка', na=False)])
        no_data = len(results_df[results_df['Статус'].str.contains('Нет|Мало', na=False)])
        
        print(f"  ✓ Успешно: {ok_count}")
        print(f"  ⚠ Проверить: {check_count}")
        print(f"  ✗ Ошибки: {error_count}")
        print(f"  📭 Нет данных: {no_data}")
        print(f"  🛣️ Общий пробег: {results_df['Пробег (км)'].sum():.1f} км")
        
        # Показать первые 5 результатов
        print("\n📋 Первые 5 результатов:")
        print("-" * 80)
        for i, row in results_df.head().iterrows():
            mileage = row['Пробег (км)']
            if isinstance(mileage, (int, float)):
                mileage_str = f"{mileage:7.1f} км"
            else:
                mileage_str = "        "
            
            print(f"{row['№']:2d}. {row['ФИО'][:20]:20} {row['Номер авто'][:10]:10} "
                  f"{mileage_str} - {row['Статус']}")
    
    # 10. Проверить установленные библиотеки
    print("\n" + "=" * 70)
    print("💡 ИНФОРМАЦИЯ О БИБЛИОТЕКАХ:")
    print("=" * 70)
    
    libs = ['pandas', 'openpyxl', 'xlrd', 'xlwt']
    for lib in libs:
        try:
            __import__(lib)
            print(f"✓ {lib:10} - установлен")
        except ImportError:
            print(f"✗ {lib:10} - НЕ установлен")
    
    print("\nДля работы с .xls файлами установите:")
    print("  pip install xlrd xlwt")
    print("\nДля работы с .xlsx файлами:")
    print("  pip install openpyxl")
    
    print("\n" + "=" * 70)
    print("Готово! Нажмите Enter для выхода...")
    input()

if __name__ == "__main__":
    # Установите нужные библиотеки если их нет
    required_libs = ['pandas', 'requests']
    
    missing = []
    for lib in required_libs:
        try:
            __import__(lib)
        except ImportError:
            missing.append(lib)
    
    if missing:
        print(f"❌ Отсутствуют библиотеки: {missing}")
        print("Установите командой:")
        print(f"pip install {' '.join(missing)}")
        input("\nНажмите Enter для выхода...")
    else:
        main()