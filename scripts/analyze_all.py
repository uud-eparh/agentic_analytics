import requests
import json
from clickhouse_driver import Client
import time
from datetime import datetime

# Подключение к ClickHouse
client = Client(
    host='localhost',
    port=9000,
    user='admin',
    password='admin',
    database='analytics'
)

SYSTEM_PROMPT = """
Ты — Senior Support-аналитик в крупном E-commerce.
Твоя задача: на основе сырых данных из БД (жалобы и суммы) принять РЕШЕНИЕ.

Правила:
1. Если сумма потерь > 5000$ -> статус "Красный". Действие: "Связаться с клиентом в течение 1 часа и предложить бонус 10%".
2. Если жалоб больше 3 от одного юзера -> статус "Желтый". Действие: "Проверить логи оплаты, возможно сбой платежного шлюза".
3. Во всех остальных случаях -> статус "Зеленый". Действие: "Отправить стандартную анкету удовлетворенности".

Ты ОБЯЗАН вернуть ТОЛЬКО JSON.
Формат: {"user_id": 123, "status": "Красный", "action": "текст действия", "reason": "краткая причина"}
Никаких лишних слов, только JSON.
"""

# Создаем таблицу, если её нет
client.execute('''
CREATE TABLE IF NOT EXISTS analytics.client_scoring (
    user_id UInt32,
    status String,
    action String,
    reason String,
    analyzed_at DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY (analyzed_at)
''')

# Получаем проблемных клиентов
query = """
SELECT 
    user_id,
    count(*) as failed_attempts,
    sum(amount) as lost_revenue
FROM analytics.transactions 
WHERE status != 'success'
GROUP BY user_id 
HAVING failed_attempts > 0
"""

print("🔍 Получаем всех проблемных клиентов...")
data = client.execute(query)
print(f"📊 Найдено {len(data)} проблемных клиентов")

batch_size = 5
processed = 0
batches_processed = 0

for i in range(0, len(data), batch_size):
    batch = data[i:i+batch_size]
    batches_processed += 1
    print(f"\n{'='*60}")
    print(f"🔄 Батч {batches_processed}/{(len(data)+batch_size-1)//batch_size}")
    print(f"⏱️  Время: {datetime.now().strftime('%H:%M:%S')}")
    
    users_data = []
    for row in batch:
        users_data.append({
            'id': row[0],
            'attempts': row[1],
            'loss': round(row[2], 2)
        })
    
    # Выводим данные, отправляемые в LLM
    print("\n📤 Отправляем в LLM:")
    print(json.dumps(users_data, ensure_ascii=False, indent=2))
    
    prompt = f"""
    Клиенты: {json.dumps(users_data, ensure_ascii=False)}
    Верни JSON-массив с полями: user_id, status (Красный/Желтый/Зеленый), action, reason
    """
    
    try:
        response = requests.post(
            'http://localhost:11434/api/generate',
            json={
                "model": "mistral:7b-instruct-v0.3-q4_0",
                "prompt": SYSTEM_PROMPT + "\n\n" + prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "num_predict": 4096,
                    "top_p": 0.9
                }
            },
            timeout=120
        )
        
        if response.status_code == 200:
            result_text = response.json()['response']
            
            # Выводим сырой ответ от LLM
            print("\n📥 Ответ от LLM (сырой):")
            print(result_text)
            
            # Извлекаем JSON
            start = result_text.find('[')
            end = result_text.rfind(']') + 1
            if start != -1 and end != 0:
                json_str = result_text[start:end]
                try:
                    decisions = json.loads(json_str)
                    
                    # Выводим красиво отформатированный JSON
                    print("\n✅ JSON (отформатированный):")
                    print(json.dumps(decisions, ensure_ascii=False, indent=2))
                    
                    # Сохраняем в ClickHouse
                    batch_to_insert = []
                    for d in decisions:
                        batch_to_insert.append({
                            'user_id': int(d['user_id']),
                            'status': d['status'],
                            'action': d['action'],
                            'reason': d.get('reason', '')
                        })
                    
                    if batch_to_insert:
                        client.execute('INSERT INTO client_scoring (user_id, status, action, reason) VALUES', batch_to_insert)
                        processed += len(batch_to_insert)
                        print(f"\n💾 Сохранено {len(batch_to_insert)} клиентов (всего {processed})")
                        
                        # Показываем текущую статистику
                        stats = client.execute('''
                        SELECT status, count(*) as cnt 
                        FROM analytics.client_scoring 
                        GROUP BY status 
                        ORDER BY cnt DESC
                        ''')
                        print("📊 Текущая статистика:")
                        for row in stats:
                            print(f"  {row[0]}: {row[1]}")
                except json.JSONDecodeError as e:
                    print(f"\n❌ Ошибка парсинга JSON: {e}")
                    print("Попытка восстановить JSON...")
            else:
                print("\n⚠️ JSON не найден в ответе")
        else:
            print(f"\n❌ HTTP ошибка: {response.status_code}")
            print(response.text)
    
    except requests.exceptions.Timeout:
        print("\n⏰ Таймаут запроса к Ollama")
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
    
    time.sleep(0.5)
    print("="*60)

print(f"\n✅ Всего сохранено {processed} клиентов")
print(f"✅ Обработано {batches_processed} батчей")