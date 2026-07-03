# Fase 1 — Esqueleto de datos

Setup de PostgreSQL + Redis. Base sobre la que corre todo el sistema.

---

## Requisitos

- Docker Desktop corriendo
- Archivo `.env` creado (ver paso 1)

---

## Paso 1 — Crear `.env`

```powershell
cp env.example .env
```

Editar `.env` y poner el mismo password en los 4 lugares:

```env
POSTGRES_PASSWORD=tu_password
DATABASE_URL=postgresql://factory:tu_password@localhost:5432/content_factory

REDIS_PASSWORD=tu_password
REDIS_URL=redis://:tu_password@localhost:6379
```

> `.env` nunca va al repositorio. Ya está en `.gitignore`.

---

## Paso 2 — Levantar servicios

```powershell
docker compose up -d
```

Verificar que levantaron sanos:

```powershell
docker compose ps
```

Salida esperada:

```
NAME                STATUS
...-postgres-1      running (healthy)
...-redis-1         running (healthy)
```

Si alguno no está `healthy`, ver logs:

```powershell
docker compose logs postgres
docker compose logs redis
```

---

## Paso 3 — Verificar PostgreSQL

**Desde terminal (psql interactivo):**

```powershell
docker compose exec postgres psql -U factory -d content_factory
```

Comandos útiles dentro del psql:

```sql
\dt                         -- listar todas las tablas
\d channels                 -- ver columnas de una tabla
SELECT * FROM channels;     -- query directo
\q                          -- salir
```

Tablas que deben existir tras el init:

| Tabla               | Sistema   |
|---------------------|-----------|
| `channels`          | Radar     |
| `channel_snapshots` | Radar     |
| `observed_videos`   | Radar     |
| `niches`            | Radar     |
| `active_channels`   | Fábrica   |
| `topics`            | Fábrica   |
| `videos`            | Fábrica   |
| `video_results`     | Fábrica   |

**Desde cliente gráfico (TablePlus / DBeaver / DataGrip):**

| Campo    | Valor                    |
|----------|--------------------------|
| Host     | `localhost`              |
| Port     | `5432`                   |
| Database | `content_factory`        |
| User     | `factory`                |
| Password | valor de `POSTGRES_PASSWORD` en `.env` |

---

## Paso 4 — Verificar Redis

**Desde terminal:**

```powershell
docker compose exec redis redis-cli -a <REDIS_PASSWORD>
```

Comandos útiles:

```
KEYS *      -- ver todas las keys (vacío por ahora)
DBSIZE      -- cantidad de keys
PING        -- → PONG si está vivo
exit
```

---

## Comandos de mantenimiento

```powershell
# Ver logs en vivo
docker compose logs -f postgres
docker compose logs -f redis

# Parar sin borrar datos
docker compose down

# Parar Y borrar todos los datos (reset total)
docker compose down -v

# Entrar al shell del contenedor
docker compose exec postgres bash
docker compose exec redis sh
```

---

## Criterio de done

- `docker compose ps` muestra ambos servicios `healthy`
- `\dt` en psql muestra las 8 tablas del schema
- Redis responde `PONG`

Cuando esto pasa: **Fase 1 completa → arrancar Fase 2 (channel_scraper).**

---

---

# Fase 2 — Radar mínimo (channel_scraper + snapshot_writer)

Descubre canales de contenido IA en YouTube y acumula snapshots semanales.

---

## Prerequisito: YOUTUBE_API_KEY

Conseguir una clave en [Google Cloud Console](https://console.cloud.google.com/):

1. Crear proyecto → habilitar **YouTube Data API v3**
2. Credenciales → Crear clave de API
3. Copiar la clave al `.env`:

```env
YOUTUBE_API_KEY=AIza...tu_clave
```

La API es gratuita con quota de **10,000 unidades/día**. El pipeline usa ~800 unidades por ejecución (7 búsquedas × 100 + detalles de canales).

---

## Levantar el radar

```powershell
# Reconstruir imagen con el código nuevo y levantar todo
docker compose up -d --build

# Ver que el radar arrancó
docker compose ps
```

Salida esperada:

```
NAME                STATUS
...-postgres-1      running (healthy)
...-redis-1         running (healthy)
...-radar-1         running
```

---

## Ver logs del radar en vivo

```powershell
docker compose logs -f radar
```

Al arrancar corre inmediatamente. Verás:

```
=== Radar pipeline: start ===
channel_scraper: start
  search: 'AI story animated'
  → 20 channels
  search: 'lyric video español'
  → 18 channels
...
Upserted 87 channels
snapshot_writer: start
Channels to snapshot: 87
...
snapshot_writer: done
=== Radar pipeline: done ===
Scheduler activo — próxima ejecución en 1 semana
```

---

## Verificar datos en PostgreSQL

```powershell
docker compose exec postgres psql -U factory -d content_factory
```

```sql
-- Canales descubiertos
SELECT id, platform_id, handle, title FROM channels LIMIT 20;

-- Conteo por plataforma
SELECT platform, COUNT(*) FROM channels GROUP BY platform;

-- Snapshots guardados
SELECT c.title, s.subscribers, s.total_views, s.captured_at
FROM channel_snapshots s
JOIN channels c ON c.id = s.channel_id
ORDER BY s.subscribers DESC
LIMIT 20;

-- Videos observados
SELECT c.title AS canal, v.title AS video, v.views, v.likes, v.published_at
FROM observed_videos v
JOIN channels c ON c.id = v.channel_id
ORDER BY v.views DESC
LIMIT 20;

-- Proxy de viralidad: views / suscriptores
SELECT
    c.title,
    s.subscribers,
    AVG(v.views) AS avg_views,
    ROUND(AVG(v.views)::numeric / NULLIF(s.subscribers, 0), 2) AS views_per_sub
FROM channels c
JOIN channel_snapshots s ON s.channel_id = c.id
JOIN observed_videos v ON v.channel_id = c.id
GROUP BY c.title, s.subscribers
ORDER BY views_per_sub DESC
LIMIT 20;
```

---

## Editar keywords de búsqueda

Archivo: [radar/radar/channel_scraper.py](radar/radar/channel_scraper.py)

```python
SEARCH_KEYWORDS = [
    "AI story animated",
    "lyric video español",
    # agregar/quitar según el nicho que querés explorar
]
```

Después de editar, reiniciar el contenedor para que tome los cambios:

```powershell
docker compose restart radar
```

---

## Ejecutar el pipeline manualmente (sin esperar el cron)

```powershell
docker compose exec radar python -m radar.scheduler
```

---

## Estructura de archivos creados

```
radar/
├── Dockerfile
├── requirements.txt
└── radar/
    ├── __init__.py
    ├── db.py              # conexión a postgres
    ├── youtube.py         # wrapper YouTube Data API
    ├── channel_scraper.py # descubrimiento de canales
    ├── snapshot_writer.py # snapshots semanales
    └── scheduler.py       # cron semanal + entry point
```

---

## Criterio de done

- `docker compose ps` muestra radar `running`
- Logs muestran channels encontrados y upserted
- `SELECT COUNT(*) FROM channels;` devuelve > 0
- `SELECT COUNT(*) FROM channel_snapshots;` devuelve > 0

Cuando esto pasa: **Fase 2 completa → acumulá snapshots una semana y pasás a Fase 3 (niche_analyzer).**
