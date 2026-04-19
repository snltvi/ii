import requests
import pandas as pd
import os
import re
import webbrowser

# --- НАСТРОЙКИ ---
API_BASE_URL = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN = "abvprom"
PASSWORD = "29328"
INPUT_FILE = 'CAN_пробег_датчики_06_02_2026.xlsx'

def get_sid():
    try:
        res = requests.get(f"{API_BASE_URL}/connect", 
                           params={'login': LOGIN, 'password': PASSWORD, 'lang': 'ru-ru', 'timezone': '3'},
                           timeout=10)
        return res.headers.get('sessionid') or res.json().get('sessionid')
    except: return None

def get_tank_volume(oid, sid):
    try:
        res = requests.get(f"{API_BASE_URL}/objsensorslist", params={'oid': oid}, headers={'SessionId': sid}, timeout=10).json()
        for sensor in res.get('obj_sensors', []):
            name = sensor.get('name', '')
            volumes = re.findall(r'(\d{3,4})', name)
            if volumes: return int(max(volumes, key=len))
    except: pass
    return 600

def main():
    sid = get_sid()
    if not sid: print("❌ Ошибка авторизации"); return
    if not os.path.exists(INPUT_FILE): print(f"❌ Нет файла {INPUT_FILE}"); return

    df_input = pd.read_excel(INPUT_FILE)
    ids_list = df_input['ID объекта'].dropna().unique()

    print("📡 Опрос датчиков и сбор данных о заправках...")
    tank_map = {int(oid): get_tank_volume(int(oid), sid) for oid in ids_list}

    d_start = input("📅 НАЧАЛО (ГГГГ-ММ-ДД ЧЧ:ММ:СС): ").strip()
    d_end   = input("📅 КОНЕЦ  (ГГГГ-ММ-ДД ЧЧ:ММ:СС): ").strip()

    ids_str = ";".join([str(int(x)) for x in ids_list])
    fuel_data = requests.get(f"{API_BASE_URL}/getobjectsfuelinfo", 
                             params={'date_from': d_start, 'date_to': d_end, 'objuids': ids_str},
                             headers={'SessionId': sid}).json()
    
    driver_map = pd.Series(df_input.ФИО.values, index=df_input['ID объекта']).to_dict()
    results = []

    for obj in fuel_data:
        oid = obj.get('object_id')
        t_start, t_end, total_refills = 0, 0, 0
        
        for s in obj.get('sensors', []):
            if any(w in s.get('sensor_name', '').lower() for w in ["бак", "lls", "fuel", "уровень"]):
                t_start += s.get('beginLevel', 0)
                t_end += s.get('endLevel', 0)
                # Суммируем все заправки по этому датчику
                total_refills += s.get('refillSum', 0)

        vol = tank_map.get(oid, 600)
        # Расход = Остаток на начало + Заправки - Остаток на конец
        consumption = t_start + total_refills - t_end
        perc = min(100, int((t_end / vol) * 100)) if t_end > 0 else 0
        
        results.append({
            'driver': driver_map.get(oid, "—"),
            'car': obj.get('object_name', 'N/A'),
            'max_vol': vol,
            'start': round(t_start, 1),
            'refills': round(total_refills, 1),
            'end': round(t_end, 1),
            'consumption': round(consumption, 1),
            'perc': perc
        })

    # --- ГЕНЕРАЦИЯ HTML ---
    html = f"""
    <html><head><meta charset='UTF-8'><style>
        body {{ font-family: 'Segoe UI', sans-serif; background: #f0f2f5; padding: 20px; }}
        .card {{ background: white; padding: 25px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); max-width: 1300px; margin: auto; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
        th {{ background: #f8f9fa; padding: 12px; text-align: left; border-bottom: 2px solid #ddd; color: #666; font-size: 13px; }}
        td {{ padding: 12px; border-bottom: 1px solid #eee; font-size: 14px; }}
        .tank-size {{ font-weight: bold; color: #1a73e8; }}
        .refill-col {{ color: #2e7d32; font-weight: bold; background: #f1f8e9; }}
        .cons-col {{ color: #d32f2f; font-weight: bold; }}
        .bar-bg {{ background: #eee; width: 80px; height: 10px; border-radius: 5px; display: inline-block; }}
        .bar-fill {{ background: #28a745; height: 100%; border-radius: 5px; }}
    </style></head><body>
    <div class='card'>
        <h2>⛽ Полный отчет по топливу (Уровни + Заправки)</h2>
        <p>Период: <b>{d_start}</b> — <b>{d_end}</b></p>
        <table>
            <tr>
                <th>Водитель</th>
                <th>Автомобиль</th>
                <th style='background:#eef6ff'>Объем бака</th>
                <th>Старт</th>
                <th class='refill-col'>Заправлено</th>
                <th>Конец</th>
                <th class='cons-col'>Расход</th>
                <th>Уровень (%)</th>
            </tr>
    """
    for r in results:
        html += f"""
            <tr>
                <td><b>{r['driver']}</b></td>
                <td>{r['car']}</td>
                <td class='tank-size'>{r['max_vol']} л</td>
                <td>{r['start']} л</td>
                <td class='refill-col'>+ {r['refills']} л</td>
                <td>{r['end']} л</td>
                <td class='cons-col'>{r['consumption']} л</td>
                <td><div class='bar-bg'><div class='bar-fill' style='width:{r['perc']}%'></div></div> {r['perc']}%</td>
            </tr>"""
    html += "</table></div></body></html>"

    file_path = os.path.abspath("Fuel_Full_Report.html")
    with open(file_path, "w", encoding="utf-8") as f: f.write(html)
    webbrowser.open("file://" + file_path)
    print(f"\n✅ Полный отчет сформирован!")

if __name__ == "__main__": main()