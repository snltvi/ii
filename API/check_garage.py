import requests
from datetime import datetime

API_URL = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN    = "abvprom"
PASSWORD = "29328"
TIME_OFFSET = 2  # UTC+2 Украина


def get_session():
    res = requests.get(f"{API_URL}/connect", params={
        'login': LOGIN, 'password': PASSWORD, 'lang': 'ru-ru', 'timezone': str(TIME_OFFSET)
    }, timeout=10)
    sid = res.headers.get('sessionid') or res.json().get('sessionid')
    if not sid:
        raise RuntimeError("Ошибка авторизации")
    return sid


def find_garage_zones(sid):
    """Рекурсивно находит все геозоны с именем 'гараж' (без учёта регистра)."""
    res = requests.get(f"{API_URL}/getgeotree", headers={'SessionId': sid},
                       params={'all': 'true'}, timeout=10)
    data = res.json()
    if data.get('result') != 'Ok':
        raise RuntimeError(f"Ошибка getgeotree: {data.get('result')}")

    found = []

    def walk(nodes):
        for node in (nodes or []):
            if node.get('name', '').lower() == 'гараж' and not node.get('IsGroup'):
                found.append({'id': node['real_id'], 'name': node['name'],
                               'type': node.get('geo_type', '—')})
            walk(node.get('children') or [])

    walk(data.get('children', []))
    return found


def check_vehicle_in_garage(sid, obj_id, zone_ids, date_from, date_to):
    res = requests.get(f"{API_URL}/zonesvisits", headers={'SessionId': sid}, params={
        'objects_ids': str(obj_id),
        'zones_ids': ','.join(map(str, zone_ids)),
        'from': date_from,
        'to': date_to,
    }, timeout=15)
    return res.json().get('visits', [])


def fmt(dt_str):
    """Форматирует время из UTC в UTC+2."""
    if not dt_str:
        return '—'
    dt = datetime.fromisoformat(dt_str.replace('Z', '')) + __import__('datetime').timedelta(hours=TIME_OFFSET)
    return dt.strftime('%d.%m.%Y %H:%M:%S')


def main():
    print("=" * 60)
    print("  ПРОВЕРКА: БУВ ЧИ АВТОМОБІЛЬ У ГАРАЖІ")
    print("=" * 60)

    obj_id   = input("ID об'єкта (авто): ").strip()
    date_from = input("Початок (РРРР-ММ-ДД ГГ:ХХ:СС): ").strip()
    date_to   = input("Кінець   (РРРР-ММ-ДД ГГ:ХХ:СС): ").strip()

    print("\n🔌 Авторизація...")
    sid = get_session()

    print("📍 Пошук геозон 'Гараж'...")
    garage_zones = find_garage_zones(sid)

    if not garage_zones:
        print("❌ Геозони 'Гараж' не знайдено!")
        return

    print(f"✅ Знайдено геозон: {len(garage_zones)}")
    for z in garage_zones:
        print(f"   • [{z['id']}] {z['name']} ({z['type']})")

    zone_ids = [z['id'] for z in garage_zones]

    print(f"\n📡 Запит відвідувань для авто {obj_id}...")
    visits = check_vehicle_in_garage(sid, obj_id, zone_ids, date_from, date_to)

    print("\n" + "=" * 60)

    if not visits:
        print(f"🚗 Авто {obj_id}: у гаражі НЕ БУЛО у вказаний період.")
    else:
        print(f"🚗 Авто {obj_id}: знайдено {len(visits)} відвідувань гаражу\n")
        zone_map = {z['id']: z['name'] for z in garage_zones}

        for i, v in enumerate(visits, 1):
            in_dt  = fmt(v.get('in_dt'))
            out_dt = fmt(v.get('out_dt')) if not v.get('not_Ended') else 'ЩЕ В ЗОНІ'
            zone_name = zone_map.get(v.get('geo_id'), str(v.get('geo_id')))

            print(f"  [{i}] Зона: {zone_name}")
            print(f"       В'їзд : {in_dt}")
            print(f"       Виїзд : {out_dt}")

            if not v.get('not_Ended') and v.get('in_dt') and v.get('out_dt'):
                t_in  = datetime.fromisoformat(v['in_dt'].replace('Z', ''))
                t_out = datetime.fromisoformat(v['out_dt'].replace('Z', ''))
                secs  = int((t_out - t_in).total_seconds())
                print(f"       Час у зоні: {secs // 3600}г {(secs % 3600) // 60}хв")
            print()

        currently_in = any(v.get('not_Ended') for v in visits)
        print("📌 Статус зараз:", "В ГАРАЖІ" if currently_in else "НЕ в гаражі")

    print("=" * 60)


if __name__ == "__main__":
    main()
