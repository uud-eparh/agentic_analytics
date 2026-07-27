import pandas as pd
from clickhouse_driver import Client
import random
import glob
from datetime import datetime

# Подключение к ClickHouse
client = Client(
    host='localhost',
    port=9000,
    user='admin',
    password='admin',
    database='analytics'
)

# Находим первый CSV файл в папке data
csv_files = glob.glob('data/**/*.csv', recursive=True)
if not csv_files:
    print("❌ CSV файл не найден в папке data/")
    exit(1)

csv_file = csv_files[0]
print(f"📂 Найден файл: {csv_file}")

# Читаем данные
df = pd.read_csv(csv_file, encoding='latin1')

# Очистка
df = df.dropna(subset=['CustomerID'])
df['InvoiceDate'] = pd.to_datetime(df['InvoiceDate'])
df['Amount'] = df['Quantity'] * df['UnitPrice']

# Переименовываем колонки под нашу схему
df = df.rename(columns={
    'InvoiceNo': 'transaction_id',
    'CustomerID': 'user_id',
    'Amount': 'amount',
    'InvoiceDate': 'created_at'
})

# Добавляем статусы (90% успешных, 10% проблемных)
problems = ['failed', 'refund', 'chargeback']
comments = [
    'Оплата не прошла, карта отклонена',
    'Возврат товара, не подошел размер',
    'Оспоренная транзакция в банке',
    'Таймаут оплаты на шлюзе',
    'Двойное списание средств'
]

statuses = []
comments_list = []

for _ in range(len(df)):
    if random.random() < 0.1:  # 10% проблем
        status = random.choice(problems)
        statuses.append(status)
        comments_list.append(random.choice(comments))
    else:
        statuses.append('success')
        comments_list.append('')

df['status'] = statuses
df['comment'] = comments_list

# Загружаем в ClickHouse батчами по 1000 записей
batch = []
total = 0

for _, row in df.iterrows():
    # Преобразуем дату в правильный формат для ClickHouse
    created_at = row['created_at'].to_pydatetime()
    
    batch.append({
        'transaction_id': int(abs(hash(row['transaction_id'])) % 1000000000),
        'user_id': int(row['user_id']),
        'amount': float(row['amount']),
        'status': row['status'],
        'comment': row['comment'],
        'created_at': created_at  # Передаем datetime, а не строку
    })
    
    if len(batch) >= 1000:
        client.execute('INSERT INTO transactions VALUES', batch)
        total += len(batch)
        print(f"Загружено {total} записей...")
        batch = []

# Загружаем остаток
if batch:
    client.execute('INSERT INTO transactions VALUES', batch)
    total += len(batch)

print(f"\n✅ Загружено {total} транзакций в ClickHouse!")