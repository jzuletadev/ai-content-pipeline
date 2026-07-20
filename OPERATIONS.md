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
...-factory-worker-1              Up
...-imagegen-1                    Up (healthy)
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

### Fábrica — pipeline de texto (normalmente corre sola diario)
```powershell
docker compose exec factory-scheduler python -c "
from src.topic_scraper import run; run()
"

docker compose exec factory-scheduler python -c "
from src.script_generator import run; run()
"
```

> `script_generator` encola automáticamente cada video en `video_jobs` (Redis) al terminar. El `factory-worker` (RQ) lo procesa solo — no hace falta correr assets/render a mano si el worker está corriendo.

### Fábrica — assets + render (Fase 5, manual / debug)

Normalmente corre solo, disparado por la cola. Para forzar un video puntual o debuggear:

```powershell
# Ver logs del worker en vivo (acá se ve la generación de imágenes, voz y el render)
docker compose logs -f factory-worker

# Generar assets + render para UN video específico (saltea lo ya generado)
docker compose exec factory-worker python -c "
from src.jobs import process_video
process_video(8)
"

# Solo assets (sin render)
docker compose exec factory-worker python -c "
from src.asset_generator import generate_assets_for_video
generate_assets_for_video(8)
"

# Solo render (asume que ya tiene assets)
docker compose exec factory-worker python -c "
from src.render_worker import render_video
render_video(8)
"

# Ver el estado de la cola RQ
docker compose exec factory-worker python -c "
from src.queue import get_video_queue
q = get_video_queue()
print('pendientes:', len(q))
print('fallidos:', q.failed_job_registry.count)
"
```

### Ver videos renderizados

```powershell
# Los MP4 quedan en el volumen 'media', accesible desde el contenedor
docker compose exec factory-worker ls -la /data/renders/

# Copiar un render al Desktop para verlo (Windows)
docker compose cp factory-worker:/data/renders/8.mp4 ./8.mp4
```

### imagegen — generación de imágenes self-hosted (Stable Diffusion)

Reemplaza a Gemini (que pedía prepago de $25 mínimo). Corre `sd-turbo` en tu GPU local (RTX 3060), sin costo por imagen.

```powershell
# Ver logs (acá se ve la carga del modelo en GPU al arrancar)
docker compose logs -f imagegen

# Probar el servicio directo (sin pasar por el pipeline completo)
curl -X POST http://127.0.0.1:7860/generate -H "Content-Type: application/json" -d '{"prompt": "a red bicycle in a park"}' --output test.png

# Ver uso de GPU en vivo (desde Windows, fuera de Docker)
nvidia-smi

# Healthcheck
curl http://127.0.0.1:7860/health
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

> **Ojo con los workers de larga duración (`factory-worker`, cualquier `scheduler`):** sincronizar el archivo `.py` en disco NO alcanza si el proceso Python ya está corriendo — un proceso long-running tiene el módulo viejo cargado en memoria y no lo recarga solo. Después de editar código que usa `factory-worker` (asset_generator, render_worker, jobs) o cualquier scheduler, hace falta:
> ```powershell
> docker compose restart factory-worker factory-scheduler
> ```
> Si no reiniciás, el worker sigue ejecutando la versión vieja del código aunque el archivo ya esté actualizado — esto pasó en Fase 5 (un video se procesó con Gemini viejo después de haber migrado a `imagegen`, porque el worker no se había reiniciado).

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
| `IMAGEGEN_URL` | Factory (Fase 5) | URL interna del servicio `imagegen` (default `http://imagegen:7860`) |
| `ELEVENLABS_API_KEY` | Factory (Fase 5) | TTS para voz (solo nichos narrados, no lyric_videos) |
| `ELEVENLABS_VOICE_ID` | Factory (Fase 5) | Voz a usar (default: voz multilingüe) |
| `SHORT_DURATION_SEC` | Factory (Fase 5) | Duración de los lyric videos (default `30` — formato Shorts/Reels/TikTok, no canción completa) |

---

## Modelo de imagegen

**Modelo actual:** `stable-diffusion-v1-5/stable-diffusion-v1-5` (SD 1.5 estándar, no destilado).

Se probó primero `stabilityai/sd-turbo` (más rápido, 1-4 steps) pero producía anatomía
deformada en escenas con varias personas — es un modelo **destilado**, calibrado
específicamente para pocos steps; subir steps más allá de ~4 no mejora calidad porque
no fue entrenado para ese rango. Como el pipeline corre de noche sin nadie esperando,
el tiempo extra de SD 1.5 no es un costo real.

**Config actual** (`imagegen/app.py`):
- `steps = 30`, `guidance_scale = 7.5` (CFG real — sd-turbo no lo soporta)
- `negative_prompt` con lista fija: manos deformadas, extremidades extra, mala anatomía, etc.
- Resolución `576x1024` (9:16 exacto — Remotion ya no recorta, antes con 512x512 cuadrado se perdía ~44% del ancho)
- Lock de concurrencia (`threading.Lock`) — el pipeline no es thread-safe, dos requests simultáneos corrompían el modelo ("Already borrowed")
- ~5-8s por imagen en la RTX 3060 — aceptable dado el margen de tiempo overnight

Si igual aparecen deformidades en casos puntuales, ajustar `DEFAULT_NEGATIVE_PROMPT`
en `imagegen/app.py` agregando términos específicos al problema visto.

### Control de calidad automático (Claude vision)

`factory/src/asset_generator.py` — después de generar cada imagen, se la manda a Claude
(vision, modelo `CLAUDE_MODEL` — Haiku por defecto) preguntando si se ve coherente.
Si falla, reintenta la generación hasta `IMAGE_QC_MAX_RETRIES` veces (default 2) antes
de aceptar la última igual. Costo real: ~$0.03/video — insignificante.

Variables de entorno:
- `IMAGE_QC_ENABLED` — default `true`. Poner `false` para desactivar y ahorrar las llamadas a Claude.
- `IMAGE_QC_MAX_RETRIES` — default `2`.

Si Claude falla o no responde bien formado, el chequeo se **acepta por defecto**
(nunca bloquea el pipeline por un error de QC).

> Después de editar `imagegen/app.py`, reiniciar el contenedor — no recarga solo (mismo motivo que `factory-worker`/`factory-scheduler`, ver nota arriba):
> ```powershell
> docker compose restart imagegen
> ```
> Si cambiás el `MODEL_ID`, además hay que actualizar la pre-descarga en `imagegen/Dockerfile`
> con los mismos argumentos exactos, y correr `docker compose build imagegen`.

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

### Videos atascados en 'generating_assets' o 'rendering'
Pasa si el job de RQ falló las 2 veces del retry (revisar `docker compose logs factory-worker` para la causa real).

```sql
-- Ver cuáles están atascados
SELECT id, status, metadata->>'title' AS titulo FROM videos
WHERE status IN ('generating_assets', 'rendering');
```

```powershell
# Re-encolar manualmente un video atascado
docker compose exec factory-worker python -c "
from src.jobs import process_video
process_video(8)
"
```

### radar en crash loop (`docker compose ps` muestra "Restarting")
```powershell
docker compose logs radar --tail 30
```
Causa típica: quota de YouTube API agotada (10K/día) — no rompe nada, `snapshot_writer`
solo loguea el error y sigue. Si el crash real es en `niche_analyzer` con
`ForeignKeyViolation` sobre `niches` — ya está resuelto (upsert por `name` en vez de
borrar-y-reinsertar), pero si reaparece: revisar que `active_channels.niche_id`
siga apuntando a un nicho existente.

### El build de Docker falla en el paso de Chromium / npm install
Es el paso de mayor riesgo del proyecto — headless Chrome en Docker es frágil. Pasos:
1. Copiar el error exacto de `docker compose up -d --build factory-scheduler`
2. Si es una librería `.so` faltante (`error while loading shared libraries: libXXX.so`), instalar el paquete apt correspondiente en el `Dockerfile`
3. Si es timeout de `npm install`, reintentar — a veces es la red

### Render falla con error de Chromium/Remotion
```powershell
# Ver el error completo
docker compose logs factory-worker

# Probar el render a mano dentro del contenedor para ver el stack completo
docker compose exec factory-worker sh -c "cd remotion && npx remotion render src/index.ts MainVideo /tmp/test.mp4 --browser-executable=/usr/bin/chromium"
```

### Costos de ElevenLabs en pruebas
`asset_generator` es idempotente: si una imagen o el audio ya existen en disco, los salta. Reintentar un video fallido NO regenera lo que ya se generó — solo completa lo que faltó.

### imagegen no arranca / error "could not select device driver nvidia"
Docker Desktop no tiene habilitado el passthrough de GPU. Chequear:
1. Docker Desktop → Settings → General → "Use the WSL 2 based engine" activo
2. Actualizar WSL2: abrir PowerShell normal (fuera de este proyecto) y correr `wsl --update`
3. Reiniciar Docker Desktop
4. Confirmar que Windows ve la GPU: `nvidia-smi` en PowerShell debe mostrar la RTX 3060
5. Reintentar `docker compose up -d imagegen`

### imagegen tarda mucho en pasar a "healthy"
Normal la primera vez — el modelo se pre-descarga en build, pero cargarlo en VRAM al arrancar el contenedor tarda ~30-90s. El healthcheck tiene `start_period: 120s` para tolerar esto. Si pasa de 2 minutos:
```powershell
docker compose logs imagegen
```

### imagegen responde con CUDA out of memory
6GB VRAM es justo. Si pasa, bajar resolución en `imagegen/app.py` (default 768x768) o cerrar otras apps que usen GPU mientras corre el pipeline.

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
