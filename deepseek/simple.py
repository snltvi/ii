#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
РАСЧЕТ СУТОЧНОГО ПРОБЕГА
Автоматически использует файл: CAN_пробег_датчики_06_02_2026.xlsx
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
import os

# Настройки
API_URL = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN = "abvprom"
PASSWORD = "29328"

# Имя файла который всегда используется
TARGET_FILE = "CAN_пробег_датчики_06_02_2026.xlsx"

def main():
    print("=" * 70)
    print("РАСЧЕТ СУТОЧНОГО ПРОБЕГА")
    print(f"Используется файл: {TARGET_FILE}")
    print("=" * 70)
    
    # 1. Проверить наличие файла
    if not os.path.exists(TARGET_FILE):
        print(f"\n❌ ОШИБКА: Файл '{TARGET_FILE}' не найден!")
        print(f"\nТекущая папка: {os.getcwd()}")
        print("\n💡 Положите файл '{TARGET_FILE}' в эту папку.")
        input("\nНажмите Enter для выхода...")
        return
    
    print(f"\n✓ Файл найден: {TARGET_FILE}")
    
    # 2. Прочитать файл
    try:
        df = pd.read_excel(TARGET_FILE)
        print(f"✓ Прочитано записей: {len(df)}")
        print(f"✓ Колонки в файле: {list(df.columns)}")
    except Exception as e:
        print(f"\n❌ Ошибка чтения файла: {e}")
        input("\nНажмите Enter для выхода...")
        return
    
    # 3. Проверить обязательные колонки
    required_cols = ['ID объекта', 'SID']
    missing_cols = [col for col in required_cols if col not in df.columns]
    
    if missing_cols:
        print(f"\n❌ ОШИБКА: В файле отсутствуют колонки: {missing_cols}")
        print("Файл должен содержать колонки: 'ID объекта' и 'SID'")
        input("\nНажмите Enter для выхода...")
        return
    
    print(f"✓ Обязательные колонки присутствуют")
    
    # 4. Показать список ТС
    print(f"\n📋 СПИСОК ТРАНСПОРТНЫХ СРЕДСТВ ({len(df)} шт.):")
    print("-" * 70)
    for i, row in df.iterrows():
        driver = str(row.get('ФИО', row.get('Карта Амик', f'ID_{row["ID объекта"]}')))[:20]
        vehicle = str(row.get('Номер авто', row.get('Сокар', '')))[:15]
        print(f"{i+1:2d}. {driver:20} | {vehicle:15} | ID: {row['ID объекта']:6d} | SID: {row['SID']:8d}")
    print("-" * 70)
    
    # 5. Подключиться к API
    print("\n🔗 Подключение к Mobiteam API...")
    try:
        response = requests.get(
            f"{API_URL}/connect",
            params={'login': LOGIN, 'password': PASSWORD, 'lang': 'ru-ru', 'timezone': '3'},
            timeout=10
        )
        
        if response.status_code != 200:
            print(f"❌ Ошибка API: {response.status_code}")
            print(f"Ответ: {response.text[:100]}")
            input("\nНажмите Enter для выхода...")
            return
        
        session_id = response.headers.get('sessionid')
        if not session_id:
            print("❌ SessionId не получен")
            input("\nНажмите Enter для выхода...")
            return
        
        print(f"✓ Подключено успешно!")
        
    except Exception as e:
        print(f"❌ Ошибка подключения: {e}")
        input("\nНажмите Enter для выхода...")
        return
    
    # 6. Выбрать дату
    print("\n📅 ВЫБОР ДАТЫ РАСЧЕТА")
    print("Формат: ГГГГ-ММ-ДД (например: 2026-02-05)")
    
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
    date_display = target_date.strftime('%d.%m.%Y')
    
    # 7. Расчет пробега
    print(f"\n🚗 НАЧИНАЮ РАСЧЕТ ПРОБЕГА ЗА {date_display}")
    print("=" * 70)
    
    results = []
    
    for idx, row in df.iterrows():
        # Показать прогресс
        percent = (idx + 1) / len(df) * 100
        print(f"\r📊 Обработка: {idx+1}/{len(df)} ({percent:.1f}%)", end='', flush=True)
        
        try:
            # Основные данные
            oid = int(row['ID объекта'])
            sid = int(row['SID'])
            
            # Дополнительные данные
            driver = str(row.get('ФИО', row.get('Карта Амик', f'ID_{oid}'))).strip()
            vehicle = str(row.get('Номер авто', row.get('Сокар', f'Объект {oid}'))).strip()
            trailer = str(row.get('Номер прицепа', '')).strip()
            
            # Запрос данных одометра
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
            
            if data.get('result') == 'Ok':
                records = data.get('obj_data', {}).get('records', [])
                
                if records:
                    # Найти все валидные значения одометра
                    values = []
                    for rec in records:
                        if len(rec) > 1 and rec[1] is not None:
                            try:
                                val = float(str(rec[1]).strip())
                                if val >= 0:  # Только положительные
                                    values.append(val)
                            except:
                                continue
                    
                    if len(values) >= 2:
                        start_odo = values[0]
                        end_odo = values[-1]
                        mileage = end_odo - start_odo
                        
                        # Проверка на корректность
                        if mileage < 0:
                            # Пробуем найти разницу мин-макс
                            if len(values) > 2:
                                mileage = max(values) - min(values)
                                status = 'Проверить (корр.)' if mileage > 0 else 'Ошибка'
                                if mileage < 0:
                                    mileage = 0
                            else:
                                mileage = 0
                                status = 'Ошибка данных'
                        elif mileage > 2000:
                            status = 'Проверить (>2000км)'
                        elif mileage == 0 and len(values) > 5:
                            status = 'Нулевой пробег'
                        else:
                            status = 'OK'
                    else:
                        mileage = 0
                        status = 'Мало данных'
                        start_odo = None
                        end_odo = None
                else:
                    mileage = 0
                    status = 'Нет данных'
                    start_odo = None
                    end_odo = None
            else:
                mileage = 0
                status = 'Ошибка API'
                start_odo = None
                end_odo = None
            
            # Добавить результат
            results.append({
                '№': idx + 1,
                'ФИО': driver,
                'Номер авто': vehicle,
                'Номер прицепа': trailer,
                'ID объекта': oid,
                'SID': sid,
                'Одометр начало (км)': round(start_odo, 2) if start_odo is not None else '',
                'Одометр конец (км)': round(end_odo, 2) if end_odo is not None else '',
                'Пробег (км)': round(mileage, 2),
                'Статус': status
            })
            
        except Exception as e:
            results.append({
                '№': idx + 1,
                'ФИО': str(row.get('ФИО', f'ID_{row.get("ID объекта", "?")}')),
                'Номер авто': str(row.get('Номер авто', '')),
                'Номер прицепа': str(row.get('Номер прицепа', '')),
                'ID объекта': int(row['ID объекта']) if 'ID объекта' in row else 0,
                'SID': int(row['SID']) if 'SID' in row else 0,
                'Одометр начало (км)': '',
                'Одометр конец (км)': '',
                'Пробег (км)': 0,
                'Статус': f'Ошибка: {str(e)[:30]}'
            })
    
    print("\n\n✅ РАСЧЕТ ЗАВЕРШЕН!")
    
    # 8. Сохранить результаты
    results_df = pd.DataFrame(results)
    
    # Имя выходного файла
    output_file = f"Пробег_{date_str}.xlsx"
    
    try:
        # Сохраняем в Excel
        results_df.to_excel(output_file, index=False)
        print(f"\n💾 Результаты сохранены в файл: {output_file}")
        print(f"📂 Путь: {os.path.join(os.getcwd(), output_file)}")
        
    except Exception as e:
        print(f"\n❌ Ошибка сохранения в Excel: {e}")
        
        # Пробуем сохранить в CSV
        try:
            csv_file = f"Пробег_{date_str}.csv"
            results_df.to_csv(csv_file, index=False, encoding='utf-8-sig')
            print(f"✓ Результаты сохранены в CSV: {csv_file}")
            output_file = csv_file
        except:
            print("❌ Не удалось сохранить результаты!")
            input("\nНажмите Enter для выхода...")
            return
    
    # 9. Вывести статистику
    print("\n" + "=" * 70)
    print("📊 СТАТИСТИКА РАСЧЕТА")
    print("=" * 70)
    
    total = len(results_df)
    ok = len(results_df[results_df['Статус'] == 'OK'])
    check = len(results_df[results_df['Статус'].str.contains('Проверить', na=False)])
    errors = len(results_df[results_df['Статус'].str.contains('Ошибка', na=False)])
    no_data = len(results_df[results_df['Статус'].str.contains('Нет данных|Мало данных', na=False)])
    
    print(f"Всего ТС: {total}")
    print(f"✓ Успешно: {ok}")
    print(f"⚠ Проверить: {check}")
    print(f"✗ Ошибки: {errors}")
    print(f"📭 Нет данных: {no_data}")
    print(f"🛣️ Общий пробег: {results_df['Пробег (км)'].sum():.1f} км")
    print(f"📈 Средний пробег: {results_df['Пробег (км)'].mean():.1f} км")
    
    # 10. Показать топ по пробегу
    if total > 0:
        # Топ-3 максимальных пробега
        top3 = results_df.nlargest(3, 'Пробег (км)')
        print(f"\n🏆 ТОП-3 ПО ПРОБЕГУ:")
        print("-" * 60)
        for i, (_, row) in enumerate(top3.iterrows(), 1):
            print(f"{i}. {row['ФИО'][:20]:20} {row['Пробег (км)']:7.1f} км")
        
        # Показать нулевые пробеги
        zero_mileage = results_df[results_df['Пробег (км)'] == 0]
        if len(zero_mileage) > 0:
            print(f"\n📭 НУЛЕВОЙ ПРОБЕГ ({len(zero_mileage)} шт.):")
            for _, row in zero_mileage.iterrows():
                print(f"  {row['ФИО'][:20]:20} - {row['Статус']}")
    
    print("\n" + "=" * 70)
    print("🎉 РАСЧЕТ ЗАВЕРШЕН УСПЕШНО!")
    print("=" * 70)
    
    # Предложение открыть файл
    if os.path.exists(output_file):
        open_file = input("\nОткрыть файл с результатами? (y/N): ").strip().lower()
        if open_file == 'y':
            try:
                os.startfile(output_file)
                print("Файл открывается...")
            except:
                print(f"Не удалось открыть файл. Откройте вручную: {output_file}")
    
    input("\nНажмите Enter для выхода...")

if __name__ == "__main__":
    try:
        import pandas as pd
        import requests
        main()
    except ImportError:
        print("❌ Отсутствуют необходимые библиотеки!")
        print("Установите командой: pip install pandas requests openpyxl")
        input("\nНажмите Enter для выхода...")