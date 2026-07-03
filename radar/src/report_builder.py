import logging
from datetime import datetime
from pathlib import Path
from .db import get_conn

logger = logging.getLogger(__name__)

REPORT_DIR = Path("/app/reports")


def run():
    logger.info("report_builder: start")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    niches = _load_niches()
    report = _build_report(niches)

    filename = REPORT_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.md"
    filename.write_text(report, encoding="utf-8")

    # Imprimir en logs para verlo sin entrar al contenedor
    logger.info(f"Reporte guardado: {filename}")
    print("\n" + report)

    logger.info("report_builder: done")


def _load_niches() -> list[dict]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                name,
                demand_score,
                saturation_score,
                opportunity_score,
                sample_channels,
                computed_at
            FROM niches
            ORDER BY opportunity_score DESC
        """)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _build_report(niches: list[dict]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# Reporte de nichos — {now}",
        "",
        f"**Total nichos analizados:** {len(niches)}",
        "",
        "---",
        "",
        "## Ranking de oportunidades",
        "",
        "| # | Nicho | Demanda | Saturación | Oportunidad |",
        "|---|-------|---------|------------|-------------|",
    ]

    for i, n in enumerate(niches, 1):
        medal = " 🥇" if i == 1 else " 🥈" if i == 2 else " 🥉" if i == 3 else ""
        lines.append(
            f"| {i} | **{n['name']}**{medal} "
            f"| {n['demand_score']} "
            f"| {n['saturation_score']} "
            f"| {n['opportunity_score']} |"
        )

    lines += ["", "---", "", "## Detalle por nicho", ""]

    for i, n in enumerate(niches, 1):
        signal = _opportunity_label(float(n["opportunity_score"]))
        lines += [
            f"### {i}. {n['name']}  {signal}",
            "",
            f"| Métrica | Valor |",
            f"|---------|-------|",
            f"| Demanda | {n['demand_score']} |",
            f"| Saturación | {n['saturation_score']} |",
            f"| **Oportunidad** | **{n['opportunity_score']}** |",
            "",
            "**Canales de muestra:**",
            "",
        ]
        for ch in (n["sample_channels"] or []):
            lines.append(f"- {ch['title']} ({ch['subscribers']:,} subs)")
        lines.append("")

    return "\n".join(lines)


def _opportunity_label(score: float) -> str:
    if score > 5:
        return "🔥 Alta"
    if score > 2:
        return "⚡ Media"
    if score > 1:
        return "📈 Moderada"
    return "⚠️ Baja"
