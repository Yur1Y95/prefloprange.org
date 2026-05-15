#!/bin/bash
cd "$(dirname "$0")"
echo "🛑 Останавливаю NLH Trainer..."
docker-compose down
echo "✅ Сервер остановлен"
