# Favorable Soil — документация проекта

Актуально на 13 сентября 2026.

Содержание:

1. [Что делает проект](#1-что-делает-проект)
2. [Архитектура и поток данных](#2-архитектура-и-поток-данных)
3. [Локальный запуск](#3-локальный-запуск)
4. [Деплой: Railway, Vercel, Neon](#4-деплой-railway-vercel-neon)
5. [Аутентификация](#5-аутентификация)
6. [API](#6-api)
7. [Модели базы данных](#7-модели-базы-данных)
8. [Источники данных и методики](#8-источники-данных-и-методики)
9. [Разбор файлов](#9-разбор-файлов)
10. [Проверки и CI](#10-проверки-и-ci)
11. [Известные ограничения и открытые вопросы](#11-известные-ограничения-и-открытые-вопросы)

---

## 1. Что делает проект

Веб-приложение для оценки сельскохозяйственных участков по спутниковым данным.
Пользователь открывает карту, выделяет участок (или берёт готовый контур из
OpenStreetMap), выбирает тип анализа и нажимает «Анализировать». Бэкенд
запрашивает растры у публичных сервисов, считает индексы и возвращает
картинку-маску (PNG в base64), статистику, названный метод расчёта и
агроклиматический контекст.

Шесть типов анализа в интерфейсе:

| Тип в UI | Эндпоинт | Что считается |
|---|---|---|
| Плодородие | `POST /api/analyze/` | Композит: многолетний NDVI × оценка почвы SoilGrids, маска WorldCover, уклон DEM; плюс погода, химия почвы и подбор культур |
| Качество жизни почвы | `POST /api/growth/analyze/` | NDVI текущей сцены, NDMI (влажность покрова), отклонение от нормы прошлых лет, стадия роста |
| Сорняки | `POST /api/weeds/detect/` | Участки, где NDVI отличается от медианы поля более чем на 2 MAD, внутри пашни по WorldCover |
| Инфраструктура | `POST /api/urban/analyze/` `infrastructure` | Класс «застройка» WorldCover + контуры зданий OSM |
| Динамика застройки | `POST /api/urban/analyze/` `prediction` | WorldCover 2020 → 2021, новая застройка, свободная земля рядом |
| Покров земли | `POST /api/urban/analyze/` `urban_filter` | 11 классов ESA WorldCover с официальной легендой |

Стек: Django 5.2 + Django REST Framework, vanilla JS + Leaflet + Vite,
OpenCV/NumPy/Pillow, PostgreSQL (Neon) в проде и SQLite локально, locmem или
Redis для кеша. Опционально PyTorch ResNet-18, по умолчанию выключен.

Все внешние источники бесплатны и без ключей: Microsoft Planetary Computer
(Sentinel-2, WorldCover), ISRIC SoilGrids, Open-Meteo (погода и рельеф),
OpenStreetMap Overpass (границы полей, здания), Nominatim (страна), ArcGIS
World Imagery (подложка карты).

---

## 2. Архитектура и поток данных

### Топология в проде

```
Браузер
   │  https://ilm-flame.vercel.app          статика фронтенда (Vercel)
   │  https://ilm-flame.vercel.app/api/*    rewrite из frontend/vercel.json
   ▼
Railway: ilm-production.up.railway.app     контейнер из Dockerfile, gunicorn
   │  DATABASE_URL
   ▼
Neon PostgreSQL
```

Фронтенд и API для браузера живут на одном домене, поэтому CORS в проде не
нужен. Бэкенд ходит наружу только к публичным геосервисам.

### Поток одного запроса анализа

```
frontend/script.js
   │  X-Device-Id: <uuid>          fetch(JSON)
   ▼
config/urls.py → api/urls.py → api/views.py
   │  DeviceAuthentication → User "device_<uuid>"
   │  ScopedRateThrottle: analysis 30/ч, crud 600/ч
   ▼
AnalysisView.parse_request
   │  AnalyzeRequestSerializer → validators.parse_bbox
   │  field_id резолвится только среди своих полей
   ▼
api/analysis/*  (fertility | vegetation | weeds | urban | environment)
   │
   ├─ services/sentinel.py ───► Planetary Computer: STAC + raster API (NDVI, NDMI, SCL)
   ├─ services/worldcover.py ─► Planetary Computer: ESA WorldCover 2020/2021
   ├─ services/buildings.py ──► Overpass: контуры зданий
   ├─ services/elevation.py ──► Open-Meteo Elevation: сетка 10×10 высот
   ├─ services/soilgrids.py ──► ISRIC SoilGrids: pH, N, SOC, CEC, глина, песок, wv0033
   ├─ services/weather.py ────► Open-Meteo Forecast: погода + осадки за 7 дней
   ├─ services/geocoding.py ──► Nominatim: страна
   ├─ services/osm_fields.py ─► Overpass: полигоны farmland/meadow/…
   └─ utils/tiles.py ─────────► ArcGIS: RGB-мозаика для фолбэка
   ▼
analysis/imagery.encode_overlay → PNG base64
   ▼
Response {overlay, stats, legend, method, imagery, components, environment}
   │  save_result=true + field_id → SoilAnalysis / GrowthMonitoring / InvasiveSpeciesReport
   ▼
Браузер: L.imageOverlay на карту, renderResult → #results-container
```

Правила, которые соблюдаются во всём бэкенде:

* каждый queryset фильтруется по `request.user`, анонимного доступа нет;
* пайплайны получают уже валидированный `bbox` и бросают `AnalysisError`
  с текстом для пользователя, а не возвращают `None`;
* каждый клиент внешнего сервиса сам отвечает за таймаут, кеш и возврат
  `None` при отказе; выдуманные значения запрещены;
* каждый ответ анализа говорит, чем он получен (`method`) и на каком снимке
  (`imagery`).

---

## 3. Локальный запуск

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt            # + requirements-ml.txt только для ResNet
cp backend/.env.example backend/.env
cd backend && python manage.py migrate && python manage.py loaddata api/fixtures/initial_data.json
python manage.py runserver                 # :8000
cd ../frontend && npm install && npm run dev   # :5173, /api проксируется на :8000
```

Переменные окружения читаются в `backend/config/settings.py`, полный список с
комментариями в `backend/.env.example`. Значений по умолчанию достаточно для
локальной работы: SQLite, `DEBUG=True`, кеш в памяти процесса,
`CORS_ALLOW_ALL_ORIGINS=True`.

`backend/.env` в git не попадает. Если в нём задать `DATABASE_URL`, локальный
`runserver`, `migrate` и `loaddata` пойдут в эту базу. Тесты этого не делают:
`manage.py test` подставляет `config.settings_test` с in-memory SQLite.

Локальный venv на Python 3.14, образ для Railway на Python 3.12, ruff целится в
3.11. Тесты проходят на обоих, но при странностях в зависимостях стоит
проверить версию.

---

## 4. Деплой: Railway, Vercel, Neon

### 4.1 Бэкенд на Railway

Сервис собирается из корневого `Dockerfile` по правилам `railway.toml`:

| Параметр | Значение | Зачем |
|---|---|---|
| `builder` | `DOCKERFILE` | Образ `python:3.12-slim` + libgl для OpenCV, gunicorn 2 воркера × 4 потока |
| `preDeployCommand` | `python manage.py migrate --noinput` | Миграции выполняются в новом образе до переключения трафика; упавшая миграция не заменяет работающий деплой |
| `healthcheckPath` | `/api/health/` | Railway пробует его по HTTP с Host `healthcheck.railway.app`; эндпоинт без авторизации, лимитов и БД, исключён из HTTPS-редиректа |
| `restartPolicyType` | `ON_FAILURE`, 5 попыток | Перезапуск при падении |

Gunicorn слушает порт из переменной `PORT`, которую задаёт Railway (с запасным
значением 8000 для `docker run`). **Порт публичного домена в Settings →
Networking должен совпадать с этим портом**, иначе роутер Railway отвечает
502 «Application failed to respond» с заголовком `x-railway-fallback: true`.

Переменные сервиса (Variables):

```
DJANGO_DEBUG=False
DJANGO_SECRET_KEY=<python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())">
DATABASE_URL=<строка подключения Neon>
GEOCODER_CONTACT=<e-mail, который Nominatim просит указывать в User-Agent>
```

Необязательные:

```
REDIS_URL=${{Redis.REDIS_URL}}     общий кеш тайлов и SoilGrids между воркерами и рестартами
DJANGO_ALLOWED_HOSTS=...           только для своего домена
DJANGO_CSRF_TRUSTED_ORIGINS=...    только если нужна админка по своему домену
```

Домен `*.up.railway.app` в `ALLOWED_HOSTS` подставлять не нужно: настройки
читают `RAILWAY_PUBLIC_DOMAIN`, которую Railway задаёт после создания
публичного домена, и добавляют его вместе с `healthcheck.railway.app`. Пока
домена нет, переменной нет, и production-настройки откажутся стартовать с
ошибкой про `DJANGO_ALLOWED_HOSTS`. Это ожидаемо: сначала Generate Domain.

Типичные ошибки первого деплоя и что они значат:

| Строка в логах | Причина |
|---|---|
| `DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is False` | Не задана переменная секрета |
| `DJANGO_ALLOWED_HOSTS must list the hostnames…` | Нет публичного домена и не задана переменная вручную |
| `DATABASE_URL must be set in production` | Не задана строка базы |
| 502 с `x-railway-fallback: true` на любом пути | Порт домена не совпадает с портом gunicorn |

Текущий домен: `ilm-production.up.railway.app`. Проверка:

```
curl https://ilm-production.up.railway.app/api/health/      # {"status":"ok"}
```

### 4.2 Фронтенд на Vercel

Vercel хостит только статику. `.vercelignore` исключает всё питоновское,
иначе Vercel находил `backend/manage.py` и пытался собрать Django.

Проект настроен с Root Directory `frontend`, поэтому действует
`frontend/vercel.json`: `framework: vite`, `npm run build`, `outputDirectory:
dist` и rewrite `/api/(.*)` → `https://ilm-production.up.railway.app/api/$1`.
Корневой `vercel.json` описывает тот же деплой для случая, когда Root Directory
не задан (`installCommand: npm ci --prefix frontend`, `outputDirectory:
frontend/dist`), и содержит такой же rewrite. При смене домена бэкенда
правятся обе строки.

Сборка происходит на каждый push в `main`. Текущий домен:
`https://ilm-flame.vercel.app`.

Почему бэкенд не на Vercel: один анализ качает и склеивает десятки растров и
гоняет по ним OpenCV, что выходит за лимит времени serverless-функции;
`opencv` + `numpy` почти упираются в лимит размера бандла; кеш тайлов не
переживает процесс.

### 4.3 База Neon

Обычный PostgreSQL, подключение через `DATABASE_URL` с `sslmode=require`.
`dj_database_url` держит соединения 600 секунд. Схема создаётся миграциями
при деплое, справочники культур и сорняков загружаются один раз:

```
python manage.py loaddata api/fixtures/initial_data.json
```

Картинки-маски хранятся в TEXT-колонках как base64 PNG (до сотен КБ на
запись), так что на бесплатном тарифе квота расходуется быстро.

### 4.4 Как выкатить изменение

1. `ruff check .`, `python manage.py test`, `npm run build && npm test`.
2. Push в `main`. CI прогоняет то же самое.
3. Railway и Vercel пересобирают сами. Railway применит миграции до
   переключения трафика.
4. Проверить `curl …/api/health/` на Railway и `…/api/session/` через Vercel
   с заголовком `X-Device-Id`.

---

## 5. Аутентификация

Регистрации нет. Файл `backend/api/authentication.py`:

1. Браузер один раз генерирует UUID v4 (`crypto.randomUUID` или ручной
   фолбэк для http://), хранит в `localStorage` под ключом
   `favorable-soil-device-id` и шлёт в заголовке `X-Device-Id`.
2. `DeviceAuthentication.authenticate` проверяет UUID регэкспом, ищет `User`
   с username `device_<uuid>`; если нет, создаёт с непригодным паролем. Гонка
   двух первых запросов ловится по `IntegrityError`.
3. Регистрация новых устройств ограничена 20 в час на IP (ключ в кеше
   `device-registrations:<ip>`).
4. Запрос без заголовка → далее пробуются `TokenAuthentication` и
   `SessionAuthentication`; если никто не опознал, `IsAuthenticated` даёт 401.

Кто владеет UUID, владеет аккаунтом; очистка данных сайта или смена браузера
означает новый пустой аккаунт. Чувствительные данные здесь хранить не
следует. `/api/health/` единственный эндпоинт без аутентификации.

---

## 6. API

Все списки пагинированы (`{count, next, previous, results}`, 20 на страницу).
Все эндпоинты, кроме `/api/health/`, требуют аутентификации.

| Метод | Путь | View | Throttle | Фронтенд |
|---|---|---|---|---|
| GET | `/api/health/` | `HealthView` | нет | нет (Railway) |
| GET | `/api/session/` | `SessionView` | crud | да |
| GET | `/api/capabilities/` | `CapabilitiesView` | crud | нет |
| POST | `/api/analyze/` | `AnalyzeView` | analysis | да |
| POST | `/api/growth/analyze/` | `GrowthAnalyzeView` | analysis | да |
| POST | `/api/weeds/detect/` | `WeedDetectionView` | analysis | да |
| POST | `/api/urban/analyze/` | `UrbanAnalyzeView` | analysis | да |
| POST | `/api/fields/detect/` | `FieldDetectView` | analysis | да |
| GET/POST | `/api/fields/` | `FieldListCreateView` | crud | да |
| GET/PUT/PATCH/DELETE | `/api/fields/{id}/` | `FieldDetailView` | crud | нет |
| GET | `/api/dashboard/` | `DashboardView` | crud | нет |
| GET | `/api/crops/`, `/api/crops/{id}/` | `CropTypeListView`, `CropTypeDetailView` | crud | нет |
| POST | `/api/crops/recommend/` | `CropPlantingRecommendationView` | crud | нет |
| GET/POST | `/api/rotations/` | `CropRotationListView` | crud | нет |
| GET | `/api/rotations/recommend/{field_id}/` | `CropRotationRecommendationView` | crud | нет |
| GET | `/api/soil-analyses/`, `/{id}/` | `SoilAnalysisListView`, `SoilAnalysisDetailView` | crud | нет |
| GET | `/api/soil-analyses/timeseries/{field_id}/` | `SoilAnalysisTimeSeriesView` | crud | нет |
| GET/POST | `/api/growth/`, `/{id}/` | `GrowthMonitoringListView`, `GrowthMonitoringDetailView` | crud | нет |
| GET | `/api/growth/timeseries/{field_id}/` | `GrowthTimeSeriesView` | crud | нет |
| GET/POST | `/api/invasive/`, `/{id}/` | `InvasiveSpeciesListView`, `InvasiveSpeciesDetailView` | crud | нет |
| GET | `/api/weeds/database/` | `WeedDatabaseListView` | crud | нет |

Тело запроса анализа:

```json
{ "bbox": [69.20, 41.30, 69.23, 41.33], "field_id": 12, "save_result": true, "analysis_type": "infrastructure" }
```

`bbox` = `[запад, юг, восток, север]` в градусах, не больше 10° по стороне;
при слишком большом выделении зум снижается, чтобы уложиться в бюджет тайлов
(`MAX_TILES_PER_REQUEST`). `analysis_type` читает только
`/api/urban/analyze/`. `field_id` чужого пользователя неотличим от
несуществующего.

Коды ошибок: 400 (bbox или валидация), 401 (устройство не опознано),
404 (чужой или несуществующий `field_id`, ненайденные контуры OSM),
429 (лимит), 502 (внешний сервис не ответил, тело `{"error": "..."}`).

Лимиты: `THROTTLE_ANALYSIS` 30/час и `THROTTLE_CRUD` 600/час на пользователя.
Списки не содержат base64-изображений, маска отдаётся только на
detail-эндпоинте.

---

## 7. Модели базы данных

Файл `backend/api/models.py`. Все пользовательские записи имеют `user`
(FK на `auth.User`, nullable; записи с `NULL` невидимы через API).

| Модель | Назначение | Ключевые поля | Связи |
|---|---|---|---|
| `Field` | Участок пользователя | `name`, `bounds_json` (TEXT, JSON-полигон), `center_lat/lon`, `area_hectares` | `user` CASCADE |
| `CropType` | Справочник культур (глобальный, через admin) | pH/температура/NPK/влажность/сезон/урожайность, инструкции | M2M `good_predecessors`, `bad_predecessors` на себя |
| `CropRotation` | Запись севооборота | `year`, `season`, `yield_amount` | `field`, `crop_type`; unique (`field`,`year`,`season`) |
| `SoilAnalysis` | Сохранённый анализ плодородия | проценты по классам, `fertility_index`, `overlay_image` (base64 PNG) | `field` CASCADE, `user` SET_NULL |
| `InvasiveSpeciesReport` | Очаг аномалии/сорняка | `species_name`, `severity`, `status`, координаты, `affected_area` | `field`, `user` |
| `GrowthMonitoring` | Наблюдение зелёности | `observation_date`, `ndvi_mean/min/max`, `health_score`, `growth_stage`, `data_source`, `ndvi_overlay` | `field`, `user`; unique (`field`,`observation_date`) |
| `WeedDatabase` | Справочник сорняков | `name`, `danger_level`, `control_methods` | нет |

Методы: `Field.get_bounds/set_bounds`, `CropType.check_soil_compatibility(ph,
n, p, k, moisture)` (оценка 0..5 → проценты, проблемы, рекомендации),
`SoilAnalysis.calculate_fertility_index()`.

Миграции: `mainofbd` → `factsofplants` → `0001_delete_feedbacklabel` →
`0002_add_user_to_models`. `makemigrations --check` чист. Фикстура
`api/fixtures/initial_data.json`: 12 `CropType` и 5 `WeedDatabase`.

Запись в чужое поле через `/api/rotations/`, `/api/growth/` и `/api/invasive/`
отклоняется на уровне сериализаторов (`OwnedFieldMixin.validate_field`, 400).

---

## 8. Источники данных и методики

### 8.1 Плодородие (`analysis/fertility.py`)

Один снимок NDVI измеряет зелёность в конкретный день, а не плодородие: пар
на плодородной земле выглядит голой почвой. Поэтому индекс собирается из
слоёв, и каждый назван в `components` ответа:

1. **Продуктивность**, вес 0.65: попиксельный пик и среднее NDVI по лучшей
   сцене на каждый месяц апрель–сентябрь за 3 последних года (облачность
   < 25 %, до 18 сцен, растр 256×256, параллельная загрузка).
2. **Почва**, вес 0.35: `soilgrids.soil_quality_score` из pH (оптимум
   6.0–7.5), органического углерода (20 г/кг = 1.0), ЁКО (25 = 1.0) и
   текстуры (песок ≥ 70 % → 0.4, глина ≥ 60 % → 0.6). Если SoilGrids пуст
   (города, вода), вес продуктивности становится 1.0 и это отмечается в
   `components.soil.note`.
3. **Покров**: вода, застройка, снег по WorldCover исключаются и показываются
   отдельными классами.
4. **Уклон**: > 15 % по Copernicus GLO-90 → «горы», непригодно.

Фолбэки по порядку: меньше 3 сезонных сцен → последняя одиночная сцена
NDVI; Planetary Computer недоступен → ExG по RGB-подложке ArcGIS. `method`
всегда называет, что сработало. Холодный расчёт 30–50 секунд, кеш 7 дней.

### 8.2 Зелёность (`analysis/vegetation.py`)

NDVI последней сцены за 90 дней с облачностью < 40 % и покрытием валидными
пикселями ≥ 50 % (маска SCL: классы 4, 5, 6, 7, 11). Дополнительно NDMI по
B08/B11 той же сцены и отклонение от NDVI того же календарного окна за два
прошлых года. Стадия роста и «здоровье» по порогам `IndexProfile`
(отдельные для NDVI и ExG). Фолбэк ExG даёт `index_type: "ExG"`, чтобы
сохранённый ряд читался правильно.

### 8.3 Офсет отражения Sentinel-2

С версии обработки 04.00 (январь 2022) продукты L2A содержат
`BOA_ADD_OFFSET = -1000`. В NDVI офсет сокращается в числителе, но не в
знаменателе, поэтому формула `(B08 − B04) / (B08 + B04 − 2000)` применяется
только к сценам с baseline ≥ 4.0. Замер по одному полю под Ташкентом: без
офсета NDVI 0.333, с офсетом 0.494, то есть одна стадия роста разницы. Тесты
`ReflectanceOffsetTests` фиксируют оба случая.

### 8.4 Сорняки (`analysis/weeds.py`)

10-метровый пиксель не определяет вид растения. Эндпоинт находит участки,
где NDVI отличается от медианы поля более чем на 2 MAD, только внутри
пашни, луга и кустарника по WorldCover, отмечает направление
(«зеленее»/«бледнее»), площадь ≥ 400 м² и серьёзность по площади. В ответе
`is_species_identified: false` и `note` об этом. Фолбэк без Sentinel: старая
текстурная дисперсия по RGB.

### 8.5 Застройка и покров (`analysis/urban.py`)

* `infrastructure`: класс «застройка» WorldCover + контуры зданий OSM через
  Overpass (область до 12 км², до 3000 зданий). Фолбэк: Canny-контуры.
* `prediction` («Динамика застройки»): WorldCover 2020 → 2021, изменение в
  процентных пунктах, новая застройка на оверлее, свободная пашня/луг рядом.
* `urban_filter` («Покров земли»): 11 классов WorldCover с официальной
  легендой и заявленной точностью.

### 8.6 Агроклимат (`analysis/environment.py`, `services/soilgrids.py`)

SoilGrids v2.0, слой 0–5 см, 250 м: pH, органический углерод, ЁКО, глина,
песок, влагоёмкость, каждое с диапазоном Q5–Q95. Выведенные величины:
доступный N = общий N × 2 %; обменный K = ЁКО × 3 % × 391; Olsen-P ≈ 4 +
1.1·SOC − 0.15·max(0, глина − 30). Влажность = влагоёмкость × (0.4 + 0.6 ×
min(1, осадки за 7 дней / 25)). Каждое значение несёт `source`: `measured`,
`derived` или `unavailable`; отказ сервиса даёт `null`.

Подбор культур: статический каталог `crop_catalog.py` с региональным
фильтром по стране из Nominatim; баллы по pH, температуре и азоту, культуры
с pH вне диапазона более чем на 0.5 отбрасываются, топ-3.

### 8.7 Границы участков (`services/osm_fields.py`)

Overpass ищет `landuse` farmland, meadow, orchard, vineyard,
greenhouse_horticulture, allotments в радиусе 100–5000 м. Возвращается то,
что размечено людьми: в Европе плотно, вокруг Ташкента пусто даже на 8 км.
Пусто → 404 и негативный кеш на 6 часов.

### 8.8 Кеширование и бережное отношение к сервисам

| Сервис | Кеш |
|---|---|
| Sentinel-2 сцена | 6 часов, массивы сжаты через `np.savez_compressed` (~0.3 МБ на запись) |
| Сезонная продуктивность | 7 дней |
| WorldCover | 30 дней |
| Overpass (здания, поля) | 7 дней |
| SoilGrids | 30 дней, негативный кеш 1 час |
| Open-Meteo погода | 30 минут |
| Open-Meteo рельеф | 90 дней |
| Тайлы ArcGIS | 7 дней |
| Nominatim | 30 дней |

У каждого запроса таймаут `HTTP_TIMEOUT_SECONDS` (8 с), User-Agent
идентифицирует приложение, число тайлов на запрос ограничено
`MAX_TILES_PER_REQUEST` (64). Без `REDIS_URL` кеш живёт в памяти каждого
воркера отдельно и теряется при рестарте.

---

## 9. Разбор файлов

### 9.1 Корень репозитория

* **`Dockerfile`**: `python:3.12-slim`, `libgl1` и `libglib2.0-0` для OpenCV,
  копирует только `backend/`, `collectstatic` при сборке, непривилегированный
  пользователь, `gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000}
  --workers 2 --threads 4 --timeout 120`. Папка `ai model` в образ не
  попадает.
* **`railway.toml`**: сборка из Dockerfile, `preDeployCommand` с миграциями,
  health-check `/api/health/`, рестарт при падении. В шапке перечислены
  переменные, которые нужно задать в Railway.
* **`vercel.json`** и **`frontend/vercel.json`**: раздача статики и rewrite
  `/api/(.*)` на Railway (см. 4.2).
* **`.vercelignore`**: исключает `backend`, `ai model`, venv, requirements,
  Dockerfile, CI и веса модели из загрузки на Vercel.
* **`.dockerignore`**: исключает `.git`, venv, `node_modules`, `frontend/dist`,
  `backend/.env`, SQLite, `ai model`, логи.
* **`package.json`** (корень): скрипты-обёртки `build`, `dev` → `frontend/`,
  `test` → Django-тесты.
* **`pyproject.toml`**: ruff, длина строки 100, правила F/E/W/I/B/UP/C4.
* **`requirements.txt`**: рантайм с пинами (Django 5.2.16, DRF 3.17.1,
  numpy 2.5.1, opencv-python-headless, gunicorn, whitenoise, dj-database-url,
  psycopg2-binary). **`requirements-ml.txt`**: torch, torchvision, tqdm.
* **`.gitattributes`**: LF для исходников, `*.pth` объявлен как Git LFS.
* **`.github/workflows/ci.yml`**: см. раздел 10.

### 9.2 `backend/` и `backend/config/`

* **`manage.py`**: выбирает `config.settings_test` при команде `test`.
* **`config/settings.py`**: всё из переменных окружения. `DEBUG`,
  `SECRET_KEY` (обязателен в проде), `ALLOWED_HOSTS` (+ `RAILWAY_PUBLIC_DOMAIN`
  и `healthcheck.railway.app` автоматически), `CSRF_TRUSTED_ORIGINS`; CORS
  (в DEBUG все origin, заголовок `x-device-id` разрешён); DRF: аутентификация
  Device → Token → Session, `IsAuthenticated`, пагинация 20, `ScopedRateThrottle`;
  БД через `dj_database_url` (`conn_max_age=600`, `ssl_require` в проде);
  кеш Redis или locmem; параметры внешних сервисов; в проде
  `SECURE_PROXY_SSL_HEADER`, `SECURE_SSL_REDIRECT` с исключением для
  `api/health/`, HSTS, secure-cookies; логирование в консоль; `LANGUAGE_CODE='ru'`;
  whitenoise.
* **`config/settings_test.py`**: `DEBUG=False`, тестовый секрет, SQLite
  `:memory:`, locmem, throttle выключен, MD5-хеши, SSL-редирект выключен.
* **`config/urls.py`**: `admin/` и `api/`. **`config/wsgi.py`**: `application`
  и алиас `app`. **`config/asgi.py`**: не используется.

### 9.3 `backend/api/`

* **`urls.py`**: 26 маршрутов из раздела 6.
* **`authentication.py`**: раздел 5.
* **`permissions.py`**: `IsOwner` (объект принадлежит `request.user`) и
  `IsOwnerOfField` (не подключён).
* **`validators.py`**: `parse_bbox` (строка или список, 4 конечных числа,
  широта ≤ 85.05, порядок, ≤ 10°), `tile_span`, `choose_zoom` (снижает зум
  до бюджета тайлов), `metres_per_pixel`.
* **`serializers.py`**: сериализаторы моделей (list-варианты без картинок,
  detail с картинками), `OwnedFieldMixin.validate_field`, входные
  `AnalyzeRequestSerializer`, `UrbanAnalyzeRequestSerializer`,
  `FieldDetectRequestSerializer` (`lat`, `lon`, `radius_m` 100–5000),
  `PlantingRecommendationRequestSerializer`.
* **`views.py`**: базовые `OwnedQuerysetMixin` (queryset по `request.user`,
  `perform_create` подставляет владельца) и `AnalysisView` (`parse_request`);
  `HealthView` (без auth/throttle/БД); остальные эндпоинты из раздела 6.
  `FieldListCreateView` аннотирует число анализов и последний индекс, чтобы
  не делать по два запроса на поле. `UrbanAnalyzeView` выбирает пайплайн из
  словаря `_PIPELINES`. `DashboardView` собирает агрегаты по полям, активные
  отчёты, 5 последних анализов и 5 угроз.
* **`admin.py`**: регистрация 7 моделей с фильтрами и поиском по владельцу.
* **`crop_catalog.py`**: статический каталог культур для быстрой подсказки
  после анализа, не связан с `CropType`.
* **`tests.py`**: 90 тестов в 27 классах, внешние сервисы замоканы; см.
  раздел 10.
* **`fixtures/initial_data.json`**, **`migrations/`**: раздел 7.
* **`management/commands/`**: пустой пакет.

### 9.4 `backend/api/analysis/`

* **`imagery.py`**: `AnalysisError`, `load_imagery` (тайлы → `AnalysisError`
  при отказе), `encode_overlay` (RGBA → data-URI PNG), `excess_green_index`,
  `local_variance`, `water_mask`, `paint`, `percentage`, `upsample_grid`.
* **`fertility.py`**, **`vegetation.py`**, **`weeds.py`**, **`urban.py`**,
  **`environment.py`**: раздел 8. В `fertility.py` также ленивая загрузка
  ResNet-18 за флагом `ENABLE_SOIL_MODEL_ON_TILES` (не валидирована на
  спутниковых тайлах, по умолчанию выключена).

### 9.5 `backend/api/services/`

Один модуль = один внешний сервис; при отказе `None`, никаких выдуманных
значений.

* **`http.py`**: `build_session(user_agent)`, `get_json` с таймаутом и
  логированием отказов.
* **`sentinel.py`**: `is_available` (`DISABLE_SENTINEL`), `search_scene`,
  `search_scenes`, `fetch_ndvi_array` / `fetch_ndvi_stats` (NDVI + SCL
  параллельно), `fetch_seasonal_productivity`, `fetch_ndmi_mean`,
  `fetch_reference_ndvi`, `resolution_for` (честные м/пиксель по размеру
  bbox), `_pack/_unpack` (сжатый кеш), `_ndvi_expression(baseline)` с офсетом.
* **`worldcover.py`**: `fetch_landcover(bbox, year, size)`,
  `class_percentages`, `paint`, `legend`; `DISABLE_WORLDCOVER`.
* **`buildings.py`**: `lookup_buildings(bbox)` через Overpass `way["building"]`,
  отказ при площади > 12 км².
* **`soilgrids.py`**: `fetch_soil_properties(lat, lon)`, `soil_quality_score`,
  `estimate_current_moisture`, выводные формулы из 8.6.
* **`weather.py`**: Open-Meteo, текущая погода и осадки за 7 дней.
* **`elevation.py`**: сетка 10×10 высот, `slope_percent` через `np.gradient`
  с реальным шагом в метрах.
* **`geocoding.py`**: Nominatim reverse с `GEOCODER_CONTACT`, фолбэк
  `approximate_country` по прямоугольникам стран с флагом `is_approximate`.
* **`osm_fields.py`**: `lookup_fields(lat, lon, radius)`, площадь по формуле
  шнурков, `nearest_field` (не вызывается).

### 9.6 `backend/utils/tiles.py`

Единственное место, которое ходит на тайл-сервер: `SatelliteImage`,
`deg2num`/`num2deg`, `download_tile` (кеш 7 дней, негативный кеш на 404,
таймаут), `fetch_satellite_image` (бюджет тайлов, 8 потоков, склейка;
меньше половины тайлов → `TileFetchError`).

### 9.7 `frontend/`

* **`index.html`**: одна страница. Сайдбар (Дашборд, Карта & Анализ, тема),
  дашборд (карточки статистики, история активности, сводка), секция анализа
  (карта Leaflet, `<select id="analysis-type-select">` с шестью типами,
  кнопка «Анализировать», печать через `window.print()`, панель привязки к
  полю с `#field-select`, чекбокс «Сохранить результат», форма создания поля,
  кнопка автоопределения контура, блок ошибок, легенда, `#results-container`).
  Leaflet 1.9.4 и leaflet.draw с CDN. Приложение подключено как
  `<script type="module" src="/script.js">`, чтобы Vite собрал бандл.
* **`script.js`** (~1500 строк): `API_URL` (`http://127.0.0.1:8000/api` на
  localhost и file://, иначе `/api`); идентичность устройства
  (`getDeviceId`, `getAuthHeaders`); `checkAuthSession` (`GET /session/`,
  включает кнопку автоопределения по `capabilities`, при не-2xx показывает
  «Не удалось установить сессию с сервером», при сетевой ошибке «Сервер
  недоступен»); `loadFields`, `saveFieldFromMap`; `initMap` (центр Душанбе,
  ArcGIS-подложка, рисование прямоугольника и полигона, `moveend` →
  `currentBounds`); `runAnalysis` (выбор эндпоинта по типу, `field_id`,
  `save_result`, ошибки через `describeHttpError` для 400/401/429/502);
  `renderResult` и вспомогательные рендеры (компоненты плодородия, бейджи
  измерено/расчёт/нет данных, дата и разрешение снимка, карточки культур);
  `updateDashboard` (счётчики сессии, курсы валют с exchangerate-api,
  справочные цены земли, 3-дневный прогноз Open-Meteo, обратное
  геокодирование Nominatim прямо из браузера); темы через CSS-переменные.
* **`style.css`**: тёмная тема по умолчанию, шрифт Outfit, макет сайдбар +
  контент, печать.
* **`vite.config.js`**: `outDir: dist`, sourcemap, порт 5173, прокси `/api`
  → `http://127.0.0.1:8000`.
* **`test/smoke.test.mjs`**: грузит `dist/index.html` и бандл в jsdom,
  подменяет `L` и `fetch`, 37 проверок: рендер плодородия, XSS-экранирование,
  зелёность ExG/NDVI, отсутствие `null` при пустых данных, дата съёмки,
  тексты ошибок 400/502/429/401, чистая консоль.
* **`vercel.json`**: раздел 4.2. **`dist/`**: результат сборки, не в git.

### 9.8 `ai model/`

`train.py` дообучает ResNet-18 на снимках почвы с земли, `predict.py`
классифицирует один снимок, `distribute_dataset.py` раскладывает датасет
(привязан к путям конкретной Windows-машины). `soil_model.pth` (44 МБ)
обучен на макроснимках, к спутниковым тайлам не валидирован, в Docker-образ
не попадает.

---

## 10. Проверки и CI

Локально:

```bash
ruff check .                                   # линт
cd backend && python manage.py test            # 90 тестов, in-memory SQLite
cd frontend && npm run build && npm test       # сборка + 37 jsdom-проверок
```

Что покрывают тесты бэкенда: health-check без БД; аутентификация устройства и
лимит регистраций; изоляция данных между устройствами, включая запись в чужое
поле; read-only справочники; валидация bbox и бюджет тайлов; выводные формулы
почвы и `soil_quality_score`; подбор культур; дашборд; размер ответов;
честность ответов анализа (`method`, 502 при отказе сервиса); троттлинг;
профили индексов; фолбэки Sentinel и плодородия; офсет отражения; маска
облаков; сезонная продуктивность; WorldCover; здания и поля из OSM.

`.github/workflows/ci.yml`, два job'а на push в `main` и pull request:

* `backend`: Python 3.12, зависимости + ruff, `ruff check .`,
  `makemigrations --check`, `manage.py test`, проверка, что
  `DJANGO_DEBUG=False manage.py check` падает без секрета.
* `frontend`: Node 20, `npm ci`, `npm run build`, `npm test`, проверка, что в
  `dist/assets` есть JS-бандл и `index.html` не ссылается на голый
  `script.js`.

---

## 11. Известные ограничения и открытые вопросы

Операционные:

* **Кеш и троттлинг в памяти процесса.** Без `REDIS_URL` два воркера
  gunicorn считают лимиты раздельно (30/час на деле до 60/час), а кеш
  Sentinel и SoilGrids дублируется и теряется при рестарте. На Railway
  достаточно добавить Redis и переменную `REDIS_URL`.
* **Лимит 20 новых устройств в час на IP** блокирует пользователей за общим
  NAT (вуз, офис, мобильный оператор). `_client_ip` доверяет
  `X-Forwarded-For` без списка доверенных прокси.
* **Base64-картинки в TEXT-колонках** быстро расходуют квоту Neon. Разумнее
  объектное хранилище или ужатие PNG.
* **Веса модели** лежат в git как обычный 44 МБ blob при объявленном правиле
  LFS в `.gitattributes`. Либо `git lfs migrate import --include="*.pth"`,
  либо убрать правило.
* **Локальный `backend/.env`** может указывать на боевую базу Neon при
  `DEBUG=True`; для локальной работы `DATABASE_URL` лучше не задавать.

Функциональные:

* **Вид сорняка не определяется** по спутнику; нужен Pl@ntNet (бесплатный
  ключ) и загрузка фото с клиента, чего в UI нет.
* **FAO GAEZ v4** (пригодность культур, почвенные ограничения) требует
  ручной загрузки растров; подбор культур пока по статическому каталогу.
* **Microsoft Global Building Footprints** разумно загрузить в PostGIS при
  деплое; сейчас здания берутся из OSM, покрытие которого неравномерно.
* **Границы участков** есть только там, где их разметили в OpenStreetMap.
* **Цены земли и курсы валют** на дашборде: цены зашиты в `LAND_PRICES` как
  ориентир, курсы берутся с `exchangerate-api.com` без ключа и SLA.
* **Внешние вызовы из браузера** (Nominatim, exchangerate-api, Open-Meteo)
  идут без идентифицирующего User-Agent, который браузер не даёт задать.

Неподключённый код: `permissions.IsOwnerOfField`, `osm_fields.nearest_field`,
`Field.get_bounds/set_bounds`, `config/asgi.py`, алиас `wsgi.app`, пустой
`api/management/commands/`, ResNet-18 за флагом, `ai model/distribute_dataset.py`.
Большая часть API (дашборд, история анализов, севооборот, очаги, справочники)
реализована и покрыта тестами, но фронтенд использует только семь маршрутов.
