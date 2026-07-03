# Content Factory — Sistema de Descubrimiento y Producción de Contenido IA

Sistema self-hosted que descubre nichos de contenido con potencial y produce videos
con IA de forma semi-automatizada. Corre completamente en hardware propio vía Docker;
el único costo externo son las APIs de IA (pago por uso). La publicación es siempre
manual, para mantener control de calidad y eliminar el riesgo de bans por automatización.

---

## Qué hace

El proyecto son **dos subsistemas** que comparten base de datos y se retroalimentan:

- **Radar de nichos** (semanal): analiza canales de contenido IA, mide demanda vs.
  saturación, y detecta nichos con oportunidad real. Acumula su propio histórico de
  métricas porque las plataformas no exponen ese dato por API.
- **Fábrica de contenido** (diaria): una vez elegido un nicho, detecta temas del día,
  genera guion + assets con IA, ensambla el video con Remotion, y lo deja listo para
  que vos lo revises y publiques.

```
Radar descubre nicho → vos elegís → Fábrica produce → vos revisás y publicás
        ▲                                                          │
        └──────────── analytics loop (qué funcionó) ◄─────────────┘
```

---

## Principios de diseño

- **Self-hosted total.** Postgres, Redis, workers, dashboard y render: todo en
  contenedores sobre tu equipo. Sin VPS, sin BD gestionada, sin object storage en la nube.
- **Storage local.** Renders y assets viven en un volumen Docker sobre tu disco.
- **Control total del código.** Render con Remotion (plantillas en React versionadas),
  no plataformas SaaS cerradas. La lógica vive en Python; Remotion solo ensambla.
- **Solo se paga lo inevitable.** Las APIs de IA generativa cobran por uso. Nada más
  tiene costo recurrente.
- **Publicación manual.** El sistema deja todo listo; vos subís. Cero riesgo de ban por bot.
- **Nada expuesto a internet.** Solo llamadas salientes a las APIs. El dashboard
  escucha en localhost.

---

## Canales en marcha

| Canal | Formato | Estado |
|---|---|---|
| Música | Lyric videos subtitulados con fondo animado por IA. Audio nativo añadido manualmente en la plataforma (mantiene licencia y monetización). | Confirmado |
| Por definir (radar) | El radar de nichos determina el segundo canal con base en datos reales, no en suposiciones. | En descubrimiento |

Idioma: contenido en español, nombres de marca en inglés. Arranque con español,
escala a inglés después si funciona.

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

### APIs externas (único costo)

| Servicio | Uso | Cobro |
|---|---|---|
| Claude (Anthropic) | Guiones, prompts, títulos, descripciones | Por token |
| Gemini / Nano Banana | Imágenes y fondos | Por imagen |
| Veo / Kling / Runway | Video generativo (según nicho) | Por segundo |
| ElevenLabs | Voz TTS | Por caracteres (tier gratis + uso) |
| HeyGen | Avatar parlante (solo si el nicho lo pide) | Por minuto |
| YouTube Data API v3 | Métricas para el radar | Gratis (quota diaria) |
| Spotify API | BPM y duración para sync de letra | Gratis |

---

## Requisitos de hardware

- CPU de 6+ núcleos recomendada (el render de Remotion es CPU-bound).
- 16 GB RAM cómodos para correr todos los contenedores + render.
- **No se necesita GPU**: la generación de video IA ocurre en las APIs externas.
- El equipo debe estar encendido en los horarios de los crons (o ajustar los crons
  a cuando esté prendido). No es un VPS siempre disponible.
- Recomendado: respaldo del volumen `media` (disco externo o rsync a otro equipo).

---

## Estructura del repositorio

```
.
├── docker-compose.yml        # orquesta todos los servicios
├── .env.example              # plantilla de claves (copiar a .env)
├── db/
│   └── init.sql              # esquema de PostgreSQL
├── radar/                    # Sistema A — descubrimiento de nichos
│   ├── Dockerfile
│   └── radar/                # channel_scraper, niche_analyzer, scheduler...
├── factory/                  # Sistema B — producción de contenido
│   ├── Dockerfile            # imagen Python + Node + Remotion
│   ├── factory/              # topic_scraper, script_generator, render_worker...
│   └── remotion/             # plantillas de video (React)
└── dashboard/                # interfaz de revisión
    ├── Dockerfile
    └── dashboard/
```

---

## Puesta en marcha

```bash
# 1. Configurar claves
cp .env.example .env
# editar .env con tus claves de API

# 2. Levantar la capa de datos y servicios
docker compose up -d postgres redis
docker compose up -d            # el resto de servicios

# 3. Verificar
docker compose ps
docker compose logs -f radar    # ver el radar trabajando

# 4. Dashboard de revisión
# abrir http://127.0.0.1:8080 en el navegador
```

---

## Flujo diario de operación

```
00:00  factory-scheduler detecta temas del nicho activo y encola jobs
00:30  factory-worker procesa: guion → assets → render Remotion
~06:00 videos listos en estado 'review'

(mañana)
  abrís el dashboard → revisás cada video
  aprobás / rechazás → descargás los MP4 aprobados
  copiás título/descripción/hashtags (música: + nombre del audio nativo)
  publicás manualmente en cada plataforma  (~3-4 min por video)
```

---

## Orden de construcción

El sistema es grande y no se construye de una. Secuencia recomendada:

1. **Esqueleto de datos** — PostgreSQL + `init.sql` + Docker Compose corriendo.
2. **Radar mínimo** — `channel_scraper` + `snapshot_writer` contra YouTube Data API.
   *Arrancar esto cuanto antes:* cada semana sin snapshots es histórico perdido.
3. **Análisis de nichos** — `niche_analyzer` + `report_builder`.
4. **Fábrica: pipeline de texto** — `topic_scraper` + `script_generator` (Claude).
   Validar guiones antes de gastar en assets.
5. **Fábrica: assets + render** — imágenes, voz, Remotion. Primer video completo.
6. **Dashboard** — capa de revisión.
7. **Loop de analytics** — resultados retroalimentando al radar.

**Estado actual:** definida la arquitectura, el `docker-compose.yml` y el `.env.example`.
Siguiente paso: `db/init.sql` + Dockerfile del radar + `channel_scraper` (pasos 1 y 2).

---

## Notas legales y de ToS

- Publicación 100% manual por diseño → sin riesgo de ban por automatización.
- Música: audio siempre nativo de la plataforma, nunca embebido. El render produce
  video mudo; vos añadís el audio al subir.
- Radar: priorizar YouTube Data API (fuente legal y limpia). El scraping de TikTok
  está en zona gris de ToS; usar con cautela.
- Contenido IA: etiquetar como generado por IA donde la plataforma lo exija.

---

## Documentos del proyecto

- `plan-canales-ia.md` — planificación de negocio, canales, proyección de ingresos.
- `arquitectura-tecnica.md` — arquitectura técnica completa, esquema de BD, código de
  referencia, decisiones justificadas.
- `README.md` — este documento (punto de entrada).
