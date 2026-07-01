# Auth setup — Google OAuth + env vars (Track D, D.2)

Памятка по ручной настройке, которую нельзя сделать из кода: регистрация Google
OAuth и переменные окружения. Что делаю я (через браузер) и что руками ты —
помечено. Бэкенд **и фронт** D.2 уже готовы (фронт `static/auth_client.js` —
2026-06-22) и **без переменных работают как раньше** (один пользователь, без
логина) — настройка ниже включает мультиюзер.

> **Безопасность (правило проекта).** Секреты — только в env vars, НИКОГДА в код,
> чат, фронт, git. Секреты здесь: **Google Client Secret**, `service_role` key,
> `DATABASE_URL` (в нём пароль БД). Публичны (можно во фронт/доки): project ref,
> `SUPABASE_URL`, **anon key**. Перед `git push` — `git diff` на секреты.

---

## Фиксированные значения проекта

- **Project ref:** `ewarfrzaxiiqboaixbwq` (виден в URL дашборда — не секрет)
- **Supabase URL:** `https://ewarfrzaxiiqboaixbwq.supabase.co`
- **Google callback URL (Supabase):**
  `https://ewarfrzaxiiqboaixbwq.supabase.co/auth/v1/callback`
  ← это значение пойдёт в Google Console как «Authorized redirect URI».

---

## Шаг 1 — Google Cloud Console (руками ТЫ) ✅ сделано 2026-06-22

Туда я зайти не могу (твой Google-аккаунт). Бесплатно.

> **Статус (2026-06-22):** сделано по этой инструкции. Создан Web OAuth-клиент
> (проект `PreflopRange`, User type **External**, режим **Testing**, сам добавлен
> в **Test users**), Authorized redirect URI = callback Supabase (значение ниже).
> JSON с **Client ID** (публичный) + **Client Secret** (СЕКРЕТ) скачан, хранится
> у пользователя вне репозитория — в код/чат/git НЕ попадал. Триал Google Cloud
> закончился — на создание OAuth-клиента это не влияет (биллинг для auth не
> нужен). Дальше — Шаг 2 (Google-провайдер в Supabase) в новом чате: Client ID
> вводит ассистент, Client Secret пользователь вставляет сам в поле Supabase.

1. https://console.cloud.google.com → создай проект (напр. «PreflopRange»).
2. **APIs & Services → OAuth consent screen:**
   - User type: **External**.
   - App name: `PreflopRange`; support email: твой.
   - Scopes: достаточно дефолтных `openid`, `email`, `profile` (можно не
     добавлять вручную — Supabase запросит их сам).
   - **Для беты остаёмся в режиме «Testing»** и добавляем себя в **Test users**.
     В Testing **не нужны** страницы Terms/Privacy и верификация Google — экран
     согласия покажет «unverified», но для тебя/тестеров это ок. Публичный
     запуск (режим «Production» + верификация) потребует ToS/Privacy — это
     отдельная задача перед открытой бетой, не сейчас.
3. **APIs & Services → Credentials → Create credentials → OAuth client ID:**
   - Application type: **Web application**.
   - **Authorized redirect URIs** → добавь РОВНО:
     `https://ewarfrzaxiiqboaixbwq.supabase.co/auth/v1/callback`
   - (Authorized JavaScript origins можно оставить пустыми — поток идёт через
     callback Supabase, не напрямую из браузера в Google.)
   - Создать → получишь **Client ID** (публичный) и **Client Secret** (СЕКРЕТ).

## Шаг 2 — Включить Google в Supabase (Я веду + ТЫ вводишь секрет) ✅ сделано 2026-06-22

Authentication → Providers → Google. Я открою страницу и заполню Client ID;
**Client Secret вводишь ТЫ сам прямо в поле** (чтобы секрет не прошёл через чат),
затем Save. Либо включи провайдер целиком сам — это просто тумблер + два поля.

> **Статус (2026-06-22):** провайдер уже был включён и настроен (тумблер ON,
> Client ID `806350654586-…apps.googleusercontent.com` подтверждён пользователем
> как его, Client Secret заполнен, Callback URL = callback Supabase). Менять
> ничего не пришлось. Google-вход проверен вживую — работает; вход тем же Gmail
> Supabase **связал с email-аккаунтом** (тот же `user_id`), что и ожидалось.

## Шаг 3 — URL Configuration в Supabase (Я веду, не секрет) ✅ сделано 2026-06-22

Authentication → URL Configuration:
- **Site URL:** `https://prefloprange.org`
- **Redirect URLs** (Add URL): `https://prefloprange.org/**` и для локали
  `http://localhost:8000/**`.
Это куда Supabase возвращает после OAuth и куда ведут ссылки писем подтверждения.

> **Статус (2026-06-22):** оба Redirect URL на месте (`http://localhost:8000/**`
> и `https://prefloprange.org/**`). **Site URL временно оставлен
> `http://localhost:8000`** — так ссылка из письма-подтверждения возвращает на
> локаль для текущего теста. ⚠️ **Перед прод-выкаткой сменить Site URL на
> `https://prefloprange.org`**, иначе письма-подтверждения реальных юзеров будут
> вести на localhost. (Прод-Redirect URL уже в списке, на проде auth ещё выключен
> — переменных нет, см. Шаг 4 — поэтому риска сейчас нет.)

---

## Шаг 4 — Переменные окружения (руками ТЫ: Railway + локальный .env)

Где взять:
- `SUPABASE_URL` = `https://ewarfrzaxiiqboaixbwq.supabase.co` (не секрет) — Project
  Settings → API / Data API.
- `SUPABASE_ANON_KEY` = anon/**publishable** key `sb_publishable_…` (публичный,
  для фронта) — Project Settings → **API Keys**.
- `DATABASE_URL` = **Session pooler** connection string (СЕКРЕТ — в нём пароль) —
  **верхняя кнопка «Connect» → вкладка Direct → Session pooler** (в новом UI
  Supabase отдельного пункта «Database» в Project Settings БОЛЬШЕ НЕТ). Заменить
  `[YOUR-PASSWORD]` своим паролем БД (там же ссылка «Reset password», если забыт).

Куда:
- **Railway** → сервис → Variables: задать все три.
- **Локально** → `.env` (в `.gitignore`), см. `.env.example`.

> **Статус (2026-06-22):** локальный `.env` создан, все три заданы (`SUPABASE_URL`
> + publishable key + Session-pooler `DATABASE_URL` с реальным паролем). Прод на
> Railway переменные **ещё НЕ получил** (там auth выключен — как и задумано до
> выкатки). Для прода — задать те же три в Railway Variables вместе с фронтом.

> **Порядок важен:** как только задан `SUPABASE_URL`, защищённые эндпоинты
> начинают **требовать токен**. Поэтому переменные включаем **вместе** с выкаткой
> фронта-логина. До этого момента не задавай `SUPABASE_URL` на проде, иначе
> текущий UI без токена получит 401.

### Ловушки локального запуска (dev на macOS) — встретились 2026-06-22
- **SSL-сертификаты Python (P-040).** Python с python.org не качает JWKS →
  `SSL: CERTIFICATE_VERIFY_FAILED` → логин на фронте проходит, но все защищённые
  `/api/*` дают `401 "Invalid or expired token"` (токен при этом валиден).
  Лечение: `/Applications/Python\ 3.13/Install\ Certificates.command`, перезапуск.
  На Linux/Railway не возникает (сертификаты системные).
- **Старый сервер на :8000 (P-041).** После правок новые маршруты дают 404, а
  старые работают → висит старый процесс. `lsof -ti :8000 | xargs kill -9`, затем
  `python3 main.py`. Признак: 404 на НОВОМ маршруте (а не «connection refused»).
- Нужны зависимости: `pip3 install -r requirements.txt` (для `python-dotenv`,
  `psycopg`, `PyJWT[crypto]`). Без `python-dotenv` `.env` не загрузится и auth не
  включится; без `PyJWT[crypto]` токен не проверить.

---

## Что считается «готово» для D.2 — ✅ закрыто ЛОКАЛЬНО 2026-06-22

- ✅ Google-провайдер включён в Supabase (Client ID + Secret).
- ✅ URL Configuration заполнен (оба Redirect URL; Site URL = localhost на время
  теста — сменить на прод при выкатке).
- ✅ Локально заданы `SUPABASE_URL` + `SUPABASE_ANON_KEY` + `DATABASE_URL`.
- ✅ Фронт-логин работает; регистрация email с подтверждением + вход ✅,
  «Continue with Google» ✅ (тем же Gmail → связался с email-аккаунтом); токен
  (ES256) принимается бэкендом; данные пишутся в `answers` под реальным `user_id`
  и изолированы (проверено в БД: все строки помечены `user_id`, чтение фильтрует
  по нему, RLS — бэкстоп).

**Остаётся для прод-беты (НЕ в этом чате):** задать те же 3 переменные в Railway
Variables вместе с выкаткой; сменить Site URL на `https://prefloprange.org`;
(опц.) включить публичный режим Google consent screen перед открытой бетой.
