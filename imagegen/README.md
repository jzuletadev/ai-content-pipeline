# imagegen — generación de imágenes self-hosted

Servicio FastAPI + `diffusers` que corre Stable Diffusion en GPU local. Reemplazó a Gemini originalmente porque Gemini pedía prepago de $25 mínimo (no pago-por-uso real en ese momento).

> **Estado: en pausa, no eliminado.** El plan vigente ([PLAN.md](../PLAN.md)) prioriza calidad sobre costo mientras se valida el nicho único de historias animadas, y usa la API de Gemini (pago por imagen, sin prepago) en su lugar — ver [factory/README.md](../factory/README.md#generación-de-imágenes-self-hosted-vs-gemini). Este servicio se mantiene documentado y funcional para volver a él si el volumen de producción hace que el costo por imagen de una API pública deje de ser conveniente frente al costo marginal ~$0 de correr GPU propia.

## Modelo actual

`nitrosocke/mo-di-diffusion` — fine-tune de SD1.5 sobre estilo "modern disney" (animado, no fotorrealista). Requiere el trigger `"modern disney style"` en el prompt. Mismo pipeline/VRAM que SD1.5 base.

Se probó primero `stabilityai/sd-turbo` (más rápido, 1-4 steps) pero producía anatomía deformada en escenas con varias personas — es un modelo destilado, calibrado para pocos steps; subir steps no mejora calidad porque no fue entrenado para ese rango. Como el pipeline corre de noche sin nadie esperando, el tiempo extra de un modelo no destilado no es un costo real.

**Config actual** (`app.py`):
- `steps = 30`, `guidance_scale = 7.5`
- `negative_prompt` con lista fija (manos deformadas, extremidades extra, mala anatomía, texto/watermarks, composición sobrecargada, fotorrealismo)
- Resolución `576x1024` — exactamente 9:16, el aspecto del video final. Generar vertical directo evita que Remotion recorte ~44% del ancho de una imagen cuadrada
- Lock de concurrencia (`threading.Lock`) — el pipeline de `diffusers` no es thread-safe; dos requests simultáneos corrompían el modelo ("Already borrowed")
- ~5-8s por imagen en una RTX 3060

## Levantar y probar

```powershell
docker compose logs -f imagegen     # ver la carga del modelo en GPU al arrancar

curl -X POST http://127.0.0.1:7860/generate -H "Content-Type: application/json" \
  -d '{"prompt": "a red bicycle in a park"}' --output test.png

curl http://127.0.0.1:7860/health
nvidia-smi                          # uso de GPU en vivo, desde Windows fuera de Docker
```

Después de editar `app.py`, reiniciar el contenedor — no recarga solo:
```powershell
docker compose restart imagegen
```

Si cambiás `MODEL_ID`, además hay que actualizar la pre-descarga en `Dockerfile` con los mismos argumentos exactos, y correr `docker compose build imagegen`.

## Troubleshooting

**No arranca / "could not select device driver nvidia":** Docker Desktop no tiene GPU passthrough habilitado.
1. Docker Desktop → Settings → General → "Use the WSL 2 based engine" activo
2. `wsl --update` en PowerShell normal
3. Reiniciar Docker Desktop
4. `nvidia-smi` en PowerShell debe mostrar la GPU
5. `docker compose up -d imagegen`

**Tarda mucho en pasar a `healthy`:** normal la primera vez (el modelo se pre-descarga en build, pero cargarlo en VRAM al arrancar tarda ~30-90s). El healthcheck tiene `start_period: 120s`. Si pasa de 2 minutos, `docker compose logs imagegen`.

**CUDA out of memory:** 6GB VRAM es justo. Bajar resolución en `app.py` o cerrar otras apps que usen GPU mientras corre el pipeline.
