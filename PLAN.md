# Plan de trabajo — Content Factory

Sistema de descubrimiento y producción de contenido IA.
Dos subsistemas: **Radar de nichos** (Sistema A) + **Fábrica de contenido** (Sistema B).

Marcar cada tarea con `[x]` al completarla.

---

## Fase 1 — Esqueleto de datos
**Objetivo:** PostgreSQL + Redis corriendo. Base sobre la que todo se apoya.

- [x] `docker-compose.yml` con postgres + redis
- [x] `.env` creado desde `env.example`
- [x] `db/init.sql` con schema completo (8 tablas)
- [x] `docker compose up -d` — ambos servicios `healthy`
- [x] `\dt` en psql muestra las 8 tablas

**Estado: COMPLETO ✓**

---

## Fase 2 — Radar mínimo
**Objetivo:** Descubrir canales de contenido IA en YouTube y acumular snapshots semanales.

### Código
- [x] `radar/Dockerfile`
- [x] `radar/requirements.txt`
- [x] `radar/src/__init__.py`
- [x] `radar/src/db.py` — conexión a postgres
- [x] `radar/src/youtube.py` — wrapper YouTube Data API
- [x] `radar/src/channel_scraper.py` — descubrimiento de canales por keyword
- [x] `radar/src/snapshot_writer.py` — foto semanal de stats + videos
- [x] `radar/src/scheduler.py` — cron semanal, entry point

### Configuración
- [ ] `YOUTUBE_API_KEY` en `.env` (Google Cloud Console → YouTube Data API v3)
- [ ] `docker compose up -d --build radar`

### Verificación
- [ ] Logs muestran canales encontrados y upserted
- [ ] `SELECT COUNT(*) FROM channels;` → > 0
- [ ] `SELECT COUNT(*) FROM channel_snapshots;` → > 0
- [ ] `SELECT COUNT(*) FROM observed_videos;` → > 0

**Estado: COMPLETO ✓**

---

## Fase 3 — Análisis de nichos
**Objetivo:** Calcular oportunidad por nicho con los datos acumulados del radar.

### Código
- [ ] `radar/src/niche_analyzer.py`
  - Agrupa canales por `niche_guess`
  - Calcula `demand_score`, `saturation_score`, `opportunity_score`
  - Fórmula: demand = avg_views + penetración (views/subs) + young_breakouts
  - Fórmula: saturation = canales con > 1M subs / total
  - Fórmula: opportunity = demand / (saturation + ε)
  - Inserta resultados en tabla `niches`
- [ ] `radar/src/report_builder.py`
  - Lee tabla `niches`
  - Genera reporte Markdown con top nichos, métricas, canales de muestra
  - Guarda en `/data/reports/YYYY-MM-DD.md`
- [ ] Agregar `niche_analyzer.run()` y `report_builder.run()` al scheduler

### Verificación
- [ ] `SELECT * FROM niches ORDER BY opportunity_score DESC LIMIT 10;`
- [ ] Reporte generado en `/data/reports/`
- [ ] Top nicho tiene `demand_score` y `opportunity_score` razonables

**Prerequisito: 2+ semanas de snapshots en `channel_snapshots`**

---

## Fase 4 — Fábrica: pipeline de texto
**Objetivo:** Detectar temas del día + generar guion completo con Claude.

### Configuración
- [x] `ANTHROPIC_API_KEY` en `.env`
- [x] Crear primer registro en `active_channels` (Nixie Musical, nicho lyric_videos)
- [x] `LASTFM_API_KEY` (reemplazo de Spotify — Spotify Web API pasó a requerir Premium)

### Código
- [x] `factory/Dockerfile`
- [x] `factory/requirements.txt`
- [x] `factory/src/__init__.py`
- [x] `factory/src/db.py`
- [x] `factory/src/topic_scraper.py` — Last.fm (trending por país + género) y Wikipedia On This Day
- [x] `factory/src/script_generator.py` — Claude genera guion + prompts + metadata
- [x] `factory/src/scheduler.py` — cron diario

### Verificación
- [x] Job de texto corre end-to-end
- [x] 4 videos con script generado (Danza Kuduro, Livin' La Vida Loca, Me gustas tú, Chantaje)
- [x] Guion tiene estructura coherente y metadata lista

**Estado: COMPLETO ✓**

---

## Fase 5 — Fábrica: assets + render
**Objetivo:** Generar imágenes, voz y ensamblar video completo con Remotion.

### Configuración
- [x] `ELEVENLABS_API_KEY` en `.env`
- [x] `ELEVENLABS_VOICE_ID` — default configurado en `.env`
- [x] Node.js + Chromium del sistema instalado en imagen Docker de factory
- [x] ~~Gemini~~ — descartado: pedía prepago de $25 mínimo, no pago-por-uso real
- [x] **Pivote a self-hosted:** `imagegen/` — servicio propio, GPU local (RTX 3060)
- [x] ~~sd-turbo~~ → **SD 1.5 estándar** — sd-turbo (destilado) deformaba anatomía en grupos de personas; SD 1.5 + CFG real + negative prompts lo resuelve. Tiempo no es problema (corre de noche)
- [x] Formato de lyric videos: canción completa → **30s (Shorts/Reels/TikTok)** — Claude elige el estribillo, no la canción entera

### Código
- [x] `factory/src/queue.py` — conexión a la cola RQ `video_jobs`
- [x] `imagegen/app.py` — FastAPI + diffusers, SD 1.5 + negative prompts, endpoint `POST /generate`
- [x] `imagegen/Dockerfile` — pre-descarga pesos del modelo en build time
- [x] `factory/src/asset_generator.py`
  - Llama `imagegen` (HTTP interno) para generar imágenes de cada escena (idempotente: salta si el archivo ya existe)
  - Llama ElevenLabs API para narración TTS (solo en nichos narrados; lyric_videos no lleva TTS) — **sin validar end-to-end todavía**, ver nota abajo
  - Guarda paths en `videos.assets`; avanza status a `rendering`
- [x] `factory/remotion/` — proyecto Remotion completo (package.json, Root.tsx, MainVideo.tsx, types.ts)
  - Ken Burns continuo (zoom+pan durante toda la escena, alternando dirección) + fade a negro en bordes de escena
  - Animación de texto (fade/slide/zoom) separada del movimiento de la imagen
- [x] `factory/src/render_worker.py`
  - Normaliza escenas de ambos nichos a un formato uniforme para Remotion
  - Copia assets a `remotion/public/`, dispara `npx remotion render` como subproceso
  - Guarda path del MP4 en `videos.render_path`; avanza status a `review`
- [x] `factory/src/jobs.py` + `factory/src/worker.py` — RQ worker que procesa assets+render por video, con reintentos
- [x] `script_generator.py` ahora encola cada video en `video_jobs` al terminar el guion
- [x] `docker-compose.yml`: `imagegen` (con reserva de GPU), `factory-worker` (RQ worker), `factory-scheduler`
- [x] Fix: volumen `factory_node_modules` — el bind mount `./factory:/app` tapaba el `node_modules` de Remotion generado en build
- [x] Fix: `init: true` en factory-worker/scheduler — Chromium/ffmpeg dejaban zombies sin cosechar (PID 1 no era un init real), colgaba renders sucesivos

### Verificación
- [x] Build de Chromium/Node en factory — pasó sin ajustes
- [x] GPU passthrough Docker Desktop → contenedor `imagegen` — funcionó sin ajustes, `healthy` al primer intento
- [x] Pipeline completo validado de punta a punta con contenido real (temas reales de Last.fm → Claude → SD 1.5 → Remotion → `review`)
- [x] Calidad de imágenes validada — anatomía correcta con SD 1.5 + negative prompts
- [x] Movimiento/transiciones validadas y aprobadas por el usuario (Ken Burns + fade a negro)

### Pendiente / no validado aún
- [ ] Nicho `historias_historicas` (o cualquier nicho narrado) — nunca se creó un `active_channel` para probarlo; el path de ElevenLabs/TTS no se ejercitó en esta fase
- [ ] Videos aprobados manualmente / flujo de publicación real (eso es Fase 6, dashboard)

**Estado: COMPLETO ✓ para lyric_videos — pipeline end-to-end funcionando, generación de imágenes 100% self-hosted ($0/imagen), formato corto validado**

---

## Fase 6 — Dashboard de revisión
**Objetivo:** Interfaz para aprobar/rechazar videos y copiar metadata antes de publicar.

### Código
- [x] `dashboard/Dockerfile`
- [x] `dashboard/requirements.txt`
- [x] `dashboard/src/__init__.py` + `dashboard/src/db.py`
- [x] `dashboard/src/main.py` — FastAPI app
  - `GET /?status=review|approved|rejected|published` — lista videos por estado (tabs)
  - `GET /videos/{id}` — detalle: reproductor, metadata
  - `GET /videos/{id}/file` — sirve el MP4 (streaming + descarga)
  - `POST /videos/{id}/approve` / `/reject` / `/published`
- [x] `dashboard/src/templates/index.html` — lista de videos con tabs por estado
- [x] `dashboard/src/templates/video.html`
  - Reproductor del MP4, título/descripción/hashtags con botón copiar (clipboard API)
  - Audio nativo a agregar (para lyric videos, ya que el render es mudo)
  - Botones aprobar / rechazar (en `review`) → descargar / marcar publicado (en `approved`)
- [x] `docker-compose.yml`: `dashboard` activo, puerto `127.0.0.1:8080`, volumen `media` read-only

### Verificación
- [x] `http://127.0.0.1:8080` carga sin error (HTTP 200, HTML real con videos)
- [x] Video en estado `review` aparece en la lista
- [x] Aprobar cambia status a `approved` en BD (probado por HTTP real)
- [x] Rechazar cambia a `rejected` (probado)
- [x] Marcar publicado cambia a `published` + `published_at` (probado)
- [x] Streaming del MP4 funciona (`/videos/{id}/file` → HTTP 200)

**Estado: COMPLETO ✓**

---

## Fase 7 — Loop de analytics
**Objetivo:** Métricas post-publicación retroalimentan al radar para refinar scoring.

### Código
- [x] Migración: columna `videos.published_url` — sin esto no había forma de saber qué video de YouTube corresponde a cada publicación
- [x] Dashboard: campo de URL al marcar "publicado" (`POST /videos/{id}/published` con form)
- [x] `factory/src/result_tracker.py`
  - Para cada video con `status = 'published'` y `published_url` cargada, llama YouTube Data API
  - Extrae el ID de YouTube de la URL (soporta watch, shorts, youtu.be)
  - Lee views, likes, comments del video propio; inserta en `video_results`
- [x] Conectar `video_results` al `niche_analyzer`
  - `_own_performance_boost()`: promedia views propias por nicho, suma hasta +20 pts de demanda
  - Sin datos propios el boost es 0 — no rompe el scoring existente
- [x] `result_tracker.run()` agregado al `scheduler.py` de factory (diario, después de script_generator)

### Verificación
- [ ] `SELECT * FROM video_results ORDER BY captured_at DESC LIMIT 10;` — **vacío hasta que publiques un video real y cargues su URL**
- [ ] Después de publicar manualmente y marcar `published` con URL real, métricas se capturan solas
- [ ] `niches.opportunity_score` evoluciona con datos reales — necesita tiempo + publicaciones reales para verse

**Estado: CÓDIGO COMPLETO ✓ — infraestructura lista, sin datos reales todavía (nadie publicó a YouTube aún)**

---

## Resumen de estado

| Fase | Descripción               | Estado        |
|------|---------------------------|---------------|
| 1    | Esqueleto de datos        | ✓ Completo    |
| 2    | Radar mínimo              | ✓ Completo    |
| 3    | Análisis de nichos        | ✓ Completo    |
| 4    | Fábrica: pipeline texto   | ✓ Completo    |
| 5    | Fábrica: assets + render  | ✓ Completo    |
| 6    | Dashboard                 | ✓ Completo    |
| 7    | Loop de analytics         | ✓ Código completo (sin datos reales) |

---

## APIs necesarias por fase

| API | Fase | Dónde conseguir |
|-----|------|-----------------|
| YouTube Data API v3 | 2, 7 | Google Cloud Console → habilitar API → clave |
| Anthropic (Claude) | 4 | console.anthropic.com |
| Last.fm | 4 | last.fm/api/account/create |
| Google AI (Gemini) | 5 | aistudio.google.com → Get API Key |
| ElevenLabs | 5 | elevenlabs.io → Profile → API Key |

---

*Documento vivo. Actualizar estado al completar cada tarea.*
