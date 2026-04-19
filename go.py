import requests
import pandas as pd
import glob
import re
from datetime import datetime
import time

# ===== НАСТРОЙКИ =====
LOGIN = "abvprom"
PASSWORD = "29328"
BASE_API_URL = "https://gps.mobiteam.com.ua/api/integration/v1"
TARGET_SIDS = [106125, 117715] # Теперь ищем оба варианта

session = requests.Session()

def connect():
    url = f"{BASE_API_URL}/connect"
    params = {'login': LOGIN, 'password': PASSWORD, 'lang': 'ru-ru', 'timezone': '3'}
    try:
        res = session.get(url, params=params, timeout=15)
        if res.status_code == 200 and "Ok" in res.text:
            sid = res.headers.get('sessionid')
            if sid:
                session.headers.update({'SessionId': sid})
                print("✅ Связь установлена!")
                return True
    except: pass
    return False

def get_sensor_val(oid, dt):
    """Пытаемся достать значение через objectinfo"""
    url = f"{BASE_API_URL}/objectinfo"
    try:
        # Пробуем запросить данные
        res = session.get(url, params={'oid': oid, 'dt': dt}, timeout=10)
        data = res.json()
        
        if "sensors" in data:
            for s in data["sensors"]:
                # Если нашли наш SID 106125 или 117715
                if s.get("sid") in TARGET_SIDS:
                    val_raw = str(s.get("val", "0"))
                    # Извлекаем только цифры (725358.31)
                    clean_val = re.sub(r'[^\d.]', '', val_raw.replace(',', '.'))
                    return float(clean_val) if clean_val else 0
    except:
        pass
    return 0

def main():
    print("=" * 70)
    files = glob.glob("*.xlsx")
    if not files: return
    
    excel_file = files[0]
    date_input = input("📅 Дата (ДД.ММ.ГГГГ): ").strip()
    target_date = datetime.strptime(date_input, "%d.%m.%Y")
    
    # Чтобы не попасть в "пустоту", берем 00:00:30 (обычно там уже есть данные)
    dt_start = target_date.strftime('%Y-%m-%d 00:00:30')
    dt_end = target_date.strftime('%Y-%m-%d 23:59:00')

    if not connect(): return

    df = pd.read_excel(excel_file)
    id_col = next((c for c in df.columns if 'ID' in str(c).upper()), None)
    
    print(f"\n🔍 Поиск датчиков {TARGET_SIDS}...")
    
    for idx, row in df.iterrows():
        if pd.isna(row[id_col]): continue
        oid = int(row[id_col])
        
        val_start = get_sensor_val(oid, dt_start)
        val_end = get_sensor_val(oid, dt_end)
        
        if val_start > 0 or val_end > 0:
            diff = round(val_end - val_start, 2)
            if diff < 0: diff = 0 # Защита от сброса одометра
            df.at[idx, 'Пробег (км)'] = diff
            print(f"✅ ID {oid}: Найдено! {val_start} -> {val_end} (Разница: {diff})")
        else:
            # Если по времени не нашло, попробуем просто текущее значение
            print(f"❌ ID {oid}: Датчики {TARGET_SIDS} не ответили на дату {date_input}")
            df.at[idx, 'Пробег (км)'] = 0

    out_name = f"Отчет_SID_106125_{target_date.strftime('%d_%m')}.xlsx"
    df.to_excel(out_name, index=False)
    print(f"\n🚀 Готово! Результат в {out_name}")

if __name__ == "__main__":
    main()