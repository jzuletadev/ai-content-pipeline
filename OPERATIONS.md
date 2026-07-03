# Guía de operaciones — Content Factory

Referencia rápida para el día a día. Si arrancás de cero o retomás después de un tiempo, seguí este documento.

---

## Arrancar el proyecto desde cero

```powershell
# Levantar todos los servicios activos
docker compose up -d

# Verificar que todos estén corriendo
docker compose ps
```

**Salida esperada:**
```
NAME                              STATUS
...-factory-scheduler-1           Up
...-postgres-1                    Up (healthy)
...-radar-1                       Up
...-redis-1                       Up (healthy)
```

Si alguno no aparece o dice `Exited`, ver sección **Troubleshooting** al final.

---

## Parar el proyecto

```powershell
# Parar sin borrar datos
docker compose down

# Parar Y borrar todos los datos (reset total — destructivo)
docker compose down -v
```

---

## Ver logs en vivo

```powershell
# Todos los servicios
docker compose logs -f

# Solo el radar
docker compose logs -f radar

# Solo la fábrica
docker compose logs -f factory-scheduler

# Solo postgres
docker compose logs -f postgres
```

---

## Entrar a la base de datos

```powershell
docker compose exec postgres psql -U factory -d content_factory
```

Para salir: `\q`

---

## Consultas útiles del día a día

### Estado general del sistema
```sql
-- Cuántos canales vigila el radar
SELECT platform, COUNT(*) FROM channels GROUP BY platform;

-- Cuántos canales clasificados como IA
SELECT is_ai_content, COUNT(*) FROM channels GROUP BY is_ai_content;

-- Snapshots tomados (histórico que acumula el radar)
SELECT DATE(captured_at) AS dia, COUNT(*) AS snapshots
FROM channel_snapshots
GROUP BY dia ORDER BY dia DESC LIMIT 10;
```

### Estado de los videos
```sql
-- Videos por estado (el estado que más importa ver cada mañana)
SELECT status, COUNT(*) FROM videos GROUP BY status ORDER BY status;

-- Videos esperando revisión
SELECT id, metadata->>'title' AS titulo, created_at
FROM videos
WHERE status = 'review'
ORDER BY created_at DESC;

-- Videos aprobados para publicar
SELECT id, metadata->>'title' AS titulo, metadata->>'audio_ref' AS audio
FROM videos
WHERE status = 'approved';

-- Videos publicados (para tracking)
SELECT id, metadata->>'title' AS titulo, published_at
FROM videos
WHERE status = 'published'
ORDER BY published_at DESC;
```

### Temas detectados
```sql
-- Temas pendientes de esta semana
SELECT id, title, trend_score, status, detected_at
FROM topics
ORDER BY detected_at DESC
LIMIT 20;
```

### Ranking de nichos (actualizado cada semana)
```sql
SELECT name, demand_score, saturation_score, opportunity_score
FROM niches
ORDER BY opportunity_score DESC;
```

### Canales más virales (proxy views/subs)
```sql
SELECT
    c.title,
    s.subscribers,
    ROUND(AVG(v.views)) AS avg_views,
    ROUND(AVG(v.views)::numeric / NULLIF(s.subscribers, 0), 2) AS views_per_sub
FROM channels c
JOIN (
    SELECT DISTINCT ON (channel_id) channel_id, subscribers
    FROM channel_snapshots ORDER BY channel_id, captured_at DESC
) s ON s.channel_id = c.id
JOIN observed_videos v ON v.channel_id = c.id
WHERE s.subscribers > 1000 AND c.is_ai_content = TRUE
GROUP BY c.title, s.subscribers
ORDER BY views_per_sub DESC
LIMIT 15;
```

---

## Correr los pipelines manualmente

### Radar completo (normalmente corre solo semanal)
```powershell
docker compose exec radar python -c "
from src.channel_scraper import run; run()
"

docker compose exec radar python -c "
from src.snapshot_writer import run; run()
"

docker compose exec radar python -c "
from src.data_cleaner import run; run()
"

docker compose exec radar python -c "
from src.niche_analyzer import run; run()
"

docker compose exec radar python -c "
from src.report_builder import run; run()
"
```

### Fábrica completa (normalmente corre sola diario)
```powershell
docker compose exec factory-scheduler python -c "
from src.topic_scraper import run; run()
"

docker compose exec factory-scheduler python -c "
from src.script_generator import run; run()
"
```

---

## Reporte de nichos

El reporte se genera automáticamente y se guarda en `radar/reports/`.

```powershell
# Ver el reporte del día
ls radar/reports/

# Leer el más reciente (PowerShell)
Get-Content radar/reports/$(Get-Date -Format "yyyy-MM-dd").md
```

---

## Flujo diario de operación (cuando Fase 6 esté activa)

```
Mañana: abrir http://127.0.0.1:8080
  → revisar videos en estado 'review'
  → reproducir cada video
  → aprobar o rechazar
  → descargar MP4 aprobados
  → copiar título / descripción / hashtags
  → para lyric videos: copiar nombre del audio (audio_ref)
  → publicar manualmente en YouTube/TikTok (~3-4 min por video)
  → marcar como 'published' en el dashboard
```

---

## Reconstruir una imagen después de cambiar código

```powershell
# Solo radar
docker compose up -d --build radar

# Solo factory
docker compose up -d --build factory-scheduler

# Todo
docker compose up -d --build
```

> **Nota:** si solo cambiaste archivos `.py` dentro de `radar/` o `factory/`, NO necesitás rebuild — el volumen sincroniza el código automáticamente. Solo rebuildeás si cambiaste `Dockerfile` o `requirements.txt`.

---

## Variables de entorno (.env)

| Variable | Usada por | Descripción |
|----------|-----------|-------------|
| `POSTGRES_PASSWORD` | Docker | Password de PostgreSQL |
| `REDIS_PASSWORD` | Docker | Password de Redis |
| `DATABASE_URL` | Python | URL de conexión local a postgres |
| `REDIS_URL` | Python | URL de conexión local a redis |
| `YOUTUBE_API_KEY` | Radar | YouTube Data API v3 (gratis, 10K unidades/día) |
| `ANTHROPIC_API_KEY` | Factory | Claude API para generar guiones |
| `LASTFM_API_KEY` | Factory | Last.fm para detectar canciones trending |
| `CLAUDE_MODEL` | Factory | Modelo de Claude (`claude-haiku-4-5-20251001` en pruebas, `claude-sonnet-5` en producción) |
| `GOOGLE_API_KEY` | Factory (Fase 5) | Gemini para generar imágenes |
| `ELEVENLABS_API_KEY` | Factory (Fase 5) | TTS para voz |

---

## Estado de los videos — máquina de estados

```
queued
  → scripting          (Claude generando guion)
  → generating_assets  (generando imágenes y voz)
  → rendering          (Remotion ensamblando MP4)
  → review             (esperando tu aprobación)
  → approved           (aprobado, listo para descargar)
  → rejected           (rechazado)
  → published          (publicado manualmente)
```

---

## Troubleshooting

### Un servicio no levanta
```powershell
docker compose logs <nombre-servicio>
```

### Postgres no conecta desde cliente externo
- Host: `localhost`, Port: `5432`, User: `factory`, DB: `content_factory`
- Password: el valor de `POSTGRES_PASSWORD` en `.env`

### Videos atascados en 'scripting'
```sql
UPDATE videos SET status = 'queued' WHERE status = 'scripting' AND script IS NULL;
```

### Topics atascados en 'selected' sin video
```sql
-- Ver topics sin video asociado
SELECT t.id, t.title, t.status
FROM topics t
LEFT JOIN videos v ON v.topic_id = t.id
WHERE t.status = 'selected' AND v.id IS NULL;

-- Resetear para reintentar
UPDATE topics SET status = 'pending' WHERE id IN (<ids>);
```

### Resetear datos de prueba (sin borrar canales ni snapshots)
```sql
DELETE FROM videos WHERE script IS NULL;
UPDATE topics SET status = 'pending' WHERE status IN ('selected', 'discarded');
```

### Ver quota usada de YouTube API
Entrar a Google Cloud Console → APIs y servicios → YouTube Data API v3 → Cuotas.
Límite: 10,000 unidades/día. El radar usa ~3,100 unidades por ejecución completa.

---

## Estructura de archivos clave

```
.
├── .env                      ← claves de API (nunca al repo)
├── docker-compose.yml        ← orquesta todos los servicios
├── db/init.sql               ← schema de PostgreSQL
├── radar/
│   └── src/
│       ├── scheduler.py      ← cron semanal (entry point)
│       ├── channel_scraper.py
│       ├── snapshot_writer.py
│       ├── data_cleaner.py
│       ├── niche_analyzer.py
│       └── report_builder.py
├── factory/
│   └── src/
│       ├── scheduler.py      ← cron diario (entry point)
│       ├── topic_scraper.py
│       ├── script_generator.py
│       └── setup_channel.py  ← correr UNA SOLA VEZ al inicio
├── radar/reports/            ← reportes semanales de nichos
└── PLAN.md                   ← plan de desarrollo con checkboxes
```
