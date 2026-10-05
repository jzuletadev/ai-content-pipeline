# Plan de trabajo — Content Factory

*Documento vivo. Actualizar estado al completar cada tarea. Última revisión de foco: 2026-08-04.*

## Cambio de foco (2026-08-04)

El proyecto original atacaba varios nichos en paralelo. **Se reduce el alcance a un solo canal — historias animadas — hasta validarlo de punta a punta.** Razón: con múltiples nichos en construcción simultánea, ninguno llegaba a producción real; es mejor tener un pipeline que efectivamente genera y publica contenido que siete a medio construir.

Decisiones que se toman en este cambio de foco:

1. **Nicho activo: historias animadas.** Técnicamente usa el generador narrado ya implementado en el código como `historias_historicas` (guion narrado + imágenes + voz TTS) — ver [factory/README.md](factory/README.md#el-nombre-del-nicho-es-una-clave-de-enrutamiento). `lyric_videos` (música) queda en pausa, sin borrarse.
2. **Radar en pausa operativa**, no eliminado — sigue corriendo semanal en background para no perder histórico, pero deja de ser el bloqueante de decisiones hasta que el primer canal esté validado.
3. **Generación de imágenes vuelve a Gemini** (API paga, sin prepago) en vez del servicio self-hosted (`imagegen/`, Stable Diffusion en GPU local) — se prioriza calidad de output sobre costo mientras se valida si el contenido funciona. El self-hosted queda documentado y disponible para retomar cuando el volumen lo justifique económicamente.
4. **Generación de video real (Veo) se evalúa pero no se adopta todavía** — el análisis de costo (abajo) muestra que es 6-20x más caro que el approach actual de imágenes + movimiento de cámara en Remotion. Se deja como mejora futura acotada a contenido ya validado, no como reemplazo del pipeline por defecto.

---

## Fases completadas (pre-pivote)

Código intacto, no se toca en este cambio de foco salvo lo indicado.

| Fase | Descripción | Estado |
|------|---|---|
| 1 | Esqueleto de datos — PostgreSQL + Redis + `init.sql` (8 tablas) + Docker Compose | ✓ Completo |
| 2 | Radar mínimo — `channel_scraper` + `snapshot_writer` contra YouTube Data API | ✓ Completo |
| 3 | Análisis de nichos — `niche_analyzer` + `report_builder`, fórmula demanda/saturación/oportunidad | ✓ Completo |
| 4 | Fábrica — pipeline de texto — `topic_scraper` (Last.fm + Wikipedia) + `script_generator` (Claude) | ✓ Completo |
| 5 | Fábrica — assets + render — imágenes (self-hosted), voz (ElevenLabs), Remotion | ✓ Completo para `lyric_videos`. **`historias_historicas` nunca se validó end-to-end** — nunca se creó un `active_channel` para probarlo; el path de ElevenLabs/TTS no se ejercitó en producción real |
| 6 | Dashboard de revisión — FastAPI, aprobar/rechazar/publicar, streaming de MP4 | ✓ Completo |
| 7 | Loop de analytics — `result_tracker` lee métricas propias de YouTube, alimenta `niche_analyzer` | ✓ Código completo — sin datos reales todavía (nadie publicó a YouTube aún) |

Detalle técnico de cada fase: ver el `README.md` de la carpeta correspondiente ([db](db/README.md), [radar](radar/README.md), [factory](factory/README.md), [imagegen](imagegen/README.md), [dashboard](dashboard/README.md)).

---

## Fase 8 — Validar historias animadas end-to-end (EN CURSO)

**Objetivo:** el primer video real del nicho activo, revisado en el dashboard, sin intervención manual en el medio del pipeline.

- [ ] Crear el `active_channel` para el nicho narrado (`docker compose exec factory-scheduler python -m src.setup_channel`)
- [ ] Confirmar que `topic_scraper` encuentra temas razonables para el nicho (hoy usa Wikipedia On This Day — revisar si esa fuente sigue siendo la mejor para "historias animadas" o si hace falta una fuente de temas propia)
- [ ] Correr un guion completo con Claude y revisarlo a mano antes de gastar en assets (igual que se hizo con música en Fase 4)
- [ ] Validar por primera vez el path de ElevenLabs con este nicho — nunca se ejercitó en Fase 5
- [ ] Video completo de punta a punta: guion → imágenes → voz → render Remotion → `review`
- [ ] Revisar en el dashboard: ¿el ritmo de imágenes vs. narración se siente bien? ¿la calidad de imagen alcanza?
- [ ] Publicar el primer video real y marcarlo `published` con URL — esto además activa Fase 7 (analytics) con datos reales por primera vez

**Prerequisito de Fase 9** si se quiere validar directamente con calidad Gemini en vez de con el self-hosted actual.

---

## Fase 9 — Migración de imágenes a Gemini (PENDIENTE)

**Objetivo:** reemplazar la llamada a `imagegen` self-hosted en `factory/src/asset_generator.py` por la API de Gemini, manteniendo el resto del pipeline sin cambios (el contrato con `render_worker.py` es solo "una lista de paths de imagen por escena").

- [ ] `GEMINI_API_KEY` en `.env`
- [ ] Elegir modelo: **Gemini 3.1 Flash Image ("Nano Banana 2")** a resolución 1K como default — el modelo actual (`gemini-2.5-flash-image`, "Nano Banana" original) se retira el 2026-10-02, no vale la pena integrar algo por retirarse en semanas. Evaluar **Gemini 3 Pro Image ("Nano Banana Pro")** para escenas que necesiten más detalle, a mayor costo por imagen
- [ ] Nueva función en `asset_generator.py` (`_generate_images_gemini()`) detrás de un flag `IMAGE_PROVIDER=gemini|self_hosted` — permite comparar calidad lado a lado y volver atrás sin reescribir código si Gemini no rinde como se espera
- [ ] Adaptar el prompt de escena: Gemini no necesita el trigger `"modern disney style"` que usa el modelo self-hosted (`mo-di-diffusion`) — revisar qué estilo visual pedir para mantener consistencia entre escenas de un mismo video
- [ ] `docker-compose.yml`: mover `imagegen` a un [profile](https://docs.docker.com/compose/profiles/) opcional en vez de levantarlo siempre — deja de ser una dependencia dura de `factory-worker`
- [ ] Validar calidad con el mismo set de prompts usados en pruebas de Fase 5, comparando contra el output actual de `imagegen`
- [ ] Instrumentar costo real: loguear el gasto estimado por video (imágenes + Claude + ElevenLabs) para tener visibilidad antes de escalar volumen

---

## Fase 10 — Generación de video real con Veo (EXPLORATORIA, no iniciada)

**No es la siguiente fase a construir — es una opción evaluada y estacionada.** Ver el análisis de costos abajo: generar video real en vez de imágenes animadas multiplica el costo por video entre 6x y 20x. Mientras el canal no tiene datos de qué contenido funciona, ese gasto no se justifica.

Si en el futuro se retoma:

- Requiere reescribir `render_worker.py` para consumir clips de video (`<Video>` de Remotion) en vez de imágenes estáticas + Ken Burns — no es un simple swap de API, es un cambio de arquitectura del render.
- Usar la **Gemini API directa** para Veo (pago por segundo, sin prepago), no Vertex AI — Vertex cobra ~$0.75/segundo, casi el doble del tier más caro de la Gemini API.
- Propuesta de uso acotado: no reemplazar el pipeline por defecto. Reservar video real para 1-2 "hero videos" por semana, sobre guiones que el loop de analytics (Fase 7) ya mostró que funcionan — gastar más solo en contenido con evidencia de que vale la pena.

---

## Costos por video (referencia 2026)

Estimación para un video narrado de ~60 segundos (nicho activo), con la arquitectura actual (imágenes fijas + movimiento de cámara en Remotion, no video generativo). Precios de las APIs a agosto de 2026 — verificar antes de comprometer presupuesto, estos mercados bajan de precio seguido.

| Componente | Detalle | Costo aprox. |
|---|---|---|
| Guion (Claude) | Script + metadata, modelo Haiku 4.5 ($1/$5 por millón in/out) | $0.01 – $0.02 |
| Imágenes (Gemini) | ~20 imágenes/video (10 escenas × 2), Nano Banana 2 a 1K (~$0.05-0.07/imagen) | $1.00 – $1.40 |
| QC de imágenes (Claude vision) | ~20-24 llamadas cortas de verificación, Haiku 4.5 | $0.05 – $0.10 |
| Voz (ElevenLabs) | ~800-900 caracteres de narración en tier pago | $0.10 – $0.30 |
| **Total por video** | | **≈ $1.20 – $1.80** |

**A escala** (solo costo de API, sin contar electricidad ni tiempo propio):

| Ritmo de publicación | Costo mensual aprox. |
|---|---|
| 1 video/día | ~$45/mes |
| 3 videos/día | ~$135/mes |
| 5 videos/día | ~$225/mes |
| 10 videos/día | ~$450/mes — punto en el que volver a self-hosted (imagegen) empieza a pagar la complejidad de mantenerlo, porque las imágenes son el componente más caro |

**Video generativo real (Veo, vía Gemini API) para comparación — no integrado:**

| Tier | Costo por segundo | Video de 60s (~8 clips de 8s) |
|---|---|---|
| Fast | $0.10 – $0.15/s | ~$8/video |
| Standard | $0.40/s | ~$25/video |
| Vertex AI (no recomendado) | $0.75/s | ~$48/video |

Es decir: el mismo video cuesta entre 6x y 20x más si se genera como video real en vez de imágenes animadas. Esto es lo que sostiene la decisión de Fase 10.

---

## APIs necesarias

| API | Fase | Dónde conseguir |
|---|---|---|
| YouTube Data API v3 | 2, 7 | Google Cloud Console → habilitar API → clave |
| Anthropic (Claude) | 4, 8 | console.anthropic.com |
| Last.fm | 4 (si se retoma música) | last.fm/api/account/create |
| Gemini (Google AI) | 9 | aistudio.google.com → Get API Key |
| ElevenLabs | 5, 8 | elevenlabs.io → Profile → API Key |

---

## Resumen de estado

| Fase | Descripción | Estado |
|------|---|---|
| 1 | Esqueleto de datos | ✓ Completo |
| 2 | Radar mínimo | ✓ Completo (en pausa operativa) |
| 3 | Análisis de nichos | ✓ Completo |
| 4 | Fábrica: pipeline texto | ✓ Completo |
| 5 | Fábrica: assets + render | ✓ Completo para `lyric_videos`; `historias_historicas` sin validar en producción |
| 6 | Dashboard | ✓ Completo |
| 7 | Loop de analytics | ✓ Código completo, sin datos reales |
| 8 | Validar historias animadas end-to-end | En curso |
| 9 | Migración de imágenes a Gemini | Pendiente |
| 10 | Generación de video real (Veo) | Exploratoria, estacionada |
