# noviy_player

Оверлей для OBS (Browser Source), собираемый в один файл `dist/overlay.html` со встроенными CSS+JS.

Оверлей:
- показывает текущий трек (берется из `GET /api/spotify-tracks`, метаданные/обложка — через Spotify oEmbed)
- показывает новые фото из `GET /api/photos` (и дополнительно пытается слушать `WS /api/ws/player` если доступно)
- поддерживает анимацию `static` / `kenburns`

## Быстрый старт
1) Установите Node.js (LTS) и зависимости:
- `npm install`

2) Соберите оверлей в один файл:
- PowerShell:
	- `$env:OVERLAY_API_TOKEN="<token>"; npm run build`
- Bash:
	- `OVERLAY_API_TOKEN="<token>" npm run build`

Откройте в OBS Browser Source:
- URL: `http://127.0.0.1:8765/overlay`

## Настройки (встраиваются в страницу)
Настройки вшиваются на этапе сборки через env переменные:
- `OVERLAY_API_TOKEN` — токен (можно пустым)
- `WS_URL` — полный URL вебсокета (если пусто, используем same-origin `ws(s)://<host>/api/ws/player`)
- `PHOTO_POLL_INTERVAL_MS`, `PHOTO_DISPLAY_MS`, `QUEUE_POLL_INTERVAL_MS`
- `WS_TOKEN_MODE` — `none` | `query:token` | `query:access_token` | `subprotocol:bearer`

Поскольку итоговый `dist/overlay.html` используется локально в OBS, секреты можно хранить прямо в нем.

## OBS рекомендации
- Browser Source: включите `Shutdown source when not visible` (по желанию)
- Width/Height: равны канвасу (например 1920x1080)
- FPS: 30 (обычно достаточно)

Важно: этот оверлей рассчитан на same-origin (API и overlay на одном домене/префиксе), тогда CORS не нужен.

Если вы всё-таки открываете overlay с другого origin (например, локально в OBS), то без CORS браузерный оверлей не сможет читать `GET /api/spotify-tracks` и `GET /api/photos`.

Минимально необходимые заголовки (для запросов с `Authorization`):
- `Access-Control-Allow-Origin: http://127.0.0.1:8765` (и/или `http://localhost:8765`)
- `Access-Control-Allow-Methods: GET, POST, OPTIONS`
- `Access-Control-Allow-Headers: Authorization, Content-Type`

Примеры настройки CORS на API:

- FastAPI:
	- добавьте `CORSMiddleware` с `allow_origins=["http://127.0.0.1:8765","http://localhost:8765"]`, `allow_methods=["*"]`, `allow_headers=["*"]`

- Nginx (в прокси перед API):
	- добавьте `add_header Access-Control-Allow-Origin ...;` и обработку `OPTIONS` (возвращать `204` с нужными заголовками)
