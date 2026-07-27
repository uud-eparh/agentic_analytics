-- Создаем базу данных
CREATE DATABASE IF NOT EXISTS analytics;

-- Переключаемся на неё
USE analytics;

-- Таблица транзакций
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id UInt32,
    user_id UInt32,
    amount Float64,
    status String,
    comment String,
    created_at DateTime
) ENGINE = MergeTree()
ORDER BY (created_at)
SETTINGS index_granularity = 8192;

-- Небольшой тестовый набор данных
INSERT INTO transactions VALUES 
(1, 101, 150.50, 'success', '', now()),
(2, 102, 2500.00, 'failed', 'Оплата не прошла, карта отклонена', now()),
(3, 101, 300.75, 'success', '', now() - INTERVAL 1 DAY),
(4, 103, 4500.00, 'refund', 'Клиент вернул товар, не подошел размер', now() - INTERVAL 2 DAY),
(5, 104, 120.00, 'failed', 'Таймаут оплаты', now() - INTERVAL 1 HOUR),
(6, 102, 600.00, 'chargeback', 'Клиент оспорил транзакцию в банке', now() - INTERVAL 3 DAY);