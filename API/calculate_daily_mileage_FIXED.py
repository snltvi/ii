import requests
import pandas as pd
from datetime import datetime, timedelta
import sys
import os

# ============================================================================
# КОНСТАНТЫ
# ============================================================================
API_BASE_URL = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN = "abvprom"
PASSWORD = "29328"

# Список имен файлов (скрипт ищет первый существующий)
EXCEL_FILES = ['CAN_пробег_датчики_06_02_2026.xlsx', 'Датчики_CAN_пробег.xlsx']

# ВАШЕ СМЕЩЕНИЕ: +2 (Украина, зима)
UTC_OFFSET = +2

def connect_to_api():
    url = f"{API_BASE_URL}/connect"
    params = {'login': LOGIN, 'password': PASSWORD, 'lang': 'ru-ru', 'timezone': str(UTC_OFFSET)}
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        sid = response.headers.get('sessionid')
        if not sid: raise Exception("SessionId не получен")
        return sid
    except Exception as e:
        print(f"✗ Ошибка подключения: {e}")
        sys.exit(1)

def get_mileage_from_report(session_id, oid, target_date):
    # Коррекция времени для UTC: от локального отнимаем смещение
    date_from_utc = target_date.replace(hour=0, minute=0, second=0) - timedelta(hours=UTC_OFFSET)
    date_to_utc = target_date.replace(hour=23, minute=59, second=59) - timedelta(hours=UTC_OFFSET)
    
    url = f"{API_BASE_URL}/getobjectsreport"
    params = {
        'date_from': date_from_utc.strftime('%Y-%m-%d %H:%M:%S'),
        'date_to': date_to_utc.strftime('%Y-%m-%d %H:%M:%S'),
        'objuids': str(oid),
        'split': 'none',
        'param': 'start_can_dist;stop_can_dist;can_dist'
    }
    headers = {'SessionId': session_id}
    try:
        res = requests.get(url, params=params, headers=headers, timeout=25).json()
        if res and len(res) > 0:
            periods = res[0].get('periods', [])
            if periods:
                prms = periods[0].get('prms', [])
                data = {p['name']: float(p['value']) for p in prms if p.get('value')}
                if data.get('can_dist', 0) > 0:
                    return data.get('start_can_dist'), data.get('stop_can_dist'), data.get('can_dist')
    except: pass
    return None, None, None

def get_mileage_from_objdata(session_id, oid, sensor_id, target_date):
    date_str = target_date.strftime('%Y-%m-%d')
    d_str_f = f"{date_str} 00:00:00"
    d_str_t = f"{date_str} 23:59:59"
    
    url = f"{API_BASE_URL}/objdata"
    params = {'oid': oid, 'slist': f's{sensor_id}', 'from': d_str_f, 'to': d_str_t}
    headers = {'SessionId': session_id}
    try:
        res = requests.get(url, headers=headers, params=params, timeout=25).json()
        records = res.get('obj_data', {}).get('records', [])
        if len(records) >= 2:
            v_start = float(records[0][1])
            v_end = float(records[-1][1])
            return v_start, v_end, round(v_end - v_start, 2)
    except: pass
    return None, None, None

def main():
    print(f"\n{'='*55}\nСТАРТ (Смещение UTC+{UTC_OFFSET})\n{'='*55}")
    
    excel_file = next((f for f in EXCEL_FILES if os.path.exists(f)), None)
    if not excel_file:
        print("✗ Файл Excel не найден. Положите файл в папку со скриптом."); return

    target_date_str = input("📅 Введите дату (ГГГГ-ММ-ДД): ").strip()
    try:
        target_date = datetime.strptime(target_date_str, '%Y-%m-%d')
    except:
        print("✗ Ошибка формата даты."); return

    sid = connect_to_api()
    df = pd.read_excel(excel_file)
    
    results = []
    print(f"\n{'№':<3} | {'Авто':<15} | {'Пробег':<8} | {'Метод'}")
    print("-" * 45)

    for i, row in df.iterrows():
        oid = row.get('ID объекта')
        if pd.isna(oid): continue # Пропуск пустых строк
        
        # 1. Сначала отчет
        o_s, o_e, dist = get_mileage_from_report(sid, int(oid), target_date)
        method = "report"
        
        # 2. Если пусто — по датчику SID
        if dist is None:
            s_id = row.get('SID')
            if pd.notna(s_id):
                o_s, o_e, dist = get_mileage_from_objdata(sid, int(oid), int(s_id), target_date)
                method = "objdata"
            else:
                method = "failed"

        print(f"{i+1:<3} | {str(row.get('Номер авто', '???'))[:15]:<15} | {str(dist or 0):<8} | {method}")
        
        results.append({
            **row.to_dict(),
            'Начало': o_s, 
            'Конец': o_e, 
            'Пробег_КМ': dist or 0, 
            'Метод_API': method
        })

    res_df = pd.DataFrame(results)
    out_file = f"Пробег_{target_date_str}.xlsx"
    res_df.to_excel(out_file, index=False)
    print(f"\n✅ Готово! Файл: {out_file}")

if __name__ == "__main__":
    main()