import requests

# Вставьте ваши куки (они у вас уже есть в коде final.py)
MY_COOKIES = "checkNewInterface=checked=True; ASP.NET_SessionId=xt4sfqdi2plrlrvjedywl1lm; SGUID=session_id=8cf66501-aef8-4c41-bb61-cddb319a09ff&Culture=uk-ua&langfile=ext-lang-ua.js&msgfile=msg-lang-ua.js&login=; .ASPXAUTH=086191C14A237119C0322F27DB56D47858BDBC92ACA2232F4906A4FFA848CC54739D87DBF6FBFFFE74D2EEE4A84FB8E8AEEED5211DA1452B163DA544223F5975A897969CB42280D8BD2BD4F629A29EDB664E5A94503D6597BE2E886FFCAAFA430C2F66050094973605DC93F9F67969ED46AE925BC473191D4065E2F4F6EB1FAC076DE5D16C62B0A67FF5640A45B9CBA9"

# Ссылка на одну машину для проверки
url = "https://gps.mobiteam.com.ua/MileageReportN.aspx?oid=8783&from=2025-12-31T22:00:00&to=2026-01-31T21:59:59&time=-1"

try:
    print("📡 Пытаюсь получить данные из таблицы...")
    res = requests.get(url, headers={'Cookie': MY_COOKIES}, timeout=30)
    
    # Сохраняем результат в файл, чтобы посмотреть структуру
    with open("debug.html", "w", encoding="utf-8") as f:
        f.write(res.text)
    
    print("✅ Файл debug.html создан!")
    print("Откройте его в этой папке и найдите строку с реальным пробегом.")
except Exception as e:
    print(f"❌ Ошибка: {e}")