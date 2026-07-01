# Poker Trainer — Визуальная карта архитектуры

Создано: 2026-06-17. Это **визуализация** `docs/architecture.md` (слои §2 + инвентарь §3 +
чек-лист уборки §6) в виде одной Mermaid-диаграммы. Парные доки: `CLAUDE.md` (решения),
`roadmap.md` (треки), `problems.md` (баги).

Связи импортов сверены с кодом 2026-06-17 (`main.py`, `srs_api.py`, `postflop_engine.py`,
`index.html`): `storage.js` не подключён → мёртвый; `srs_api` импортит только `srs` (не
`srs_fsrs`) → FSRS dev-only; `postflop_engine` лениво тянет `hand_classify` → заморожено, но
живое; `hh_parser` никто не импортит → standalone.

> **Посмотреть крупно:** открой `docs/architecture_diagram.html` двойным кликом — браузерный
> вьюер с зумом (колесо мыши / ±), перетаскиванием и кнопкой «Скачать SVG». Диаграмма в нём
> побайтово та же, что в блоке ниже.

---

## Легенда

| Цвет | Статус | Значит |
|---|---|---|
| 🟢 зелёный | **живое** | меняется, в проде, под фокусом (префлоп) |
| 🔵 синий | **заморожено** ❄ | постфлоп — в репо, но не трогаем (CLAUDE.md, roadmap) |
| 🟡 жёлтый | **dev-only** 🧪 | эксперимент, НЕ подключён к API (`srs_fsrs`, `tools/fsrs_*`) |
| 🔴 красный | **мёртвое** 🗑 | удалить — рантайм не заметит |
| ⚪ серый | данные / инструменты | JSON-стейт, GTOW-импортёры, парсер |

**Правило стрелок:** зависимости идут строго вниз (верхний слой знает про нижний, не наоборот).
Это и есть признак здоровой слоёной архитектуры — `range_engine`/`srs`/`equity` ни от чего внутри
проекта не зависят (ядро с 0 импортов), всё остальное зависит от них.

---

## Диаграмма

```mermaid
flowchart TB
    %% ===================== СЛОЙ 1: Браузер / фронтенд =====================
    subgraph L1["🖥 Браузер · static/ (vanilla JS, без сборщика)"]
        direction TB
        IDX["index.html<br/>вкладки: Visualizer · Editor · Practice · Learn · Postflop"]
        JS_live["cards.js · chips.js · drill.js · learn.js<br/>visualizer.js · editor.js · matrix_tip.js · mobile.js"]
        JS_pf["postflop.js ❄"]
        JS_dead["storage.js 🗑 МЁРТВОЕ — не грузится в index.html"]
    end

    %% ===================== СЛОЙ 2: Composition root =====================
    subgraph L2["⚙ Composition root"]
        MAIN["main.py<br/>include_router + /api/drill /ranges /stats /history + сервит UI"]
    end

    %% ===================== СЛОЙ 3: API-роутеры =====================
    subgraph L3["🔌 API-роутеры (один модуль — один роутер)"]
        direction LR
        API_srs["srs_api.py<br/>/api/srs/* (Learn)"]
        API_eq["equity_api.py ❄<br/>/api/equity/*"]
        API_pf["postflop_api.py ❄<br/>/api/postflop/*"]
    end

    %% ===================== СЛОЙ 4: Доменное ядро =====================
    subgraph L4["🧠 Доменное ядро"]
        direction TB
        subgraph CORE_LIVE["живое ядро · 0 проектных импортов"]
            direction LR
            RE["range_engine.py<br/>load/normalize · get_ev · get_*_range"]
            SRS["srs.py<br/>SM-2 · модель Card"]
        end
        DE["drill_engine.py<br/>генерация спотов · грейдинг"]
        FSRS["srs_fsrs.py 🧪 dev-only<br/>FSRS-lite параллельно SM-2 · НЕ в srs_api"]
        subgraph CORE_FROZEN["заморожено · постфлоп ❄"]
            direction LR
            EQ["equity.py ❄<br/>Монте-Карло (3× сверен)"]
            DEC["decision.py ❄<br/>пот-оддсы"]
            PFE["postflop_engine.py ❄<br/>споты · типы оппонентов"]
            HC["hand_classify.py ❄<br/>lazy import из postflop_engine"]
        end
    end

    %% ===================== СЛОЙ 5: Данные =====================
    subgraph L5["💾 Данные (БД нет — только JSON-файлы)"]
        direction LR
        DJSON["data/*.json<br/>range packs + блок ev"]
        SRSST["srs_state/*.srs.json<br/>дек на каждый пак"]
        STATS["stats.json"]
        HIST["history.json"]
    end

    %% ===================== Вне рантайма =====================
    subgraph SIDE["🛠 Вне рантайма (инструменты и фундамент)"]
        direction TB
        GTOW["tools/gtow_*.py<br/>импорт диапазонов из GTOW → паки"]
        HH["hh_parser.py<br/>standalone · фундамент Milestone 3"]
        FSRST["tools/fsrs_*.py 🧪<br/>A/B-эксперименты FSRS"]
    end

    %% ===================== Уборка дерева (Track C.1) =====================
    subgraph CLEAN["🧹 Уборка дерева · Track C.1 (не код — раздувает репозиторий)"]
        direction TB
        CL1["🗑 удалить сейчас:<br/>storage.js · zi7EnBeQ · dist/ · lead-finder.skill<br/>__pycache__ · NL10_GTOW_…/ (в корне) · _smoke_limit.json.disabled"]
        CL2["🗑 когда доверишься git:<br/>cards/_backup_* · _original · _tiles_* (~265 файлов, ~24МБ)<br/>data/*.bak (~30) · Firefly_*.png · *.pdf → docs/"]
        CL3["📦 изолировать, НЕ удалять:<br/>postflop → postflop/ · srs_fsrs+tools/fsrs_* → fsrs_experiment/<br/>hh_parser → scripts/ · test_*.py → tests/"]
    end

    %% ===================== Связи =====================
    IDX -->|HTTP| MAIN
    MAIN -->|include_router| API_srs
    MAIN -->|include_router| API_eq
    MAIN -->|include_router| API_pf
    MAIN -->|imports| RE
    MAIN -->|imports| DE
    API_srs -->|imports| SRS
    API_eq -->|imports| EQ
    API_pf -->|imports| PFE
    DE -->|imports| RE
    DEC -->|imports| EQ
    PFE -->|imports| EQ
    PFE -->|imports| DEC
    PFE -.->|lazy| HC
    RE -->|reads| DJSON
    SRS -->|reads/writes| SRSST
    MAIN -->|reads/writes| STATS
    MAIN -->|reads/writes| HIST
    GTOW -->|writes| DJSON
    FSRST -.->|imports| FSRS

    %% ===================== Статус-классы =====================
    classDef live fill:#16623a,stroke:#37a86a,color:#eafff2
    classDef frozen fill:#1f3a5f,stroke:#4d82c0,color:#dbe9fb
    classDef dev fill:#6e5410,stroke:#d3b04a,color:#fbeec0
    classDef dead fill:#5a1414,stroke:#d05a4a,color:#ffd9d2
    classDef data fill:#2a2d2f,stroke:#7a8087,color:#e2e6ea
    classDef tool fill:#34383b,stroke:#8a9097,color:#e2e6ea

    class IDX,JS_live,MAIN,API_srs,RE,SRS,DE live
    class JS_pf,API_eq,API_pf,EQ,DEC,PFE,HC frozen
    class FSRS,FSRST,CL3 dev
    class JS_dead,CL1,CL2 dead
    class DJSON,SRSST,STATS,HIST data
    class GTOW,HH tool
```

---

## Как читать

- **Пять слоёв сверху вниз** — это весь рантайм: ~13 Python-модулей + 8 живых JS. Маленький,
  аккуратный проект; «огромным» дерево делают данные/бэкапы/дампы, а не код (см. `architecture.md` §1).
- **Зелёное** — то, что реально меняется (префлоп: Drill, Learn, Visualizer, Editor + ядро
  `range_engine`/`drill_engine`/`srs`). Сюда направлен фокус.
- **Синее ❄** — постфлоп целиком заморожен: остаётся в репо, подключён в `main`, но не трогается до
  стабилизации префлопа. `hand_classify` тоже синий — он НЕ мёртвый, его лениво импортит
  `postflop_engine` (удаление сломает постфлоп при разморозке — частая ошибка старых заметок).
- **Жёлтое 🧪** — FSRS-эксперимент: `srs_fsrs` существует параллельно SM-2 и сознательно НЕ
  подключён к `srs_api` (решение #11). Живой Learn остаётся на SM-2.
- **Красное 🗑** — `storage.js` единственный реально мёртвый код в рантайме.
- **Нижний блок 🧹** — это уборка *дерева*, а не кода: гигиена файлов из `architecture.md` §6.
  Делать маленькими партиями с прогоном тестов между ними; постфлоп и FSRS — изолировать в
  отдельные папки, не удалять.

## Что это даёт для «оптимизации»

Архитектура здоровая — переписывать нечего. Рычаги ровно три, по убыванию пользы/риска:

1. **Сгруппировать по роли** (нулевой риск): `tests/`, `app/`, изоляция `postflop/` и
   `fsrs_experiment/`. Перенос Python трогает импорты и `Dockerfile` → отдельной подзадачей с тестами.
2. **Выкинуть мусор дерева** (красный/серый блок) — освоить git как бэкап, перестать держать ручные
   снапшоты колоды и десятки `.bak`.
3. **Подрезать `CLAUDE.md`** — журнал импортов GTOW-паков (решение #13) увести в `roadmap.md`,
   принципы оставить. Always-on файл должен быть коротким.
