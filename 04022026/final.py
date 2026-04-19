import requests
import openpyxl
import re

# Актуальные Cookie из вашего последнего запроса
MY_COOKIES = "checkNewInterface=checked=True; ASP.NET_SessionId=xt4sfqdi2plrlrvjedywl1lm; SGUID=session_id=8cf66501-aef8-4c41-bb61-cddb319a09ff&Culture=uk-ua&langfile=ext-lang-ua.js&msgfile=msg-lang-ua.js&login=; .ASPXAUTH=086191C14A237119C0322F27DB56D47858BDBC92ACA2232F4906A4FFA848CC54739D87DBF6FBFFFE74D2EEE4A84FB8E8AEEED5211DA1452B163DA544223F5975A897969CB42280D8BD2BD4F629A29EDB664E5A94503D6597BE2E886FFCAAFA430C2F66050094973605DC93F9F67969ED46AE925BC473191D4065E2F4F6EB1FAC076DE5D16C62B0A67FF5640A45B9CBA9"

# Используем файл с буквой N для получения чистых данных
BASE_DATA_URL = "https://gps.mobiteam.com.ua/MileageReportN.aspx"

VEHICLES = {
    8783: "DAF ВН5290РХ", 7312: "DAF BH4492PT", 8743: "DAF ВН1575РК", 
    7242: "DAF ВН3194РА", 7243: "DAF ВН3198РА", 7692: "DAF ВН4721РН", 
    7691: "DAF ВН4723РН", 8666: "DAF ВН5291РХ", 7281: "DAF ВН5651РВ",
    8200: "DAF ВН5685РМ", 7250: "DAF ВН6394РВ", 7251: "DAF ВН6395РВ",
    7248: "DAF ВН6396РВ", 8123: "DAF ВН6484РН", 8201: "DAF ВН7532РС",
    8124: "DAF ВН8941РС", 8161: "DAF ВН9546РС"
}

def get_january_data():
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Cookie': MY_COOKIES,
    }

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Машина", "Пробег за январь (км)"])

    print("📊 Начинаю сбор данных по всем машинам...")

    for oid, name in VEHICLES.items():
        # Параметры из вашего анализа сетевого трафика
        params = {
            "oid": oid,
            "from": "2025-12-31T22:00:00",
            "to": "2026-01-31T21:59:59",
            "time": -1,
            "fuelings": "true"
        }
        
        try:
            res = requests.get(BASE_DATA_URL, params=params, headers=headers, timeout=30)
            html = res.text
            
            # Извлекаем числа, которые сервер присылает в таблице
            # Ищем итоговый пробег (обычно это самое большое число в ответе)
            found_numbers = re.findall(r'(\d+[\.,]\d+)', html)
            
            if found_numbers:
                # Преобразуем строки в числа и выбираем максимальное
                mileage = max([float(n.replace(',', '.')) for n in found_numbers])
                ws.append([name, mileage])
                print(f"✅ {name}: {mileage} км")
            else:
                ws.append([name, "Данные не найдены"])
                print(f"❓ {name}: Цифры в ответе не обнаружены")
                
        except Exception as e:
            print(f"⚠️ Ошибка на {name}: {e}")

    filename = "January_Fleet_Report.xlsx"
    wb.save(filename)
    print(f"\n🏁 ГОТОВО! Проверьте файл: {filename}")

if __name__ == "__main__":
    get_january_data()