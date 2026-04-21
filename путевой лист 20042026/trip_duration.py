"""
Время в рейсе (вне гаража) за период
======================================
Логика:
  • Выезд из гаража  → начало рейса
  • Въезд в гараж    → конец рейса
  • Дни командировки = день выезда + промежуточные дни + день приезда (оба включительно)
  • Если авто уехало до начала периода — рейс считается с начала периода
  • Если авто ещё не вернулось — рейс считается до конца периода
"""

import requests
import pandas as pd
from datetime import datetime, timedelta, date

API_URL    = "https://gps.mobiteam.com.ua/api/integration/v1"
LOGIN      = "abvprom"
PASSWORD   = "29328"
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


# ── Garage zones ──────────────────────────────────────────────────────────────
def find_garage_zones(sid):
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
                found.append({"id": node["real_id"], "name": node["name"]})
            walk(node.get("children") or [])

    walk(data.get("children", []))
    return found


# ── Zone visits ───────────────────────────────────────────────────────────────
def get_visits(sid, obj_ids, zone_ids, date_from, date_to):
    r = requests.get(f"{API_URL}/zonesvisits",
                     headers={"SessionId": sid},
                     params={
                         "objects_ids": ",".join(map(str, obj_ids)),
                         "zones_ids":   ",".join(map(str, zone_ids)),
                         "from":        date_from,
                         "to":          date_to,
                         "minDuration": 0,
                     }, timeout=30)
    return r.json().get("visits", [])


# ── Objects list ──────────────────────────────────────────────────────────────
def ask_objects(sid):
    r = requests.get(f"{API_URL}/getobjectslist",
                     headers={"SessionId": sid}, timeout=20)
    objects = sorted(r.json().get("objects", []), key=lambda o: o["name"])

    print("\nДоступные объекты:")
    for i, o in enumerate(objects, 1):
        print(f"  {i:3}. [{o['id']:>7}] {o['name']}")

    raw = input("\nНомер(а) из списка или OID через запятую (Enter = все): ").strip()
    if not raw:
        return objects

    selected = []
    for token in raw.split(","):
        token = token.strip()
        if token.isdigit():
            idx = int(token)
            if 1 <= idx <= len(objects):
                selected.append(objects[idx - 1])
            else:
                selected.append({"id": idx, "name": f"OID {idx}"})
    return selected


# ── Helpers ───────────────────────────────────────────────────────────────────
def parse_utc(s):
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", ""))


def to_local(dt):
    return dt + timedelta(hours=UTC_OFFSET) if dt else None


def fmt(dt):
    return dt.strftime("%d.%m.%Y %H:%M") if dt else "—"


def count_days(start_dt, end_dt):
    """Количество дней командировки включительно (по календарным датам)."""
    d1 = start_dt.date() if start_dt else None
    d2 = end_dt.date()   if end_dt   else None
    if d1 and d2:
        return (d2 - d1).days + 1
    return None


def dur_str(seconds):
    if seconds is None:
        return "—"
    d, rem = divmod(int(seconds), 86400)
    h, m   = divmod(rem, 3600)
    return (f"{d}д " if d else "") + f"{h:02d}:{m // 60:02d}"


# ── Core logic: garage visits → trips ────────────────────────────────────────
def build_trips(obj_id, visits, period_from, period_to):
    """
    Из списка посещений гаража строит список рейсов (пробелы между посещениями).

    visit.in_dt  = момент ВЪЕЗДА в гараж  (начало пребывания в гараже)
    visit.out_dt = момент ВЫЕЗДА из гаража (конец пребывания в гараже)
                   если not_Ended=True — авто ещё в гараже, out_dt нет

    Рейс = от out_dt одного посещения до in_dt следующего.
    """
    my = sorted(
        [v for v in visits if v.get("obj_id") == obj_id],
        key=lambda v: parse_utc(v["in_dt"]) or datetime.min
    )

    trips = []

    # Строим временную шкалу «пребываний в гараже»
    garage_periods = []
    for v in my:
        in_dt  = parse_utc(v.get("in_dt"))
        out_dt = parse_utc(v.get("out_dt")) if not v.get("not_Ended") else None
        if in_dt:
            garage_periods.append((in_dt, out_dt))  # out_dt=None → ещё в гараже

    # Пробелы между периодами в гараже = рейсы
    prev_out = period_from   # если до начала периода авто было в гараже — рейс начнётся с первого выезда

    for garage_in, garage_out in garage_periods:
        # Период «на улице» до этого въезда в гараж
        trip_start = prev_out
        trip_end   = garage_in

        if trip_end > period_from and trip_start < period_to:
            # Обрезаем по рамкам запрашиваемого периода
            ts = max(trip_start, period_from)
            te = min(trip_end,   period_to)
            if te > ts:
                trips.append({
                    "start":     ts,
                    "end":       te,
                    "end_exact": True,   # факт возврата зафиксирован
                })

        # Следующий возможный старт рейса — выезд из гаража
        if garage_out:
            prev_out = garage_out
        else:
            # Авто в гараже до конца периода — рейсов после нет
            prev_out = period_to  # блокируем

    # Если после последнего выезда из гаража авто так и не вернулось
    if prev_out < period_to:
        trips.append({
            "start":     prev_out,
            "end":       period_to,
            "end_exact": False,  # конец периода, не факт возврата
        })

    return trips


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("=" * 65)
    print("  ВРЕМЯ В РЕЙСЕ (ВНЕ ГАРАЖА) ЗА ПЕРИОД")
    print("=" * 65)

    print("\nАвторизация...")
    sid = connect()
    print("  OK")

    objects = ask_objects(sid)
    obj_ids = [o["id"] for o in objects]
    obj_map = {o["id"]: o["name"] for o in objects}

    date_from_raw = input("\nНачало периода (ГГГГ-ММ-ДД): ").strip()
    date_to_raw   = input("Конец периода   (ГГГГ-ММ-ДД): ").strip()

    # UTC-строки для API (смещаем на -2 чтобы компенсировать UTC+2 отображение)
    dt_from_utc = datetime.strptime(date_from_raw, "%Y-%m-%d")
    dt_to_utc   = datetime.strptime(date_to_raw,   "%Y-%m-%d").replace(hour=23, minute=59, second=59)

    api_from = dt_from_utc.strftime("%Y-%m-%d %H:%M:%S")
    api_to   = dt_to_utc.strftime("%Y-%m-%d %H:%M:%S")

    print("\nПоиск геозон «Гараж»...")
    garage_zones = find_garage_zones(sid)
    if not garage_zones:
        print("  Геозоны «Гараж» не найдены!")
        return
    for z in garage_zones:
        print(f"  • [{z['id']}] {z['name']}")

    zone_ids = [z["id"] for z in garage_zones]

    print(f"\nЗапрос посещений гаража {api_from} — {api_to}...")
    visits = get_visits(sid, obj_ids, zone_ids, api_from, api_to)
    print(f"  Записей в API: {len(visits)}")

    # ── Build trips per vehicle ───────────────────────────────────────────────
    rows = []
    for obj in objects:
        oid   = obj["id"]
        vname = obj_map[oid]

        trips = build_trips(oid, visits, dt_from_utc, dt_to_utc)

        if not trips:
            print(f"\n  {vname}: рейсов не обнаружено (весь период в гараже или нет данных)")
            continue

        print(f"\n  {vname} — рейсов: {len(trips)}")
        for i, t in enumerate(trips, 1):
            loc_start = to_local(t["start"])
            loc_end   = to_local(t["end"])
            secs      = (t["end"] - t["start"]).total_seconds()
            days      = count_days(loc_start, loc_end)
            status    = "" if t["end_exact"] else " ⚠ не вернулся"

            print(f"    Рейс {i}: {fmt(loc_start)} → {fmt(loc_end)}"
                  f"  |  {dur_str(secs)}  |  {days} кал.дн.{status}")

            rows.append({
                "Авто":                 vname,
                "№ рейса":             i,
                "Выезд из гаража":     fmt(loc_start),
                "Въезд в гараж":       fmt(loc_end) if t["end_exact"] else "не вернулся",
                "В пути (чч:мм)":      dur_str(secs),
                "Дни командировки":    days,
                "День выезда":         loc_start.strftime("%d.%m.%Y") if loc_start else "—",
                "День возврата":       loc_end.strftime("%d.%m.%Y")   if t["end_exact"] and loc_end else "—",
                "Статус":              "Завершён" if t["end_exact"] else "В рейсе",
            })

    if not rows:
        print("\nНет данных для сохранения.")
        return

    df = pd.DataFrame(rows)
    out_file = f"Рейсы_{date_from_raw}_{date_to_raw}.xlsx"

    with pd.ExcelWriter(out_file, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Рейсы")
        ws = writer.sheets["Рейсы"]
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = max(
                len(str(col[0].value or "")),
                max((len(str(c.value or "")) for c in col), default=0)
            ) + 2

    print(f"\nФайл сохранён: {out_file}")
    print(f"Итого рейсов:  {len(rows)}")


if __name__ == "__main__":
    main()
