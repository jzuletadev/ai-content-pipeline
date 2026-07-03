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
- [ ] `ANTHROPIC_API_KEY` en `.env`
- [ ] Crear primer registro en `active_channels` (tu canal + nicho elegido tras Fase 3)

### Código
- [ ] `factory/Dockerfile` (Python + Node para Fase 5)
- [ ] `factory/requirements.txt`
- [ ] `factory/src/__init__.py`
- [ ] `factory/src/db.py`
- [ ] `factory/src/topic_scraper.py`
  - Detecta temas del día para el nicho activo (RSS, Google Trends, YouTube trending)
  - Inserta en tabla `topics` con `status = 'pending'`
- [ ] `factory/src/script_generator.py`
  - Llama Claude API
  - Input: topic + style_config del active_channel
  - Output: guion estructurado (escenas, texto, tiempos) + prompts de imagen + metadata (título, descripción, hashtags)
  - Guarda en `videos.script`, `videos.metadata`; avanza status a `generating_assets`
- [ ] `factory/src/scheduler.py` — cron diario

### Verificación
- [ ] Job de texto corre end-to-end
- [ ] `SELECT script, metadata FROM videos WHERE status = 'generating_assets' LIMIT 1;`
- [ ] Guion tiene estructura coherente y metadata lista

---

## Fase 5 — Fábrica: assets + render
**Objetivo:** Generar imágenes, voz y ensamblar video completo con Remotion.

### Configuración
- [ ] `GOOGLE_API_KEY` en `.env` (Gemini para imágenes)
- [ ] `ELEVENLABS_API_KEY` en `.env`
- [ ] Node.js + Remotion instalado en imagen Docker de factory

### Código
- [ ] `factory/src/asset_generator.py`
  - Llama Gemini API para generar imágenes de cada escena
  - Llama ElevenLabs API para generar audio (voz)
  - Guarda paths en `videos.assets`; avanza status a `rendering`
- [ ] `factory/remotion/src/index.ts` — entry point Remotion
- [ ] `factory/remotion/src/MainVideo.tsx` — composición base
  - Lee props del JSON spec (escenas, audio, subtítulos, estilo)
  - Renderiza secuencias con `Sequence`, `Img`, `Audio`
- [ ] `factory/src/render_worker.py`
  - Prepara JSON spec desde `videos.assets` + `videos.script`
  - Dispara `npx remotion render` como subproceso
  - Guarda path del MP4 en `videos.render_path`; avanza status a `review`
- [ ] Actualizar `docker-compose.yml`: descomentar `factory-worker` y `factory-scheduler`

### Verificación
- [ ] Primer MP4 generado en `/data/renders/`
- [ ] `SELECT render_path FROM videos WHERE status = 'review';` devuelve path válido
- [ ] Video se puede reproducir y tiene sentido visual

---

## Fase 6 — Dashboard de revisión
**Objetivo:** Interfaz para aprobar/rechazar videos y copiar metadata antes de publicar.

### Código
- [ ] `dashboard/Dockerfile`
- [ ] `dashboard/requirements.txt`
- [ ] `dashboard/src/__init__.py`
- [ ] `dashboard/src/main.py` — FastAPI app
  - `GET /videos?status=review` — lista videos en cola
  - `GET /videos/{id}` — detalle: script, metadata, audio_ref
  - `POST /videos/{id}/approve` — marca `approved`
  - `POST /videos/{id}/reject` — marca `rejected`
  - `POST /videos/{id}/published` — marca `published`, dispara tracking
- [ ] `dashboard/src/templates/index.html` — lista de videos
- [ ] `dashboard/src/templates/video.html`
  - Reproductor del MP4
  - Título / descripción / hashtags con botón copiar
  - Para música: nombre del audio nativo + link
  - Botones aprobar / rechazar / regenerar
- [ ] Actualizar `docker-compose.yml`: descomentar `dashboard`

### Verificación
- [ ] `http://127.0.0.1:8080` carga sin error
- [ ] Video en estado `review` aparece en la lista
- [ ] Aprobar cambia status a `approved` en BD
- [ ] MP4 descargable después de aprobar

---

## Fase 7 — Loop de analytics
**Objetivo:** Métricas post-publicación retroalimentan al radar para refinar scoring.

### Código
- [ ] `factory/src/result_tracker.py`
  - Para cada video con `status = 'published'`, llama YouTube Data API
  - Lee views, likes, comments del video propio
  - Inserta en `video_results`
- [ ] Conectar `video_results` al `niche_analyzer`
  - El scoring pondera performance real de videos propios
  - Nichos donde tus videos rinden bien suben en `opportunity_score`
- [ ] Agregar `result_tracker.run()` al scheduler de factory (diario)

### Verificación
- [ ] `SELECT * FROM video_results ORDER BY captured_at DESC LIMIT 10;`
- [ ] Después de publicar manualmente y marcar `published`, métricas se capturan solas
- [ ] `niches.opportunity_score` evoluciona semana a semana con datos reales

---

## Resumen de estado

| Fase | Descripción               | Estado        |
|------|---------------------------|---------------|
| 1    | Esqueleto de datos        | ✓ Completo    |
| 2    | Radar mínimo              | ✓ Completo    |
| 3    | Análisis de nichos        | ✓ Completo    |
| 4    | Fábrica: pipeline texto   | ✓ Completo    |
| 5    | Fábrica: assets + render  | ○ Pendiente   |
| 6    | Dashboard                 | ○ Pendiente   |
| 7    | Loop de analytics         | ○ Pendiente   |

---

## APIs necesarias por fase

| API | Fase | Dónde conseguir |
|-----|------|-----------------|
| YouTube Data API v3 | 2, 7 | Google Cloud Console → habilitar API → clave |
| Anthropic (Claude) | 4 | console.anthropic.com |
| Google AI (Gemini) | 5 | Google Cloud Console → Vertex AI o AI Studio |
| ElevenLabs | 5 | elevenlabs.io → Profile → API Key |
| Spotify (opcional) | 5 | developer.spotify.com → crear app |

---

*Documento vivo. Actualizar estado al completar cada tarea.*
