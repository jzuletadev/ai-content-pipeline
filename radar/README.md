# Radar de nichos

Sistema A — corre semanal. Descubre canales de contenido IA en YouTube, acumula snapshots históricos (YouTube no expone eso por API) y calcula un score de oportunidad por nicho.

> **Estado desde el pivote a un solo nicho:** el radar sigue funcionando y vale la pena dejarlo corriendo semanalmente (cada semana sin snapshot es histórico perdido para siempre), pero ya no bloquea el trabajo diario — el nicho activo (historias animadas) está decidido a mano. El radar vuelve a ser el driver de decisiones cuando se evalúe un segundo canal. Ver [PLAN.md](../PLAN.md).

## Componentes (`src/`)

| Archivo | Rol |
|---|---|
| `scheduler.py` | Entry point — cron semanal, corre el pipeline completo al arrancar y luego cada 7 días |
| `channel_scraper.py` | Descubre canales por keyword vía YouTube Data API |
| `youtube.py` | Wrapper delgado sobre `googleapiclient` |
| `snapshot_writer.py` | Guarda la foto semanal (`channel_snapshots`, `observed_videos`) |
| `data_cleaner.py` | Limpieza previa al análisis |
| `niche_analyzer.py` | Clasifica canales por nicho (`NICHE_TITLE_KEYWORDS`) y calcula `demand`/`saturation`/`opportunity_score` |
| `report_builder.py` | Genera el Markdown en `reports/YYYY-MM-DD.md` |

## Prerequisito: `YOUTUBE_API_KEY`

[Google Cloud Console](https://console.cloud.google.com/) → crear proyecto → habilitar **YouTube Data API v3** → Credenciales → Crear clave de API. Gratis, quota de 10,000 unidades/día; el pipeline completo usa ~3,100 unidades por ejecución.

## Levantar y operar

```powershell
docker compose up -d --build radar     # reconstruir con código nuevo
docker compose logs -f radar           # ver el pipeline correr
docker compose exec radar python -m src.scheduler   # forzar una corrida sin esperar el cron
docker compose restart radar           # tras editar cualquier .py de radar/src (el proceso no recarga solo)
```

## Editar keywords de búsqueda

Archivo: [src/channel_scraper.py](src/channel_scraper.py) → lista `SEARCH_KEYWORDS`. Después de editar, `docker compose restart radar`.

## La fórmula de oportunidad (`niche_analyzer.py`)

```
demand      = weighted(avg_views_per_video, avg_penetration, young_breakouts)
saturation  = weighted(canales_con_+1M_subs, total_canales)
opportunity = demand / (saturation + ε)
```

- **Penetración** (`views promedio ÷ subscribers`) es la métrica más fuerte disponible por API pública — un canal con 50K subs y 2M vistas promedio está llegando muy por fuera de su base.
- **`young_breakouts`**: canales de <90 días con +50K subs — señal de formato validado y todavía no copado.
- El hueco ideal: `demand` alto, `saturation` bajo, con `young_breakouts` presentes.
- La clasificación de nicho es por keywords en el título del canal (`NICHE_TITLE_KEYWORDS`, primer match gana) — ver la nota sobre esto en [factory/README.md](../factory/README.md#el-nombre-del-nicho-es-una-clave-de-enrutamiento).

## Qué se puede medir y qué no

| Métrica | ¿Disponible por API? | Proxy |
|---|---|---|
| Retención (% que ve el video completo) | No | Ratio likes/views + duración + consistencia |
| Histórico de crecimiento del canal | No directamente | `channel_snapshots` semanales (lo construye este sistema) |
| Vistas por video | Sí | Directo |
| Velocidad de viralización | Parcial | views ÷ días desde publicación |
| Penetración fuera de la base | Calculable | views promedio ÷ subscribers |

## Consultas útiles

```sql
-- Ranking de nichos
SELECT name, demand_score, saturation_score, opportunity_score
FROM niches ORDER BY opportunity_score DESC;

-- Canales más virales (proxy views/subs), solo canales IA confirmados
SELECT c.title, s.subscribers,
       ROUND(AVG(v.views)) AS avg_views,
       ROUND(AVG(v.views)::numeric / NULLIF(s.subscribers, 0), 2) AS views_per_sub
FROM channels c
JOIN (SELECT DISTINCT ON (channel_id) channel_id, subscribers
      FROM channel_snapshots ORDER BY channel_id, captured_at DESC) s
  ON s.channel_id = c.id
JOIN observed_videos v ON v.channel_id = c.id
WHERE s.subscribers > 1000 AND c.is_ai_content = TRUE
GROUP BY c.title, s.subscribers
ORDER BY views_per_sub DESC LIMIT 15;
```

## Reporte semanal

Se genera solo en `reports/YYYY-MM-DD.md`.

```powershell
ls radar/reports/
Get-Content radar/reports/$(Get-Date -Format "yyyy-MM-dd").md
```

## Troubleshooting

**Radar en crash loop** (`docker compose ps` muestra `Restarting`):
```powershell
docker compose logs radar --tail 30
```
Causa típica: quota de YouTube agotada (10K/día) — no rompe nada, `snapshot_writer` loguea el error y sigue. Si el crash es en `niche_analyzer` con `ForeignKeyViolation` sobre `niches` — ya está resuelto (upsert por `name`), pero si reaparece revisar que `active_channels.niche_id` siga apuntando a un nicho existente.

**Ver quota usada:** Google Cloud Console → APIs y servicios → YouTube Data API v3 → Cuotas.
