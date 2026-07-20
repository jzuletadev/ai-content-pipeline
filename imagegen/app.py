import io
import logging
import threading
import torch
from diffusers import StableDiffusionPipeline, DPMSolverMultistepScheduler
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Fine-tune de SD1.5 sobre estilo "modern disney" (animado, no fotorrealista) —
# mismo pipeline/VRAM que el SD1.5 base, pero entrenado específicamente para
# personajes/escenas estilizadas en vez del sesgo fotorrealista del checkpoint
# genérico. Requiere el trigger "modern disney style" en el prompt (ver
# script_generator.py). El tiempo por imagen no es un problema acá (el
# pipeline corre de noche, sin nadie esperando).
MODEL_ID = "nitrosocke/mo-di-diffusion"

DEFAULT_NEGATIVE_PROMPT = (
    "deformed, disfigured, mutated, extra limbs, extra arms, extra legs, "
    "extra fingers, missing fingers, fused fingers, too many fingers, "
    "mutated hands, poorly drawn hands, poorly drawn face, malformed limbs, "
    "disconnected limbs, cloned face, long neck, blurry, low quality, "
    "bad anatomy, bad proportions, out of frame, watermark, text, words, "
    "letters, writing, caption, signage, typography, illegible text, "
    "cluttered, busy, overcrowded, chaotic composition, too many elements, "
    "photorealistic, photo, realistic, gettyimages, stock photo, stock image"
)

logger.info(f"Cargando modelo {MODEL_ID} en GPU...")
pipe = StableDiffusionPipeline.from_pretrained(
    MODEL_ID,
    torch_dtype=torch.float16,
    safety_checker=None,
)
pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config)
pipe = pipe.to("cuda")
logger.info("Modelo cargado. Listo para generar.")

app = FastAPI()

# El pipeline de diffusers no es thread-safe: dos requests concurrentes corrompen
# el estado del tokenizer/modelo compartido ("Already borrowed", index out of bounds).
# uvicorn corre en threads, así que serializamos toda generación acá.
_generation_lock = threading.Lock()


class GenerateRequest(BaseModel):
    prompt: str
    negative_prompt: str = DEFAULT_NEGATIVE_PROMPT
    # 576x1024 = exactamente 9:16 (el aspecto del video final). Genera vertical
    # directo — sin esto, Remotion recortaba ~44% del ancho de cada imagen cuadrada
    # para llenar el frame vertical, perdiendo composición.
    width: int = 576
    height: int = 1024
    steps: int = 30
    guidance_scale: float = 7.5


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/generate")
def generate(req: GenerateRequest):
    try:
        with _generation_lock:
            image = pipe(
                prompt=req.prompt,
                negative_prompt=req.negative_prompt,
                num_inference_steps=req.steps,
                guidance_scale=req.guidance_scale,
                width=req.width,
                height=req.height,
            ).images[0]
    except Exception as e:
        logger.error(f"Generación falló: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")
