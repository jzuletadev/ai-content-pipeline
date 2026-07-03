"""
Setup inicial: crea el primer active_channel en la BD.
Correr UNA SOLA VEZ después de que Fase 3 haya generado nichos.

Uso:
    docker compose exec factory-scheduler python -m src.setup_channel
"""
import json
import sys
from dotenv import load_dotenv
load_dotenv()

from src.db import get_conn


def main():
    with get_conn() as conn:
        cur = conn.cursor()

        # Verificar que existan nichos
        cur.execute("SELECT id, name, opportunity_score FROM niches ORDER BY opportunity_score DESC")
        niches = cur.fetchall()
        if not niches:
            print("ERROR: No hay nichos en BD. Correr Fase 3 primero.")
            sys.exit(1)

        print("\nNichos disponibles:")
        for niche_id, name, score in niches:
            print(f"  [{niche_id}] {name} — oportunidad: {score}")

        print()
        niche_id_input = input("ID del nicho para el canal (Enter para lyric_videos): ").strip()

        if niche_id_input:
            niche_id = int(niche_id_input)
        else:
            cur.execute("SELECT id FROM niches WHERE name = 'lyric_videos' ORDER BY computed_at DESC LIMIT 1")
            row = cur.fetchone()
            if not row:
                print("ERROR: nicho lyric_videos no encontrado.")
                sys.exit(1)
            niche_id = row[0]

        channel_name = input("Nombre del canal (ej: LyricAI ES): ").strip() or "LyricAI ES"

        style_config = {
            "language": "es",
            "target_markets": ["MX", "ES", "AR", "CO"],
            "video_format": "lyric_video",
            "fps": 30,
            "resolution": "1920x1080",
            "voice_gender": "female",
            "music_genres": ["latin pop", "reggaeton", "bachata", "salsa"],
        }

        cur.execute(
            "SELECT id FROM active_channels WHERE niche_id = %s",
            (niche_id,)
        )
        existing = cur.fetchone()
        if existing:
            print(f"Ya existe un active_channel para este nicho (id={existing[0]}). No se crea duplicado.")
            return

        cur.execute(
            """
            INSERT INTO active_channels (name, niche_id, style_config)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (channel_name, niche_id, json.dumps(style_config)),
        )
        channel_id = cur.fetchone()[0]
        print(f"\nActive channel creado: id={channel_id}, nombre='{channel_name}', niche_id={niche_id}")
        print("Ahora podés correr: docker compose up -d factory-scheduler")


if __name__ == "__main__":
    main()
