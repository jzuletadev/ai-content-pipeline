# Base de datos

Esquema de PostgreSQL compartido por Radar y Fábrica. Vive en [init.sql](init.sql) y se aplica automáticamente la primera vez que arranca el contenedor `postgres` (montado en `/docker-entrypoint-initdb.d/`). **No se re-ejecuta sobre un volumen existente** — un cambio de esquema en un entorno ya desplegado necesita un `ALTER` manual; no hay herramienta de migraciones en este proyecto.

## Tablas — Sistema A (Radar)

| Tabla | Qué guarda |
|---|---|
| `channels` | Canales vigilados (`platform`, `platform_id`, `handle`, `title`, `niche_guess`, `is_ai_content`). Único por `(platform, platform_id)`. |
| `channel_snapshots` | Foto semanal de cada canal (`subscribers`, `total_views`, `video_count`). Es el activo central del radar: sin esto no hay histórico de crecimiento. |
| `observed_videos` | Videos individuales observados por canal (`views`, `likes`, `comments`, `duration_sec`). Único por `(platform_id, captured_at)`. |
| `niches` | Nichos detectados y su score (`demand_score`, `saturation_score`, `opportunity_score`, `sample_channels` JSONB). `name` es único — el `niche_analyzer` hace upsert por nombre. |

## Tablas — Sistema B (Fábrica)

| Tabla | Qué guarda |
|---|---|
| `active_channels` | El canal propio en producción (`name`, `niche_id`, `style_config` JSONB — idioma, mercados, formato, voz). |
| `topics` | Temas detectados para producir (`title`, `source_ref`, `trend_score`, `status`: `pending\|selected\|discarded`). |
| `videos` | Cada video producido, con trazabilidad completa: `status` (máquina de estados — ver [factory/README.md](../factory/README.md)), `script`/`metadata`/`assets` (JSONB), `render_path`, `audio_ref`, `published_at`, `published_url`. |
| `video_results` | Métricas post-publicación (`views`, `likes`, `comments`, `shares`) — cierra el loop con el radar vía `_own_performance_boost()` en `niche_analyzer.py`. |

## Relación entre sistemas

El único cruce entre Radar y Fábrica es `active_channels.niche_id → niches.id`, más `topics`/`videos.active_channel_id → active_channels.id`. No hay más acoplamiento en el esquema — ambos sistemas pueden correr de forma independiente.

## Acceso

```powershell
docker compose exec postgres psql -U factory -d content_factory
```

```sql
\dt                         -- listar tablas
\d videos                   -- ver columnas de una tabla
```

Cliente gráfico (TablePlus / DBeaver / DataGrip): host `localhost`, puerto `5432`, DB `content_factory`, user `factory`, password = `POSTGRES_PASSWORD` de `.env`.

## Consultas de estado general

```sql
-- Canales vigilados por plataforma
SELECT platform, COUNT(*) FROM channels GROUP BY platform;

-- Snapshots acumulados por día (histórico que crece con el radar)
SELECT DATE(captured_at) AS dia, COUNT(*) AS snapshots
FROM channel_snapshots GROUP BY dia ORDER BY dia DESC LIMIT 10;

-- Videos por estado — la vista más útil para el día a día
SELECT status, COUNT(*) FROM videos GROUP BY status ORDER BY status;
```

Consultas específicas de cada subsistema (ranking de nichos, canales virales, temas pendientes, videos atascados) están en [radar/README.md](../radar/README.md) y [factory/README.md](../factory/README.md).

## Reset de datos de prueba

Borra videos sin guion generado y resetea temas descartados/seleccionados sin tocar canales ni snapshots (que son costosos de reconstruir):

```sql
DELETE FROM videos WHERE script IS NULL;
UPDATE topics SET status = 'pending' WHERE status IN ('selected', 'discarded');
```
