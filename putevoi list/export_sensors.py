#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Отримує список датчиків для всіх об'єктів через /objsensorslist
і зберігає результат в Excel.
"""

import requests
import pandas as pd
import time
import os

# ═══════════════════════════════════════════════════════
API_URL  = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN    = "abvprom"
PASSWORD = "29328"
OUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "sensors_all_objects.xlsx")
# ═══════════════════════════════════════════════════════


def connect():
    r = requests.get(f"{API_URL}/connect",
                     params={'login': LOGIN, 'password': PASSWORD,
                             'lang': 'ru-ru', 'timezone': '3'},
                     timeout=10)
    sid = r.headers.get('sessionid') or r.json().get('sessionid')
    if not sid:
        raise RuntimeError(f"Авторизація не вдалась: {r.text}")
    return sid


def get_all_objects(sid):
    """
    /gettree — повертає дерево об'єктів.
    Рекурсивно збираємо всі leaf-об'єкти (реальні ТЗ).
    """
    r = requests.get(f"{API_URL}/gettree",
                     headers={'SessionId': sid},
                     params={'all': 'true'},
                     timeout=30)
    r.raise_for_status()

    objects = []

    def walk(nodes):
        for node in nodes:
            if node.get('leaf'):
                objects.append({
                    'oid':  node.get('real_id') or node.get('id'),
                    'name': node.get('name', ''),
                    'imei': node.get('IMEI', ''),
                })
            if node.get('children'):
                walk(node['children'])

    walk(r.json().get('children', []))
    return objects


def get_sensors(sid, oid):
    """
    /objsensorslist — список датчиків об'єкта.
    Повертає список {sid, pid, name, icon}.
    """
    r = requests.get(f"{API_URL}/objsensorslist",
                     headers={'SessionId': sid},
                     params={'oid': oid},
                     timeout=15)
    if r.status_code != 200:
        return []
    return r.json().get('obj_sensors', [])


def sensor_id_str(s):
    """Формує рядок ідентифікатора датчика для /objdata: s{sid} або p{pid}."""
    if s.get('sid') and s['sid'] > 0:
        return f"s{s['sid']}"
    if s.get('pid') and s['pid'] > 0:
        return f"p{s['pid']}"
    return ''


def main():
    print("=" * 60)
    print("  ЕКСПОРТ ДАТЧИКІВ ВСІХ ОБ'ЄКТІВ")
    print("=" * 60)

    print("\n[1] Підключаємось до API...")
    sid = connect()
    print(f"    SessionId: {sid[:12]}...")

    print("\n[2] Отримуємо список об'єктів...")
    objects = get_all_objects(sid)
    print(f"    Знайдено об'єктів: {len(objects)}")

    rows = []
    print(f"\n[3] Запитуємо датчики для кожного об'єкта...")

    for i, obj in enumerate(objects, 1):
        oid  = obj['oid']
        name = obj['name']
        imei = obj['imei']
        print(f"  [{i:>3}/{len(objects)}]  OID={oid}  {name}")

        sensors = get_sensors(sid, oid)
        print(f"           Датчиків: {len(sensors)}")

        if sensors:
            for s in sensors:
                rows.append({
                    'OID':          oid,
                    'Назва об\'єкта': name,
                    'IMEI':         imei,
                    'SID':          s.get('sid', 0),
                    'PID':          s.get('pid', 0),
                    'ID для objdata': sensor_id_str(s),
                    'Назва датчика': s.get('name', '').strip(),
                    'Іконка':       s.get('icon', ''),
                })
        else:
            # Записуємо рядок без датчиків щоб об'єкт був присутній
            rows.append({
                'OID':          oid,
                'Назва об\'єкта': name,
                'IMEI':         imei,
                'SID':          None,
                'PID':          None,
                'ID для objdata': '',
                'Назва датчика': '— датчики не знайдено —',
                'Іконка':       '',
            })

        time.sleep(0.15)   # щоб не спамити сервер

    print(f"\n[4] Записуємо в Excel: {OUT_FILE}")
    df = pd.DataFrame(rows, columns=[
        'OID', "Назва об'єкта", 'IMEI',
        'SID', 'PID', 'ID для objdata',
        'Назва датчика', 'Іконка',
    ])

    with pd.ExcelWriter(OUT_FILE, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Датчики')

        # Авто-ширина колонок
        ws = writer.sheets['Датчики']
        for col in ws.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 60)

    print(f"    Рядків: {len(df)}")
    print(f"    Об'єктів: {df['OID'].nunique()}")
    print(f"\n✅ Готово! Файл: {OUT_FILE}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\n❌ Помилка: {e}")
    input("\nEnter для виходу...")
