#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
РЕАЛЬНЫЙ РАСЧЕТ РАСХОДА ТОПЛИВА - MOBITEAM API
Используется endpoint: /getobjectsreport
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
import json
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
# ФУНКЦИИ API (РЕАЛЬНЫЕ ЗАПРОСЫ)
# ============================================================================

def connect_to_api():
    """Подключение к API - получаем session_id"""
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
        
        print(f"ОШИБКА ПОДКЛЮЧЕНИЯ: {response.status_code}")
        return None
        
    except Exception as e:
        print(f"ОШИБКА ПОДКЛЮЧЕНИЯ: {e}")
        return None

def get_fuel_report(session_id, object_ids, date_from, date_to, params="all_fuel"):
    """
    РЕАЛЬНЫЙ запрос данных о топливе через /getobjectsreport
    """
    try:
        # Если object_ids - список, преобразуем в строку через запятую
        if isinstance(object_ids, list):
            objuids = ",".join(str(oid) for oid in object_ids)
        else:
            objuids = str(object_ids)
        
        url = f"{API_URL}/getobjectsreport"
        
        # Параметры как в вашем curl запросе
        query_params = {
            'date_from': date_from,
            'date_to': date_to,
            'objuids': objuids,
            'split': 'day',
            'param': params
        }
        
        headers = {
            'Accept': 'application/json',
            'SessionId': session_id
        }
        
        print(f"  ЗАПРОС: {url}")
        print(f"  ПАРАМЕТРЫ: {query_params}")
        
        response = requests.get(
            url, 
            headers=headers, 
            params=query_params, 
            timeout=30
        )
        
        print(f"  ОТВЕТ: статус {response.status_code}")
        
        if response.status_code == 200:
            try:
                data = response.json()
                print(f"  ДАННЫЕ ПОЛУЧЕНЫ: {len(data) if isinstance(data, list) else 'не список'}")
                return {'result': 'Ok', 'data': data}
            except json.JSONDecodeError as e:
                print(f"  ОШИБКА JSON: {e}")
                print(f"  ТЕКСТ ОТВЕТА: {response.text[:200]}...")
                return {'result': 'Error', 'error': f'Невалидный JSON: {e}'}
            except Exception as e:
                return {'result': 'Error', 'error': str(e)[:100]}
        else:
            error_msg = f"HTTP {response.status_code}"
            print(f"  ОШИБКА: {error_msg}")
            print(f"  ТЕКСТ ОШИБКИ: {response.text[:200]}...")
            return {'result': 'Error', 'error': error_msg}
            
    except requests.exceptions.Timeout:
        return {'result': 'Error', 'error': 'Таймаут запроса'}
    except Exception as e:
        print(f"  ИСКЛЮЧЕНИЕ: {e}")
        return {'result': 'Error', 'error': str(e)[:100]}

def extract_fuel_data_from_report(api_data, target_date_str):
    """
    Извлечение данных о топливе из ответа API
    """
    if not api_data or not isinstance(api_data, list):
        return {'status': 'Нет данных', 'consumption': 0, 'fuel_params': {}}
    
    for obj_data in api_data:
        oid = obj_data.get('oid')
        obj_name = obj_data.get('obj_name', f'Объект {oid}')
        
        print(f"  АНАЛИЗ ОБЪЕКТА {oid} ({obj_name})")
        
        for period in obj_data.get('periods', []):
            period_begin = period.get('begin', '')
            period_name = period.get('name', '')
            is_total = period.get('isTotal', False)
            params = period.get('prms', [])
            
            # Проверяем дату периода
            if period_begin.startswith(target_date_str) or period_name == target_date_str.replace('-', '.'):
                print(f"    НАЙДЕН ПЕРИОД: {period_name} ({period_begin} - {period.get('end', '')})")
                print(f"    ПАРАМЕТРОВ: {len(params)}")
                
                # Извлекаем параметры топлива
                fuel_params = {}
                for param in params:
                    name = param.get('name', '')
                    value = param.get('value', '')
                    
                    if name:  # Пропускаем пустые имена
                        fuel_params[name] = value
                        print(f"      ТОПЛИВО {name}: {value}")
                
                if fuel_params:
                    # Пытаемся определить расход топлива
                    consumption = 0
                    
                    # Ищем параметры расхода
                    for key in ['fuel_cons', 'consumption', 'fuel_consumed', 'fuel_used']:
                        if key in fuel_params:
                            try:
                                consumption = float(fuel_params[key])
                                break
                            except:
                                pass
                    
                    # Ищем уровень топлива
                    fuel_level_start = None
                    fuel_level_end = None
                    
                    for key in ['fuel_level_start', 'fuel_start', 'level_start']:
                        if key in fuel_params:
                            try:
                                fuel_level_start = float(fuel_params[key])
                            except:
                                pass
                    
                    for key in ['fuel_level_end', 'fuel_end', 'level_end']:
                        if key in fuel_params:
                            try:
                                fuel_level_end = float(fuel_params[key])
                            except:
                                pass
                    
                    # Если есть начальный и конечный уровень, считаем расход
                    if fuel_level_start is not None and fuel_level_end is not None:
                        calculated_consumption = fuel_level_start - fuel_level_end
                        if calculated_consumption > 0 and consumption == 0:
                            consumption = calculated_consumption
                    
                    # Определяем статус
                    status = 'OK' if consumption > 0 else 'Нет расхода'
                    
                    return {
                        'oid': oid,
                        'obj_name': obj_name,
                        'consumption': consumption,
                        'fuel_params': fuel_params,
                        'params_count': len(params),
                        'status': status,
                        'period_name': period_name
                    }
                else:
                    print(f"    ПАРАМЕТРЫ ТОПЛИВА ОТСУТСТВУЮТ")
                    return {
                        'oid': oid,
                        'obj_name': obj_name,
                        'consumption': 0,
                        'fuel_params': {},
                        'params_count': 0,
                        'status': 'Нет данных о топливе',
                        'period_name': period_name
                    }
    
    # Если не нашли подходящий период
    return {'status': 'Период не найден', 'consumption': 0, 'fuel_params': {}}

# ============================================================================
# ОСНОВНЫЕ ФУНКЦИИ
# ============================================================================

def read_excel_file():
    """Чтение Excel файла"""
    if not os.path.exists(TARGET_FILE):
        print(f"ФАЙЛ НЕ НАЙДЕН: {TARGET_FILE}")
        print(f"ТЕКУЩАЯ ПАПКА: {os.getcwd()}")
        return None
    
    try:
        df = pd.read_excel(TARGET_FILE)
        print(f"ФАЙЛ ПРОЧИТАН: {TARGET_FILE}")
        print(f"ЗАПИСЕЙ: {len(df)}")
        return df
    except Exception as e:
        print(f"ОШИБКА ЧТЕНИЯ ФАЙЛА: {e}")
        return None

def show_vehicle_list(df):
    """Показать список транспортных средств"""
    print("\nСПИСОК ТРАНСПОРТНЫХ СРЕДСТВ:")
    print("-" * 80)
    print(f"{'№':>3} {'ФИО':<25} {'Авто':<12} {'ID':>8} {'Статус':<15}")
    print("-" * 80)
    
    for idx, row in df.iterrows():
        driver = str(row.get('ФИО', '')).strip() or f'ID_{row["ID объекта"]}'
        vehicle = str(row.get('Номер авто', '')).strip() or ''
        oid = int(row['ID объекта']) if pd.notna(row['ID объекта']) else 0
        current_status = str(row.get('Статус', '')).strip() or ''
        
        print(f"{idx+1:3d}. {driver[:24]:<25} {vehicle[:10]:<12} {oid:>8} {current_status[:15]:<15}")
    
    print("-" * 80)

def process_real_fuel_data(session_id, df, date_str):
    """
    Обработка РЕАЛЬНЫХ данных о топливе
    """
    print(f"\nРАСЧЕТ РЕАЛЬНОГО РАСХОДА ТОПЛИВА")
    print(f"Дата: {date_str}")
    print("=" * 70)
    
    results = []
    total = len(df)
    
    # Параметры для запроса
    date_from = f"{date_str} 00:00:00"
    date_to = f"{date_str} 23:59:59"
    
    for idx, row in df.iterrows():
        # Прогресс
        percent = (idx + 1) / total * 100
        print(f"\rОБРАБОТКА: {idx+1}/{total} ({percent:.1f}%)", end='', flush=True)
        
        try:
            oid = int(row['ID объекта']) if pd.notna(row['ID объекта']) else 0
            driver = str(row.get('ФИО', '')).strip() or f'ID_{oid}'
            vehicle = str(row.get('Номер авто', '')).strip() or ''
            
            if oid == 0:
                results.append(create_real_error_result(idx, row, 'Некорректный ID объекта'))
                continue
            
            # РЕАЛЬНЫЙ запрос к API
            print(f"\n\nОБЪЕКТ {idx+1}: {driver} ({vehicle}, ID: {oid})")
            
            api_response = get_fuel_report(session_id, oid, date_from, date_to, "all_fuel")
            
            if api_response['result'] == 'Ok':
                fuel_data = extract_fuel_data_from_report(api_response['data'], date_str)
                
                # Форматируем параметры топлива для вывода
                fuel_params_str = ""
                if fuel_data['fuel_params']:
                    params_list = []
                    for key, value in list(fuel_data['fuel_params'].items())[:3]:  # первые 3 параметра
                        params_list.append(f"{key}: {value}")
                    fuel_params_str = "; ".join(params_list)
                    if len(fuel_data['fuel_params']) > 3:
                        fuel_params_str += f" ... (еще {len(fuel_data['fuel_params']) - 3})"
                
                # Сохраняем результат
                result = {
                    '№': idx + 1,
                    'ID объекта': oid,
                    'Транспорт': vehicle,
                    'Водитель': driver,
                    'Расход топлива': round(fuel_data['consumption'], 2),
                    'Параметров получено': fuel_data['params_count'],
                    'Статус': fuel_data['status'],
                    'Параметры топлива': fuel_params_str[:100],  # обрезаем длинные строки
                    'Период': fuel_data.get('period_name', '')
                }
                
                results.append(result)
                
                # Выводим информацию о результате
                if fuel_data['status'] == 'OK':
                    print(f"  РАСХОД: {fuel_data['consumption']}")
                else:
                    print(f"  {fuel_data['status']}")
                
            else:
                error_msg = api_response.get('error', 'Неизвестная ошибка')
                print(f"  ОШИБКА API: {error_msg}")
                results.append(create_real_error_result(idx, row, f"API: {error_msg}"))
                
        except Exception as e:
            error_msg = str(e)[:50]
            print(f"  ИСКЛЮЧЕНИЕ: {error_msg}")
            results.append(create_real_error_result(idx, row, f"Ошибка: {error_msg}"))
    
    print("\n\nРАСЧЕТ ЗАВЕРШЕН!")
    return pd.DataFrame(results)

def create_real_error_result(idx, row, error_msg):
    """Создание записи об ошибке для реальных данных"""
    return {
        '№': idx + 1,
        'ID объекта': int(row['ID объекта']) if 'ID объекта' in row and pd.notna(row['ID объекта']) else 0,
        'Транспорт': str(row.get('Номер авто', '')).strip() or '',
        'Водитель': str(row.get('ФИО', '')).strip() or '',
        'Расход топлива': 0,
        'Параметров получено': 0,
        'Статус': error_msg,
        'Параметры топлива': '',
        'Период': ''
    }

def save_real_results(results_df, date_str):
    """Сохранение реальных результатов"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"расход_топлива_{date_str}_{timestamp}.xlsx"
    
    try:
        # Сохраняем в Excel с форматированием
        with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
            # Основные результаты
            results_df.to_excel(writer, sheet_name='Расход топлива', index=False)
            
            # Сводка
            summary = create_real_summary(results_df, date_str)
            summary.to_excel(writer, sheet_name='Сводка', index=False)
            
            # Детальные параметры (если есть)
            if any(len(str(r['Параметры топлива'])) > 10 for r in results_df.to_dict('records')):
                params_df = results_df[['Водитель', 'Транспорт', 'Параметры топлива', 'Период']].copy()
                params_df = params_df[params_df['Параметры топлива'].str.len() > 0]
                if len(params_df) > 0:
                    params_df.to_excel(writer, sheet_name='Детальные параметры', index=False)
        
        print(f"\nДАННЫЕ СОХРАНЕНЫ: {output_file}")
        print(f"ПОЛНЫЙ ПУТЬ: {os.path.join(os.getcwd(), output_file)}")
        return output_file
    except Exception as e:
        print(f"ОШИБКА СОХРАНЕНИЯ: {e}")
        
        # Пробуем CSV
        try:
            csv_file = f"расход_топлива_{date_str}.csv"
            results_df.to_csv(csv_file, index=False, sep=';', encoding='utf-8-sig')
            print(f"РЕЗУЛЬТАТЫ СОХРАНЕНЫ В CSV: {csv_file}")
            return csv_file
        except:
            print("НЕ УДАЛОСЬ СОХРАНИТЬ РЕЗУЛЬТАТЫ!")
            return None

def create_real_summary(results_df, date_str):
    """Создание сводки по реальным данным"""
    total = len(results_df)
    
    # Анализируем результаты
    success_count = len(results_df[results_df['Статус'] == 'OK'])
    no_data_count = len(results_df[results_df['Статус'].str.contains('Нет данных', na=False)])
    error_count = len(results_df[results_df['Статус'].str.contains('Ошибка|API:', na=False)])
    
    total_consumption = results_df['Расход топлива'].sum()
    
    if success_count > 0:
        avg_consumption = results_df[results_df['Статус'] == 'OK']['Расход топлива'].mean()
        max_consumption = results_df[results_df['Статус'] == 'OK']['Расход топлива'].max()
        min_consumption = results_df[results_df['Статус'] == 'OK']['Расход топлива'].min()
    else:
        avg_consumption = max_consumption = min_consumption = 0
    
    summary_data = {
        'Показатель': [
            'Дата расчета',
            'Всего объектов',
            'С данными о топливе',
            'Без данных о топливе',
            'С ошибками',
            'Общий расход топлива',
            'Средний расход',
            'Максимальный расход',
            'Минимальный расход',
            'Время формирования отчета',
            'Использованный endpoint',
            'Параметры запроса'
        ],
        'Значение': [
            date_str,
            total,
            success_count,
            no_data_count,
            error_count,
            f"{total_consumption:.2f}",
            f"{avg_consumption:.2f}" if success_count > 0 else "0",
            f"{max_consumption:.2f}" if success_count > 0 else "0",
            f"{min_consumption:.2f}" if success_count > 0 else "0",
            datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
            "/getobjectsreport",
            "param=all_fuel, split=day"
        ]
    }
    
    return pd.DataFrame(summary_data)

def show_real_statistics(results_df):
    """Показать статистику по реальным данным"""
    print("\nСТАТИСТИКА ПО РЕАЛЬНЫМ ДАННЫМ:")
    print("=" * 70)
    
    total = len(results_df)
    
    # Группируем по статусам
    status_counts = results_df['Статус'].value_counts()
    
    print(f"Всего транспортных средств: {total}")
    print("\nРаспределение по статусам:")
    
    for status, count in status_counts.items():
        percentage = count / total * 100
        
        if status == 'OK':
            icon = '[OK]'
        elif 'Нет данных' in status:
            icon = '[НЕТ]'
        elif 'Ошибка' in status or 'API:' in status:
            icon = '[ОШИБКА]'
        elif 'Нет расхода' in status:
            icon = '[0]'
        else:
            icon = '[?]'
        
        print(f"  {icon} {status:<30} {count:>3} ({percentage:.1f}%)")
    
    # Фильтруем успешные результаты
    success_df = results_df[results_df['Статус'] == 'OK']
    if len(success_df) > 0:
        total_consumption = success_df['Расход топлива'].sum()
        avg_consumption = success_df['Расход топлива'].mean()
        
        print(f"\nОБЩИЙ РАСХОД ТОПЛИВА: {total_consumption:.2f}")
        print(f"СРЕДНИЙ РАСХОД: {avg_consumption:.2f}")
        
        # Топ по расходу
        if len(success_df) > 0:
            top5 = success_df.nlargest(5, 'Расход топлива')
            print(f"\nТОП-5 ПО РАСХОДУ ТОПЛИВА:")
            for i, (_, row) in enumerate(top5.iterrows(), 1):
                driver = row['Водитель'][:20] if len(row['Водитель']) > 20 else row['Водитель']
                vehicle = row['Транспорт'][:10]
                consumption = row['Расход топлива']
                print(f"  {i}. {driver:<20} {vehicle:<10} - {consumption:>6.2f}")
    
    # Показываем объекты без данных
    no_data_df = results_df[results_df['Статус'].str.contains('Нет данных', na=False)]
    if len(no_data_df) > 0:
        print(f"\nОБЪЕКТЫ БЕЗ ДАННЫХ О ТОПЛИВЕ ({len(no_data_df)}):")
        for _, row in no_data_df.head(10).iterrows():
            print(f"  - {row['Водитель'][:20]:<20} {row['Транспорт']:<10}")

# ============================================================================
# ГЛАВНАЯ ФУНКЦИЯ
# ============================================================================

def main():
    print("=" * 70)
    print("РЕАЛЬНЫЙ РАСЧЕТ РАСХОДА ТОПЛИВА - MOBITEAM API")
    print("Используется endpoint: /getobjectsreport")
    print("=" * 70)
    
    # 1. Чтение файла
    df = read_excel_file()
    if df is None:
        input("\nНажмите Enter для выхода...")
        return
    
    # 2. Показать список ТС
    show_vehicle_list(df)
    
    # 3. Подключение к API
    print("\nПОДКЛЮЧЕНИЕ К MOBITEAM API...")
    session_id = connect_to_api()
    
    if not session_id:
        print("НЕ УДАЛОСЬ ПОДКЛЮЧИТЬСЯ К API")
        input("\nНажмите Enter для выхода...")
        return
    
    print("ПОДКЛЮЧЕНИЕ УСПЕШНО")
    
    # 4. Выбор даты
    print("\nВЫБОР ДАТЫ РАСЧЕТА")
    print("Формат: ГГГГ-ММ-ДД")
    print("Пример: 2026-02-06")
    
    date_input = input("Введите дату или нажмите Enter для вчерашней: ").strip()
    
    if date_input:
        try:
            target_date = datetime.strptime(date_input, '%Y-%m-%d')
        except:
            print("НЕВЕРНЫЙ ФОРМАТ ДАТЫ!")
            input("\nНажмите Enter для выхода...")
            return
    else:
        target_date = datetime.now() - timedelta(days=1)
        print(f"ИСПОЛЬЗУЕМ ВЧЕРАШНЮЮ ДАТУ: {target_date.strftime('%d.%m.%Y')}")
    
    date_str = target_date.strftime('%Y-%m-%d')
    
    # 5. РЕАЛЬНЫЙ расчет расхода топлива
    print(f"\n{'='*70}")
    print(f"НАЧИНАЕМ РЕАЛЬНЫЙ РАСЧЕТ РАСХОДА ТОПЛИВА")
    print(f"Дата: {date_str}")
    print(f"Endpoint: /getobjectsreport")
    print(f"Параметры: all_fuel")
    print(f"{'='*70}")
    
    results_df = process_real_fuel_data(session_id, df, date_str)
    
    if results_df.empty:
        print("НЕТ РЕЗУЛЬТАТОВ ДЛЯ СОХРАНЕНИЯ")
        input("\nНажмите Enter для выхода...")
        return
    
    # 6. Сохранение РЕАЛЬНЫХ результатов
    saved_file = save_real_results(results_df, date_str)
    
    # 7. Статистика по РЕАЛЬНЫМ данным
    show_real_statistics(results_df)
    
    # 8. Завершение
    print("\n" + "=" * 70)
    print("РАСЧЕТ РАСХОДА ТОПЛИВА ЗАВЕРШЕН!")
    print("=" * 70)
    
    if saved_file and os.path.exists(saved_file):
        open_file = input("\nОТКРЫТЬ ФАЙЛ С ДАННЫМИ? (y/N): ").strip().lower()
        if open_file == 'y':
            try:
                os.startfile(saved_file)
                print(f"ФАЙЛ ОТКРЫВАЕТСЯ: {saved_file}")
            except:
                print(f"ОТКРОЙТЕ ФАЙЛ ВРУЧНУЮ: {saved_file}")
    
    print("\nВАЖНО: Этот скрипт использует РЕАЛЬНЫЙ endpoint /getobjectsreport")
    print("который вы предоставили. Если параметры топлива пустые (prms: []),")
    print("значит в Mobiteam нет данных о топливе за указанную дату.")
    
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
        print(f"ОТСУТСТВУЮТ БИБЛИОТЕКИ: {e}")
        print("\nУстановите: pip install pandas requests openpyxl")
        input("\nНажмите Enter для выхода...")
    except KeyboardInterrupt:
        print("\nПРЕРВАНО ПОЛЬЗОВАТЕЛЕМ")
    except Exception as e:
        print(f"\nОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        input("\nНажмите Enter для выхода...")