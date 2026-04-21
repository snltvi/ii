"""
Посещения геозоны «Гараж» за период
=====================================
Запрашивает дерево геозон, находит все геозоны с именем «гараж»,
затем через /zonesvisits получает факты въезда / выезда за период.
Результат выводится в консоль и сохраняется в Excel.
"""

import requests
import pandas as pd
from datetime import datetime, timedelta

API_URL   = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN     = "abvprom"
PASSWORD  = "29328"
UTC_OFFSET = 2  # UTC+2


# ── Auth ──────────────────────────────────────────────────────────────────────
def connect():
    r = requests.get(f"{API_URL}/connect",
                     params={"login": LOGIN, "password": PASSWORD,
                             "lang": "ru-ru", "timezone": str(UTC_OFFSET)},
                     timeout=10)
    sid = r.headers.get("sessionid") or r.json().get("sessionid")
    if not sid:
        raise RuntimeError("Ошибка авторизации")
    return sid


# ── Geofence tree → garage zones ─────────────────────────────────────────────
def find_garage_zones(sid):
    """Рекурсивно ищет все реальные геозоны с именем 'гараж' (без учёта регистра)."""
    r = requests.get(f"{API_URL}/getgeotree",
                     headers={"SessionId": sid},
                     params={"all": "true"}, timeout=15)
    data = r.json()
    if data.get("result") != "Ok":
        raise RuntimeError(f"getgeotree: {data.get('result')}")

    found = []

    def walk(nodes):
        for node in (nodes or []):
            if node.get("name", "").lower() == "гараж" and not node.get("IsGroup"):
                found.append({
                    "id":   node["real_id"],
                    "name": node["name"],
                    "type": node.get("geo_type", "—"),
                })
            walk(node.get("children") or [])

    walk(data.get("children", []))
    return found


# ── Zone visits ───────────────────────────────────────────────────────────────
def get_visits(sid, obj_ids, zone_ids, date_from, date_to, min_duration=0):
    """
    /zonesvisits — все факты въезда/выезда.
    obj_ids, zone_ids — списки int.
    date_from/date_to — строки 'YYYY-MM-DD HH:MM:SS' (UTC).
    """
    r = requests.get(f"{API_URL}/zonesvisits",
                     headers={"SessionId": sid},
                     params={
                         "objects_ids":  ",".join(map(str, obj_ids)),
                         "zones_ids":    ",".join(map(str, zone_ids)),
                         "from":         date_from,
                         "to":           date_to,
                         "minDuration":  min_duration,
                     }, timeout=30)
    return r.json().get("visits", [])


# ── Helpers ───────────────────────────────────────────────────────────────────
def to_local(utc_str):
    """UTC ISO-строка → datetime UTC+2."""
    if not utc_str:
        return None
    dt = datetime.fromisoformat(utc_str.replace("Z", ""))
    return dt + timedelta(hours=UTC_OFFSET)


def fmt(dt):
    return dt.strftime("%d.%m.%Y %H:%M:%S") if dt else "—"


def duration_str(seconds):
    d, rem = divmod(int(seconds), 86400)
    h, rem = divmod(rem, 3600)
    m      = rem // 60
    return (f"{d}д " if d else "") + f"{h:02d}:{m:02d}"


# ── Interactive input ─────────────────────────────────────────────────────────
def ask_objects(sid):
    """Получает список ТС и предлагает выбрать одно или несколько."""
    r = requests.get(f"{API_URL}/getobjectslist",
                     headers={"SessionId": sid}, timeout=20)
    objects = sorted(r.json().get("objects", []), key=lambda o: o["name"])

    print("\nДоступные объекты:")
    for i, o in enumerate(objects, 1):
        print(f"  {i:3}. [{o['id']:>7}] {o['name']}")

    raw = input("\nВведите номер(а) из списка или OID через запятую: ").strip()
    selected = []
    for token in raw.split(","):
        token = token.strip()
        if token.isdigit():
            idx = int(token)
            if 1 <= idx <= len(objects):
                selected.append(objects[idx - 1])
            else:
                selected.append({"id": idx, "name": f"OID {idx}"})
    return selected if selected else objects   # пусто → все


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("  ПОСЕЩЕНИЯ ГЕОЗОНЫ «ГАРАЖ» ЗА ПЕРИОД")
    print("=" * 60)

    print("\nАвторизация...")
    sid = connect()
    print("  OK")

    objects = ask_objects(sid)
    obj_ids = [o["id"] for o in objects]
    obj_map = {o["id"]: o["name"] for o in objects}

    date_from_raw = input("\nНачало периода (ГГГГ-ММ-ДД): ").strip()
    date_to_raw   = input("Конец периода   (ГГГГ-ММ-ДД): ").strip()
    date_from = f"{date_from_raw} 00:00:00"
    date_to   = f"{date_to_raw} 23:59:59"

    min_dur_raw = input("Минимальное время в зоне (сек, 0 = любое): ").strip()
    min_dur = int(min_dur_raw) if min_dur_raw.isdigit() else 0

    print("\nПоиск геозон «Гараж»...")
    garage_zones = find_garage_zones(sid)
    if not garage_zones:
        print("  Геозоны «Гараж» не найдены!")
        return

    print(f"  Найдено геозон: {len(garage_zones)}")
    for z in garage_zones:
        print(f"    • [{z['id']}] {z['name']} ({z['type']})")

    zone_ids = [z["id"] for z in garage_zones]
    zone_map = {z["id"]: z["name"] for z in garage_zones}

    print(f"\nЗапрос посещений {date_from} — {date_to}...")
    visits = get_visits(sid, obj_ids, zone_ids, date_from, date_to, min_dur)

    if not visits:
        print("  Посещений не найдено за указанный период.")
        return

    print(f"  Найдено записей: {len(visits)}\n")

    rows = []
    for v in visits:
        in_dt  = to_local(v.get("in_dt"))
        out_dt = to_local(v.get("out_dt")) if not v.get("not_Ended") else None
        still_in = v.get("not_Ended", False)

        dur_sec = None
        if in_dt and out_dt:
            dur_sec = (out_dt - in_dt).total_seconds()

        rows.append({
            "Авто":              obj_map.get(v.get("obj_id"), str(v.get("obj_id"))),
            "Геозона":           zone_map.get(v.get("geo_id"), str(v.get("geo_id"))),
            "Въезд (UTC+2)":     fmt(in_dt),
            "Выезд (UTC+2)":     "ЕЩЁ В ЗОНЕ" if still_in else fmt(out_dt),
            "Время в зоне":      duration_str(dur_sec) if dur_sec is not None else ("в зоне" if still_in else "—"),
            "Статус":            "В ГАРАЖЕ" if still_in else "Выехал",
        })

    # ── Console output ────────────────────────────────────────────────────────
    for i, row in enumerate(rows, 1):
        print(f"  [{i:3}] {row['Авто']:30} | {row['Геозона']:10} | "
              f"въезд {row['Въезд (UTC+2)']} | выезд {row['Выезд (UTC+2)']} | "
              f"{row['Время в зоне']} | {row['Статус']}")

    # ── Excel ─────────────────────────────────────────────────────────────────
    df = pd.DataFrame(rows)
    out_file = f"Гараж_{date_from_raw}_{date_to_raw}.xlsx"
    df.to_excel(out_file, index=False)
    print(f"\nФайл сохранён: {out_file}")


if __name__ == "__main__":
    main()
