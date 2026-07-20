FROM node:20-bookworm-slim

# chromium: usamos el paquete del sistema (apt resuelve sus propias dependencias .so)
# en vez de dejar que Remotion descargue su propio Chrome Headless Shell.
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    chromium \
    ca-certificates \
    fonts-noto \
    fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV REMOTION_BROWSER_EXECUTABLE=/usr/bin/chromium

COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

# package.json solo (cache de npm install separado de cambios en código Python)
COPY remotion/package.json ./remotion/
RUN cd remotion && npm install

COPY . .

CMD ["python3", "-m", "src.scheduler"]
