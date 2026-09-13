# Favorable Soil

Веб-приложение для оценки сельскохозяйственных участков по спутниковым данным:
карта плодородия, мониторинг зелёности, аномалии растительности, покров земли,
застройка и её динамика, подбор культур по почве и погоде.

**Стек:** Django 5.2 + DRF (API), vanilla JS + Leaflet + Vite (фронтенд),
PostgreSQL, OpenCV/NumPy для растров.

**Где работает:** фронтенд на Vercel, бэкенд в контейнере на Railway
(`ilm-production.up.railway.app`), база данных Neon PostgreSQL. Все запросы
`/api/*` с сайта проксируются на Railway, поэтому для браузера это один домен.

---

## Источники данных

Все источники бесплатны и не требуют ключей, аккаунтов или регистрации.

| Показатель | Откуда берётся | Разрешение |
|---|---|---|
| NDVI, стадия роста | Sentinel-2 L2A через [Microsoft Planetary Computer](https://planetarycomputer.microsoft.com) | 10 м, снимок с датой |
| Влажность покрова (NDMI) | Sentinel-2, каналы B08/B11, та же сцена | 10–20 м |
| Отклонение от нормы | NDVI того же календарного окна за 2 прошлых года | 10 м |
| Плодородие по площади | Пик и среднее NDVI за 3 сезона × оценка почвы SoilGrids, маска WorldCover, уклон DEM | 10 м |
| Классы покрова: вода, застройка, пашня, деревья | [ESA WorldCover](https://esa-worldcover.org) 2020/2021 через Planetary Computer | 10 м |
| Контуры зданий | OpenStreetMap через Overpass (области до 12 км²) | по контуру |
| Динамика застройки | WorldCover 2020 → 2021, класс «застройка» | 10 м |
| Уклон рельефа | Copernicus GLO-90 через Open-Meteo Elevation | 90 м |
| pH, органический углерод, ЁКО, текстура с диапазоном Q5–Q95 | [ISRIC SoilGrids v2.0](https://soilgrids.org), слой 0–5 см | 250 м |
| Доступный азот, обменный калий, фосфор | Выведены из SoilGrids задокументированными правилами | 250 м |
| Влажность почвы | Полевая влагоёмкость + осадки за 7 дней | 250 м |
| Погода | [Open-Meteo](https://open-meteo.com) | точка |
| Границы участков | OpenStreetMap через [Overpass](https://overpass-api.de) | по контуру |
| Аномалии растительности | Отклонение NDVI от медианы поля (> 2 MAD) внутри пашни по WorldCover | 10 м |

Каждое значение химии почвы несёт `source`: `measured` (пришло от SoilGrids
как есть), `derived` (выведено правилом) или `unavailable`. Сервис недоступен →
поле равно `null`, а не выдуманному числу.

### Как считается плодородие

Один снимок NDVI говорит, насколько зелёно поле сегодня, а не насколько оно
плодородно: пар на плодородной земле выглядит «голой почвой». Поэтому карта
складывается из четырёх слоёв, и каждый назван в ответе (`components`):

1. **Продуктивность**, вес 65 %: попиксельный пик и среднее NDVI за
   вегетационные сезоны (апрель–сентябрь) трёх последних лет, до 18 ясных сцен.
2. **Почва**, вес 35 %: pH, органический углерод, ЁКО и текстура из SoilGrids,
   сведённые в оценку 0–1 (`soil_quality_score`). Если SoilGrids для точки пуст
   (города, вода), индекс строится по одной продуктивности и ответ это сообщает.
3. **Покров**: вода, застройка, снег по WorldCover исключаются из оценки.
4. **Уклон**: больше 15 % по Copernicus GLO-90 считается непригодным.

Холодный расчёт занимает 30–50 секунд, результат кешируется на 7 дней. Если
сезонных снимков меньше трёх, используется последняя одиночная сцена, затем
ExG по RGB-подложке; `method` в ответе называет, что именно сработало.

**Вид сорняка по спутнику не определяется.** Эндпоинт `/api/weeds/detect/`
отмечает участки, где NDVI заметно отличается от медианы поля, и говорит об
этом в `note`. Для видовой идентификации нужен осмотр или фото с земли.

### Офсет отражения Sentinel-2

С версии обработки 04.00 продукты L2A содержат `BOA_ADD_OFFSET = -1000`.
В NDVI офсет сокращается в числителе, но не в знаменателе. Замер по одному полю
под Ташкентом: без офсета NDVI 0.333 («вегетация»), с офсетом 0.494
(«цветение»). Код применяет офсет только к сценам, чья версия обработки этого
требует, и тесты фиксируют оба случая.

### Фолбэки

Если Planetary Computer недоступен или область закрыта облаками, анализ
переключается на индекс ExG по RGB-подложке, грубее и без даты съёмки. В ответе
тогда `index_type: "ExG"`. Принудительно включается `DISABLE_SENTINEL=true`.

Границы участков берутся из OpenStreetMap, то есть из того, что размечено
людьми. В Европе покрытие плотное, вокруг Ташкента может не быть ничего даже
на 8 км. Если ничего не размечено, эндпоинт отвечает 404, а не выдуманным
прямоугольником.

---

## Быстрый старт локально

```bash
git clone https://github.com/ktoevich/ilm.git
cd ilm

python -m venv venv && source venv/bin/activate    # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp backend/.env.example backend/.env
cd backend
python manage.py migrate
python manage.py loaddata api/fixtures/initial_data.json
python manage.py runserver                          # http://127.0.0.1:8000
```

В другом терминале:

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173, запросы к /api проксируются на :8000
```

Значений из `.env.example` достаточно: SQLite, `DEBUG=True`, кеш в памяти.
Если в `.env` задать `DATABASE_URL`, локальный сервер будет работать с этой
базой, поэтому строку боевой базы туда лучше не класть.

---

## Аутентификация

Регистрации нет. Браузер один раз генерирует UUID, кладёт его в `localStorage`
и присылает в заголовке `X-Device-Id`; бэкенд заводит под него пользователя.

```
X-Device-Id: 3f2504e0-4f89-41d3-9a0c-0305e82c3301
```

Запрос без валидного UUID получает `401`. Все выборки ограничены
`request.user`. Кто владеет UUID, владеет аккаунтом; чистка данных сайта или
смена браузера означает новый пустой аккаунт. `Authorization: Token …`
(DRF TokenAuthentication) тоже поддерживается.

---

## API

Списки пагинированы (`{count, next, previous, results}`), 20 на страницу.

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/api/health/` | Проверка живости для хостинга, без авторизации |
| GET | `/api/session/` | Проверить, что устройство опознано |
| GET | `/api/capabilities/` | Какие источники данных доступны |
| POST | `/api/fields/detect/` | Границы участка по координате (OSM) |
| POST | `/api/analyze/` | Карта плодородия + агроклимат |
| POST | `/api/growth/analyze/` | Зелёность: NDVI, NDMI, отклонение от нормы |
| POST | `/api/weeds/detect/` | Аномалии растительности |
| POST | `/api/urban/analyze/` | `infrastructure`, `prediction` или `urban_filter` |
| GET/POST | `/api/fields/` | Участки пользователя |
| GET/PUT/DELETE | `/api/fields/{id}/` | Один участок |
| GET | `/api/dashboard/` | Сводка по своим данным |
| GET | `/api/crops/`, `/api/crops/{id}/` | Справочник культур |
| POST | `/api/crops/recommend/` | Совместимость культур с параметрами почвы |
| GET/POST | `/api/rotations/` | Севооборот |
| GET | `/api/rotations/recommend/{field_id}/` | Что сеять следующим |
| GET | `/api/soil-analyses/`, `/{id}/`, `/timeseries/{field_id}/` | История анализов |
| GET/POST | `/api/growth/`, `/{id}/`, `/timeseries/{field_id}/` | Наблюдения зелёности |
| GET/POST | `/api/invasive/`, `/{id}/` | Очаги сорняков |
| GET | `/api/weeds/database/` | Справочник сорняков |

Тело запроса анализа:

```json
{ "bbox": [69.20, 41.30, 69.23, 41.33], "field_id": 12, "save_result": true }
```

`bbox` — `[запад, юг, восток, север]` в градусах, не больше 10° по стороне.
Лимиты: 30 анализов и 600 обычных запросов в час на пользователя.

---

## Разработка

```bash
ruff check .                              # линт
cd backend && python manage.py test       # 90 тестов, in-memory SQLite
cd frontend && npm run build && npm test  # прод-сборка + 37 jsdom-проверок
```

`manage.py test` автоматически берёт `config.settings_test`, поэтому тесты не
ходят в базу из `.env`. CI (`.github/workflows/ci.yml`) гоняет то же самое
плюс проверку, что production-настройки отказываются стартовать без секрета.

Структура:

```
backend/
  api/
    analysis/     пайплайны (fertility, vegetation, weeds, urban, environment)
    services/     клиенты внешних API (sentinel, worldcover, buildings, soilgrids,
                  weather, elevation, geocoding, osm_fields)
    authentication.py   опознание устройства по X-Device-Id
    validators.py       разбор bbox, бюджет тайлов
  utils/tiles.py  загрузка и склейка тайлов подложки
  config/         настройки; settings_test.py для тестов
frontend/         Vite + Leaflet, деплоится на Vercel
ai model/         обучение и инференс ResNet-18 (опционально, выключено)
Dockerfile        образ бэкенда для Railway
railway.toml      сборка, миграции и health-check на Railway
vercel.json       раздача фронтенда и прокси /api на Railway
```

---

## Деплой

Подробности в [DOCUMENTATION.md](DOCUMENTATION.md), раздел 4. Кратко:

**Бэкенд, Railway.** Сервис собирается из корневого `Dockerfile` по
`railway.toml`: перед переключением трафика выполняются миграции, живость
проверяется по `/api/health/`. Обязательные переменные сервиса:

```
DJANGO_DEBUG=False
DJANGO_SECRET_KEY=<сгенерировать>
DATABASE_URL=<строка Neon>
GEOCODER_CONTACT=<e-mail для Nominatim>
```

Домен Railway подхватывается из `RAILWAY_PUBLIC_DOMAIN` автоматически, поэтому
`DJANGO_ALLOWED_HOSTS` нужен только для своего домена. Порт домена в Railway
должен совпадать с портом, на котором слушает gunicorn (переменная `PORT`).

**Фронтенд, Vercel.** Проект с Root Directory `frontend`, сборка `vite build`.
`frontend/vercel.json` переписывает `/api/(.*)` на домен Railway. При смене
домена бэкенда меняется только эта строка.

**База, Neon.** Обычный PostgreSQL. Без `REDIS_URL` кеш живёт в памяти
процесса и теряется при перезапуске.

Настройки отказываются стартовать при `DJANGO_DEBUG=False` без `SECRET_KEY`,
`ALLOWED_HOSTS` или `DATABASE_URL`.

---

## Внешние сервисы

| Сервис | Назначение | Кеш |
|---|---|---|
| Microsoft Planetary Computer | Sentinel-2: NDVI, NDMI, многолетняя продуктивность | 6 часов / 7 дней |
| Microsoft Planetary Computer | ESA WorldCover 2020/2021 | 30 дней |
| Overpass (OpenStreetMap) | контуры зданий и границы участков | 7 дней |
| ISRIC SoilGrids | свойства почвы | 30 дней |
| Open-Meteo | погода и осадки | 30 минут |
| Open-Meteo Elevation | рельеф (GLO-90) | 90 дней |
| ArcGIS World Imagery | подложка карты и фолбэк-индекс | 7 дней |
| Nominatim | обратное геокодирование | 30 дней |

Все сервисы волонтёрские или с политикой честного использования, поэтому
ответы кешируются, у каждого запроса есть таймаут, а User-Agent
идентифицирует приложение. Nominatim просит указывать контакт: задайте
`GEOCODER_CONTACT`.
