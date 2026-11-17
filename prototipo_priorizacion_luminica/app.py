from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.data import TOLOLO_LAT, TOLOLO_LON, default_data_path, load_zones
from src.model import rank_zones

st.set_page_config(page_title="Priorización lumínica · MVP", page_icon="🌌", layout="wide")

st.title("🌌 Priorización de mitigación lumínica · MVP")
st.caption("Caso de estudio: Cerro Tololo · Región de Coquimbo")

st.info(
    "Análisis basado en datos reales VIIRS. La versión actual utiliza un modelo base que combina radiancia "
    "y distancia al sitio receptor para estimar la prioridad relativa de intervención. En etapas posteriores "
    "se pueden incorporar factores físicos adicionales —como relieve, condiciones atmosféricas y características "
    "espectrales de la iluminación— para refinar la estimación del impacto sobre el cielo. El cumplimiento de la "
    "Norma Lumínica requiere información específica de las fuentes emisoras que no forma parte de este análisis."
)

with st.sidebar:
    st.header("Escenario")
    reduction_pct = st.select_slider(
        "Reducción simulada por zona", options=[10, 20, 30], value=20,
        format_func=lambda x: f"{x} %"
    )
    uploaded = st.file_uploader("Opcional: cargar CSV de zonas", type=["csv"])
    with st.expander("Parámetros técnicos"):
        alpha = st.slider("Exponente de distancia (exploratorio)", 1.0, 3.0, 2.0, 0.1)
        spatial_scale_km = st.number_input(
            "Escala espacial mínima (km)", min_value=1.0, max_value=20.0,
            value=5.0, step=1.0,
            help="Evita tratar la celda que contiene a Tololo como una fuente puntual a distancia cero."
        )

try:
    if uploaded is not None:
        df = load_zones(uploaded)
        source_label = "CSV cargado por usuario"
    else:
        path = default_data_path()
        df = load_zones(path)
        source_label = path.name

    # La celda que contiene al sitio receptor no es una zona emisora candidata a intervención.
    # Solo se excluye automáticamente si su centro está prácticamente sobre Cerro Tololo.
    receiver_zone = None
    candidates = df.copy()
    nearest_idx = candidates["distance_km"].astype(float).idxmin()
    nearest_distance = float(candidates.loc[nearest_idx, "distance_km"])
    if nearest_distance < 1.0:
        receiver_zone = candidates.loc[[nearest_idx]].copy()
        candidates = candidates.drop(index=nearest_idx).copy()

    ranked = rank_zones(
        candidates,
        reduction_pct=float(reduction_pct),
        alpha=float(alpha),
        spatial_scale_km=float(spatial_scale_km),
    )
except Exception as exc:
    st.error(f"No se pudo procesar el conjunto de datos: {exc}")
    st.stop()

is_synthetic = ranked.get("data_source", pd.Series(dtype=str)).astype(str).str.contains(
    "synthetic|sint", case=False, regex=True
).any()
if is_synthetic:
    st.info("Actualmente se están usando datos sintéticos de demostración. Al generar data/viirs_tololo.csv, la app lo usará automáticamente.")
else:
    st.success("Se están usando datos VIIRS/cargados para el escenario mostrado.")

# Comparación de los dos top-10: medida más interpretable que contar cualquier cambio de posición.
top_k = min(10, len(ranked))
top_priority = set(ranked.nsmallest(top_k, "priority_rank")["zone_id"])
top_brightness = set(ranked.nsmallest(top_k, "brightness_rank")["zone_id"])
overlap = len(top_priority & top_brightness)
top = ranked.iloc[0]
brightest = ranked.nsmallest(1, "brightness_rank").iloc[0]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Zonas candidatas", f"{len(ranked)}")
c2.metric("Reducción simulada", f"{reduction_pct} %")
c3.metric(f"Coincidencia Top {top_k}", f"{overlap}/{top_k}")
c4.metric("Zona prioritaria", str(top["zone_id"]))

receiver_note = ""
if receiver_zone is not None:
    receiver_id = str(receiver_zone.iloc[0]["zone_id"])
    receiver_note = f" · Zona receptora excluida del ranking: {receiver_id}"

st.caption(
    f"Fuente cargada: {source_label} · Zona más brillante: {brightest['zone_id']}{receiver_note} · "
    "El color del mapa representa el percentil del ranking, no una magnitud física."
)

left, right = st.columns([1.2, 1])

with left:
    st.subheader("Mapa de prioridad relativa")
    fig = go.Figure()
    fig.add_trace(
        go.Scattergeo(
            lat=ranked["latitude"],
            lon=ranked["longitude"],
            mode="markers",
            text=[
                f"{z}<br>Radiancia: {r:.2f}<br>Distancia: {d:.1f} km"
                f"<br>Rank prioridad: {pr}<br>Percentil: {p:.1f}/100"
                for z, r, d, pr, p in zip(
                    ranked["zone_id"], ranked["radiance"], ranked["distance_km"],
                    ranked["priority_rank"], ranked["priority_score"]
                )
            ],
            hoverinfo="text",
            marker=dict(
                size=11,
                color=ranked["priority_score"],
                colorscale="Viridis",
                cmin=0,
                cmax=100,
                colorbar=dict(title="Percentil"),
                line=dict(width=0.4),
            ),
            name="Zonas",
        )
    )
    if receiver_zone is not None:
        rz = receiver_zone.iloc[0]
        fig.add_trace(
            go.Scattergeo(
                lat=[float(rz["latitude"])],
                lon=[float(rz["longitude"])],
                mode="markers",
                marker=dict(size=14, symbol="square-open", line=dict(width=2)),
                text=[f"{rz['zone_id']} · Zona receptora (excluida del ranking)"],
                hoverinfo="text",
                name="Celda receptora",
            )
        )

    fig.add_trace(
        go.Scattergeo(
            lat=[TOLOLO_LAT], lon=[TOLOLO_LON], mode="markers+text",
            marker=dict(size=14, symbol="star"), text=["Cerro Tololo"],
            textposition="top center", name="Sitio receptor"
        )
    )
    pad = 0.15
    fig.update_geos(
        projection_type="mercator",
        showland=True,
        showcountries=True,
        showcoastlines=True,
        lataxis_range=[float(ranked.latitude.min()) - pad, float(ranked.latitude.max()) + pad],
        lonaxis_range=[float(ranked.longitude.min()) - pad, float(ranked.longitude.max()) + pad],
        resolution=50,
    )
    fig.update_layout(height=520, margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h"))
    st.plotly_chart(fig, use_container_width=True)

with right:
    st.subheader("¿Brillo = prioridad?")
    scatter = px.scatter(
        ranked,
        x="radiance",
        y="priority_score",
        hover_name="zone_id",
        hover_data={
            "distance_km": ":.1f",
            "brightness_rank": True,
            "priority_rank": True,
            "relative_benefit": ":.1f",
        },
        labels={"radiance": "Radiancia VIIRS", "priority_score": "Percentil de prioridad (0–100)"},
    )
    scatter.update_layout(height=360, margin=dict(l=10, r=10, t=20, b=10))
    scatter.update_yaxes(range=[0, 100])
    x_max = float(ranked["radiance"].max())
    scatter.update_xaxes(
        range=[0, max(5.0, x_max * 1.05)],
        tickmode="linear",
        tick0=0,
        dtick=5,
        tickformat=".0f",
        exponentformat="none",
        showexponent="none",
    )
    st.plotly_chart(scatter, use_container_width=True)
    st.markdown(
        "**Lectura:** el ranking combina radiancia y distancia al sitio receptor. "
        "Una zona menos brillante puede quedar por encima de otra más brillante si está suficientemente más cerca. "
        "El eje vertical muestra posición relativa en el ranking, no una predicción física de brillo del cielo."
    )

st.subheader("Ranking de beneficio marginal")
cols = [
    "priority_rank", "zone_id", "radiance", "distance_km", "brightness_rank", "rank_delta",
    "marginal_benefit", "relative_benefit", "priority_score"
]
show = ranked[cols].copy()
show.columns = [
    "Prioridad", "Zona", "Radiancia", "Distancia (km)", "Rank brillo", "Cambio rank",
    "Beneficio marginal (índice)", "Beneficio relativo al máximo", "Percentil prioridad"
]
show["Distancia (km)"] = show["Distancia (km)"].map(
    lambda d: "< 1" if float(d) < 1.0 else f"{float(d):.1f}"
)
st.dataframe(show, use_container_width=True, hide_index=True)

csv = ranked.to_csv(index=False).encode("utf-8")
st.download_button(
    "Descargar ranking CSV",
    data=csv,
    file_name=f"ranking_tololo_reduccion_{reduction_pct}.csv",
    mime="text/csv",
)

with st.expander("Cómo calcula este MVP"):
    st.latex(r"C_i = \\frac{L_i}{(d_i^2+s^2)^{\\alpha/2}}")
    st.latex(r"B_i = C_i - C_i^{(reducido)}")
    st.write(
        "Lᵢ es la radiancia VIIRS de la zona, dᵢ su distancia a Cerro Tololo y s una escala espacial mínima. "
        "La celda que contiene al sitio receptor se conserva en el mapa, pero se excluye del ranking porque no "
        "representa una zona emisora candidata a intervención. Bᵢ es el beneficio marginal del escenario. "
        "La versión futura puede incorporar topografía, mediciones "
        "terrestres y un modelo de propagación validado."
    )
    st.info(
        "En esta línea base la respuesta es lineal respecto de la reducción de radiancia. Por eso 10 %, 20 % y 30 % "
        "cambian la magnitud del beneficio estimado, pero normalmente no el orden del ranking."
    )
