# Fábrica de contenido

Sistema B — corre diario. Detecta temas para el nicho activo, genera guion con Claude, genera assets (imágenes + voz), renderiza con Remotion, y deja el video en `review` para aprobación manual en el [dashboard](../dashboard/README.md).

> **Foco actual: un solo nicho — historias animadas.** Ver [PLAN.md](../PLAN.md) para el estado de la migración de generación de imágenes (self-hosted → Gemini API) y el resto del roadmap. `lyric_videos` (el nicho original, música) queda de lado por ahora, no borrado.

## Componentes (`src/`)

| Archivo | Rol |
|---|---|
| `scheduler.py` | Entry point — cron diario (00:00), corre `topic_scraper → script_generator → result_tracker` |
| `topic_scraper.py` | Detecta temas del día (Last.fm trending, Wikipedia On This Day) |
| `script_generator.py` | Claude genera guion + prompts + metadata; encola el video en RQ al terminar |
| `queue.py` | Conexión a la cola RQ `video_jobs` |
| `worker.py` | Entry point del worker RQ — consume `video_jobs` |
| `jobs.py` | `process_video()` — el job de RQ: `generate_assets_for_video()` → `render_video()` |
| `asset_generator.py` | Genera imágenes (imagegen) y narración (ElevenLabs); QC de imágenes vía Claude vision |
| `render_worker.py` | Normaliza escenas al formato uniforme de Remotion y dispara el render |
| `setup_channel.py` | Script interactivo, correr **una sola vez** para crear el primer `active_channel` |
| `result_tracker.py` | Lee métricas de YouTube para videos publicados, alimenta el `niche_analyzer` del radar |

## El nombre del nicho es una clave de enrutamiento

`radar/src/niche_analyzer.py` clasifica canales en nichos por keyword en el título (`NICHE_TITLE_KEYWORDS`) y escribe filas en la tabla `niches`. `script_generator.py` después **rama según el nombre del nicho del canal activo**:

```python
if niche == "lyric_videos": ...
elif niche == "historias_historicas": ...
else: raise ValueError(f"Sin generador para nicho: {niche}")
```

y `asset_generator.py` chequea el mismo nombre contra `NICHES_WITH_NARRATION` para decidir si llama a ElevenLabs. El nicho de "historias animadas" narradas usa el generador ya implementado para `historias_historicas` — es el mismo patrón técnico (guion narrado + imágenes + voz), aplicado hoy a temas históricos. Agregar un nicho nuevo (por ejemplo, animadas no-históricas) implica: una entrada de keywords en `niche_analyzer.py` **y** una rama nueva en `script_generator.py` — no están acopladas automáticamente.

## Máquina de estados (`videos.status`)

```
queued → scripting → generating_assets → rendering → review → approved/rejected → published
```

`script_generator.py` mueve `queued → scripting` y, al terminar, encola el job RQ dejando el video en `generating_assets`. De ahí en más el consumidor RQ (`jobs.py:process_video`) es dueño del resto: `asset_generator.py` deja el video en `rendering`, `render_worker.py` lo deja en `review`. El dashboard solo mueve entre `review/approved/rejected/published`.

## Levantar y operar

```powershell
docker compose up -d --build factory-scheduler   # reconstruye la imagen (misma para factory-worker)
docker compose logs -f factory-worker            # acá se ve generación de imágenes, voz y render
docker compose logs -f factory-scheduler

# tras editar cualquier .py de factory/src — el proceso long-running NO recarga solo
docker compose restart factory-worker factory-scheduler
```

> **Volumen `factory_node_modules`:** protege el `node_modules` de Remotion (generado en build) del bind mount `./factory:/app`. No lo borres sin volver a construir la imagen.

## Correr los pipelines manualmente

```powershell
docker compose exec factory-scheduler python -c "from src.topic_scraper import run; run()"
docker compose exec factory-scheduler python -c "from src.script_generator import run; run()"
```

`script_generator` encola automáticamente cada video en `video_jobs`; el `factory-worker` lo procesa solo, no hace falta correr assets/render a mano salvo para debug puntual:

```powershell
# Forzar/debuggear UN video específico (saltea lo ya generado — todo es idempotente)
docker compose exec factory-worker python -c "from src.jobs import process_video; process_video(8)"

# Solo assets / solo render
docker compose exec factory-worker python -c "from src.asset_generator import generate_assets_for_video; generate_assets_for_video(8)"
docker compose exec factory-worker python -c "from src.render_worker import render_video; render_video(8)"

# Estado de la cola RQ
docker compose exec factory-worker python -c "
from src.queue import get_video_queue
q = get_video_queue()
print('pendientes:', len(q))
print('fallidos:', q.failed_job_registry.count)
"

# Ver renders
docker compose exec factory-worker ls -la /data/renders/
docker compose cp factory-worker:/data/renders/8.mp4 ./8.mp4
```

## El contrato Python → Remotion

Python no renderiza. `render_worker.py` normaliza el guion (formato distinto por nicho) a una lista uniforme de escenas, copia los assets a `remotion/public/assets/{video_id}/`, escribe un JSON spec, y dispara `npx remotion render` como subproceso con `--browser-executable=/usr/bin/chromium` (el Chromium instalado por apt, no el que Remotion intenta descargar solo). `remotion/src/MainVideo.tsx` solo lee ese JSON vía input props y anima (Ken Burns continuo + fade de texto) — no hay lógica de negocio duplicada del lado Node. Si un render se ve mal, revisar `_normalize_scenes()` / el JSON spec antes de tocar el `.tsx`.

Para nichos narrados, `duration_sec` por escena es solo una estimación de Claude — `render_worker.py` reescala todos los rangos de frames proporcionalmente a la duración **real** del audio de ElevenLabs (leída con `mutagen`) para que el video nunca corte la narración a la mitad.

## Generación de imágenes: self-hosted vs. Gemini

El código actual (`asset_generator.py`) llama al servicio `imagegen` self-hosted (ver [imagegen/README.md](../imagegen/README.md)) — gratis mientras se corre en GPU propia, pero calidad limitada y consumo de tiempo de configuración. El plan vigente ([PLAN.md](../PLAN.md)) es migrar el path de imágenes a la API de Gemini (`GEMINI_API_KEY` en `.env`) para priorizar calidad mientras se valida el nicho único, y volver a self-hosted más adelante si el volumen lo justifica económicamente. Hasta que esa migración se implemente, `IMAGEGEN_URL` sigue siendo la ruta activa.

### Control de calidad de imágenes (`asset_generator.py`)

Después de generar cada imagen, se manda a Claude (vision, modelo `CLAUDE_MODEL`) preguntando si se ve coherente — reintenta hasta `IMAGE_QC_MAX_RETRIES` veces (default 2). Si Claude falla o no responde bien formado, el chequeo se acepta por defecto (nunca bloquea el pipeline). `IMAGE_QC_ENABLED=false` lo desactiva.

## El caso especial de la música (`lyric_videos`, en pausa)

El render produce video **mudo** — `videos.audio_ref` guarda el nombre exacto de la canción para agregar el audio nativo al publicar (mantiene licencia y monetización de la plataforma). No lleva TTS.

## Fase de pruebas: un video a la vez

`script_generator.py` respeta `TEST_MODE_SINGLE_VIDEO` (default `true`): si hay cualquier video en `scripting`/`generating_assets`/`rendering` en todo el sistema, no arranca uno nuevo. Es un freno deliberado de gasto en APIs durante validación — pasar a `false` en `.env` antes de esperar más de un video en curso.

## Variables de entorno específicas de Factory

| Variable | Descripción |
|---|---|
| `ANTHROPIC_API_KEY` | Claude — guiones y QC de imágenes |
| `CLAUDE_MODEL` | Modelo de Claude (default `claude-haiku-4-5-20251001`) |
| `LASTFM_API_KEY` | Last.fm — temas trending para `topic_scraper` |
| `LYRIC_DURATION_SEC` / `HISTORY_DURATION_SEC` | Duración objetivo del video por nicho (default 30 / 60) |
| `TEST_MODE_SINGLE_VIDEO` | Límite de 1 video en curso a la vez (default `true`) |
| `IMAGEGEN_URL` | URL interna del servicio self-hosted (default `http://imagegen:7860`) — activo hasta que se complete la migración a Gemini |
| `GEMINI_API_KEY` | Reservada para la migración de imágenes a Gemini (ver PLAN.md) — aún no consumida por el código |
| `IMAGE_QC_ENABLED` / `IMAGE_QC_MAX_RETRIES` | Control de calidad de imágenes vía Claude vision |
| `ELEVENLABS_API_KEY` / `ELEVENLABS_VOICE_ID` | TTS — solo nichos narrados |
| `YOUTUBE_API_KEY` | Usada por `result_tracker.py` para leer métricas de videos propios publicados |

## Estructura de archivos

```
factory/
├── Dockerfile              # Python + Node + Chromium del sistema
├── requirements.txt
├── src/
│   ├── scheduler.py        # cron diario, entry point
│   ├── worker.py           # RQ worker, entry point
│   ├── topic_scraper.py
│   ├── script_generator.py
│   ├── asset_generator.py
│   ├── render_worker.py
│   ├── jobs.py
│   ├── queue.py
│   ├── result_tracker.py
│   ├── setup_channel.py
│   └── db.py
└── remotion/                # proyecto Remotion (React) — plantillas versionadas
    ├── package.json
    └── src/{index.ts,Root.tsx,MainVideo.tsx,types.ts}
```

## Troubleshooting

**Videos atascados en `scripting`:**
```sql
UPDATE videos SET status = 'queued' WHERE status = 'scripting' AND script IS NULL;
```

**Topics atascados en `selected` sin video:**
```sql
SELECT t.id, t.title FROM topics t
LEFT JOIN videos v ON v.topic_id = t.id
WHERE t.status = 'selected' AND v.id IS NULL;

UPDATE topics SET status = 'pending' WHERE id IN (<ids>);
```

**Videos atascados en `generating_assets` o `rendering`:** el job de RQ agotó los 2 reintentos — revisar `docker compose logs factory-worker` para la causa real, después re-encolar:
```powershell
docker compose exec factory-worker python -c "from src.jobs import process_video; process_video(8)"
```

**Build falla en el paso de Chromium/npm install:** es el paso de mayor riesgo del proyecto (headless Chrome en Docker es frágil). Copiar el error exacto de `docker compose up -d --build factory-scheduler`; si es una `.so` faltante, instalar el paquete apt correspondiente en el `Dockerfile`; si es timeout de `npm install`, reintentar.

**Render falla con error de Chromium/Remotion:**
```powershell
docker compose logs factory-worker
docker compose exec factory-worker sh -c "cd remotion && npx remotion render src/index.ts MainVideo /tmp/test.mp4 --browser-executable=/usr/bin/chromium"
```

**Costos de ElevenLabs en pruebas:** `asset_generator` es idempotente — reintentar un video fallido no regenera lo que ya existe en disco, solo completa lo que faltó.

**Reset de datos de prueba:** ver [db/README.md](../db/README.md#reset-de-datos-de-prueba).
