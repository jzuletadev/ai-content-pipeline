FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cu124

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-descargar los pesos del modelo durante el build (evita esperar en el primer arranque).
# Los argumentos deben coincidir EXACTO con los de app.py para pegarle al cache de HF.
RUN python3 -c "from diffusers import StableDiffusionPipeline; import torch; StableDiffusionPipeline.from_pretrained('nitrosocke/mo-di-diffusion', torch_dtype=torch.float16, safety_checker=None)"

COPY . .

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
