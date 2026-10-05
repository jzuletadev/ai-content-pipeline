# Dashboard de revisión

FastAPI + templates Jinja2 mínimos. Único punto donde un humano interviene en el pipeline: revisar, aprobar/rechazar, y copiar metadata antes de publicar manualmente. Escucha solo en `127.0.0.1:8080` — nunca expuesto a internet.

## Endpoints (`src/main.py`)

| Endpoint | Qué hace |
|---|---|
| `GET /?status=review\|approved\|rejected\|published` | Lista videos por estado (tabs) |
| `GET /videos/{id}` | Detalle: reproductor, metadata, audio_ref |
| `GET /videos/{id}/file` | Sirve el MP4 (streaming + descarga) |
| `POST /videos/{id}/approve` | Marca `approved` |
| `POST /videos/{id}/reject` | Marca `rejected` |
| `POST /videos/{id}/published` | Marca `published`, guarda `published_url` (form) — dispara el tracking de `result_tracker.py` en la próxima corrida diaria |

## Levantar

```powershell
docker compose up -d dashboard
docker compose logs -f dashboard
```

Abrir `http://127.0.0.1:8080`. El volumen `media` se monta **read-only** — el dashboard nunca escribe renders, solo los sirve.

## Flujo de revisión

1. Abrir el dashboard, tab `review`
2. Reproducir cada video
3. Aprobar o rechazar
4. Para los aprobados: descargar el MP4, copiar título/descripción/hashtags (botón copiar)
5. Para lyric videos: copiar también el nombre del audio nativo (`audio_ref`) — el render es mudo, el audio se agrega en la plataforma
6. Publicar manualmente en cada plataforma (~3-4 min por video)
7. Volver al dashboard, marcar `published` pegando la URL real — esto habilita el tracking de resultados que retroalimenta al radar

## Templates

`src/templates/index.html` — lista con tabs por estado. `src/templates/video.html` — reproductor, metadata con botón copiar (Clipboard API), botones de acción según el estado actual.

Después de editar `src/main.py`, `docker compose restart dashboard` (bind mount sincroniza el `.py`, pero uvicorn en el contenedor no tiene `--reload` activo).
