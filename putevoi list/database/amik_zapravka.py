import pandas as pd
import re
import os
import sqlite3

# Настройки
file_fleet = 'Cцепка_водитель-авто-прицеп_на_20_01_2026_с_ID_объектов.xlsx'
file_trans = 'отчет по транзакциям.xlsx'
db_file = 'fleet_monitoring.db'

# 1. Загрузка
df_fleet = pd.read_excel(file_fleet)
df_transactions = pd.read_excel(file_trans)

# 2. Функция очистки ключа (последние 4 цифры)
def get_clean_key(value):
    if pd.isna(value): return None
    val_str = str(value).replace('.0', '').strip()
    match = re.search(r'(\d{4})$', val_str)
    return match.group(1) if match else None

# Применяем ключи
df_transactions['key_card'] = df_transactions['Номер топливной карты'].apply(get_clean_key)
df_fleet['key_card'] = df_fleet['Карта Амик'].apply(get_clean_key)

# 3. Объединение
fleet_lookup = df_fleet[['key_card', 'ID объекта', 'Номер авто', 'ФИО', 'Номер прицепа']].copy()
fleet_lookup = fleet_lookup.dropna(subset=['key_card']).drop_duplicates(subset=['key_card'])

final_df = pd.merge(df_transactions, fleet_lookup, on='key_card', how='left')

# 4. ПРЕОБРАЗОВАНИЕ ДЛЯ БАЗЫ ДАННЫХ (Важный блок!)
# Преобразуем колонку 'Дата' в настоящий формат даты Python
# Это позволит вам потом делать запросы "выдай заправки за март"
if 'Дата' in final_df.columns:
    final_df['Дата'] = pd.to_datetime(final_df['Дата'], dayfirst=True, errors='coerce')

# Убираем технический ключ
final_df_to_db = final_df.drop(columns=['key_card'])

# 5. ЗАПИСЬ В SQLITE
try:
    conn = sqlite3.connect(db_file)
    
    # Записываем в таблицу 'amik_refills'
    # if_exists='replace' — перезаписывает таблицу полностью (актуально для свежего отчета)
    final_df_to_db.to_sql('amik_refills', conn, if_exists='replace', index=False)
    
    print(f"✅ Данные успешно перенесены в базу: {db_file}")
    print(f"📊 Всего строк в базе: {len(final_df_to_db)}")
    print(f"🚗 Привязано заправок к госномерам: {final_df_to_db['Номер авто'].notna().sum()}")
    
    conn.close()
except Exception as e:
    print(f"❌ Ошибка записи в базу: {e}")

# 6. Сохраняем и Excel на всякий случай
final_df_to_db.to_excel('амик_заправки_финал.xlsx', index=False)
