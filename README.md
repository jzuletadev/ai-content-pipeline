# Content Factory — Sistema de Descubrimiento y Producción de Contenido IA

Sistema self-hosted que descubre nichos de contenido con potencial y produce videos con IA de forma semi-automatizada. Corre en Docker sobre hardware propio; el único costo recurrente son las APIs de IA (pago por uso). La publicación es siempre manual, para mantener control de calidad y eliminar el riesgo de bans por automatización.

**Enfoque actual: un solo nicho — historias animadas.** El proyecto originalmente atacaba varios nichos en paralelo (radar de descubrimiento + música + historias). Se redujo el alcance a validar un único canal de principio a fin antes de expandir. Ver [PLAN.md](PLAN.md) para el roadmap vigente, costos actualizados y el criterio para volver a abrir el radar.

---

## Qué hace

El proyecto son **dos subsistemas** que comparten base de datos y se retroalimentan:

- **Radar de nichos** (semanal, en pausa operativa): analiza canales de contenido IA, mide demanda vs. saturación, y detecta nichos con oportunidad real. Acumula su propio histórico de métricas porque las plataformas no exponen ese dato por API. Sigue corriendo en background para no perder histórico, pero no bloquea el trabajo diario mientras se valida el nicho único.
- **Fábrica de contenido** (diaria): para el nicho activo (historias animadas), detecta temas del día, genera guion + assets con IA, ensambla el video con Remotion, y lo deja listo para revisión y publicación manual.

```
Radar descubre nicho → vos elegís → Fábrica produce → vos revisás y publicás
        ▲                                                          │
        └──────────── analytics loop (qué funcionó) ◄─────────────┘
```

---

## Principios de diseño

- **Self-hosted total.** Postgres, Redis, workers, dashboard y render: todo en contenedores sobre tu equipo. Sin VPS, sin BD gestionada, sin object storage en la nube.
- **Storage local.** Renders y assets viven en un volumen Docker sobre tu disco.
- **Control total del código.** Render con Remotion (plantillas en React versionadas), no plataformas SaaS cerradas. La lógica vive en Python; Remotion solo ensambla.
- **Calidad primero mientras se valida.** Generación de imágenes vía API de Gemini (pago por uso, sin prepago) mientras se prueba si el nicho funciona. El servicio self-hosted de imágenes (`imagegen/`, GPU local, costo marginal ~$0) queda documentado y listo para retomarse si el volumen de producción lo justifica económicamente — ver [imagegen/README.md](imagegen/README.md).
- **Publicación manual.** El sistema deja todo listo; vos subís. Cero riesgo de ban por bot.
- **Nada expuesto a internet.** Solo llamadas salientes a las APIs. El dashboard escucha en localhost.

---

## Canal en marcha

| Canal | Formato | Estado |
|---|---|---|
| Historias animadas | Videos narrados (~60s) con voz TTS, imágenes generadas por IA y Ken Burns/transiciones en Remotion. | Nicho activo — validando pipeline end-to-end |
| Música (lyric videos) | Lyric videos subtitulados con fondo animado. Audio nativo agregado manualmente en la plataforma. | En pausa (código intacto, no es el foco actual) |
| Por definir (radar) | El radar de nichos determina el próximo canal con base en datos reales una vez validado el primero. | En pausa |

Idioma: contenido en español, nombres de marca en inglés.

---

## Stack

| Capa | Tecnología |
|---|---|
| Orquestación | Python |
| Render de video | Remotion (Node + React), self-hosted, CPU-bound |
| Base de datos | PostgreSQL (contenedor + volumen) |
| Cola de trabajos | Redis + RQ |
| Dashboard | FastAPI + frontend mínimo (solo localhost) |
| Despliegue | Docker Compose en hardware propio |

### APIs externas (el costo real del negocio)

| Servicio | Uso | Cobro (referencia 2026) |
|---|---|---|
| Claude (Anthropic) | Guiones, prompts, títulos, descripciones, QC de imágenes | Sonnet 5 ~$3/$15 por millón de tokens in/out (Haiku 4.5 ~$1/$5) |
| Gemini (Nano Banana / Gemini 2.5-3 Flash Image) | Imágenes de escena | ~$0.04–0.15 por imagen según resolución/modelo |
| ElevenLabs | Voz TTS (nichos narrados) | Por caracteres (tier gratis + uso) |
| YouTube Data API v3 | Métricas para el radar | Gratis (quota diaria 10K unidades) |
| Last.fm | Temas trending (música) | Gratis |
| Veo (Google) — evaluado, no integrado | Video generativo real por escena | ~$0.05–0.75/segundo según tier — ver análisis de costo/viabilidad en [PLAN.md](PLAN.md) |

Desglose completo de costo por video y el análisis de viabilidad del negocio: [PLAN.md § Costos](PLAN.md#costos-por-video-referencia-2026).

---

## Requisitos de hardware

- CPU de 6+ núcleos recomendada (el render de Remotion es CPU-bound).
- 16 GB RAM cómodos para correr todos los contenedores + render.
- **GPU opcional.** Con el path de imágenes vía Gemini no se necesita GPU en absoluto — baja bastante la barrera de entrada. Solo hace falta GPU (6GB+ VRAM) si en el futuro se retoma la generación de imágenes self-hosted (`imagegen/`).
- El equipo debe estar encendido en los horarios de los crons (o ajustar los crons a cuando esté prendido). No es un VPS siempre disponible.
- Recomendado: respaldo del volumen `media` (disco externo o rsync a otro equipo).

---

## Estructura del repositorio

```
.
├── docker-compose.yml        # orquesta todos los servicios
├── .env                       # claves de API (nunca al repo — ver .gitignore)
├── PLAN.md                    # roadmap vigente, estado por fase, costos
├── db/
│   ├── init.sql                # esquema de PostgreSQL
│   └── README.md                # documentación del esquema
├── radar/                     # Sistema A — descubrimiento de nichos
│   ├── src/                     # channel_scraper, niche_analyzer, scheduler...
│   ├── reports/                 # reportes semanales generados
│   └── README.md
├── factory/                   # Sistema B — producción de contenido
│   ├── src/                     # topic_scraper, script_generator, render_worker...
│   ├── remotion/                 # plantillas de video (React)
│   └── README.md
├── imagegen/                  # generación de imágenes self-hosted (en pausa)
│   └── README.md
└── dashboard/                 # interfaz de revisión
    └── README.md
```

Cada carpeta de servicio tiene su propio `README.md` con comandos específicos, variables de entorno y troubleshooting — este documento cubre solo lo que aplica a todo el sistema.

---

## Puesta en marcha

```powershell
# 1. Crear .env — no hay plantilla en el repo; usar la tabla de variables de cada README de servicio
#    (radar, factory, imagegen, dashboard) como referencia de qué completar
notepad .env

# 2. Levantar la capa de datos primero
docker compose up -d postgres redis
docker compose ps          # ambos deben quedar "healthy"

# 3. Verificar el esquema
docker compose exec postgres psql -U factory -d content_factory -c "\dt"   # deben aparecer 8 tablas

# 4. Levantar el resto de servicios
docker compose up -d
docker compose ps

# 5. Dashboard de revisión
# abrir http://127.0.0.1:8080

# 6. Una sola vez: crear el primer canal activo (necesita que el radar ya tenga al menos un nicho)
docker compose exec factory-scheduler python -m src.setup_channel
```

Ver [db/README.md](db/README.md) para verificación detallada de PostgreSQL/Redis y [radar/README.md](radar/README.md) / [factory/README.md](factory/README.md) para el arranque de cada subsistema.

---

## Operación diaria

```powershell
docker compose logs -f                  # todos los servicios
docker compose logs -f factory-worker   # generación de assets + render, el más útil para debug
docker compose exec postgres psql -U factory -d content_factory

# Solo cambiaste .py en radar/ o factory/: sincroniza solo, NO hace falta rebuild.
# Sí hace falta rebuild si cambiaste Dockerfile o requirements.txt:
docker compose up -d --build <servicio>

# factory-worker y cualquier *-scheduler son procesos long-running: el bind mount
# sincroniza el .py en disco pero el proceso ya cargado en memoria NO se entera.
# Reiniciar explícitamente después de editar su código:
docker compose restart factory-worker factory-scheduler
```

**Flujo del día a día una vez que hay videos en `review`:**

```
00:00  factory-scheduler detecta temas del nicho activo y encola jobs
00:30  factory-worker procesa: guion → assets → render Remotion
~06:00 videos listos en estado 'review'

(mañana)
  abrís el dashboard → revisás cada video
  aprobás / rechazás → descargás los MP4 aprobados
  copiás título/descripción/hashtags
  publicás manualmente en la plataforma (~3-4 min por video)
  marcás 'published' con la URL real en el dashboard
```

Consultas SQL de estado, troubleshooting de videos atascados, y comandos para forzar pipelines manualmente están en el `README.md` de cada servicio — [db](db/README.md), [radar](radar/README.md), [factory](factory/README.md), [dashboard](dashboard/README.md).

---

## Notas legales y de ToS

- Publicación 100% manual por diseño → sin riesgo de ban por automatización.
- Música: audio siempre nativo de la plataforma, nunca embebido. El render produce video mudo; el audio se agrega al subir.
- Radar: priorizar YouTube Data API (fuente legal y limpia). El scraping de TikTok está en zona gris de ToS; usar con cautela si se retoma.
- Contenido IA: etiquetar como generado por IA donde la plataforma lo exija.

---

## Documentos del proyecto

- **[PLAN.md](PLAN.md)** — roadmap vigente por fase, estado de la migración a Gemini, análisis de costos y viabilidad.
- **[db/README.md](db/README.md)**, **[radar/README.md](radar/README.md)**, **[factory/README.md](factory/README.md)**, **[imagegen/README.md](imagegen/README.md)**, **[dashboard/README.md](dashboard/README.md)** — documentación específica de cada componente.
- **[CLAUDE.md](CLAUDE.md)** — guía de arquitectura para agentes de código (Claude Code) trabajando en este repo.
