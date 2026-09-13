# Favorable Soil — полная документация проекта

Дата разбора: 13 сентября 2026

Содержание:

1. [Что делает проект](#1-что-делает-проект)
2. [Архитектура и поток данных](#2-архитектура-и-поток-данных)
3. [Запуск и окружение](#3-запуск-и-окружение)
4. [Аутентификация](#4-аутентификация)
5. [API](#5-api)
6. [Модели базы данных](#6-модели-базы-данных)
7. [Разбор каждого файла](#7-разбор-каждого-файла)
8. [Найденные ошибки и риски](#8-найденные-ошибки-и-риски)
9. [Неподключённый и мёртвый код](#9-неподключённый-и-мёртвый-код)
10. [Доработка от 13 сентября 2026: официальные источники вместо эвристик](#10-доработка-от-13-сентября-2026-официальные-источники-вместо-эвристик)

---

## 1. Что делает проект

Веб-приложение для оценки сельскохозяйственных участков по спутниковым данным. Пользователь открывает карту, наводит её на участок, выбирает тип анализа и нажимает «Анализировать». Бэкенд скачивает снимки, считает индексы и возвращает картинку-маску (PNG в base64), статистику и агроклиматический контекст.

Пять типов анализа:

| Тип в UI | Эндпоинт | Что считается |
|---|---|---|
| Плодородие | `POST /api/analyze/` | Классы плодородия по NDVI (Sentinel-2) или ExG (RGB-подложка), уклон по DEM, маска воды, плюс погода, химия почвы и подбор культур |
| Качество жизни почвы | `POST /api/growth/analyze/` | Вегетационный индекс (NDVI или ExG), стадия роста, «здоровье» |
| Сорняки | `POST /api/weeds/detect/` | Текстурные аномалии растительности (кандидаты в очаги сорняков) |
| Инфраструктура | `POST /api/urban/analyze/` `infrastructure` | Контуры зданий, плотность застройки |
| Предсказание застройки | `POST /api/urban/analyze/` `prediction` | Свободная земля рядом с застройкой |

Стек: Django 5.2 + Django REST Framework (бэкенд), vanilla JS + Leaflet + Vite (фронтенд), OpenCV/NumPy/Pillow (обработка изображений), PostgreSQL или SQLite (БД), locmem или Redis (кеш). Опционально PyTorch ResNet-18 (выключен по умолчанию).

Все внешние источники данных бесплатны и без ключей: Microsoft Planetary Computer (Sentinel-2), ISRIC SoilGrids, Open-Meteo (погода и рельеф), OpenStreetMap Overpass (границы полей), Nominatim (страна), ArcGIS World Imagery (тайлы подложки).

---

## 2. Архитектура и поток данных

```
Браузер (frontend/script.js)
   │  X-Device-Id: <uuid>          fetch(JSON)
   ▼
Django (config/urls.py → api/urls.py → api/views.py)
   │  DeviceAuthentication → User "device_<uuid>"
   │  ScopedRateThrottle: analysis 30/ч, crud 600/ч
   ▼
api/views.AnalysisView.parse_request
   │  serializers.AnalyzeRequestSerializer → validators.parse_bbox
   ▼
api/analysis/*  (fertility | vegetation | weeds | urban | environment)
   │
   ├─ api/services/sentinel.py ──► Planetary Computer (STAC + raster API, NDVI + SCL)
   ├─ utils/tiles.py ────────────► ArcGIS тайлы (fallback, RGB мозаика)
   ├─ api/services/elevation.py ─► Open-Meteo Elevation (сетка 10×10 высот)
   ├─ api/services/soilgrids.py ─► ISRIC SoilGrids (pH, N, SOC, CEC, clay, sand, wv0033)
   ├─ api/services/weather.py ───► Open-Meteo Forecast (текущая погода + осадки 7 дн)
   ├─ api/services/geocoding.py ─► Nominatim (страна) / фолбэк по bbox стран
   └─ api/services/osm_fields.py ► Overpass (полигоны farmland/meadow/…)
   │
   ▼
api/analysis/imagery.encode_overlay → PNG base64
   │
   ▼
Response JSON {overlay, stats, legend, method, imagery, environment}
   │  (при save_result=true и field_id) → SoilAnalysis / GrowthMonitoring / InvasiveSpeciesReport
   ▼
Браузер: L.imageOverlay на карту, renderResult → HTML в #results-container
```

Ключевые правила, которые проект соблюдает во всём бэкенде:

* каждый queryset фильтруется по `request.user` (нет анонимного доступа);
* пайплайны анализа принимают уже валидированный `bbox` и бросают `AnalysisError` с текстом для пользователя, а не возвращают `None`;
* каждый клиент внешнего сервиса сам отвечает за таймаут, кеш и возврат `None` при отказе; выдуманные значения запрещены;
* каждый ответ анализа говорит, чем он получен (`method`) и на каком снимке (`imagery`).

Порядок предпочтения источников для плодородия и зелёности: сначала Sentinel-2 NDVI (10 м, реальная дата съёмки, маска облаков). Если каталог недоступен, за 90 дней нет сцены с облачностью < 40 % или облака закрывают > 50 % области, происходит переключение на ExG по RGB-подложке (без даты, грубее). `DISABLE_SENTINEL=true` выключает первый путь принудительно.

---

## 3. Запуск и окружение

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt            # + requirements-ml.txt только для ResNet
cp backend/.env.example backend/.env
cd backend && python manage.py migrate && python manage.py loaddata api/fixtures/initial_data.json
python manage.py runserver                 # :8000
cd ../frontend && npm install && npm run dev   # :5173, /api проксируется на :8000
```

Проверки:

```bash
ruff check .                     # линт (проходит)
cd backend && python manage.py test        # 89 тестов, in-memory SQLite (проходят)
cd frontend && npm run build && npm test   # сборка + 37 jsdom-проверок (проходят)
```

Переменные окружения читаются в `backend/config/settings.py` (полный список в `backend/.env.example`). При `DJANGO_DEBUG=False` без `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS` или `DATABASE_URL` сервер отказывается стартовать.

Текущее состояние локального `backend/.env` (файл не в git): `DJANGO_DEBUG=True`, `DJANGO_ALLOWED_HOSTS=*`, `DATABASE_URL` указывает на хостинговый Neon PostgreSQL. См. [ошибку №4](#8-найденные-ошибки-и-риски).

Деплой: Dockerfile в корне собирает образ с gunicorn (2 воркера × 4 потока). `vercel.json` раздаёт только фронтенд и должен проксировать `/api` на хост бэкенда.

---

## 4. Аутентификация

Регистрации нет. Файл `backend/api/authentication.py`:

1. Браузер один раз генерирует UUID v4 (`crypto.randomUUID` или ручной фолбэк), хранит в `localStorage` под ключом `favorable-soil-device-id` и шлёт в заголовке `X-Device-Id`.
2. `DeviceAuthentication.authenticate` проверяет UUID регэкспом, ищет `User` с username `device_<uuid>`; если нет, создаёт с непригодным паролем. Гонка двух первых запросов ловится по `IntegrityError`.
3. Регистрация новых устройств ограничена 20 в час на IP (ключ в кеше `device-registrations:<ip>`); IP берётся из `X-Forwarded-For` без проверки доверенных прокси.
4. Запрос без заголовка → `None` → далее пробуются `TokenAuthentication` и `SessionAuthentication`; если никто не опознал, `IsAuthenticated` возвращает 401.

Последствие, заявленное в README: кто владеет UUID, владеет аккаунтом; очистка данных сайта = новый пустой аккаунт.

---

## 5. API

Все списки пагинированы (`{count, next, previous, results}`, 20 на страницу). Все эндпоинты требуют аутентификации.

| Метод | Путь | View | Throttle | Используется фронтендом |
|---|---|---|---|---|
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

`bbox` = `[запад, юг, восток, север]` в градусах, не больше 10° по стороне. `analysis_type` читает только `/api/urban/analyze/`. Ошибки: 400 (bbox/валидация), 401 (устройство не опознано), 404 (чужой или несуществующий `field_id`), 429 (лимит), 502 (внешний сервис не ответил, тело `{"error": "..."}`).

---

## 6. Модели базы данных

Файл `backend/api/models.py`. Все пользовательские записи имеют `user` (FK на `auth.User`, nullable; записи с `NULL` невидимы через API).

| Модель | Назначение | Ключевые поля | Связи |
|---|---|---|---|
| `Field` | Участок пользователя | `name`, `bounds_json` (TEXT, JSON-полигон), `center_lat/lon`, `area_hectares` | `user` CASCADE |
| `CropType` | Справочник культур (глобальный, только через admin) | pH/температура/NPK/влажность/сезон/урожайность | M2M `good_predecessors`, `bad_predecessors` на себя |
| `CropRotation` | Запись севооборота | `year`, `season`, `yield_amount` | `field`, `crop_type`; unique (`field`,`year`,`season`) |
| `SoilAnalysis` | Сохранённый анализ плодородия | проценты по классам, `fertility_index`, `overlay_image` (base64 PNG) | `field` CASCADE, `user` SET_NULL |
| `InvasiveSpeciesReport` | Очаг сорняка/вредителя | `species_name`, `severity`, `status`, координаты, `affected_area` | `field`, `user` |
| `GrowthMonitoring` | Наблюдение зелёности | `observation_date`, `ndvi_mean/min/max` (на деле ExG или NDVI), `health_score`, `growth_stage`, `ndvi_overlay` | `field`, `user`; unique (`field`,`observation_date`) |
| `WeedDatabase` | Справочник сорняков | `name`, `danger_level`, `control_methods` | нет |

Методы: `Field.get_bounds/set_bounds` (JSON), `CropType.check_soil_compatibility(ph, n, p, k, moisture)` (оценка 0..5 → проценты, список проблем и рекомендаций), `SoilAnalysis.calculate_fertility_index()` (взвешенная сумма процентов).

Миграции: `mainofbd` (начальная, сгенерирована Django 6.0.1) → `factsofplants` (агрономические поля `CropType`) → `0001_delete_feedbacklabel` → `0002_add_user_to_models`. `makemigrations --check` чист.

Фикстура `api/fixtures/initial_data.json`: 12 `CropType` и 5 `WeedDatabase`.

---

## 7. Разбор каждого файла

### 7.1 Корень репозитория

**`README.md`** — описание проекта на русском: источники данных, офсет отражения Sentinel-2, быстрый старт, аутентификация, таблица API, деплой. Актуален по смыслу, но говорит про 41 тест (реально 68).

**`Dockerfile`** — образ `python:3.12-slim`, ставит `libgl1`, `libglib2.0-0` для OpenCV, копирует только `backend/`, собирает статику через `collectstatic` (с `DJANGO_DEBUG=True` только на время сборки), запускает под непривилегированным пользователем `gunicorn config.wsgi:application --workers 2 --threads 4 --timeout 120`. Папка `ai model` в образ не попадает (см. `.dockerignore`), поэтому ResNet в контейнере недоступен по умолчанию.

**`.dockerignore`** — исключает `.git`, `venv`, `node_modules`, `frontend/dist`, `backend/.env`, `backend/db.sqlite3`, `ai model`, логи.

**`vercel.json`** — `buildCommand: npm run build`, `outputDirectory: frontend/dist`, rewrite `/api/:path*` → `https://REPLACE-WITH-YOUR-BACKEND-HOST/api/:path*`. Хостит только статику фронтенда.

**`package.json`** (корень) — скрипты-обёртки: `build` и `dev` делегируют в `frontend/`, `test` запускает Django-тесты. Зависимостей нет.

**`pyproject.toml`** — конфигурация ruff: длина строки 100, правила F/E/W/I/B/UP/C4, исключены миграции, venv, frontend.

**`requirements.txt`** — рантайм-зависимости с пинами: Django 5.2.16, DRF 3.17.1, django-cors-headers, dj-database-url, psycopg2-binary, numpy 2.5.1, Pillow, opencv-python-headless, requests, gunicorn, whitenoise, python-dotenv.

**`requirements-ml.txt`** — torch 2.13.0, torchvision 0.28.0, tqdm. Ставится только для обучения или включения модели на тайлах.

**`.gitattributes`** — LF для исходников, бинарные картинки, `*.pth` объявлен как Git LFS.

**`.gitignore`** — venv, node_modules, dist, `*.pyc`, `.env` (кроме `.env.example`), `*.sqlite3`, `*.log`, `backend/staticfiles`.

**`.github/workflows/ci.yml`** — два job'а. `backend`: Python 3.12, `pip install -r requirements.txt` + ruff, `ruff check .`, `makemigrations --check` (с `DJANGO_DEBUG=True`), `python manage.py test` (без переменных окружения), проверка, что `DJANGO_DEBUG=False manage.py check` падает без SECRET_KEY. `frontend`: Node 20, `npm ci`, `npm run build`, `npm test`, проверка, что в `dist/` есть JS-бандл и `index.html` не ссылается на голый `script.js`.

### 7.2 `backend/` — точки входа и конфигурация

**`manage.py`** — стандартный, но выбирает `config.settings_test`, если в аргументах есть `test`, иначе `config.settings`. Нужно, чтобы тесты не шли в хостинговую БД из `.env`.

**`config/settings.py`** — единственный источник настроек, всё из переменных окружения:

* `load_dotenv(BASE_DIR/'.env')` (не перекрывает уже заданные переменные);
* `env_bool`, `env_list` — парсеры;
* `DEBUG`, `SECRET_KEY` (в проде обязателен, иначе `ImproperlyConfigured`), `ALLOWED_HOSTS` (в DEBUG по умолчанию localhost/testserver), `CSRF_TRUSTED_ORIGINS`;
* `INSTALLED_APPS`: admin, auth, contenttypes, sessions, messages, staticfiles, rest_framework, rest_framework.authtoken, corsheaders, api;
* `MIDDLEWARE`: corsheaders первым, затем security, whitenoise, sessions, common, csrf, auth, messages, clickjacking;
* CORS: в DEBUG без списка — `CORS_ALLOW_ALL_ORIGINS=True`; заголовок `x-device-id` разрешён явно;
* `REST_FRAMEWORK`: аутентификация `DeviceAuthentication` → Token → Session; `IsAuthenticated`; `PageNumberPagination` по 20; `ScopedRateThrottle` со scope `analysis` (30/час) и `crud` (600/час);
* БД: `DATABASE_URL` через `dj_database_url` (`conn_max_age=600`, `ssl_require=not DEBUG`), иначе SQLite только в DEBUG;
* кеш: Redis при `REDIS_URL`, иначе `LocMemCache` (6 часов, 2000 записей);
* внешние сервисы: `GEOCODER_CONTACT`, `TILE_SERVER_URL` (ArcGIS), `MAX_TILES_PER_REQUEST=64`, `HTTP_TIMEOUT_SECONDS=8`, `SOIL_MODEL_PATH` (по умолчанию `<repo>/ai model/soil_model.pth`);
* безопасность в проде: `SECURE_PROXY_SSL_HEADER`, `SECURE_SSL_REDIRECT`, HSTS год, secure-cookies; всегда `X_FRAME_OPTIONS=DENY`, nosniff, referrer same-origin;
* логирование в консоль, логгеры `django`, `django.db.backends` (по умолчанию WARNING), `api`;
* `LANGUAGE_CODE='ru'`, `USE_TZ=True`, whitenoise `CompressedManifestStaticFilesStorage`.

**`config/settings_test.py`** — `from .settings import *`, затем: `DEBUG=False`, тестовый SECRET_KEY, SQLite `:memory:`, locmem-кеш, throttle выключен (`None`), MD5-хеши паролей, обычное static storage, SSL-редирект выключен, логи только ERROR.

**`config/urls.py`** — `admin/` и `api/` → `api.urls`.

**`config/wsgi.py`** — добавляет `backend/` и его родителя в `sys.path`, экспортирует `application` и алиас `app` (наследие Vercel).

**`config/asgi.py`** — стандартный ASGI, не используется в деплое.

### 7.3 `backend/api/` — приложение

**`api/apps.py`** — `ApiConfig`, BigAutoField.

**`api/urls.py`** — 25 маршрутов, все перечислены в разделе 5.

**`api/authentication.py`** — описано в разделе 4. Экспортирует `DeviceAuthentication`, константы `DEVICE_HEADER`, `USERNAME_PREFIX`, `NEW_DEVICE_LIMIT_PER_HOUR`, функцию `_client_ip`.

**`api/permissions.py`** — `IsOwner` (объект принадлежит `request.user`, `NULL` = ничей) и `IsOwnerOfField` (владелец через `obj.field`; в проекте нигде не подключён).

**`api/validators.py`** —
* `parse_bbox(raw)`: принимает строку `"a,b,c,d"` или список; проверяет 4 числа, конечность, диапазоны (широта ≤ 85.05 из-за Web Mercator), порядок, размер ≤ 10°; бросает `BBoxError` с русским текстом;
* `tile_span(bbox, zoom)`: сколько тайлов по x и y (импортирует `utils.tiles.deg2num` лениво, чтобы избежать циклического импорта);
* `choose_zoom(bbox, preferred, max_tiles)`: снижает зум, пока тайлов не станет ≤ бюджета;
* `metres_per_pixel(lat, zoom)`: разрешение пикселя тайла с учётом широты.

**`api/serializers.py`** —
* `FieldSerializer`: поля участка + `analyses_count`, `latest_fertility_index` (берутся из аннотаций queryset, иначе считаются запросом);
* `CropTypeSerializer`, `CropTypeBriefSerializer` (короткая форма для рекомендаций);
* `CropRotationSerializer` (+ `field_name`, `crop_type_name`);
* `SoilAnalysisListSerializer` (без `overlay_image`, с `has_overlay`) и `SoilAnalysisDetailSerializer` (с картинкой);
* `InvasiveSpeciesReportSerializer` / `...DetailSerializer` (с `image_base64`);
* `GrowthMonitoringListSerializer` (`index_type` всегда `'ExG'`) / `...DetailSerializer` (с `ndvi_overlay`);
* `WeedDatabaseSerializer`;
* входные: `AnalyzeRequestSerializer` (`bbox` JSONField, `field_id`, `save_result`), `UrbanAnalyzeRequestSerializer` (+ `analysis_type`), `PlantingRecommendationRequestSerializer` (pH 0–14, NPK ≥ 0, влажность 0–100).

**`api/views.py`** — все эндпоинты. Базовые классы:
* `OwnedQuerysetMixin`: `get_queryset` фильтрует `model.objects.filter(user=request.user)`, `perform_create` подставляет `user`; throttle `crud`;
* `AnalysisView(APIView)`: throttle `analysis`, `parse_request` валидирует тело, разбирает bbox, резолвит `field_id` через `get_object_or_404(Field, id=..., user=request.user)`;
* `analysis_error_response(exc)` → 502 `{"error": str(exc)}`.

Эндпоинты:
* `SessionView.get` — `authenticated`, `user_id`, `fields_count`, `capabilities` (`sentinel.is_available()`, `osm_fields.is_available()`);
* `AnalyzeView.post` — `fertility.analyze_fertility(bbox)` + `analyze_environment(bbox)`; при `save_result` и поле — создаёт `SoilAnalysis`, `non_fertile_percent = desert + water`, `notes = "Метод: …"`;
* `FieldListCreateView` — аннотирует `analyses_count_annotated` (Count) и `latest_fertility_index_annotated` (Subquery последнего анализа), сортирует `-created_at, -id`;
* `FieldDetailView` — RetrieveUpdateDestroy + `IsOwner`;
* `FieldDetectView.post` — `lat`, `lon`, `radius_m` → `osm_fields.lookup_fields`; пусто → 404; отдаёт до 50 полигонов;
* `CapabilitiesView.get` — флаги и названия источников;
* `CropTypeListView`, `CropTypeDetailView`, `WeedDatabaseListView` — read-only справочники с `prefetch_related`;
* `CropRotationListView` — список с фильтром `?field_id=`, `perform_create` проверяет, что `field.user_id == request.user.id` (единственное место с такой проверкой);
* `CropRotationRecommendationView.get` — по последней записи севооборота отдаёт `good_successors`, иначе первые 3 культуры;
* `CropPlantingRecommendationView.post` — прогоняет `check_soil_compatibility` по всем `CropType`, сортирует по проценту;
* `SoilAnalysisListView` (фильтр `?field_id=`), `SoilAnalysisDetailView` (RetrieveDestroy + `IsOwner`), `SoilAnalysisTimeSeriesView` (массивы дат и процентов);
* `GrowthMonitoringListView` (ListCreate), `GrowthMonitoringDetailView` (RetrieveDestroy + `IsOwner`);
* `GrowthAnalyzeView.post` — `vegetation.analyze_vegetation(bbox)`; при сохранении `update_or_create(field, observation_date=today)` в колонки `ndvi_*`;
* `GrowthTimeSeriesView.get` — ряд по полю + `vegetation.summarise_history`;
* `InvasiveSpeciesListView` (ListCreate), `InvasiveSpeciesDetailView` (RetrieveUpdateDestroy + `IsOwner`);
* `WeedDetectionView.post` — `weeds.detect_weeds(bbox)`; при сохранении `bulk_create` до 50 `InvasiveSpeciesReport`;
* `UrbanAnalyzeView.post` — словарь `_PIPELINES` → `urban.detect_buildings` / `predict_development` / `filter_urban_areas`; ответ `{data, overlay, method[, legend]}`;
* `DashboardView.get` — агрегаты по полям (`Count`, `Sum`), число активных отчётов, 5 последних анализов, 5 угроз.

**`api/admin.py`** — регистрация всех 7 моделей с `list_display`, фильтрами, поиском по `user__email`, `fieldsets`, `autocomplete_fields` для севооборота, `list_editable=['status']` для отчётов.

**`api/crop_catalog.py`** — статический `CROP_DATABASE` (39 культур: имя, иконка, диапазон pH, `temp_min`, `nitrogen_req`, описание) и `get_allowed_crops_for_country(name)` — грубый региональный фильтр (Средняя Азия / Казахстан / Россия-Беларусь-Украина / иначе `None` = без фильтра). Не связан с моделью `CropType`: используется для быстрой подсказки сразу после анализа.

**`api/tests.py`** — 68 тестов, 18 классов: аутентификация устройства, изоляция данных между устройствами, read-only справочник, валидация bbox, бюджет тайлов, разрешение, вывод химии почвы, рекомендации культур, дашборд, размер ответов, честность ответов анализа (метод, 502 при отказе), троттлинг, профили индексов, фолбэк Sentinel, офсет отражения, маска облаков, достижимость классов плодородия, OSM-поля. Внешние сервисы замоканы.

**`api/management/commands/`** — пусто, команд нет.

**`api/migrations/`** — см. раздел 6.

### 7.4 `backend/api/analysis/` — пайплайны анализа

**`analysis/__init__.py`** — описание конвенций (docstring), кода нет.

**`analysis/imagery.py`** — общие примитивы:
* `AnalysisError` — исключение с пользовательским текстом;
* `load_imagery(bbox, zoom)` → `utils.tiles.fetch_satellite_image`, `TileFetchError` переупаковывается в `AnalysisError`;
* `encode_overlay(rgba)` → `data:image/png;base64,…` через `cv2.imencode`;
* `excess_green_index(rgb)` — ExG = (2G−R−B)/(2G+R+B), клип [−1, 1]; явно «не NDVI»;
* `local_variance(rgb, kernel=7)` — текстура через blur;
* `water_mask(rgb)` — HSV-синий или очень тёмный **и** гладкий (иначе асфальт и крыши считались водой);
* `paint`, `percentage`, `upsample_grid` (INTER_NEAREST).

**`analysis/fertility.py`** —
* константы: `ZOOM=13`, метки классов `L_BARE…L_VERY_HIGH`, `STEEP_SLOPE_PERCENT=15`, палитра `COLOURS`, `LEGEND`, пороги `_EXG_BANDS` (калиброваны под ArcGIS-подложку) и `_NDVI_BANDS` (0.15/0.30/0.45/0.60), `NDVI_WATER_THRESHOLD=−0.05`;
* `model_enabled()` — `ENABLE_SOIL_MODEL_ON_TILES`;
* `load_soil_model()` — ленивая загрузка ResNet-18 с 3 выходами из `settings.SOIL_MODEL_PATH`; без torch/весов → `(None, None)` и состояние `unavailable`;
* `_classify_by_vegetation(index, land_mask, bands)` — `np.select` по порогам сверху вниз;
* `_steep_terrain_mask(bbox, shape)` — `elevation.fetch_elevation_grid` → `slope_percent` → апсемплинг → `> 15 %`; без DEM маска пустая и `elevation_model=None`;
* `_classify_with_model(image, labels, land_mask, grid_size=10)` — режет мозаику на 100 клеток, гонит батчем через ResNet, перекрашивает клетки с ≥ 50 % суши;
* `_build_result(labels, bbox, method, imagery_meta)` — RGBA-оверлей, `np.bincount` по классам, статистика `very_high/high/moderate/low/mountains/water/desert`;
* `_from_sentinel(bbox)` — NDVI + маска валидности → вода (`ndvi < −0.05`), крутизна, классификация; невалидные пиксели = `L_BARE`; `method = 'NDVI по Sentinel-2 + уклон по DEM'`;
* `_from_basemap(bbox)` — RGB-мозаика → `water_mask` → крутизна → ExG-классы; опционально ResNet (`method` меняется на «ResNet-18 … (экспериментально)»);
* `analyze_fertility(bbox)` — сначала Sentinel, при `SentinelUnavailable` → подложка.

**`analysis/vegetation.py`** —
* `IndexProfile` — пороги стадий роста, шкала здоровья, палитра для одного индекса; экземпляры `NDVI` (0.10/0.20/0.40/0.60, здоровье 0..0.85) и `EXG` (0.02/0.06/0.12/0.18, здоровье −0.10..0.25);
* `_paint(index, profile, shape)` — раскраска, NaN прозрачный, ниже нижнего порога — «вода»;
* `analyze_vegetation(bbox)` — Sentinel → фолбэк;
* `_from_sentinel` — `sentinel.fetch_ndvi_stats` → статистика, оверлей, `index_type='NDVI'`;
* `_from_basemap` — ExG по мозаике, `index_type='ExG'`;
* `summarise_history(records)` — тренд по среднему второй половины ряда минус первой (порог ±0.03): `improving/declining/stable/insufficient_data`.

**`analysis/weeds.py`** — `detect_weeds(bbox)`: зум 14; маска растительности по HSV; локальная дисперсия серого; аномалия = дисперсия выше 75-го перцентиля среди растительности; морфология close/open; контуры ≥ 100 px; для каждого — центр в градусах, площадь в м² через `imagery.pixels_to_area_sqm`, `severity` по площади (1 000 / 5 000 / 20 000 м²), `anomaly_strength`, рекомендация из `RECOMMENDATIONS`. Явно `is_species_identified: False`. Без растительности возвращает пустой результат с `note`.

**`analysis/urban.py`** — три эвристики на оптике:
* `detect_buildings` (зум 15): CLAHE → Canny → close → контуры; фильтр по площади ≥ 50 px, 3–6 вершин, соотношение сторон 0.2–5; плотность → тип района; список до 200 зданий с координатами и площадью;
* `predict_development` (зум 14): застройка = дилатированные края; непригодное = вода ∪ лес (HSV); зона расширения = дилатация застройки ×5; свободная = расширение ∩ доступное; проценты, статус, рекомендации;
* `filter_urban_areas` (зум 14): застройка = текстура минус (растительность ∪ вода); статистика `urban/veg/water_percent` и легенда.

**`analysis/environment.py`** —
* `analyze_environment(bbox)`: центр bbox → `geocoding.reverse_geocode_country`, `weather.fetch_weather`, `soilgrids.fetch_soil_properties`; влажность через `soilgrids.estimate_current_moisture(wv0033, осадки_7д)`; собирает `weather`, `soil_chemistry` (со словарём `sources`: measured/derived/unavailable), `warnings`, `recommendation` (`chemistry_recommendation`), `crops` (`recommend_crops`);
* `recommend_crops(environment, limit=3)`: по `CROP_DATABASE` с региональным фильтром; баллы только по известным критериям (pH — 2, температура — 2, азот — 1); pH вне диапазона более чем на 0.5 → культура отбрасывается; < 50 % совпадения отбрасывается; топ-3.

### 7.5 `backend/api/services/` — клиенты внешних сервисов

**`services/__init__.py`** — конвенция: один модуль = один сервис; при отказе `None`.

**`services/http.py`** — `build_session(user_agent)` и `get_json(session, url, params, timeout, service)`: GET, таймаут из настроек, любой отказ (таймаут, сеть, не-200, не-JSON) логируется и превращается в `None`.

**`services/sentinel.py`** — Planetary Computer:
* `is_available()` — только `DISABLE_SENTINEL`;
* `_ndvi_expression(baseline)` — при baseline ≥ 4.0 (или неизвестном) формула `(B08−B04)/(B08+B04−2000)` с учётом `BOA_ADD_OFFSET`;
* `search_scene(bbox, lookback=90, max_cloud=40)` — POST на STAC `/search`, последняя сцена; ошибки → `SentinelUnavailable`;
* `_fetch_raster(bbox, size, params)` — GET `/item/bbox/{bbox}/{size}x{size}.npy` → `np.load`;
* `fetch_ndvi_array(bbox, size=512)` — кеш `sentinel-ndvi:<size>:<bbox 4 знака>` на 6 часов; параллельно качает NDVI и SCL (`ThreadPoolExecutor(2)`); валидные классы SCL 4,5,6,7,11; покрытие < 50 % → `SentinelUnavailable`; кладёт в кеш `(ndvi.tolist(), valid.tolist(), metadata)`; `metadata.metres_per_pixel` всегда 10;
* `fetch_ndvi_stats(bbox)` — mean/min/max/std по валидным пикселям + сырые массивы.

**`services/soilgrids.py`** — ISRIC SoilGrids v2.0, слой 0–5 см, кеш 30 дней по координатам с 3 знаками:
* `_extract_layers(payload)` — значения делятся на `d_factor` (или фолбэк-таблицу);
* выводные формулы: доступный N = общий N × 1000 × 2 %; обменный K = CEC × 3 % × 391; Olsen-P ≈ 4 + 1.1·SOC − 0.15·max(0, clay−30), клип 3..60; `_texture_label(clay, sand)`;
* `fetch_soil_properties(lat, lon)` — `{ph, texture, organic_carbon, clay_percent, water_holding_capacity, nitrogen, potassium, phosphorus, provider, depth}` с `source` у каждого; без `phh2o` → негативный кеш на час и `None`;
* `estimate_current_moisture(whc, rain_7d)` — `whc × (0.4 + 0.6 × min(1, rain/25))`.

**`services/weather.py`** — Open-Meteo forecast: текущие температура, влажность, ветер (м/с), код погоды → `describe_weather_code`; `daily.precipitation_sum` с `past_days=7` → сумма за 7 прошедших дней; кеш 30 минут по координатам с 2 знаками; отказ → негативный кеш 5 минут.

**`services/elevation.py`** — Open-Meteo Elevation (Copernicus GLO-90): `_grid_coordinates` (10×10 центров ячеек, строка 0 — север), `fetch_elevation_grid(bbox)` (один запрос на 100 точек, кеш 90 дней), `slope_percent(grid, bbox)` (`np.gradient` с реальным шагом в метрах, `hypot × 100`).

**`services/geocoding.py`** — Nominatim reverse с `zoom=5`, `accept-language=ru`, User-Agent с `GEOCODER_CONTACT`; кеш 30 дней по координатам с 1 знаком; при отказе `approximate_country(lat, lon)` по прямоугольникам стран (порядок: от меньших к большим) и флаг `is_approximate=True`.

**`services/osm_fields.py`** — Overpass: `_build_query` (`way`/`relation` с `landuse~farmland|meadow|orchard|vineyard|greenhouse_horticulture|allotments` в радиусе), `_ring_area_sqm` (формула шнурков на локальной плоскости), `_element_to_feature` (→ `{id, type, type_label, name, crop, area_sqm, area_hectares, bounds [[lat,lon]…], bbox, source}`), `lookup_fields(lat, lon, radius)` (радиус клипуется 100..5000, кеш 7 дней, пусто → негативный кеш 6 часов и `None`), `nearest_field` (содержащий точку, иначе крупнейший; в проекте не вызывается).

### 7.6 `backend/utils/tiles.py`

Единственное место, которое ходит на тайл-сервер:
* `SatelliteImage` — dataclass: `pixels` (H×W×3 uint8), `bounds` `[[min_lat,min_lon],[max_lat,max_lon]]`, `zoom`, `metres_per_pixel`, `tiles_requested/retrieved`, метод `pixels_to_area_sqm`;
* `deg2num` / `num2deg` — стандартные преобразования slippy-map;
* `download_tile(x, y, z)` — кеш `tile:z:x:y` на 7 дней (негативный кеш `b''` на 404), таймаут `HTTP_TIMEOUT_SECONDS`, декодирование через Pillow;
* `fetch_satellite_image(bbox, zoom=13)` — `choose_zoom` по бюджету `MAX_TILES_PER_REQUEST`, параллельная загрузка (8 потоков), склейка в мозаику; 0 тайлов или меньше половины → `TileFetchError`.

Папка `utils/` без `__init__.py` работает как namespace-пакет.

### 7.7 `frontend/`

**`index.html`** — одна страница: сайдбар (Дашборд, Карта & Анализ, выбор темы), секция дашборда (5 карточек статистики, история активности, сводка), секция анализа (карта Leaflet, тулбар с `<select id="analysis-type-select">` и кнопкой «Анализировать», кнопка PDF через `window.print()`, панель привязки к полю с `#field-select`, форма создания поля, скрытая кнопка `#detect-field-btn`, блок ошибок, легенда, `#results-container`). Leaflet 1.9.4 и leaflet.draw 1.0.4 с CDN (с SRI). Приложение подключено как `<script type="module" src="/script.js">`, что даёт Vite собрать бандл. В `<style>` в шапке принудительно скрыты `.env-icon` и `.forecast-icon`.

**`script.js`** — вся логика (1386 строк), ключевые части:
* `API_URL`: `http://127.0.0.1:8000/api` на localhost/file, иначе `/api`;
* `getDeviceId` / `fallbackUuid` / `getAuthHeaders` — идентичность устройства;
* `escapeHtml`, `formatNumber`, `formatDate`, `readList` (распаковка пагинации);
* `checkAuthSession` — `GET /session/`, применяет `capabilities` (`applyCapabilities` показывает кнопку автоопределения);
* `LAND_PRICES` + `getLandPriceConfig` — справочные цены земли по стране (жёстко зашиты, помечены как ориентир);
* `lookupPlace` — прямой вызов Nominatim из браузера с кешем по 3 знакам;
* `changeTheme` — переключение CSS-переменных, сохранение в `localStorage`;
* `sessionStats` — счётчики сессии (анализов, здоровья, сорняков, активности), таймер;
* `DOMContentLoaded`: `initMap`, `switchPage('analysis')`, `checkAuthSession`, `loadFields`, тема, обработчик выбора поля (рисует полигон из `bounds_json`, `fitBounds`), дата печати;
* `loadFields` — `GET /fields/` → `<select>`;
* `saveFieldFromMap` — сохраняет прямоугольник `currentBounds` как поле (`POST /fields/`), площадь по плоской формуле;
* `switchPage`, `setAnalysisType` (заголовки, сброс оверлея/легенды/результатов);
* `initMap` — карта на Душанбе (38.55, 68.78, зум 12), ArcGIS-подложка, `L.FeatureGroup` + `L.Control.Draw` с `draw: false` (только редактирование), `moveend` → `currentBounds = map.getBounds()`, если нет нарисованного слоя;
* `runAnalysis` — bbox из `currentBounds`, выбор эндпоинта по `currentAnalysisType`, `field_id` из селекта, `save_result` из `#save-result-check`, `POST`, ошибки → `describeHttpError` (401/429/400/502 с текстом сервера);
* `updateDashboard` — статистика сессии, курсы валют с `api.exchangerate-api.com`, справочная стоимость земли, 3-дневный прогноз Open-Meteo, последняя активность;
* `renderResult(data)` — обновляет счётчики, ставит `L.imageOverlay`, `updateLegend`, строит HTML для зелёности / плодородия / сорняков / инфраструктуры / прогноза застройки / агроклимата (с бейджами «измерено / расчёт / нет данных») и карточек культур (`renderCropsBottom`); `renderImageryNote` показывает источник, дату съёмки, провайдера, м/пиксель, облачность, DEM;
* `detectField` — `POST /fields/detect/` → полигон первого участка на карту;
* `renderBar`, `updateLegend` (легенда сервера или дефолтные для ndvi/weeds), `setLoading`, `setError`.

**`style.css`** — тёмная тема по умолчанию через CSS-переменные, шрифт Outfit с Google Fonts, макет сайдбар + контент, карточки, бейджи, бары статистики, легенда, лоадер, печать (`.print-header`).

**`vite.config.js`** — `outDir: dist`, sourcemap, порт 5173, прокси `/api` → `http://127.0.0.1:8000`.

**`package.json`** — `dev`/`build`/`preview`/`test`; зависимость `leaflet` (фактически грузится с CDN), dev: `vite ^5`, `jsdom ^25`.

**`test/smoke.test.mjs`** — грузит `dist/index.html` и бандл в jsdom, подменяет `L` и `fetch`, проверяет 28 утверждений: рендер плодородия, XSS-экранирование, зелёность ExG/NDVI, отсутствие `null` при пустых данных, дату съёмки Sentinel-2, тексты ошибок для 400/502/429/401, отсутствие ошибок в консоли.

**`dist/`** — результат `vite build` (в git не входит).

### 7.8 `ai model/`

**`distribute_dataset.py`** — одноразовый скрипт с абсолютными Windows-путями: раскладывает Soil-Classification-Dataset (Alluvial/Black → high, Red/Yellow/Mountain → medium, Arid/Laterite → low) на train/val 80/20.

**`train.py`** — дообучение ResNet-18 (`pretrained=True`, старый API torchvision) на `./dataset`, 10 эпох, Adam 1e-3, сохраняет `soil_model.pth` (state_dict).

**`predict.py`** — CLI: `--image`, `--model`; загружает state_dict, классифицирует один снимок, печатает класс, уверенность, описание и рекомендацию. `CLASS_NAMES` в алфавитном порядке ImageFolder: `high_fertility, low_fertility, medium_fertility`.

**`soil_model.pth`** — веса, 44.8 МБ, лежат в git как обычный blob (не LFS-указатель).

Модель обучена на макроснимках почвы с земли; применение к спутниковым тайлам в `fertility._classify_with_model` не валидировано и выключено по умолчанию.

---

## 8. Найденные ошибки и риски

Отсортированы по серьёзности. «Подтверждено» означает, что дефект воспроизведён в этой сессии.

**Статус на 13 сентября 2026 (после доработки, см. раздел 10):** исправлены пункты 1, 2, 3, 6, 7, 8, 9, 13. Пункты 4, 5, 10, 11, 12 и остальные требуют действий вне кода (переменные окружения, LFS, Redis, деплой) и остаются открытыми.

### Критичные (ломают основную функциональность или безопасность)

**1. Результаты анализа никогда не сохраняются из интерфейса.** Подтверждено.
`frontend/script.js:554` читает чекбокс `#save-result-check`, которого нет в `index.html`. Поэтому `save_result` всегда `false`, и ветки сохранения в `backend/api/views.py:146` (SoilAnalysis), `:445` (GrowthMonitoring), `:525` (InvasiveSpeciesReport) из UI недостижимы. История анализов, временные ряды, дашборд бэкенда и связка «поле → анализы» пусты для всех пользователей. Исправление: добавить чекбокс «Сохранить результат» в панель привязки к полю, либо сохранять автоматически, когда выбрано поле.

**2. Запись в чужие участки через `/api/growth/` и `/api/invasive/`.** Подтверждено (оба запроса вернули 201).
`GrowthMonitoringListView` (`views.py:422`) и `InvasiveSpeciesListView` (`views.py:502`) используют `perform_create` из `OwnedQuerysetMixin`, который подставляет `user`, но не проверяет владельца `field`. `InvasiveSpeciesDetailView` (`views.py:510`) через PUT тоже позволяет переназначить `field`. Проверка есть только в `CropRotationListView.perform_create` (`views.py:306`). Дополнительный эффект: `GrowthMonitoring` имеет `unique_together (field, observation_date)`, поэтому чужая запись на сегодняшнюю дату перехватывается `update_or_create` жертвы и перезаписывается. Исправление: вынести проверку из `CropRotationListView` в `validate_field` сериализаторов или в общий миксин.

**3. CI-шаг «Run tests» падает.** Подтверждено симуляцией без `.env`.
`config/settings_test.py` начинается с `from .settings import *`; `settings.py:49` бросает `ImproperlyConfigured` о `DJANGO_SECRET_KEY`, потому что в CI нет `.env` и `DJANGO_DEBUG` не задан. Локально всё проходит только благодаря `.env` с `DJANGO_DEBUG=True`. Исправление: в `settings_test.py` перед импортом сделать `os.environ.setdefault('DJANGO_DEBUG', 'True')` и `setdefault('DJANGO_SECRET_KEY', 'test')`, либо добавить `env:` в шаг CI.

**4. Локальный `.env` направляет разработку в продовую БД и открывает DEBUG.**
`backend/.env`: `DJANGO_DEBUG=True`, `DJANGO_ALLOWED_HOSTS=*`, `DATABASE_URL` на Neon. `runserver`, `migrate`, `loaddata` и любые ручные эксперименты идут в хостинговую базу. Если этот же файл используется как источник переменных на хостинге, сайт работает с `DEBUG=True` (трейсбеки с настройками наружу, `CORS_ALLOW_ALL_ORIGINS=True`, `ssl_require=False`). Исправление: локально убрать `DATABASE_URL` (SQLite), прод-переменные задавать в панели платформы с `DJANGO_DEBUG=False`.

**5. Деплой фронтенда на Vercel неработоспособен.**
`vercel.json` проксирует `/api` на `https://REPLACE-WITH-YOUR-BACKEND-HOST/…` — плейсхолдер, все запросы уйдут в никуда. Кроме того, `buildCommand: npm run build` выполняется из корня, где `package.json` не имеет зависимостей; `vite` лежит только в `frontend/node_modules`, так что без `installCommand: npm ci --prefix frontend` (или `rootDirectory: frontend`) сборка, скорее всего, упадёт с «vite: command not found». Не запускалось на Vercel, вывод по конфигурации.

### Серьёзные

**6. 500 на `/api/fields/detect/` при нечисловом `radius_m`.** Подтверждено (`ValueError` в `osm_fields.py:122`). `views.py:227` передаёт значение как есть. Исправление: валидировать через сериализатор с `IntegerField(min_value=100, max_value=5000)`.

**7. Пользователь не может нарисовать область.** `script.js:503` создаёт `L.Control.Draw` с `draw: false`, поэтому событие `L.Draw.Event.CREATED` не срабатывает никогда, а `currentBounds` всегда равен видимой области карты. Надпись «Выберите область на карте» вводит в заблуждение; при зуме ниже ~7 запрос получает 400 «область слишком велика», при среднем зуме бэкенд снижает разрешение до 64 тайлов. Сохранённое «поле» — это прямоугольник экрана. Исправление: включить `draw: { rectangle: true, polygon: true, … }`.

**8. Кеш Sentinel съедает память.** `sentinel.py:265` кладёт 512×512 NDVI и маску как Python-списки; измеренный размер одной записи после pickle — 2.6 МБ. При `MAX_ENTRIES=2000` в locmem это до ~5 ГБ на процесс, а gunicorn запускает два. Исправление: хранить `np.save` в bytes или float16 и уменьшить TTL/лимит.

**9. Неверная метка разрешения для Sentinel-2.** `sentinel.py:261` всегда пишет `metres_per_pixel: 10`, хотя растр 512×512 растягивается на любой bbox (для области 20 км это 40 м/пиксель). UI показывает «10 м/пиксель». Исправление: считать `(max_lon−min_lon)·111320·cos(lat)/size`.

**10. Веса модели в git как 44 МБ blob при объявленном LFS.** `.gitattributes` требует LFS для `*.pth`, `git lfs` на машине не установлен, файл закоммичен обычным объектом. У коллеги с LFS `git add` создаст указатель, и история станет несогласованной; каждый клон качает 44 МБ. Исправление: либо `git lfs migrate import --include="*.pth"`, либо убрать правило и хранить веса вне git.

**11. Лимит 20 новых устройств в час на IP блокирует пользователей за NAT.** `authentication.py:33`. В вузе, офисе или у мобильного оператора 21-й новый посетитель получает 401 и сообщение «обновите страницу», которое не помогает. При этом `_client_ip` (`authentication.py:96`) доверяет `X-Forwarded-For` от любого клиента, так что лимит обходится подделкой заголовка. Исправление: считать по реальному адресу за доверенным прокси и поднять лимит либо заменить на глобальный.

**12. Троттлинг и кеш живут в памяти процесса.** Без `REDIS_URL` при двух воркерах лимиты 30/час фактически 60/час, кеш тайлов и SoilGrids дублируется, а `device-registrations` считается раздельно. README это признаёт, но в проде это надо закрыть Redis.

### Средние

**13. Незаданная CSS-переменная `--primary-rgb`.** `index.html:168`, `script.js:646`, `:1162` используют `rgba(var(--primary-rgb), 0.1)`; переменной нет ни в `style.css`, ни в `changeTheme`. Фон этих элементов не рисуется.

**14. Незаэкранированные вставки в innerHTML.** `script.js:855–858` (`last.text`, `last.type`, `last.time`), `:1062` (`building_density`), `:1076` (`growth_status`). Значения приходят с сервера, поэтому XSS возможен только при компрометации бэкенда или MITM, но проект в остальном экранирует всё через `escapeHtml`, и эти места выбиваются.

**15. Base64-картинки в TEXT-колонках.** `SoilAnalysis.overlay_image`, `GrowthMonitoring.ndvi_overlay`, `InvasiveSpeciesReport.image_base64` — до сотен КБ на строку. На бесплатном Neon это быстро упирается в квоту. Разумнее хранить файлы в объектном хранилище или ужимать PNG.

**16. Внешние вызовы прямо из браузера.** `script.js:149` (Nominatim без идентифицирующего User-Agent, который браузер не даёт задать) и `:662` (`api.exchangerate-api.com`, без ключа и SLA). Первый нарушает политику Nominatim при частом обновлении дашборда, второй может пропасть в любой момент; оба тянутся при каждом `updateDashboard`.

**17. Ненадёжный `bounds_json`.** `FieldSerializer` принимает любую строку; `JSON.parse` на фронтенде упадёт тихо в `console.error`. Стоит валидировать JSON и структуру полигона на сервере.

**18. Разные версии Python.** Локальный venv — Python 3.14.5, Dockerfile — 3.12, ruff `target-version` — py311. Тесты локально проходят, но поведение зависимостей на 3.14 и 3.12 может отличаться.

**19. Курс валют и стоимость земли выдуманы.** `LAND_PRICES` в `script.js:114` жёстко зашиты и показываются в карточке «Стоимость земли» на дашборде. Подписано как ориентир, но в главной статистике выглядит как факт.

### Мелкие

**20. Испорченные эмодзи в разметке.** В `index.html` и `script.js` (заголовки, `getIconForType`, тексты кнопок) остались одиночные символы U+FE0F без базового эмодзи и пустые `<span class="nav-item-icon">`. В шапке `index.html` иконки прогноза и агроклимата принудительно скрыты `display:none !important`.

**21. Кнопка меняет подпись.** `setLoading(false)` ставит текст « Анализировать состояние», хотя исходно было «Анализировать».

**22. Несогласованные цифры в документации.** README: 41 тест (реально 68), 63 участка в Баварии (в `osm_fields.py` — 120).

**23. Региональный фильтр ссылается на отсутствующие культуры.** `crop_catalog.py`: «Ячмень», «Вишня» есть в списках стран, но не в `CROP_DATABASE`; 33 из 39 культур без иконки.

**24. Мусор в рабочей директории.** `backend/db_queries.log` (от старой конфигурации логирования), `backend/db.sqlite3`, `.ruff_cache` в двух местах. Всё в `.gitignore`, но сбивает с толку.

**25. Нестандартные имена миграций.** `mainofbd`, `factsofplants` вместо нумерованных; первая сгенерирована Django 6.0.1, следующая 5.2.9. Работает, но затрудняет чтение истории.

**26. Огромный незакоммиченный рефакторинг.** В рабочем дереве 28 изменённых файлов (+3120/−1967), 4 удалённых (`backend/README.md`, `api/auth_views.py`, `api/processing.py`, `vercel_app.py`) и 15 новых, последний коммит от 10 августа. Ссылок на удалённые модули не осталось, всё работает, но всё это может быть потеряно одной командой. Стоит закоммитить.

---

## 9. Неподключённый и мёртвый код

* **Эндпоинты без UI**: `/api/dashboard/`, `/api/soil-analyses/*`, `/api/growth/` (list/detail/timeseries), `/api/invasive/*`, `/api/crops/*`, `/api/rotations/*`, `/api/weeds/database/`, `/api/capabilities/`, `/api/fields/{id}/`. Бэкенд полный, фронтенд использует только 7 маршрутов.
* **`permissions.IsOwnerOfField`** — нигде не подключён.
* **`osm_fields.nearest_field`** — не вызывается.
* **`Field.get_bounds/set_bounds`** — не используются в API.
* **`config/asgi.py`** — не используется (gunicorn запускает WSGI).
* **`wsgi.app`** — алиас для Vercel, который больше не нужен.
* **`api/management/commands/`** — пустой пакет.
* **ResNet-18 в `fertility._classify_with_model`** — за флагом `ENABLE_SOIL_MODEL_ON_TILES`, torch не в основных зависимостях, весов в Docker-образе нет.
* **`ai model/distribute_dataset.py`** — привязан к путям на конкретной Windows-машине.
* **`frontend/script.js`**: `setAnalysisType` ищет кнопки `#tab-*`, которых нет; `L.Draw.Event.CREATED` не срабатывает из-за `draw: false`.
* **`db_queries.log`** — никакая текущая конфигурация в него не пишет.

---

## 10. Доработка от 13 сентября 2026: официальные источники вместо эвристик

Цель: чтобы каждое число в интерфейсе имело названный публичный источник и погрешность. Всё бесплатно и без ключей; используются два клиента, которые уже были в проекте (Planetary Computer и SoilGrids), плюс Overpass.

### Что изменилось по типам анализа

| Анализ | Было | Стало | Файлы |
|---|---|---|---|
| Плодородие | один снимок NDVI → классы | композит: пик и среднее NDVI за 3 сезона (65 %) + оценка почвы SoilGrids (35 %); вода, застройка, снег по WorldCover; уклон по DEM. Фолбэки: одна сцена → ExG | `analysis/fertility.py`, `services/sentinel.py`, `services/soilgrids.py`, `services/worldcover.py` |
| Зелёность | NDVI + стадия | + NDMI (влажность покрова, B08/B11), + отклонение от NDVI того же окна за 2 прошлых года с подписью | `analysis/vegetation.py`, `services/sentinel.py` |
| Сорняки | текстурная дисперсия RGB | отклонение NDVI от медианы поля (> 2 MAD) только внутри пашни, луга и кустарника по WorldCover; направление «зеленее/бледнее»; явная `note`, что вид не определяется. Фолбэк: старая текстура | `analysis/weeds.py` |
| Инфраструктура | Canny-контуры | класс «застройка» WorldCover + контуры зданий OSM (до 12 км², до 3000 зданий). Фолбэк: Canny | `analysis/urban.py`, `services/buildings.py` |
| «Предсказание застройки» | морфология RGB | переименовано в «Динамика застройки»: WorldCover 2020 → 2021, изменение в п.п., новая застройка на оверлее, свободная пашня/луг у застройки. Фолбэк: старая морфология | `analysis/urban.py` |
| Покров земли | HSV-маски | 11 классов WorldCover с официальной легендой и заявленной точностью | `analysis/urban.py`, `services/worldcover.py` |
| Агроклимат | средние SoilGrids | + диапазоны Q5–Q95 для pH, углерода, ЁКО, глины, влагоёмкости; + ЁКО и разрешение 250 м в ответе | `services/soilgrids.py`, `analysis/environment.py` |

### Новые модули

* **`services/worldcover.py`** — `fetch_landcover(bbox, year, size)` → массив классов + метаданные; `class_percentages`, `paint`, `legend`; константы классов; кеш 30 дней; `DISABLE_WORLDCOVER` для отключения.
* **`services/buildings.py`** — `lookup_buildings(bbox)` через Overpass `way["building"]`; отказ при площади > 12 км²; кеш 7 дней.
* **`services/sentinel.py`** — добавлены `search_scenes`, `fetch_seasonal_productivity` (лучшая сцена на месяц, апрель–сентябрь, до 3 лет, параллельная загрузка), `fetch_ndmi_mean`, `fetch_reference_ndvi`, `resolution_for` (честные м/пиксель), `_pack/_unpack` (кеш через `np.savez_compressed`: 2.6 МБ → ~0.3 МБ на запись).
* **`services/soilgrids.py`** — `soil_quality_score(properties)` → `(0..1, factors)` по правилам: pH оптимум 6.0–7.5, SOC 20 г/кг = 1.0, ЁКО 25 = 1.0, текстура (песок ≥ 70 % → 0.4, глина ≥ 60 % → 0.6).

### Замеры на реальных сервисах (bbox 3×3 км, орошаемая пашня у Чиназа)

| Пайплайн | Холодный запуск | Метод в ответе |
|---|---|---|
| Плодородие | 48 с (18 сцен) | NDVI Sentinel-2 за 3 сезона + почва SoilGrids + покров WorldCover + уклон DEM |
| Зелёность | 11 с | NDVI + NDMI 0.089 + отклонение +0.040 от 2024–2025 |
| Сорняки | < 1 с (из кеша сцены) | 21 очаг, медиана NDVI поля 0.508 |
| Инфраструктура | 2 с | WorldCover 13 % застройки + 3 здания OSM |
| Динамика | < 1 с | застройка +1.18 п.п. 2020→2021 |

Над центром Ташкента SoilGrids возвращает `null` (города замаскированы в исходных растрах), и индекс честно строится по одной продуктивности с пометкой в `components.soil.note`.

### Исправленные ошибки из раздела 8

1. Чекбокс `#save-result-check` добавлен в `index.html`, включён по умолчанию — результаты теперь сохраняются в выбранное поле.
2. `OwnedFieldMixin.validate_field` в `serializers.py` для севооборота, мониторинга и отчётов — чужое поле даёт 400. Покрыто тестами `CrossTenantWriteTests`.
3. `settings_test.py` ставит `DJANGO_DEBUG`/`DJANGO_SECRET_KEY` до импорта настроек — тесты проходят без `.env` (проверено симуляцией CI).
6. `FieldDetectRequestSerializer` валидирует `lat`, `lon`, `radius_m` (100–5000).
7. В `L.Control.Draw` включены прямоугольник и полигон.
8. Кеш Sentinel хранит сжатые массивы.
9. `metres_per_pixel` считается из размера bbox и растра.
13. Переменная `--primary-rgb` объявлена в `style.css` и переключается в `changeTheme`.

### Что не сделано и почему

* **FAO GAEZ v4** (пригодность культур, почвенные ограничения) — требует ручной загрузки растров с портала GAEZ; код подбора культур пока прежний.
* **Microsoft Global Building Footprints** — файлы по регионам весят сотни МБ, разумно загрузить их в PostGIS при деплое; сейчас здания берутся из OSM.
* **Pl@ntNet** для определения вида по фото — нужен бесплатный ключ и загрузка фото с клиента; не входит в текущий UI.
* Пункты 4 (локальный `.env` с продовой БД), 5 (Vercel), 10 (LFS), 11–12 (лимит устройств, Redis) — операционные, вне кода.

### Проверки после доработки

`ruff check .` чист, `manage.py test` — 89 тестов проходят (в том числе без `.env`), `npm run build && npm test` — 37 проверок проходят.
