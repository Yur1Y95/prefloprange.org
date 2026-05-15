#!/bin/bash

# Переходим в папку проекта (скрипт лежит рядом с docker-compose.yml)
cd "$(dirname "$0")"

echo "🃏 Запуск NLH Trainer..."
echo ""

# Проверяем что Docker запущен
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker не запущен. Открываю Docker Desktop..."
    open -a Docker
    echo "⏳ Жду пока Docker запустится..."
    while ! docker info > /dev/null 2>&1; do
        sleep 2
    done
    echo "✅ Docker готов"
fi

# Останавливаем старый контейнер если есть
echo "🔄 Останавливаю старый контейнер..."
docker-compose down 2>/dev/null

# Пересобираем и запускаем
echo "🔨 Пересобираю образ..."
docker-compose build

echo ""
echo "🚀 Запускаю контейнер..."
docker-compose up -d

echo ""
echo "✅ Готово! Открываю браузер..."
sleep 2
open http://localhost:8000

echo ""
echo "📋 Логи (Ctrl+C чтобы закрыть это окно, сервер продолжит работать):"
echo "   Для остановки сервера запусти stop.command"
echo ""
docker-compose logs -f
