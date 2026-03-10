# Gesture YOLO HA (Русский)

Gesture YOLO HA — система распознавания жестов для Home Assistant с несколькими видеопотоками.
Поддерживает YOLO `.pt`, встроенную модель MediaPipe, MQTT Discovery и многоязычный веб-интерфейс.

## 1. Возможности

- Несколько видеопотоков (USB / RTSP)
- Модели:
  - YOLO `.pt` (загрузка через веб)
  - Встроенная `mediapipe_hands`
- Переключение моделей:
  - Глобально
  - Для каждой карточки отдельно
- Веб-интерфейс:
  - Матрица онлайн-мониторинга
  - Клонирование карточек
  - Копирование MQTT topic
  - Переключение языка (中文 / English / Русский)
- Интеграция с Home Assistant через MQTT Discovery

## 2. Требования

- Python 3.10+ (рекомендуется 3.11)
- Доступ к видеопотокам
- MQTT Broker + MQTT Integration в Home Assistant

## 3. Быстрый запуск

### Windows PowerShell

```powershell
cd gesture-yolo-ha
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Linux / macOS

```bash
cd gesture-yolo-ha
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Откройте: `http://127.0.0.1:8000/`

## 4. Конфигурация (.env)

Основные переменные:

- `HOST`, `PORT`
- `MODEL_DIR`, `MODEL_FILE` (`.pt` или `mediapipe_hands`)
- `SOURCE` (`0`, `rtsp://...` или `auto`)
- `CONF`, `IOU`, `IMG_SIZE`, `DETECT_INTERVAL`
- `MQTT_HOST`, `MQTT_PORT`, `MQTT_USER`, `MQTT_PASSWORD`
- `MQTT_CLIENT_ID`, `MQTT_DISCOVERY_PREFIX`, `MQTT_STATE_TOPIC`

При `SOURCE=auto` RTSP URL собирается из:

- `RTSP_HOST`
- `RTSP_USER`
- `RTSP_PASSWORD`
- `RTSP_PATH`

## 5. Веб-интерфейс

- Добавление/удаление источников
- Загрузка и переключение моделей
- Отдельная модель для каждой карточки
- Клонирование карточек
- Переключение языка в правом верхнем углу

Добавлена защита локального редактирования: автообновление не перезаписывает текущий ввод пользователя.

## 6. Интеграция с Home Assistant

MQTT Discovery публикуется при запуске.

Поля состояния:

- `gesture`
- `confidence`
- `model`
- `timestamp`
- `source_id`

## 7. Основные API

- `GET /api/status`
- `GET /api/models`
- `POST /api/models/upload`
- `POST /api/models/activate`
- `GET /api/sources`
- `POST /api/sources`
- `PUT /api/sources/{source_id}`
- `DELETE /api/sources/{source_id}`
- `GET /snapshot/{source_id}.jpg`
- `GET /api/mqtt`, `PUT /api/mqtt`, `POST /api/mqtt/test`

## 8. Release и автодеплой

### GitHub Release

- При push тега `v*` (например `v1.0.0`) автоматически создается GitHub Release
- Workflow: `.github/workflows/release.yml`

### Автодеплой при push

- Push в `main` запускает автодеплой на сервер
- Workflow: `.github/workflows/deploy.yml`
- Нужные secrets репозитория:
  - `DEPLOY_HOST`
  - `DEPLOY_USER`
  - `DEPLOY_PASSWORD`
  - `DEPLOY_PORT` (необязательно, по умолчанию `22`)
  - `DEPLOY_PATH` (например `/home/linaro/gesture-yolo-ha`)
  - `DEPLOY_SERVICE` (например `gesture-yolo-ha.service`)
