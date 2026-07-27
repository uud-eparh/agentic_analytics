import requests
import json
from clickhouse_driver import Client
from datetime import datetime, timedelta

# Подключение к ClickHouse
client = Client(
    host='localhost',
    port=9000,
    user='admin',
    password='admin',
    database='analytics'
)

# Системный промпт для агента
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

# 1. Получаем проблемных клиентов за последние 7 дней
query = """
SELECT 
    user_id,
    count(*) as failed_attempts,
    sum(amount) as lost_revenue,
    groupArray(comment) as complaints
FROM transactions 
WHERE status != 'success' 
  AND created_at > now() - INTERVAL 7 DAY
GROUP BY user_id 
HAVING failed_attempts > 1
LIMIT 10
"""

print("🔍 Получаем проблемных клиентов...")
data = client.execute(query)

if not data:
    print("✅ Проблемных клиентов за последние 7 дней нет!")
    exit(0)

print(f"📊 Найдено {len(data)} проблемных клиентов")

# 2. Формируем данные для LLM
users_data = []
for row in data:
    users_data.append({
        'user_id': row[0],
        'failed_attempts': row[1],
        'lost_revenue': round(row[2], 2),
        'complaints': row[3]
    })

user_data_str = json.dumps(users_data, ensure_ascii=False, indent=2)

# 3. Формируем промпт
prompt = f"""
Проанализируй этих клиентов и для каждого верни JSON-решение:

Данные:
{user_data_str}

Верни массив JSON-объектов в формате:
[
  {{"user_id": 123, "status": "Красный", "action": "текст", "reason": "причина"}},
  ...
]
"""

print("🧠 Отправляем запрос к LLM...")

# 4. Отправляем запрос к Ollama
response = requests.post(
    'http://localhost:11434/api/generate',
    json={
        "model": "mistral:7b-instruct-v0.3-q4_0",
        "prompt": SYSTEM_PROMPT + "\n\n" + prompt,
        "stream": False,
        "options": {
            "temperature": 0.1  # Низкая температура для предсказуемых ответов
        }
    },
    timeout=60
)

if response.status_code != 200:
    print(f"❌ Ошибка при запросе к Ollama: {response.status_code}")
    print(response.text)
    exit(1)

# 5. Парсим ответ
result_text = response.json()['response']
print(f"\n📝 Ответ LLM:\n{result_text}")

# Пробуем извлечь JSON из ответа
try:
    # Ищем JSON в ответе
    start = result_text.find('[')
    end = result_text.rfind(']') + 1
    if start != -1 and end != 0:
        json_str = result_text[start:end]
        decisions = json.loads(json_str)
        print(f"\n✅ Получено {len(decisions)} решений:")
        for d in decisions:
            print(f"  - Клиент {d['user_id']}: {d['status']} → {d['action']}")
    else:
        print("⚠️ Не удалось найти JSON в ответе")
        print(f"Полный ответ:\n{result_text}")
except json.JSONDecodeError as e:
    print(f"❌ Ошибка парсинга JSON: {e}")
    print(f"Ответ:\n{result_text}")