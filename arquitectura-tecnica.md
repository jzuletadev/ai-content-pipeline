# Arquitectura Técnica — Sistema de Descubrimiento y Producción de Contenido IA

> Documento de arquitectura — versión 1.0
> Perfil del operador: desarrollador con experiencia en infra (local y nube), control total, prefiere ver código.
> Principio rector: APIs directas (pago por uso), nada de plataformas SaaS cerradas, render self-hosted.

---

## 1. Visión general

El sistema son **dos subsistemas independientes** que comparten base de datos y se retroalimentan:

- **Sistema A — Radar de nichos:** corre semanal. Descubre qué nichos de contenido IA están funcionando y cuáles no están saturados. Acumula su propia base histórica de métricas. Output: un reporte de oportunidades.
- **Sistema B — Fábrica de contenido:** corre diario. Una vez elegido un nicho, produce videos completos para ese nicho y los deja listos para revisión y publicación manual.

Ambos se comunican por la base de datos y por una cola de trabajos. No hay acoplamiento directo: el radar puede correr sin la fábrica y viceversa.

---

## 2. Decisiones de arquitectura (con justificación)

| Decisión | Elección | Por qué |
|---|---|---|
| Lenguaje del orquestador | Python | Mejor ecosistema para scraping, manejo de medios, clientes de APIs de IA |
| Render de video | Remotion (Node/React) | Control total, self-hosted, sin cuota de plataforma. Único componente en Node |
| Base de datos | PostgreSQL | Necesitás queries analíticas (agregaciones, ventanas temporales) para el radar. SQLite se queda corto cuando acumulás histórico |
| Cola de trabajos | Redis + RQ (o Celery) | Los jobs de video son largos (minutos) y fallan; necesitás reintentos y visibilidad |
| Almacenamiento de assets | S3 / R2 / B2 | Los videos pesan. Local no escala y no es respaldable fácil |
| Orquestación de servicios | Docker Compose | Reproducible, fácil de mover entre local y VPS |
| Scheduler | Cron del host o APScheduler | A esta escala no necesitás Airflow |

**Nota sobre Python + Node:** el sistema es mayormente Python, pero Remotion es Node. La separación es limpia: Python prepara un archivo JSON con todo lo que el video necesita (rutas de assets, textos, tiempos), y dispara el render de Remotion como subproceso. Remotion lee ese JSON y produce el MP4. Cero acoplamiento de lógica entre ambos.

---

## 3. Topología de componentes

```
                    ┌─────────────────────────────┐
                    │   PostgreSQL  +  Redis        │
                    │   (estado compartido)         │
                    └──────────┬──────────┬─────────┘
                               │          │
         ┌─────────────────────┘          └────────────────────┐
         │                                                       │
┌────────▼─────────┐                              ┌─────────────▼──────────┐
│  SISTEMA A        │                              │  SISTEMA B              │
│  Radar de nichos  │                              │  Fábrica de contenido   │
│  (cron semanal)   │                              │  (cron diario)          │
│                   │                              │                         │
│  channel_scraper  │                              │  topic_scraper          │
│  niche_analyzer   │                              │  script_generator       │
│  snapshot_writer  │                              │  asset_generator        │
│  report_builder   │                              │  render_worker (Remotion)│
└───────────────────┘                              │  dashboard (FastAPI)    │
                                                    └─────────────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │  Object Storage      │
                    │  (S3 / R2 / B2)      │
                    └──────────────────────┘
```

---

## 4. Esquema de base de datos

El esquema está diseñado para que el radar acumule histórico (snapshots) y para que la fábrica tenga trazabilidad completa de cada video.

```sql
-- ===== SISTEMA A: Radar de nichos =====

-- Canales que el radar vigila
CREATE TABLE channels (
    id              BIGSERIAL PRIMARY KEY,
    platform        TEXT NOT NULL,           -- 'youtube', 'tiktok'
    platform_id     TEXT NOT NULL,           -- ID del canal en la plataforma
    handle          TEXT,
    title           TEXT,
    niche_guess     TEXT,                    -- nicho inferido por el analyzer
    is_ai_content   BOOLEAN DEFAULT NULL,    -- detectado como contenido IA
    discovered_at   TIMESTAMPTZ DEFAULT now(),
    UNIQUE (platform, platform_id)
);

-- Snapshots periódicos: AQUÍ está el valor del radar.
-- YouTube no te da histórico, así que lo construís vos guardando fotos semanales.
CREATE TABLE channel_snapshots (
    id              BIGSERIAL PRIMARY KEY,
    channel_id      BIGINT REFERENCES channels(id),
    captured_at     TIMESTAMPTZ DEFAULT now(),
    subscribers     BIGINT,
    total_views     BIGINT,
    video_count     INT
);

-- Videos individuales observados (para calcular proxies de retención/viralidad)
CREATE TABLE observed_videos (
    id              BIGSERIAL PRIMARY KEY,
    channel_id      BIGINT REFERENCES channels(id),
    platform_id     TEXT NOT NULL,
    title           TEXT,
    published_at    TIMESTAMPTZ,
    duration_sec    INT,
    captured_at     TIMESTAMPTZ DEFAULT now(),
    views           BIGINT,
    likes           BIGINT,
    comments        BIGINT,
    UNIQUE (platform_id, captured_at)
);

-- Nichos detectados y su score de oportunidad
CREATE TABLE niches (
    id                  BIGSERIAL PRIMARY KEY,
    name                TEXT NOT NULL,        -- 'historias animadas de amor'
    demand_score        NUMERIC,              -- qué tan alto es el consumo
    saturation_score    NUMERIC,              -- qué tan lleno está
    opportunity_score   NUMERIC,              -- demanda / saturación, ponderado
    sample_channels     JSONB,                -- canales de referencia
    computed_at         TIMESTAMPTZ DEFAULT now()
);

-- ===== SISTEMA B: Fábrica de contenido =====

-- El nicho que elegiste atacar y su canal
CREATE TABLE active_channels (
    id              BIGSERIAL PRIMARY KEY,
    name            TEXT NOT NULL,            -- nombre de tu canal
    niche_id        BIGINT REFERENCES niches(id),
    style_config    JSONB,                    -- estética, formato, voz, etc.
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- Temas detectados por el topic_scraper para producir
CREATE TABLE topics (
    id              BIGSERIAL PRIMARY KEY,
    active_channel_id BIGINT REFERENCES active_channels(id),
    title           TEXT,
    source_ref      TEXT,                     -- de dónde salió el tema
    trend_score     NUMERIC,
    status          TEXT DEFAULT 'pending',   -- pending|selected|discarded
    detected_at     TIMESTAMPTZ DEFAULT now()
);

-- Cada video producido, con trazabilidad completa
CREATE TABLE videos (
    id              BIGSERIAL PRIMARY KEY,
    topic_id        BIGINT REFERENCES topics(id),
    active_channel_id BIGINT REFERENCES active_channels(id),
    status          TEXT DEFAULT 'queued',
    -- queued|scripting|generating_assets|rendering|review|approved|rejected|published
    script          JSONB,                    -- guion estructurado
    metadata        JSONB,                    -- título, descripción, hashtags
    assets          JSONB,                    -- rutas a imágenes, audio, clips
    render_path     TEXT,                     -- ruta al MP4 final
    audio_ref       TEXT,                     -- para música: nombre del audio nativo
    created_at      TIMESTAMPTZ DEFAULT now(),
    published_at    TIMESTAMPTZ
);

-- Resultados post-publicación (cierra el loop con el radar)
CREATE TABLE video_results (
    id              BIGSERIAL PRIMARY KEY,
    video_id        BIGINT REFERENCES videos(id),
    captured_at     TIMESTAMPTZ DEFAULT now(),
    views           BIGINT,
    likes           BIGINT,
    comments        BIGINT,
    shares          BIGINT
);
```

---

## 5. Sistema A — Radar de nichos en detalle

### 5.1 channel_scraper

Descubre y mide canales de contenido IA. Fuentes de descubrimiento:

- Búsqueda por keywords en YouTube Data API (términos asociados a formatos IA: "AI story", "lyric video", etc.)
- Canales relacionados / recomendados a partir de semillas que vos das
- Hashtags en TikTok (vía scraping controlado, ver nota legal)

Lo que extrae por la YouTube Data API (gratis, con quota de 10,000 unidades/día):
- `channels.list`: subscriberCount, viewCount, videoCount
- `search.list` + `videos.list`: por cada video reciente, viewCount, likeCount, duración, fecha

### 5.2 Qué se puede medir y qué no (honestidad técnica)

| Métrica que querés | ¿Disponible por API ajena? | Proxy que sí podés calcular |
|---|---|---|
| Retención (% que ve el video completo) | NO (solo el dueño la ve) | Ratio likes/views + duración + consistencia |
| Histórico de crecimiento del canal | NO directamente | Lo construís con `channel_snapshots` semanales |
| Vistas por video | SÍ | Directo |
| Velocidad de viralización | Parcial | views ÷ días desde publicación |
| Penetración fuera de su base | Calculable | views promedio ÷ subscribers |

La métrica más potente que SÍ tenés es **views/subscribers ratio**. Un canal con 50K subs cuyos videos promedian 2M vistas está llegando masivamente fuera de su audiencia — eso es viralidad real y formato validado. Eso lo calculás perfecto con datos públicos.

### 5.3 niche_analyzer — fórmula de oportunidad

```python
# Pseudocódigo de la lógica de scoring

def compute_opportunity(niche_channels):
    # DEMANDA: qué tan hambriento está el público de este formato
    avg_views_per_video = mean([c.recent_avg_views for c in niche_channels])
    avg_penetration = mean([c.avg_views / max(c.subs, 1) for c in niche_channels])
    young_breakouts = count(c for c in niche_channels
                            if c.age_days < 90 and c.subs > 50_000)

    demand = weighted(
        avg_views_per_video,   # consumo bruto
        avg_penetration,       # alcance fuera de base
        young_breakouts        # señal de formato fresco y validado
    )

    # SATURACIÓN: qué tan dominado está el nicho
    established = count(c for c in niche_channels if c.subs > 1_000_000)
    total_channels = len(niche_channels)

    saturation = weighted(established, total_channels)

    # OPORTUNIDAD: mucho consumo, pocos dominadores
    opportunity = demand / (saturation + epsilon)
    return demand, saturation, opportunity
```

El hueco ideal: `demand` alto, `saturation` bajo, y presencia de `young_breakouts` (canales nuevos explotando = formato validado pero no copado).

### 5.4 snapshot_writer

Corre semanal. Guarda una foto de cada canal vigilado en `channel_snapshots`. Después de 4-6 semanas tenés curvas de crecimiento reales que ninguna API te habría dado. Este es el activo que hace al radar cada vez más inteligente.

### 5.5 report_builder

Genera el reporte de oportunidades: top nichos ordenados por `opportunity_score`, con canales de muestra, métricas, y ejemplos de videos. Vos lo revisás y decidís.

---

## 6. Sistema B — Fábrica de contenido en detalle

### 6.1 Flujo de un video (máquina de estados)

```
queued
  → scripting           (Claude genera guion + prompts + metadata)
  → generating_assets   (imágenes, video IA, voz, avatar)
  → rendering           (Remotion ensambla todo)
  → review              (espera tu aprobación en el dashboard)
  → approved / rejected
  → published           (vos lo subís manualmente, marcás como publicado)
```

Cada transición se guarda en `videos.status`. Si un paso falla, el job vuelve a la cola con backoff. Los outputs intermedios se persisten para no re-generar lo costoso.

### 6.2 Etapas y APIs (todas pago-por-uso, sin suscripción)

| Etapa | Servicio | Cobro | Notas |
|---|---|---|---|
| Guion + prompts + metadata | Claude API | por token | También genera los prompts de imagen/video |
| Imágenes / fondos | Gemini (Nano Banana) o Vertex AI | por imagen | ~$0.04/img |
| Video generativo | Veo, Kling o Runway | por segundo | El más caro; elegir según estilo |
| Voz (TTS) | ElevenLabs API | por caracteres | Tier gratis + pago por uso |
| Avatar parlante (si aplica) | HeyGen API | por minuto | Solo si el nicho lo requiere |
| Ensamble final | Remotion | $0 self-hosted | Render en tu máquina/VPS |

### 6.3 El contrato Python → Remotion

Python no renderiza. Prepara un JSON y dispara Remotion como subproceso:

```python
# render_worker.py
import json, subprocess
from pathlib import Path

def render_video(video_id: int, spec: dict) -> str:
    """
    spec contiene todo lo que el video necesita:
    - scenes: lista de {background_image, text, start, duration}
    - audio_path: voz o pista
    - subtitles: lista de {text, start, end}
    - style: colores, fuentes, transiciones
    """
    spec_path = Path(f"/tmp/render_{video_id}.json")
    spec_path.write_text(json.dumps(spec))

    out_path = f"/data/renders/{video_id}.mp4"

    # Remotion renderiza leyendo el JSON como input props
    subprocess.run([
        "npx", "remotion", "render",
        "src/index.ts",            # composición Remotion
        "MainVideo",               # id de la composición
        out_path,
        f"--props={spec_path}",
    ], check=True, cwd="/app/remotion")

    return out_path
```

```tsx
// Remotion: MainVideo.tsx (lado Node/React)
// Lee las props que Python pasó y arma el video con código.
import { useCurrentFrame, AbsoluteFill, Img, Audio, Sequence } from "remotion";

export const MainVideo: React.FC<{ scenes: Scene[]; audioPath: string }> = ({
  scenes, audioPath
}) => {
  return (
    <AbsoluteFill>
      <Audio src={audioPath} />
      {scenes.map((scene, i) => (
        <Sequence key={i} from={scene.start} durationInFrames={scene.duration}>
          <Img src={scene.backgroundImage} />
          <SubtitleOverlay text={scene.text} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
```

Esta separación es la clave de tu "control total": la lógica de negocio vive en Python, la presentación visual en plantillas Remotion que vos escribís y versionás como código.

### 6.4 El caso especial de la música

Para lyric videos el render produce un video MUDO (sin audio embebido). El `videos.audio_ref` guarda el nombre exacto de la canción para que vos añadás el audio nativo en la plataforma y quedes dentro de la licencia.

Para sincronizar la letra sin tener el audio embebido, el sistema necesita BPM y duración:

```python
# Obtener tempo y duración para sincronizar la letra animada
# Spotify API: audio-features endpoint da tempo, duration_ms, etc.
def get_sync_data(track_name: str, artist: str) -> dict:
    track = spotify.search(q=f"{track_name} {artist}", type="track")
    track_id = track["tracks"]["items"][0]["id"]
    features = spotify.audio_features([track_id])[0]
    return {
        "bpm": features["tempo"],
        "duration_sec": features["duration_ms"] / 1000,
    }
```

Con BPM y duración, el layout planner reparte las líneas de letra en el tiempo, y Remotion las anima al ritmo correcto. Cuando vos pegás el audio nativo, encaja.

---

## 7. El dashboard de revisión

API en FastAPI + frontend mínimo. Solo lo usás vos. Endpoints:

```
GET  /videos?status=review     → lista de videos esperando aprobación
GET  /videos/{id}              → detalle: preview, guion, metadata, audio_ref
POST /videos/{id}/approve      → marca approved, deja descargable el MP4
POST /videos/{id}/reject       → marca rejected (opcional: regenerar)
POST /videos/{id}/published    → marca published, dispara tracking de resultados
```

El frontend muestra por cada video: reproductor, título/descripción/hashtags con botón de copiar, y para música el nombre del audio + link. Botones aprobar / rechazar / regenerar.

---

## 8. Orquestación y despliegue

### docker-compose.yml (estructura)

```yaml
services:
  postgres:
    image: postgres:16
    volumes: [pgdata:/var/lib/postgresql/data]

  redis:
    image: redis:7

  radar:
    build: ./radar
    command: python -m radar.scheduler   # cron interno semanal
    depends_on: [postgres, redis]

  factory-worker:
    build: ./factory
    command: rq worker video_jobs        # procesa la cola
    depends_on: [postgres, redis]
    # monta volumen con node+remotion para el render

  factory-scheduler:
    build: ./factory
    command: python -m factory.scheduler # cron diario que encola temas
    depends_on: [postgres, redis]

  dashboard:
    build: ./dashboard
    ports: ["8080:8080"]
    command: uvicorn dashboard.main:app --host 0.0.0.0 --port 8080

volumes:
  pgdata:
```

### Dónde correrlo

- **Desarrollo:** todo local con Docker Compose.
- **Producción:** un VPS con buena CPU para el render de Remotion (el render es CPU-bound; no necesitás GPU porque la generación de video IA ocurre en las APIs externas, no en tu máquina). Un VPS de 4-8 vCPU alcanza para 3 videos/día.
- **Storage:** Cloudflare R2 o Backblaze B2 (sin cargos de egreso como S3).

---

## 9. Estimación de costos mensuales (escala pequeña: ~3 videos/día)

| Componente | Costo |
|---|---|
| VPS (4-8 vCPU para render) | $20–40 |
| PostgreSQL (en el mismo VPS o gestionado) | $0–15 |
| Object storage (R2/B2) | $5–10 |
| Claude API (guiones) | $3–8 |
| Gemini imágenes | $10–25 |
| Video IA (Veo/Kling, el variable grande) | $30–150 |
| ElevenLabs (voz) | $5–22 |
| **Total** | **~$80–270/mes** |

El rango es amplio porque el video generativo es el costo dominante y depende de cuántos segundos generás. Si la música usa fondos animados con loops reutilizables en vez de video IA fresco por cada video, ese costo baja muchísimo.

---

## 10. Consideraciones legales y de ToS (resumen técnico)

- **Scraping de TikTok:** no tienen API pública de tendencias abierta. El scraping de páginas públicas está en zona gris de ToS. YouTube Data API es la fuente limpia y legal; priorizar YouTube para el radar.
- **Publicación:** 100% manual por diseño, elimina el riesgo de ban por automatización.
- **Música:** audio siempre nativo de la plataforma, nunca embebido. El render produce video mudo.
- **Contenido IA:** etiquetar como generado por IA donde la plataforma lo exija (TikTok, Meta).

---

## 11. Orden de construcción sugerido

El sistema es grande; no se construye de una. Secuencia recomendada:

1. **Esqueleto de datos:** PostgreSQL + esquema + Docker Compose corriendo. Base sobre la que todo se apoya.
2. **Radar mínimo:** channel_scraper + snapshot_writer contra YouTube Data API. Empezá a acumular histórico desde ya, porque el valor del radar crece con el tiempo.
3. **niche_analyzer + report_builder:** una vez tengas datos, calculá oportunidades.
4. **Fábrica — pipeline de texto:** topic_scraper + script_generator (Claude). Validá guiones antes de gastar en assets.
5. **Fábrica — assets + render:** integrá imágenes, voz, y Remotion. Primer video completo.
6. **Dashboard:** la capa de revisión.
7. **Loop de analytics:** video_results retroalimentando al radar.

El paso 2 conviene arrancarlo cuanto antes aunque el resto no esté, porque cada semana que el snapshot_writer no corre es histórico que perdés para siempre.

---

*Documento vivo. Se actualiza conforme se toman decisiones de implementación.*
