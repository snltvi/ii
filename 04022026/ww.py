import requests
import re

# Убедитесь, что куки свежие (взяты минуту назад)
MY_COOKIES = "checkNewInterface=checked=True; ASP.NET_SessionId=xt4sfqdi2plrlrvjedywl1lm; SGUID=session_id=8cf66501-aef8-4c41-bb61-cddb319a09ff&Culture=uk-ua&langfile=ext-lang-ua.js&msgfile=msg-lang-ua.js&login=; .ASPXAUTH=086191C14A237119C0322F27DB56D47858BDBC92ACA2232F4906A4FFA848CC54739D87DBF6FBFFFE74D2EEE4A84FB8E8AEEED5211DA1452B163DA544223F5975A897969CB42280D8BD2BD4F629A29EDB664E5A94503D6597BE2E886FFCAAFA430C2F66050094973605DC93F9F67969ED46AE925BC473191D4065E2F4F6EB1FAC076DE5D16C62B0A67FF5640A45B9CBA9"

# Тестовая ссылка на одну машину
url = "https://gps.mobiteam.com.ua/MileageReportN.aspx?oid=8783&from=2025-12-31T22:00:00&to=2026-01-31T21:59:59&time=-1"

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Cookie': MY_COOKIES,
    'Accept': '*/*'
}

try:
    print("📡 Запрашиваю данные...")
    res = requests.get(url, headers=headers, timeout=30)
    
    # Печатаем длину ответа
    print(f"Длина полученных данных: {len(res.text)} символов")
    
    # Если данные есть, ищем пробег
    if len(res.text) > 200:
        # Ищем все, что похоже на числа в ячейках <td>123.45</td>
        raw_data = re.findall(r'<td>(.*?)</td>', res.text)
        print("\n--- Найденные данные в таблице: ---")
        for item in raw_data:
            if any(char.isdigit() for char in item): # Печатаем только те ячейки, где есть цифры
                print(f"Найдено значение: {item}")
        
        # Если ничего не напечаталось выше, выведем начало "пустого" файла для диагностики
        if not raw_data:
            print("\nТекст ответа (первые 300 символов):")
            print(res.text[:300])
    else:
        print("❌ Ответ слишком короткий. Проверьте куки в браузере!")

except Exception as e:
    print(f"⚠️ Ошибка: {e}")