import requests
import pandas as pd
import os
import time
from datetime import datetime

# --- НАСТРОЙКИ ---
API_URL = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN = "abvprom"
PASSWORD = "29328"
TARGET_FILE = "CAN_пробег_датчики_06_02_2026.xlsx"

def connect_to_api():
    """Получаем SID для доступа"""
    try:
        res = requests.get(f"{API_URL}/connect", 
                           params={'login': LOGIN, 'password': PASSWORD, 'lang': 'ru-ru', 'timezone': '3'})
        return res.headers.get('sessionid')
    except:
        return None

def get_address(sid, lat, lon):
    """Запрашиваем адрес по координатам"""
    try:
        res = requests.get(f"{API_URL}/getaddress", 
                           headers={'SessionId': sid}, 
                           params={'lat': lat, 'lon': lon}, timeout=10)
        return res.text.strip() if res.status_code == 200 else "Адрес не определен"
    except:
        return "Ошибка геокодера"

def main():
    print("🚀 Запуск формирования отчета по заправкам...")
    
    if not os.path.exists(TARGET_FILE):
        print(f"❌ Файл {TARGET_FILE} не найден!"); return

    df_input = pd.read_excel(TARGET_FILE)
    sid = connect_to_api()
    if not sid:
        print("❌ Ошибка авторизации"); return

    date_input = input("📅 Введите дату (ГГГГ-ММ-ДД): ").strip()
    date_from, date_to = f"{date_input} 00:00:00", f"{date_input} 23:59:59"

    results = []

    for _, row in df_input.iterrows():
        oid = row.get('ID объекта')
        if pd.isna(oid): continue
        
        oid = int(oid)
        driver = row.get('ФИО', '—')
        vehicle = row.get('Номер авто', '—')
        trailer = row.get('Прицеп', '—')

        print(f"🔎 Обработка {vehicle} (ID: {oid})...")
        
        try:
            # Запрос заправок
            f_res = requests.get(f"{API_URL}/fuelings", 
                                 headers={'SessionId': sid}, 
                                 params={'oid': oid, 'from': date_from, 'to': date_to})
            data = f_res.json()
            
            if data.get('result') == 'Ok':
                for event in data.get('fuelings', []):
                    if event.get('fuel_type') == 'fueling':
                        lat, lon = event.get('lat'), event.get('lon')
                        
                        # Получаем адрес
                        address = get_address(sid, lat, lon)
                        
                        results.append({
                            'Дата/Время': event.get('start_time'),
                            'Водитель': driver,
                            'Номер авто': vehicle,
                            'Прицеп': trailer,
                            'Объем (л)': round(float(event.get('volume', 0)), 1),
                            'Адрес заправки': address,
                            'Координаты': f"{lat}, {lon}"
                        })
                        time.sleep(0.1) # Пауза для стабильности API
        except:
            continue

    if results:
        df_final = pd.DataFrame(results)
        out_name = f"Заправки_с_адресами_{date_input}.xlsx"
        df_final.to_excel(out_name, index=False)
        print(f"✅ Готово! Файл: {out_name}")
    else:
        print("📭 Заправок не найдено.")

if __name__ == "__main__":
    main()