import requests
import pandas as pd
import os
import time
from calendar import monthrange

# --- НАСТРОЙКИ ---
API_URL = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN = "abvprom"
PASSWORD = "29328"
TARGET_FILE = r"c:/Users/snltv/Desktop/ii/putevoi list/CAN_пробег_датчики_06_02_2026.xlsx"

def connect_to_api():
    headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
    params = {'login': LOGIN, 'password': PASSWORD, 'timezone': '3', 'lang': 'ru-ru'}
    try:
        res = requests.get(f"{API_URL}/connect", params=params, headers=headers, timeout=15)
        sid = res.headers.get('sessionid') or res.headers.get('SessionId')
        return sid
    except:
        return None

def get_monthly_fuel(sid, oid, year, month):
    """Считает общую заправку за месяц"""
    # Определяем количество дней в месяце
    last_day = monthrange(year, month)[1]
    
    date_from = f"{year}-{month:02d}-01 00:00:00"
    date_to = f"{year}-{month:02d}-{last_day} 23:59:59"
    
    headers = {'SessionId': sid, 'Accept': 'application/json'}
    params = {
        'date_from': date_from,
        'date_to': date_to,
        'objuids': str(oid)
    }
    
    try:
        res = requests.get(f"{API_URL}/getobjectsfuelinfo", headers=headers, params=params, timeout=30)
        if res.status_code != 200: return 0
        data = res.json()
        
        max_monthly_fuel = 0
        for obj in data:
            for sensor in obj.get('sensors', []):
                val = float(sensor.get('summ_refuelings', 0))
                # Выбираем датчик с максимальным значением (ДУТ / Общее топливо)
                if val > max_monthly_fuel:
                    max_monthly_fuel = val
        return round(max_monthly_fuel, 1)
    except:
        return 0

if __name__ == "__main__":
    print("🚀 Отчет по заправкам за МЕСЯЦ")
    
    if not os.path.exists(TARGET_FILE):
        print(f"❌ Файл не найден: {TARGET_FILE}")
    else:
        # Ввод месяца
        print("\nВведите период в формате ГГГГ-ММ (например, 2025-06)")
        period = input("Период: ").strip()
        
        try:
            year = int(period.split('-')[0])
            month = int(period.split('-')[1])
        except:
            print("❌ Ошибка формата! Используйте ГГГГ-ММ")
            input()
            exit()
            
        sid = connect_to_api()
        if not sid:
            print("❌ Ошибка входа.")
        else:
            print(f"✅ Подключено. Начинаю сбор данных за {period}...")
            df = pd.read_excel(TARGET_FILE)
            
            monthly_results = []
            
            print(f"\n📊 Итоги за {period}:")
            print("-" * 65)
            print(f"{'Госномер / ФИО':<35} | {'Итого за месяц':<15}")
            print("-" * 65)
            
            for index, row in df.iterrows():
                oid = row.get('ID объекта')
                if pd.isna(oid):
                    monthly_results.append(0)
                    continue
                
                name = str(row.get('Номер авто', '---'))
                fio = str(row.get('ФИО', '---'))
                
                # Запрос суммы за месяц
                total_fuel = get_monthly_fuel(sid, int(oid), year, month)
                
                display_name = f"{name} ({fio})"
                print(f"{display_name[:35]:<35} | {total_fuel:>10} л")
                
                monthly_results.append(total_fuel)
                time.sleep(0.2) # Небольшая пауза для стабильности
            
            # Сохранение
            column_name = f"Заправка_мес_{period}"
            df[column_name] = monthly_results
            
            output_path = TARGET_FILE.replace(".xlsx", f"_отчет_{period}.xlsx")
            df.to_excel(output_path, index=False)
            
            print("-" * 65)
            print(f"✅ Отчет сохранен: {output_path}")

    print("\n" + "="*40)
    input("Нажмите ENTER для выхода...")