# Poker Trainer — Доска треков

Обновлено: 2026-06-19. Это **визуальная карта всех треков и задач** проекта — блок-схемами,
которые GitHub рисует сам (Mermaid). Источник истины по сути работы остаётся `docs/roadmap.md`;
эта доска — его «вид сверху» для отслеживания статусов. Парные доки: `CLAUDE.md` (решения),
`docs/problems.md` (баги), `docs/design.md` (визуал), `docs/architecture_diagram.md` (карта кода).

> **Как обновлять.** Когда статус подзадачи меняется — поменяй её эмодзи в подписи узла
> (✅/🔄/⬜/🟦/❄️) и её строку `class …` в конце нужного блока. Держи в синхроне с `roadmap.md`.

---

## Легенда статусов

| Цвет | Маркер | Статус | Значит |
|---|---|---|---|
| 🟢 зелёный | ✅ | **done** | сделано, в коде/проде |
| 🟡 золотой | 🔄 | **в работе** | активно / частично сделано / рутина |
| ⚪ серый | ⬜ | **не начато** | запланировано, ещё не начинали |
| 🔵 синий | 🟦 | **отложено** | сознательно отложено, путь зафиксирован |
| 🟣 фиолетовый | ❄️ | **заморожено** | в репо, но не трогаем (постфлоп, анализатор) |

**Текущий фокус: только префлоп.** Постфлоп заморожен целиком (код в репо, не трогается).

---

## Обзор — треки A–F + фич-хвост

```mermaid
flowchart TB
    ROOT["🎯 Poker Trainer — фокус: только префлоп<br/>постфлоп заморожен ❄️"]
    ROOT --> SA
    ROOT --> SB
    ROOT --> SC
    ROOT --> SD
    ROOT --> SE
    ROOT --> STF
    ROOT --> SF

    SA["Track A · Логика и SRS — 🔄 в работе<br/>ближайший шаг: A.1 history-логирование"]
    SB["Track B · Визуал и мобилка — 🔄 в работе<br/>ближайший: B.6 редизайн UI + интеграция фишек"]
    SC["Track C · Техдолг и чистота — 🔄 по ходу<br/>ближайший: C.1 уборка мёртвого кода"]
    SD["Track D · Веб-экспансия и бета — 🔄 в работе<br/>ближайший: D.1 Postgres на Supabase"]
    SE["Track E · Мультиформат — 🔄 дизайн готов<br/>HU + 8/9-max + 200bb · спека multiformat.md"]
    STF["Track F · Портфолио и поиск работы — 🔄 дизайн готов<br/>backend · релокация · репо+профиль+резюме (англ.)"]
    SF["Фич-хвост · префлоп-данные и споты — 🔄<br/>GTOW-паки NL10–NL1000 готовы · далее iso / vs_limp / squeeze"]

    classDef root fill:#0f1512,stroke:#c9a84c,color:#e8c97a
    classDef active fill:#6e5410,stroke:#d3b04a,color:#fbeec0
    class ROOT root
    class SA,SB,SC,SD,SE,STF,SF active
```

---

## Track A — Логика и алгоритм SRS

Learn Mode MVP закрыт, SM-2-движок работает. UX-улучшения сделаны; дальше — накопление данных и
калибровка алгоритма по ним (не наугад).

```mermaid
flowchart TB
    subgraph SGA["Track A · Логика и алгоритм SRS — 🔄"]
        direction TB
        subgraph A_UX["Learn UX — готово ✅"]
            direction LR
            A0["A.0 · убрана Easy, добавлена «Показать ответ» ✅<br/>2026-06-01"]
            A01["A.0.1 · шафл новых карт + лимит/день + фикс выпадашки ✅<br/>2026-06-15"]
            A5["A.5 · Auto-Next в Learn ✅<br/>2026-06-15"]
        end
        subgraph A_ALG["Алгоритм — накопление и калибровка"]
            direction LR
            A1["A.1 · history-логирование в Card 🔄<br/>модель done · показ по дням → веб-статблок"]
            A2["A.2 · накопление практики 2–3 недели ⬜<br/>пассивно, в фоне"]
            A3["A.3 · калибровка SM-2-констант 🟦<br/>после ≥2 недель данных из A.2"]
            A4["A.4 · FSRS-апгрейд 🟦<br/>каркас srs_fsrs собран, НЕ подключён к API"]
        end
        A1 --> A2 --> A3 --> A4
    end

    classDef done fill:#16623a,stroke:#37a86a,color:#eafff2
    classDef active fill:#6e5410,stroke:#d3b04a,color:#fbeec0
    classDef todo fill:#2a2d2f,stroke:#7a8087,color:#e2e6ea
    classDef defer fill:#1f3a5f,stroke:#4d82c0,color:#dbe9fb
    class A0,A01,A5 done
    class A1 active
    class A2 todo
    class A3,A4 defer
```

---

## Track B — Визуал и мобильная адаптация

Стол, карты, фишки, банк, мобилка — сделаны. Открыто: интеграция Higgsfield-фишек, редизайн всего
интерфейса (B.6, новое), палитра матрицы и editor-UX. Принцип: роскошь в столе/картах, строгость
вокруг (см. `design.md`).

```mermaid
flowchart TB
    subgraph SGB["Track B · Визуал и мобильная адаптация — 🔄"]
        direction TB
        subgraph B_TABLE["Стол и фелт — готово ✅"]
            direction LR
            B0["B.0 · собрать референсы ✅"]
            B1["B.1 · десктоп: стол, рассадка, состояние карт ✅<br/>2026-05-29"]
            Bpolish["B.1-polish · фелт: объём, чёрный борт ✅<br/>2026-05-29"]
            Btableart["B.1-table-art · растровый стол PNG ✅<br/>Higgsfield sage, 2026-06-17"]
        end
        subgraph B_CARDS["Карты и фишки"]
            direction LR
            Bcards["B.1-cards · карты: 4-цвет embossed-плитка ✅<br/>2026-06-14"]
            Bpot["B.1-pot · банк: пилюля Total Pot ✅<br/>2026-05-31"]
            Bggref["B.1-gg-ref · веер карт + масштаб фишек ✅<br/>2026-05-31"]
            Blegacy["B.1-legacy · фишки: казино-номиналы ✅<br/>2026-05-30"]
            Bchips3d["B.1-chips-3d · casino-3D рендер фишек ✅<br/>2026-06-15"]
            Bchipsart["B.1-chips-art · Higgsfield clay-фишки 🔄<br/>ассеты + preview одобрены · интеграция отдельным чатом"]
        end
        subgraph B_MATRIX["Матрица и анимации"]
            direction LR
            B3["B.3 · editor-матрица: структура портирована 🔄<br/>палитра — открытый вопрос (design §9.1)"]
            B2["B.2 · десктоп: анимации и микро-полиш ⬜"]
        end
        subgraph B_MOBILE["Мобилка"]
            B4["B.4 · мобильная адаптация ✅<br/>Drill / Learn / Visualizer, 2026-05-29"]
        end
        subgraph B_REDESIGN["Редизайн и editor-UX — не начато"]
            direction LR
            B6["B.6 · редизайн интерфейса через Higgsfield ⬜<br/>NEW, решение 2026-06-17"]
            B5["B.5 · editor UX (P-012…P-017) ⬜<br/>якорь P-016: тулбар вплотную к матрице"]
        end
        subgraph B_FUTURE["На перспективу 🟦"]
            direction LR
            Bfut1["B-future · цвет стола (эргономика глаз) 🟦"]
            Bfut2["B-future · центр фелта: логотип / реклама 🟦<br/>зависит от Track D"]
        end
    end

    classDef done fill:#16623a,stroke:#37a86a,color:#eafff2
    classDef active fill:#6e5410,stroke:#d3b04a,color:#fbeec0
    classDef todo fill:#2a2d2f,stroke:#7a8087,color:#e2e6ea
    classDef defer fill:#1f3a5f,stroke:#4d82c0,color:#dbe9fb
    class B0,B1,Bpolish,Btableart,Bcards,Bpot,Bggref,Blegacy,Bchips3d,B4 done
    class Bchipsart,B3 active
    class B2,B6,B5 todo
    class Bfut1,Bfut2 defer
```

---

## Track C — Техдолг и чистота

Архитектура здоровая (чистые слои), задача — гигиена дерева, а не переписывание. Дизайн уборки
готов (`architecture.md`), исполнять маленькими партиями с прогоном тестов.

```mermaid
flowchart TB
    subgraph SGC["Track C · Техдолг и чистота — 🔄 по ходу"]
        direction TB
        C1["C.1 · уборка мёртвого кода 🔄<br/>дизайн готов (architecture.md) · исполнять партиями + тесты"]
        C2["C.2 · журнал багов в problems.md 🔄<br/>рутина: баг → P-NNN → resolved"]
        C3["C.3 · документация консистентна с кодом 🔄<br/>рутина: сверять CLAUDE.md с реальностью"]
    end

    classDef active fill:#6e5410,stroke:#d3b04a,color:#fbeec0
    class C1,C2,C3 active
```

---

## Track D — Веб-экспансия и бета

Прод на Railway, авто-деплой из GitHub на `prefloprange.org`. Фундамент готов. Дальше — строгая
последовательность к бете; **платежи делаем последними**. Хранилище + авторизация = один сервис
**Supabase** (managed Postgres + Auth), решение 2026-06-17.

```mermaid
flowchart TB
    subgraph SGD["Track D · Веб-экспансия и бета — 🔄"]
        direction TB
        subgraph D_DONE["Фундамент — готово ✅"]
            direction LR
            D0["D.0 · открытые вопросы ✅<br/>Railway · multi-user, 2026-05-30"]
            D11["D.1.1 · GitHub + SSH + гигиена репо ✅"]
            D12["D.1.2 · деплой-здоровье + консоль ✅"]
        end
        subgraph D_SEQ["Последовательность к бете — платежи последними"]
            direction TB
            DE0["Этап 0 = D.1 · Postgres + схема на Supabase ⬜<br/>журнал answers · cards (SRS) · goals"]
            DE1["Этап 1 = D.2 · Auth — Supabase, email + Google ⬜"]
            DE2["Этап 2 · личный кабинет: статистика и прогресс ⬜"]
            DE3["Этап 3 = D.3 / D.4 · бета: тестеры + фидбек ⬜<br/>пока бесплатно"]
            DE4["Этап 4 = D.5 · Freemium + платежи ⬜<br/>NEW, один путь первым"]
            DE0 --> DE1 --> DE2 --> DE3 --> DE4
        end
    end

    classDef done fill:#16623a,stroke:#37a86a,color:#eafff2
    classDef todo fill:#2a2d2f,stroke:#7a8087,color:#e2e6ea
    class D0,D11,D12 done
    class DE0,DE1,DE2,DE3,DE4 todo
```

---

## Track E — Мультиформат: размеры столов + глубина

Дизайн готов (2026-06-19, спека `docs/multiformat.md`). Размер стола и глубина — свойства пака
(`meta` + `config.positions`); ветка = новые паки + точечные правки, не переписывание движков.
Анте вне ветки. Узлов на пак @100bb: HU 4 · 6-max 50 · 8-max 91 · 9-max 116.

```mermaid
flowchart TB
    subgraph SGE["Track E · Мультиформат — 🔄 дизайн готов"]
        direction TB
        E0["E.0 · дизайн ✅ 2026-06-19<br/>multiformat.md · Track E · CLAUDE #19 · P-037"]
        E1["E.1 · heads-up @ 100bb ⬜<br/>4 узла · координаты 2-max · прогон нового типа стола"]
        E2["E.2 · алиас позиций под размер стола ⬜<br/>снять мину HJ→MP (P-037) · фундамент 8/9-max"]
        E3["E.3 · 8-max @ 100bb ⬜ — ~91 узел"]
        E4["E.4 · 9-max @ 100bb ⬜ — ~116 узлов"]
        E5["E.5 · 200bb + спот vs_5bet ⬜<br/>аддитивно, зеркало vs_4bet"]
        E0 --> E1 --> E2 --> E3 --> E4 --> E5
    end

    classDef done fill:#16623a,stroke:#37a86a,color:#eafff2
    classDef todo fill:#2a2d2f,stroke:#7a8087,color:#e2e6ea
    class E0 done
    class E1,E2,E3,E4,E5 todo
```

---

## Track F — Портфолио и поиск работы

Технически проект сильный (тесты, equity-движок, чистая архитектура, data-пайплайн), но
презентационно невидим: нет README/LICENSE/демо/CI, доки на русском. Трек — про подачу под
backend-роль и релокацию (всё на английском), не про фичи. Опирается на Track D (демо = D.3,
БД-пробел закрывает D.1). Код не трогаем.

```mermaid
flowchart TB
    subgraph SGTF["Track F · Портфолио и поиск работы — 🔄 дизайн готов"]
        direction TB
        F0["F.0 · дизайн ✅ 2026-06-19<br/>Track F · доска · framing · аудит · MIT"]
        F1["F.1 · README.md (English) ⬜<br/>hook · стек · архитектура · how-it-works · тесты · LICENSE"]
        F2["F.2 · гигиена репо + GitHub-поверхность ⬜<br/>topics · pin · security-pass diff · конвенция коммитов"]
        F3["F.3 · скриншоты / демо-GIF ⬜<br/>тренажёр · визуализатор · матрица · мобилка"]
        F5["F.5 · живое демо (= D.3) ⬜<br/>Railway/Render free-tier · ссылка в README"]
        F4["F.4 · CI (GitHub Actions) ⬜<br/>stdlib-тесты на push · зелёный badge"]
        F6["F.6 · GitHub profile README ⬜<br/>кто · backend-навыки · ссылки · relocation/remote"]
        F7["F.7 · резюме/CV (English, 1 стр.) ⬜<br/>проект как кейс · измеримые буллеты"]
        F8["F.8 · внешний обзор ⬜<br/>глазами рекрутера · ссылки · секреты · английский"]
        F0 --> F1 --> F2 --> F3 --> F5 --> F4 --> F6 --> F7 --> F8
    end

    classDef done fill:#16623a,stroke:#37a86a,color:#eafff2
    classDef todo fill:#2a2d2f,stroke:#7a8087,color:#e2e6ea
    class F0 done
    class F1,F2,F3,F4,F5,F6,F7,F8 todo
```

---

## Фич-хвост — параллельная работа (в основном префлоп-данные)

Это не отдельный «трек» из roadmap, а параллельная фич-работа: данные диапазонов из GTOW и
расширение спот-схемы префлопа. Заливка GTOW-паков по лимитам в основном закрыта; остаются iso
(не из GTOW), vs_limp и доборы squeeze.

```mermaid
flowchart TB
    subgraph SGF["Фич-хвост · префлоп-данные и споты"]
        direction TB
        subgraph F_DATA["GTOW-данные — готово ✅"]
            direction LR
            FP["7 GTOW-паков: NL10 · NL25 · NL50 · NL100 · NL200 · NL500 · NL1000 ✅<br/>RFI · vs_RFI · vs_3bet · vs_4bet — частоты + EV"]
            FEV["Drill GTO-EV: Этап 1 (код) ✅ · Этап 2 (данные RFI) ✅"]
        end
        subgraph F_SPOTS["Спот-схема префлопа"]
            direction LR
            FS4b["vs_4bet ✅ — все слои, 2026-06-05"]
            FSiso["iso (изолейт) 🔄<br/>схема ✅ · данные из базы рук ⬜"]
            FSsq["squeeze / мультивей 🔄<br/>Этап 0/1/2a ✅ · тренажёр 2b/3 ⬜"]
            FSvsq["vs_squeeze 🔄<br/>парсер ✅ · движок и фронт ⬜"]
            FS3b["Drill: кнопки vs_3bet allin/4bet/call/fold ⬜"]
            FSlimp["vs_limp / complete ⬜ — не начат"]
        end
        subgraph F_DEFER["Отложено — путь зафиксирован 🟦"]
            direction LR
            FDsize["размеры открытий (микс сайзов) 🟦<br/>глубина 200bb → Track E"]
            FDhu["спины: 3-max + короткий стек + анте 🟦<br/>heads-up → Track E"]
            FDev3["EV Этап 3: per-action EV + EV минусовых рук 🟦"]
        end
        subgraph F_FROZEN["Заморожено ❄️"]
            direction LR
            FZpf["постфлоп: терн / ривер / vulnerability ❄️"]
            FZan["анализатор раздач — Milestone 3 ❄️"]
            FZrp["реплеер раздач ❄️"]
        end
    end

    classDef done fill:#16623a,stroke:#37a86a,color:#eafff2
    classDef active fill:#6e5410,stroke:#d3b04a,color:#fbeec0
    classDef defer fill:#1f3a5f,stroke:#4d82c0,color:#dbe9fb
    classDef frozen fill:#3a1f4f,stroke:#9a5fc0,color:#f0dcff
    class FP,FEV,FS4b done
    class FSiso,FSsq,FSvsq,FS3b,FSlimp active
    class FDsize,FDhu,FDev3 defer
    class FZpf,FZan,FZrp frozen
```

---

## Сводка по трекам

| Трек | Тема | Статус | Ближайший шаг |
|---|---|---|---|
| **A** | Логика и алгоритм SRS | 🔄 в работе | A.1 — history-логирование (показ по дням → веб) |
| **B** | Визуал + мобильная адаптация | 🔄 в работе | B.6 редизайн UI / интеграция Higgsfield-фишек |
| **C** | Техдолг и чистота | 🔄 по ходу | C.1 — уборка мёртвого кода (партиями) |
| **D** | Веб-экспансия и бета | 🔄 в работе | D.1 — Postgres + схема на Supabase |
| **E** | Мультиформат: столы + глубина | 🔄 дизайн готов | E.1 — heads-up @ 100bb (`multiformat.md`) |
| **F** | Портфолио и поиск работы | 🔄 дизайн готов | F.1 — README (English) + LICENSE |
| **Фич-хвост** | Префлоп-данные и споты | 🔄 | iso (из базы рук), vs_limp, доборы squeeze |
