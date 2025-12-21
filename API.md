# noviy_2026_bot — API

Бэкенд — FastAPI.

- OpenAPI схема: `GET /openapi.json`
- Swagger UI: `GET /docs`
- ReDoc: `GET /redoc`

По умолчанию сервер запускается из [api/main.py](api/main.py) на `http://localhost:8000`.

## Общие правила

- Формат данных: JSON
- Ошибки (FastAPI `HTTPException`): `{"detail": "..."}`
- Аутентификация: в текущей версии **не реализована** (все методы без токена)

### Пагинация

Во всех списках используются параметры:
- `limit` (int, default 100 или 200)
- `offset` (int, default 0)

## Health

### `GET /health`

Ответ:
```json
{"ok": true}
```

## Users

Модель `UserOut`:
```json
{
  "id": 123,
  "username": "some_user",
  "first_name": "Ivan",
  "last_name": "Ivanov",
  "is_admin": false,
  "is_blacklisted": false,
  "registered_at": "2025-12-21T12:34:56.000000",
  "last_active": "2025-12-21T12:34:56.000000"
}
```

### `GET /users`

Параметры: `limit`, `offset`

Ответ: массив `UserOut`.

### `GET /users/{user_id}`

- `404` если пользователь не найден.

Ответ: `UserOut`.

### `POST /users`

Тело запроса (`UserCreate`):
```json
{
  "id": 123,
  "username": "some_user",
  "first_name": "Ivan",
  "last_name": "Ivanov",
  "is_admin": false,
  "is_blacklisted": false
}
```

- `201` создано
- `409` если пользователь с таким `id` уже существует

Ответ: `UserOut`.

### `PUT /users/{user_id}`

Тело запроса (`UserUpdate`) — любые поля опциональны:
```json
{
  "username": "new_name",
  "is_admin": true
}
```

- `404` если пользователь не найден

Ответ: `UserOut`.

### `DELETE /users/{user_id}`

- `204` успешное удаление
- `404` если пользователь не найден

## Chats

Модель `ChatOut`:
```json
{
  "chat_id": 1001,
  "type": "group",
  "title": "My Group",
  "created_at": "2025-12-21T12:34:56.000000"
}
```

### `GET /chats`

Параметры: `limit`, `offset`

Ответ: массив `ChatOut`.

### `GET /chats/{chat_id}`

- `404` если чат не найден

Ответ: `ChatOut`.

### `POST /chats`

Тело запроса (`ChatCreate`):
```json
{
  "chat_id": 1001,
  "type": "group",
  "title": "My Group"
}
```

- `201` создано
- `409` если чат уже существует

Ответ: `ChatOut`.

### `PUT /chats/{chat_id}`

Тело запроса (`ChatUpdate`) — любые поля опциональны:
```json
{
  "title": "New Title"
}
```

- `404` если чат не найден

Ответ: `ChatOut`.

### `DELETE /chats/{chat_id}`

- `204` успешное удаление
- `404` если чат не найден

## Blacklist

Ключ записи — `tag` (на сервере нормализуется: убирается ведущий `@`, приводится к lower-case).

Модель `BlacklistOut`:
```json
{
  "tag": "some_tag",
  "note": "optional note",
  "created_at": "2025-12-21T12:34:56.000000"
}
```

### `GET /blacklist`

Параметры: `limit`, `offset`

Ответ: массив `BlacklistOut`.

### `GET /blacklist/{tag}`

- `tag` можно передавать с `@` или без
- `404` если тега нет

Ответ: `BlacklistOut`.

### `POST /blacklist`

Тело запроса (`BlacklistCreate`):
```json
{
  "tag": "@Some_Tag",
  "note": "optional"
}
```

- `201` создано
- `409` если тег уже существует

Ответ: `BlacklistOut`.

### `PUT /blacklist/{tag}`

Тело запроса (`BlacklistUpdate`):
```json
{
  "note": "new note"
}
```

- `404` если тега нет

Ответ: `BlacklistOut`.

### `DELETE /blacklist/{tag}`

- `204` успешное удаление
- `404` если тега нет

## Settings

Модель `SettingOut`:
```json
{"key": "some_key", "value": "some_value"}
```

### `GET /settings`

Параметры: `limit` (default 200), `offset`

Ответ: массив `SettingOut`.

### `GET /settings/{key}`

- `404` если ключ не найден

Ответ: `SettingOut`.

### `PUT /settings/{key}`

Upsert (создаёт или обновляет).

Тело (`SettingUpsert`):
```json
{"value": "new_value"}
```

Ответ: `SettingOut`.

### `DELETE /settings/{key}`

- `204` успешное удаление
- `404` если ключ не найден

## Spotify tracks

Модель `SpotifyTrackOut`:
```json
{
  "id": 1,
  "spotify_id": "6rqhFgbbKwnb9MLmUQDhG6",
  "name": "Track name",
  "artist": "Artist",
  "url": "https://open.spotify.com/track/...",
  "added_by": 123,
  "added_at": "2025-12-21T12:34:56.000000"
}
```

### `GET /spotify-tracks`

Параметры: `limit`, `offset`

Ответ: массив `SpotifyTrackOut`.

### `GET /spotify-tracks/{track_id}`

- `404` если трек не найден

Ответ: `SpotifyTrackOut`.

### `POST /spotify-tracks`

Тело (`SpotifyTrackCreate`):
```json
{
  "spotify_id": "6rqhFgbbKwnb9MLmUQDhG6",
  "name": "Track name",
  "artist": "Artist",
  "url": "https://open.spotify.com/track/...",
  "added_by": 123
}
```

- `201` создано
- `409` если `spotify_id` уже существует

Ответ: `SpotifyTrackOut`.

### `PUT /spotify-tracks/{track_id}`

Тело (`SpotifyTrackUpdate`) — любые поля опциональны:
```json
{
  "name": "New name",
  "artist": "New artist"
}
```

- `404` если трек не найден

Ответ: `SpotifyTrackOut`.

### `DELETE /spotify-tracks/{track_id}`

- `204` успешное удаление
- `404` если трек не найден

## WebSocket: Player

### `WS /ws/player`

Подключение: `ws://<host>:8000/ws/player`

Сервер **сразу** после подключения отправляет текущее состояние:

```json
{
  "type": "state",
  "playing": false,
  "index": 0,
  "current": {
    "id": 1,
    "spotify_id": "...",
    "name": "...",
    "artist": "...",
    "url": "...",
    "added_by": 123,
    "added_at": "2025-12-21T12:34:56.000000"
  },
  "playlist": [
    {"id": 1, "spotify_id": "...", "name": "...", "artist": "...", "url": "...", "added_by": 123, "added_at": "..."}
  ]
}
```

### Команды клиента

Клиент отправляет JSON с полем `op`:

- `{"op": "ping"}` → `{"type": "pong"}`
- `{"op": "get_state"}` или `{"op": "state"}` → текущее `type=state`
- `{"op": "get_playlist"}` или `{"op": "playlist"}` →
  ```json
  {"type": "playlist", "index": 0, "playlist": [ ... ]}
  ```
- `{"op": "refresh_playlist"}` или `{"op": "refresh"}` → перечитывает плейлист из БД и рассылает `type=state` всем
- `{"op": "play"}` → `playing=true` и рассылка `type=state`
- `{"op": "pause"}` → `playing=false` и рассылка `type=state`
- `{"op": "next"}` / `{"op": "next_track"}` → сдвиг индекса вперёд и рассылка `type=state`
- `{"op": "prev"}` / `{"op": "previous"}` / `{"op": "prev_track"}` → сдвиг индекса назад и рассылка `type=state`
- `{"op": "set_index", "index": 3}` или `{"op": "seek", "index": 3}` → установка индекса и рассылка `type=state`

### Ошибки WS

Сервер может ответить:
- `{"type": "error", "message": "Missing op"}`
- `{"type": "error", "message": "Unknown op: ..."}`
- `{"type": "error", "message": "Invalid index"}`
- `{"type": "error", "message": "Index out of range"}`

## Экспорт OpenAPI в файл

Для передачи схемы как файла (например, для генерации типов на фронте):

```bash
python scripts/export_openapi.py --out openapi.json
```
