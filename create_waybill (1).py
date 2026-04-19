"""
ПУТЕВОЙ ЛИСТ: Получение данных из API
На основе базы с ID объектов
"""

import requests
import pandas as pd
from datetime import datetime, timedelta

# ===== НАСТРОЙКИ =====
LOGIN = "abvprom"
PASSWORD = "29328"
BASE_URL = "https://gps.mobiteam.com.ua"

# Автопоиск Excel файла
import os
import glob

possible_files = glob.glob("*с_ID_объектов*.xlsx") + glob.glob("*цепка*.xlsx") + glob.glob("*.xlsx")
EXCEL_FILE = None

if possible_files:
    # Показываем найденные файлы
    print("\n📁 Найденные Excel файлы:")
    for i, f in enumerate(possible_files[:5], 1):
        print(f"  {i}. {f}")
    
    # Используем первый подходящий
    EXCEL_FILE = possible_files[0]
    print(f"\n✅ Используется файл: {EXCEL_FILE}")
else:
    print("\n❌ Excel файлы не найдены в текущей папке!")
    print(f"Текущая папка: {os.getcwd()}")
    print("\nПоложите файл 'Cцепка_водитель-авто-прицеп_на_20_01_2026_с_ID_объектов.xlsx'")
    print("в эту папку или в папку со скриптом")
    input("\nНажмите Enter для выхода...")
    exit()

# =====================

print("=" * 90)
print("ПУТЕВОЙ ЛИСТ - ПОЛУЧЕНИЕ ДАННЫХ ИЗ API")
print("=" * 90)

# ===== ВВОД ДАННЫХ =====
print("\n📅 НАСТРОЙКИ:")
print("-" * 90)

date_input = input("Введите дату (ДД.ММ.ГГГГ) или Enter для сегодня: ").strip()
if date_input:
    try:
        target_date = datetime.strptime(date_input, "%d.%m.%Y")
    except:
        print("❌ Неверный формат даты! Используем сегодня.")
        target_date = datetime.now()
else:
    target_date = datetime.now()

print(f"\n✅ Дата для путевого листа: {target_date.strftime('%d.%m.%Y')}")

# Временной диапазон (весь день)
date_from = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
date_to = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)


# ===== ЧТЕНИЕ БАЗЫ =====
print(f"\n[1/4] Чтение базы водителей...")

try:
    df = pd.read_excel(EXCEL_FILE)
    
    # Убираем пустые строки
    df = df.dropna(subset=['ФИО'])
    df = df[df['ID объекта'].notna()]
    
    print(f"✅ Загружено записей: {len(df)}")
    
    # Добавляем колонки для результатов
    df['Время выезда'] = None
    df['Время въезда'] = None
    df['Одометр выезд'] = None
    df['Одометр въезд'] = None
    df['Пробег'] = None
    df['Статус'] = None
    
except Exception as e:
    print(f"❌ Ошибка чтения файла: {e}")
    input("\nНажмите Enter для выхода...")
    exit()


# ===== ПОДКЛЮЧЕНИЕ К API =====
print(f"\n[2/4] Подключение к API...")

try:
    url = f"{BASE_URL}/api/integration/v1/connect"
    params = {'login': LOGIN, 'password': PASSWORD, 'lang': 'ru-ru', 'timezone': '3'}
    response = requests.get(url, params=params)
    
    if response.status_code != 200 or response.text.strip('"') != 'Ok':
        print("❌ Ошибка подключения!")
        input("\nНажмите Enter для выхода...")
        exit()
    
    session_id = response.headers.get('sessionid')
    headers = {'SessionId': session_id}
    print("✅ Подключено!")
    
except Exception as e:
    print(f"❌ Ошибка: {e}")
    input("\nНажмите Enter для выхода...")
    exit()


# ===== ПОЛУЧЕНИЕ ДАННЫХ ДЛЯ КАЖДОГО ВОДИТЕЛЯ =====
print(f"\n[3/4] Получение данных по каждому объекту...")
print("-" * 90)

for idx, row in df.iterrows():
    fio = row['ФИО']
    obj_id = int(row['ID объекта'])
    plate = row.get('Номер авто', 'Н/Д')
    
    print(f"\n{idx + 1}. {fio} (ID: {obj_id}, {plate})")
    
    try:
        # Получаем трек движения за день
        url = f"{BASE_URL}/api/integration/v1/track"
        params = {
            'oid': obj_id,
            'from': date_from.strftime('%Y-%m-%d %H:%M:%S'),
            'to': date_to.strftime('%Y-%m-%d %H:%M:%S')
        }
        
        response = requests.get(url, headers=headers, params=params)
        
        if response.status_code != 200:
            print(f"   ❌ Ошибка HTTP {response.status_code}")
            df.at[idx, 'Статус'] = f"Ошибка {response.status_code}"
            continue
        
        data = response.json()
        
        if data.get('result') != 'Ok':
            print(f"   ⚠ {data.get('result')}")
            df.at[idx, 'Статус'] = data.get('result')
            continue
        
        track = data.get('track', [])
        
        if not track:
            print(f"   ⚠ Нет данных за этот день")
            df.at[idx, 'Статус'] = "Нет данных"
            continue
        
        print(f"   ✓ Получено точек: {len(track)}")
        
        # Берём первую и последнюю точки
        first_point = track[0]
        last_point = track[-1]
        
        # Извлекаем данные (разные поля в API)
        time_start = first_point.get('dt', first_point.get('time', first_point.get('timestamp', '')))
        time_end = last_point.get('dt', last_point.get('time', last_point.get('timestamp', '')))
        
        mileage_start = first_point.get('m', first_point.get('mileage', first_point.get('odometer', 0)))
        mileage_end = last_point.get('m', last_point.get('mileage', last_point.get('odometer', 0)))
        
        # Записываем в DataFrame
        df.at[idx, 'Время выезда'] = time_start
        df.at[idx, 'Время въезда'] = time_end
        df.at[idx, 'Одометр выезд'] = mileage_start
        df.at[idx, 'Одометр въезд'] = mileage_end
        
        if mileage_start and mileage_end:
            daily_mileage = mileage_end - mileage_start
            df.at[idx, 'Пробег'] = daily_mileage
            df.at[idx, 'Статус'] = "ОК"
            print(f"   ✅ Выезд: {time_start} ({mileage_start:.1f} км)")
            print(f"   ✅ Въезд: {time_end} ({mileage_end:.1f} км)")
            print(f"   📊 Пробег: {daily_mileage:.1f} км")
        else:
            df.at[idx, 'Статус'] = "Нет одометра"
            print(f"   ⚠ Одометр не найден")
        
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
        df.at[idx, 'Статус'] = f"Ошибка: {str(e)[:30]}"


# ===== СОХРАНЕНИЕ РЕЗУЛЬТАТОВ =====
print(f"\n[4/4] Сохранение результатов...")
print("=" * 90)

output_file = f"Путевой_лист_{target_date.strftime('%d_%m_%Y')}.xlsx"

try:
    # Выбираем нужные колонки
    result_cols = [
        'ФИО',
        'Номер авто',
        'Номер прицепа',
        'ID объекта',
        'Время выезда',
        'Время въезда',
        'Одометр выезд',
        'Одометр въезд',
        'Пробег',
        'Карта Амик',
        'Сокар',
        'Статус'
    ]
    
    # Убираем колонки которых нет
    result_cols = [col for col in result_cols if col in df.columns]
    
    df_result = df[result_cols].copy()
    
    df_result.to_excel(output_file, index=False)
    
    print(f"✅ Результаты сохранены: {output_file}")
    
except Exception as e:
    print(f"❌ Ошибка сохранения: {e}")


# ===== СТАТИСТИКА =====
print("\n" + "=" * 90)
print("СТАТИСТИКА")
print("=" * 90)

status_counts = df['Статус'].value_counts()
print("\nПо статусам:")
for status, count in status_counts.items():
    print(f"  {status}: {count}")

ok_count = len(df[df['Статус'] == 'ОК'])
total = len(df)

print(f"\n✅ Успешно обработано: {ok_count} из {total}")

if ok_count > 0:
    total_mileage = df[df['Статус'] == 'ОК']['Пробег'].sum()
    print(f"📊 Общий пробег: {total_mileage:.1f} км")


# ===== ПРЕДВАРИТЕЛЬНЫЙ ПРОСМОТР =====
print("\n" + "=" * 90)
print("ПРЕДВАРИТЕЛЬНЫЙ ПРОСМОТР")
print("=" * 90)

preview_cols = ['ФИО', 'Номер авто', 'Время выезда', 'Пробег', 'Статус']
preview_cols = [col for col in preview_cols if col in df.columns]

if preview_cols:
    print(df[preview_cols].head(10).to_string(index=False))

print("\n" + "=" * 90)
print("ГОТОВО!")
print("=" * 90)
print(f"\n💡 Откройте файл: {output_file}")

input("\nНажмите Enter для выхода...")
