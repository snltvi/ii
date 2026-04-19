"""
Соединение водителей с объектами API
"""

import requests
import pandas as pd

# ===== НАСТРОЙКИ =====
LOGIN = "abvprom"
PASSWORD = "29328"
BASE_URL = "https://gps.mobiteam.com.ua"
EXCEL_FILE = "Cцепка_водитель-авто-прицеп_на_20_01_2026.xlsx"
# =====================

print("=" * 80)
print("СОЕДИНЕНИЕ ВОДИТЕЛЕЙ С ОБЪЕКТАМИ API")
print("=" * 80)

# ===== ШАГ 1: ЧТЕНИЕ EXCEL =====
print("\n[1/3] Чтение Excel файла с водителями...")

try:
    df = pd.read_excel(EXCEL_FILE)
    
    # Очищаем данные
    df = df[['ФИО', 'Номер авто', 'Номер прицепа', 'Карта Амик', 'Сокар']].copy()
    df = df.dropna(subset=['ФИО'])  # Удаляем пустые строки
    
    # Нормализуем номера авто (убираем пробелы, приводим к верхнему регистру)
    df['Номер авто'] = df['Номер авто'].astype(str).str.strip().str.upper()
    
    print(f"✅ Загружено водителей: {len(df)}")
    
except FileNotFoundError:
    print(f"❌ Файл не найден: {EXCEL_FILE}")
    print("Положите файл в ту же папку, что и скрипт!")
    input("\nНажмите Enter для выхода...")
    exit()
except Exception as e:
    print(f"❌ Ошибка чтения файла: {e}")
    input("\nНажмите Enter для выхода...")
    exit()


# ===== ШАГ 2: ПОДКЛЮЧЕНИЕ К API =====
print("\n[2/3] Подключение к Mobiteam API...")

url = f"{BASE_URL}/api/integration/v1/connect"
params = {'login': LOGIN, 'password': PASSWORD, 'lang': 'ru-ru', 'timezone': '3'}
response = requests.get(url, params=params)

if response.status_code != 200 or response.text.strip('"') != 'Ok':
    print("❌ Ошибка подключения к API!")
    input("Нажмите Enter для выхода...")
    exit()

session_id = response.headers.get('sessionid')
print(f"✅ Подключено к API!")

headers = {'SessionId': session_id}


# ===== ШАГ 3: ПОЛУЧЕНИЕ ОБЪЕКТОВ ИЗ API =====
print("\n[3/3] Получение объектов из API...")

url = f"{BASE_URL}/api/integration/v1/getobjectslist"
response = requests.get(url, headers=headers)

if response.status_code != 200:
    print(f"❌ Ошибка API: HTTP {response.status_code}")
    input("Нажмите Enter для выхода...")
    exit()

data = response.json()

if data.get('result') != 'Ok':
    print(f"❌ Ошибка API: {data.get('result')}")
    input("Нажмите Enter для выхода...")
    exit()

objects = data.get('objects', [])
print(f"✅ Получено объектов из API: {len(objects)}")


# ===== СОЕДИНЕНИЕ ДАННЫХ =====
print("\n" + "=" * 80)
print("РЕЗУЛЬТАТ СОЕДИНЕНИЯ")
print("=" * 80)

# Создаем словарь: номер авто -> объект API
api_objects_dict = {}
for obj in objects:
    plate = obj.get('plate_num', obj.get('plate', '')).strip().upper()
    if plate:
        api_objects_dict[plate] = obj

# Соединяем с водителями
matched = []
not_matched_drivers = []
not_matched_api = []

print("\n📋 ВОДИТЕЛИ С НАЙДЕННЫМИ ОБЪЕКТАМИ:\n")
print("-" * 80)

for idx, row in df.iterrows():
    driver_name = row['ФИО']
    plate = str(row['Номер авто']).strip().upper()
    trailer = row['Номер прицепа']
    amik = row['Карта Амик']
    sokar = row['Сокар']
    
    # Ищем в API
    if plate in api_objects_dict:
        obj = api_objects_dict[plate]
        obj_id = obj.get('id')
        obj_name = obj.get('name', 'Без названия')
        
        matched.append({
            'driver': driver_name,
            'plate': plate,
            'trailer': trailer,
            'object_id': obj_id,
            'object_name': obj_name,
            'amik': amik,
            'sokar': sokar
        })
        
        print(f"✅ {driver_name}")
        print(f"   Номер авто:    {plate}")
        print(f"   Прицеп:        {trailer}")
        print(f"   → ID объекта:  {obj_id}")
        print(f"   → Название:    {obj_name}")
        print(f"   Карта Амик:    {amik}")
        print(f"   Сокар:         {sokar}")
        print("-" * 80)
        
    else:
        not_matched_drivers.append({
            'driver': driver_name,
            'plate': plate,
            'trailer': trailer
        })

# Объекты из API без водителей
for plate, obj in api_objects_dict.items():
    if plate not in df['Номер авто'].values:
        not_matched_api.append({
            'object_id': obj.get('id'),
            'object_name': obj.get('name', 'Без названия'),
            'plate': plate
        })


# ===== СТАТИСТИКА =====
print("\n" + "=" * 80)
print("СТАТИСТИКА")
print("=" * 80)
print(f"✅ Успешно соединено:              {len(matched)}")
print(f"⚠  Водители без объектов в API:   {len(not_matched_drivers)}")
print(f"⚠  Объекты API без водителей:     {len(not_matched_api)}")

# Водители без объектов
if not_matched_drivers:
    print("\n⚠ ВОДИТЕЛИ БЕЗ ОБЪЕКТОВ В API:")
    print("-" * 80)
    for item in not_matched_drivers:
        print(f"   • {item['driver']}")
        print(f"     Номер авто: {item['plate']}")
        print(f"     Прицеп:     {item['trailer']}")

# Объекты без водителей
if not_matched_api:
    print("\n⚠ ОБЪЕКТЫ API БЕЗ ВОДИТЕЛЕЙ:")
    print("-" * 80)
    for item in not_matched_api:
        print(f"   • ID: {item['object_id']} - {item['object_name']}")
        print(f"     Номер: {item['plate']}")


# ===== СОХРАНЕНИЕ В EXCEL =====
print("\n" + "=" * 80)
print("СОХРАНЕНИЕ РЕЗУЛЬТАТОВ")
print("=" * 80)

if matched:
    result_df = pd.DataFrame(matched)
    output_file = "Водители_с_ID_объектов.xlsx"
    
    result_df.to_excel(output_file, index=False, columns=[
        'driver', 'plate', 'trailer', 'object_id', 'object_name', 'amik', 'sokar'
    ])
    
    # Переименовываем колонки для красоты
    result_df_renamed = pd.DataFrame(matched)
    result_df_renamed.columns = [
        'ФИО водителя', 'Номер авто', 'Номер прицепа', 'ID объекта', 
        'Название объекта', 'Карта Амик', 'Сокар'
    ]
    
    result_df_renamed.to_excel(output_file, index=False)
    
    print(f"✅ Результаты сохранены в файл: {output_file}")
else:
    print("⚠ Нет данных для сохранения")

print("\n" + "=" * 80)
input("Нажмите Enter для выхода...")
