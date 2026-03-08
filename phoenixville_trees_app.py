"""
Phoenixville Borough Tree Inventory - Public Dashboard
------------------------------------------------------
Requirements:
    pip install streamlit folium streamlit-folium pandas plotly numpy

Run with:
    streamlit run phoenixville_trees_app.py

Put your CSV in the same folder as this script, named:
    pville_tree_inventory_2022.csv
"""

import pandas as pd
import os
import numpy as np
import folium
from folium.plugins import MarkerCluster
import streamlit as st
from streamlit_folium import st_folium
import plotly.express as px
import plotly.graph_objects as go

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Phoenixville Urban Forest",
    page_icon="🌳",
    layout="wide",
)

# Inject CSS to prevent Streamlit from clipping metric labels
st.markdown("""
<style>
    [data-testid="stMetricLabel"] { font-size: 0.75rem; white-space: normal !important; }
    [data-testid="stMetricValue"] { font-size: 1.2rem; }
    div[data-testid="column"] { padding: 0 6px; }
</style>
""", unsafe_allow_html=True)

# ── Colour maps ───────────────────────────────────────────────────────────────
CONDITION_COLOR = {
    "Good":    "#4caf50",
    "Fair":    "#ff9800",
    "Poor":    "#f44336",
    "Unknown": "#9e9e9e",
}

# Top 10 hardwood genera + Other Hardwood + Other Softwood
GENUS_GROUPS = {
    "Quercus (Oak)":            "#8B4513",
    "Acer (Maple)":             "#e53935",
    "Amelanchier (Serviceberry)":"#9c27b0",
    "Gleditsia (Honeylocust)":  "#ff9800",
    "Tilia (Linden)":           "#26a69a",
    "Platanus (Sycamore)":      "#00838f",
    "Prunus (Cherry/Plum)":     "#ec407a",
    "Pyrus (Pear)":             "#fdd835",
    "Ulmus (Elm)":              "#5c6bc0",
    "Syringa (Lilac)":          "#ab47bc",
    "Other Hardwood":           "#607d8b",
    "Other Softwood":           "#2e7d32",
}

SOFTWOOD_GENERA = {
    "Picea","Pinus","Abies","Thuja","Juniperus",
    "Taxus","Pseudotsuga","Larix","Cedrus",
}

TOP10_MAP = {
    "Quercus":    "Quercus (Oak)",
    "Acer":       "Acer (Maple)",
    "Amelanchier":"Amelanchier (Serviceberry)",
    "Gleditsia":  "Gleditsia (Honeylocust)",
    "Tilia":      "Tilia (Linden)",
    "Platanus":   "Platanus (Sycamore)",
    "Prunus":     "Prunus (Cherry/Plum)",
    "Pyrus":      "Pyrus (Pear)",
    "Ulmus":      "Ulmus (Elm)",
    "Syringa":    "Syringa (Lilac)",
}

def assign_genus_group(genus):
    if pd.isna(genus): return "Other Hardwood"
    g = str(genus).strip()
    if g in TOP10_MAP:      return TOP10_MAP[g]
    if g in SOFTWOOD_GENERA: return "Other Softwood"
    return "Other Hardwood"

# ── Ecosystem service tables ──────────────────────────────────────────────────
STORMWATER_BASE = {
    "0-3":150,"3-6":400,"6-12":900,"12-18":1800,
    "18-24":3200,"24-30":5000,">30":8500,
}
CARBON_BASE = {
    "0-3":40,"3-6":120,"6-12":400,"12-18":900,
    "18-24":1800,"24-30":3200,">30":6000,
}
AIRQUALITY_BASE = {
    "0-3":1.0,"3-6":2.0,"6-12":3.5,"12-18":5.0,
    "18-24":6.5,"24-30":7.5,">30":9.0,
}
ENERGY_BASE = {
    "0-3":0.5,"3-6":1.5,"6-12":3.0,"12-18":5.0,
    "18-24":7.0,"24-30":8.0,">30":9.5,
}

# Multipliers per genus group
ECO_MULT = {
    #                              storm  carbon  airq  energy
    "Quercus (Oak)":            (1.30,  1.40,   1.20,  1.25),
    "Acer (Maple)":             (1.15,  1.10,   1.05,  1.10),
    "Amelanchier (Serviceberry)":(0.75, 0.70,   0.80,  0.80),
    "Gleditsia (Honeylocust)":  (0.70,  0.75,   0.75,  0.90),
    "Tilia (Linden)":           (1.20,  1.15,   1.10,  1.15),
    "Platanus (Sycamore)":      (1.35,  1.30,   1.20,  1.20),
    "Prunus (Cherry/Plum)":     (0.85,  0.80,   0.85,  0.85),
    "Pyrus (Pear)":             (0.75,  0.70,   0.75,  0.75),
    "Ulmus (Elm)":              (1.20,  1.10,   1.10,  1.10),
    "Syringa (Lilac)":          (0.65,  0.60,   0.70,  0.70),
    "Other Hardwood":           (1.00,  1.00,   1.00,  1.00),
    "Other Softwood":           (1.10,  0.90,   1.15,  0.85),
}

def get_dbh_bin(dbh):
    if pd.isna(dbh): return "6-12"
    if dbh <= 3:  return "0-3"
    if dbh <= 6:  return "3-6"
    if dbh <= 12: return "6-12"
    if dbh <= 18: return "12-18"
    if dbh <= 24: return "18-24"
    if dbh <= 30: return "24-30"
    return ">30"

def calc_services(row):
    g   = row["genus_group"]
    b   = get_dbh_bin(row["DBH"])
    m   = ECO_MULT.get(g, (1,1,1,1))
    sw  = round(STORMWATER_BASE[b] * m[0])
    co  = round(CARBON_BASE[b]     * m[1])
    aq  = round(min(10, AIRQUALITY_BASE[b] * m[2]), 1)
    en  = round(min(10, ENERGY_BASE[b]     * m[3]), 1)
    return sw, co, aq, en

# ── DBH → radius ──────────────────────────────────────────────────────────────
def dbh_to_radius(dbh):
    if pd.isna(dbh): return 4
    c = max(1, min(82, dbh))
    return 4 + (c - 1) / (82 - 1) * 16

# ── Load data ─────────────────────────────────────────────────────────────────
def load_data():
    # Always load from same folder as this script
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pville_tree_inventory_2022.csv")
    df = pd.read_csv(path)
    df = df[df["City"] == "Phoenixville"]
    df = df[df["Status"] == "Alive"]
    df["Latitude"]  = pd.to_numeric(df["Latitude"],  errors="coerce")
    df["Longitude"] = pd.to_numeric(df["Longitude"], errors="coerce")
    df = df.dropna(subset=["Latitude","Longitude"])
    df["Common Name"]     = df["Common Name"].fillna("Unknown")
    df["Scientific Name"] = df["Scientific Name"].fillna("")
    df["DBH"]             = pd.to_numeric(df["DBH"], errors="coerce")
    df["Condition"]       = df["Condition"].replace("Excellent","Good").fillna("Unknown")
    df.loc[~df["Condition"].isin(["Good","Fair","Poor"]), "Condition"] = "Unknown"
    df["genus_group"]     = df["Genus"].apply(assign_genus_group)
    svc = df.apply(calc_services, axis=1, result_type="expand")
    svc.columns = ["stormwater_gal","carbon_lbs","airquality_idx","energy_idx"]
    return pd.concat([df.reset_index(drop=True), svc], axis=1)

df = load_data()  # loads from script folder

# ── Sidebar ───────────────────────────────────────────────────────────────────
st.sidebar.title("🌳 Tree Inventory")
st.sidebar.markdown("**Borough of Phoenixville**")
st.sidebar.divider()

sel_conditions = st.sidebar.multiselect(
    "Condition", ["Good","Fair","Poor","Unknown"],
    default=["Good","Fair","Poor","Unknown"],
)
dbh_min_val = 0
dbh_max_val = int(df["DBH"].dropna().max()) + 1  # +1 so trees at the max DBH aren't cut off
sel_dbh = st.sidebar.slider(
    "DBH range (inches)", dbh_min_val, dbh_max_val,
    (dbh_min_val, dbh_max_val),
)
sel_species = st.sidebar.multiselect(
    "Species (leave blank for all)",
    options=sorted(df["Common Name"].dropna().unique()), default=[],
    placeholder="All species",
)
sel_landuse = st.sidebar.multiselect(
    "Land Use (leave blank for all)",
    options=sorted(df["Land Use"].dropna().unique()), default=[],
    placeholder="All land uses",
)
st.sidebar.divider()
st.sidebar.caption(
    "Data: Phoenixville Tree Advisory Commission · 2022 Inventory\n\n"
    "Dot size = DBH · Ecosystem service estimates derived from "
    "i-Tree Eco NE US regional averages (USDA Forest Service)"
)

# ── Filter ────────────────────────────────────────────────────────────────────
filtered = df[df["Condition"].isin(sel_conditions)]
filtered = filtered[
    filtered["DBH"].isna() |
    ((filtered["DBH"] >= sel_dbh[0]) & (filtered["DBH"] <= sel_dbh[1]))
]
if sel_species: filtered = filtered[filtered["Common Name"].isin(sel_species)]
if sel_landuse: filtered = filtered[filtered["Land Use"].isin(sel_landuse)]

# ── Top-level page tabs ────────────────────────────────────────────────────────
st.title("🌳 Phoenixville Urban Forest Dashboard")
st.caption("Phoenixville Tree Advisory Commission · 2022 Inventory")

page_about, page_explorer = st.tabs(["🌿 About This Dashboard", "🗺️ Inventory Explorer"])

# ══════════════════════════════════════════════════════════════════════════════
# ABOUT TAB
# ══════════════════════════════════════════════════════════════════════════════
with page_about:

    st.markdown("""
    <style>
        .about-hero {
            background: linear-gradient(135deg, #2C5F2D 0%, #4A7C4E 100%);
            border-radius: 10px;
            padding: 2rem 2.5rem;
            color: white;
            margin-bottom: 1.5rem;
        }
        .about-hero h2 { color: #97BC62; margin-top: 0; font-size: 1.6rem; }
        .about-hero p  { font-size: 1.05rem; line-height: 1.6; margin-bottom: 0; }
        .stat-box {
            background: #f5f9f0;
            border-left: 4px solid #2C5F2D;
            border-radius: 6px;
            padding: 1rem 1.2rem;
            text-align: center;
        }
        .stat-box .val { font-size: 2rem; font-weight: 700; color: #2C5F2D; }
        .stat-box .lbl { font-size: 0.85rem; color: #555; margin-top: 0.2rem; }
        .section-head {
            color: #2C5F2D;
            font-size: 1.2rem;
            font-weight: 700;
            margin-top: 1.5rem;
            margin-bottom: 0.5rem;
            border-bottom: 2px solid #97BC62;
            padding-bottom: 0.3rem;
        }
        .photo-placeholder {
            background: #E8F0E9;
            border: 2px dashed #97BC62;
            border-radius: 8px;
            padding: 2.5rem 1rem;
            text-align: center;
            color: #4A7C4E;
            font-style: italic;
            font-size: 0.9rem;
        }
        .callout-box {
            background: #FFF8E1;
            border-left: 4px solid #E8A020;
            border-radius: 6px;
            padding: 1rem 1.2rem;
            margin: 1rem 0;
        }
        .callout-box-red {
            background: #FFF0F0;
            border-left: 4px solid #C0392B;
            border-radius: 6px;
            padding: 1rem 1.2rem;
            margin: 1rem 0;
        }
    </style>
    """, unsafe_allow_html=True)

    # ── Hero banner ──────────────────────────────────────────────────────────
    st.markdown("""
    <div class="about-hero">
        <h2>Phoenixville's Urban Forest</h2>
        <p>The trees lining Phoenixville's streets and filling its parks are a living public
        infrastructure — reducing stormwater runoff, cooling neighborhoods, cleaning the air,
        and making the borough a more beautiful place to live. This dashboard makes that
        resource visible, measurable, and manageable.</p>
    </div>
    """, unsafe_allow_html=True)

    # ── Key stats row ─────────────────────────────────────────────────────────
    s1, s2, s3, s4 = st.columns(4)
    with s1:
        st.markdown("""<div class="stat-box">
            <div class="val">~2,500</div>
            <div class="lbl">Live trees in the borough inventory</div>
        </div>""", unsafe_allow_html=True)
    with s2:
        st.markdown("""<div class="stat-box">
            <div class="val">$357K</div>
            <div class="lbl">Estimated annual ecosystem services value</div>
        </div>""", unsafe_allow_html=True)
    with s3:
        st.markdown("""<div class="stat-box">
            <div class="val">$25M</div>
            <div class="lbl">Estimated replacement value of the urban forest</div>
        </div>""", unsafe_allow_html=True)
    with s4:
        st.markdown("""<div class="stat-box">
            <div class="val">101</div>
            <div class="lbl">Species represented in the urban forest</div>
        </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Why trees matter + photo ──────────────────────────────────────────────
    col_text, col_photo = st.columns([3, 2], gap="large")

    with col_text:
        st.markdown('<div class="section-head">🌳 Why Street Trees Matter</div>',
                    unsafe_allow_html=True)
        st.markdown("""
        Urban trees are among the highest-return public investments a municipality can make.
        Phoenixville's urban forest delivers measurable benefits every year:

        - **Stormwater management** — tree canopies intercept rainfall and roots absorb runoff,
          reducing strain on the borough's storm system
        - **Cooling** — street trees can reduce surface temperatures by 5–10°F, lowering
          air conditioning costs for nearby buildings
        - **Air quality** — trees filter particulates and absorb pollutants like ozone and NO₂
        - **Carbon sequestration** — the urban forest stores carbon and offsets emissions
        - **Property values** — studies consistently show homes near mature street trees
          sell for 5–15% more
        - **Community character** — Phoenixville's tree canopy is part of what makes the
          borough a desirable place to live, work, and visit
        """)

    with col_photo:
        st.markdown('<div class="section-head">📷 Phoenixville Street Trees</div>',
                    unsafe_allow_html=True)
        st.markdown("""
        <div class="photo-placeholder">
            📷 Photo placeholder<br><br>
            <em>Suggested: A well-canopied street scene in Phoenixville —
            Bridge St., Gay St., or a neighborhood block showing mature tree canopy</em>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("""
        <div class="photo-placeholder">
            📷 Photo placeholder<br><br>
            <em>Suggested: Volunteer planting event or TAC members at work</em>
        </div>
        """, unsafe_allow_html=True)

    st.divider()

    # ── The inventory + why management matters ────────────────────────────────
    col_inv, col_mgmt = st.columns(2, gap="large")

    with col_inv:
        st.markdown('<div class="section-head">📋 The 2022 Inventory</div>',
                    unsafe_allow_html=True)
        st.markdown("""
        In 2022, Brandywine Urban Forest Consulting completed a comprehensive field inventory
        of Phoenixville's borough-managed trees — recording the species, size, condition,
        and location of every tree in the public right-of-way and parks.

        That inventory is the foundation of this dashboard. It allows the Tree Advisory
        Commission to answer questions like:

        - Which blocks have the most trees in poor condition?
        - How diverse is our urban forest — are we too reliant on one genus?
        - Where is canopy cover lowest, and where should we prioritize new plantings?
        - What is the total value of the trees we manage?
        """)

        st.markdown("""
        <div class="callout-box">
        <strong>⚠️ Note on data currency</strong><br>
        The inventory reflects conditions as of 2022. Trees removed, planted, or changed
        in condition since then are not yet reflected. The TAC is working to keep this
        data current.
        </div>
        """, unsafe_allow_html=True)

    with col_mgmt:
        st.markdown('<div class="section-head">✂️ Why Active Management Matters</div>',
                    unsafe_allow_html=True)
        st.markdown("""
        Urban trees don't manage themselves. Without regular attention, problems accumulate:

        - **Emerald Ash Borer (EAB)** has killed millions of ash trees across Pennsylvania.
          Phoenixville has ash trees in the inventory that may already be dead or declining.
        - **Monoculture risk** — when too many trees of the same species are planted, a
          single pest or disease can devastate the entire canopy. The 10% rule recommends
          no genus exceed 10% of the urban forest.
        - **Infrastructure conflicts** — trees with sidewalk infringement or utility
          conflicts need monitoring before they become costly emergencies.
        - **Succession planning** — large, old trees eventually decline. Planting younger
          trees in strategic locations now ensures canopy continuity for future generations.
        """)

        st.markdown("""
        <div class="callout-box-red">
        <strong>🚨 Ash tree alert</strong><br>
        The 2022 inventory includes 42 ash trees (<em>Fraxinus</em> spp.). Emerald Ash Borer
        has been confirmed in Chester County. Many of these trees may be dead or dying.
        Field verification is a priority.
        </div>
        """, unsafe_allow_html=True)

    st.divider()

    # ── Planting priorities + photo ───────────────────────────────────────────
    col_plant, col_mapphoto = st.columns([2, 3], gap="large")

    with col_plant:
        st.markdown('<div class="section-head">🌱 Planting for Equity & Resilience</div>',
                    unsafe_allow_html=True)
        st.markdown("""
        Not all neighborhoods in Phoenixville have equal tree canopy. Using **Tree Equity
        Scores** — which combine canopy cover data with demographic and health indicators —
        the TAC has identified two priority areas for new plantings:

        - **Downtown** (along Bridge St. corridor)
        - **North Side** (Emmett, Franklin, and Rhodes St. area)

        Since 2021, the TAC has planted **279 trees** through volunteer and contract
        planting programs, with species selected to improve diversity and resilience.
        """)

    with col_mapphoto:
        st.markdown('<div class="section-head">🗺️ Canopy Cover & Planting Priority Map</div>',
                    unsafe_allow_html=True)
        st.markdown("""
        <div class="photo-placeholder">
            📷 Map placeholder<br><br>
            <em>Suggested: The Tree Equity Score + cluster analysis overlay map
            showing downtown and North Side priority areas in red/orange —
            from the TAC Planting Site Selection analysis</em>
        </div>
        """, unsafe_allow_html=True)

    st.divider()

    # ── How to use + get involved ─────────────────────────────────────────────
    col_use, col_involve = st.columns(2, gap="large")

    with col_use:
        st.markdown('<div class="section-head">🖥️ How to Use This Dashboard</div>',
                    unsafe_allow_html=True)
        st.markdown("""
        Use the **Inventory Explorer** tab to explore Phoenixville's trees interactively:

        1. **Filter** by condition, species, DBH size, or land use using the sidebar
        2. **Map** — click any tree pin to see its species, DBH, and condition
        3. **Charts** — see the distribution of species and conditions across the filtered set
        4. **Download** — export any filtered view as a CSV for your own analysis

        The dashboard updates automatically as you adjust the filters — all charts,
        metrics, and the map reflect your current selection.
        """)

    with col_involve:
        st.markdown('<div class="section-head">🤝 Get Involved</div>',
                    unsafe_allow_html=True)
        st.markdown("""
        The Phoenixville Tree Advisory Commission is an all-volunteer group that advises
        Borough Council on tree planting, removal, and management. There are several ways
        to support Phoenixville's urban forest:

        - **Volunteer** at a spring or fall planting event
        - **Report a concern** about a borough tree — hazardous limbs, disease signs,
          or a tree in poor condition — to Borough Hall
        - **Attend a TAC meeting** — meetings are open to the public
        - **Learn more** at the [TAC website](https://www.phoenixville.org/337/Tree-Advisory-Commission)

        *Data and dashboard maintained by the Phoenixville Tree Advisory Commission.*
        """)

# ══════════════════════════════════════════════════════════════════════════════
# INVENTORY EXPLORER TAB
# ══════════════════════════════════════════════════════════════════════════════
with page_explorer:

    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Showing (filtered)",      f"{len(filtered):,}")
    c2.metric("Unique Species",          f"{filtered['Common Name'].nunique()}")
    c3.metric("In Good Condition",
              f"{(filtered['Condition']=='Good').mean()*100:.0f}%"
              if len(filtered) else "—")
    c4.metric("Median DBH",
              f"{filtered['DBH'].median():.1f} in"
              if filtered['DBH'].notna().any() else "—")

    st.divider()

    # ── Ecosystem services panel ──────────────────────────────────────────────────
    st.subheader("🌿 Estimated Annual Ecosystem Services")
    st.caption("Figures are estimates based on i-Tree Eco regional averages scaled by genus and DBH. Values update with sidebar filters.")

    eco1, eco2, eco3, eco4 = st.columns(4)

    total_sw = filtered["stormwater_gal"].sum()
    total_co = filtered["carbon_lbs"].sum()
    avg_aq   = filtered["airquality_idx"].mean()
    avg_en   = filtered["energy_idx"].mean()

    with eco1:
        st.markdown("##### 💧 Stormwater Intercepted")
        st.markdown(f"### {total_sw:,.0f}")
        st.markdown("gallons per year")
        st.caption("Rainfall captured and evapotranspired, reducing runoff into storm drains. Large-canopy oaks and sycamores contribute most.")

    with eco2:
        st.markdown("##### 🌱 Carbon Stored")
        st.markdown(f"### {total_co:,.0f}")
        st.markdown("pounds (cumulative)")
        st.caption("Carbon locked in tree biomass plus annual sequestration. Scales strongly with DBH — large oaks dominate this figure.")

    with eco3:
        st.markdown("##### 🌬️ Air Quality Benefit")
        st.markdown(f"### {avg_aq:.1f} / 10")
        st.markdown("average index score")
        st.caption("Relative score for particulate matter and ozone removal. Larger, denser-canopy trees score highest.")

    with eco4:
        st.markdown("##### ☀️ Cooling & Shade")
        st.markdown(f"### {avg_en:.1f} / 10")
        st.markdown("average index score")
        st.caption("Relative index of summer cooling and energy savings from shading. Large oaks, lindens, and sycamores score highest.")

    st.divider()

    # ── Map builder ───────────────────────────────────────────────────────────────
    def build_map(color_field, color_map, legend_html, map_key):
        m = folium.Map(location=[40.130,-75.515], zoom_start=14, tiles="CartoDB positron")
        cluster = MarkerCluster(options={"maxClusterRadius":40,"disableClusteringAtZoom":16})

        for _, row in filtered.iterrows():
            color  = color_map.get(row[color_field], "#9e9e9e")
            radius = dbh_to_radius(row["DBH"])
            dbh_str = f'{row["DBH"]:.1f}"' if pd.notna(row["DBH"]) else "N/A"
            ccolor  = CONDITION_COLOR.get(row["Condition"], "#9e9e9e")

            popup_html = f"""
            <div style='font-family:sans-serif;min-width:210px;font-size:13px'>
              <b style='font-size:15px'>{row['Common Name']}</b><br>
              <i style='color:#666'>{row['Scientific Name']}</i>
              <hr style='margin:5px 0'>
              <b>Address:</b> {row.get('Address','')}<br>
              <b>Condition:</b> <span style='color:{ccolor};font-weight:bold'>{row['Condition']}</span><br>
              <b>DBH:</b> {dbh_str} &nbsp;|&nbsp; <b>Tag #:</b> {row.get('Tag Number','')}<br>
              <b>Genus group:</b> {row['genus_group']}<br>
              <b>Height:</b> {row.get('Height Range','N/A')}<br>
              <hr style='margin:5px 0'>
              <span style='color:#2e7d32'><b>🌿 Ecosystem Services (est.)</b></span><br>
              💧 Stormwater: <b>{row['stormwater_gal']:,} gal/yr</b><br>
              🌱 Carbon: <b>{row['carbon_lbs']:,} lbs</b><br>
              🌬️ Air quality: <b>{row['airquality_idx']} / 10</b><br>
              ☀️ Cooling: <b>{row['energy_idx']} / 10</b>
            </div>
            """
            tooltip = (
                f"{row['Common Name']} · {row['Condition']} · DBH {row['DBH']:.0f}\""
                if pd.notna(row["DBH"]) else row["Common Name"]
            )
            folium.CircleMarker(
                location=[row["Latitude"],row["Longitude"]],
                radius=radius, color=color, fill=True,
                fill_color=color, fill_opacity=0.78, weight=1,
                popup=folium.Popup(popup_html, max_width=280),
                tooltip=tooltip,
            ).add_to(cluster)

        cluster.add_to(m)
        m.get_root().html.add_child(folium.Element(legend_html))
        _ = st_folium(m, width="100%", height=580, returned_objects=[], key=map_key)

    # ── Legends ───────────────────────────────────────────────────────────────────
    cond_legend = """
    <div style="position:fixed;bottom:30px;left:30px;z-index:1000;background:white;
                padding:12px 16px;border-radius:8px;box-shadow:2px 2px 8px rgba(0,0,0,0.25);
                font-family:sans-serif;font-size:12px;line-height:1.9">
      <b>Condition</b><br>
      <span style="color:#4caf50">●</span> Good<br>
      <span style="color:#ff9800">●</span> Fair<br>
      <span style="color:#f44336">●</span> Poor<br>
      <span style="color:#9e9e9e">●</span> Unknown<br>
      <hr style="margin:6px 0"><b>Dot size</b> = DBH
    </div>"""

    genus_legend_html = (
        '<div style="position:fixed;bottom:30px;left:30px;z-index:1000;background:white;'
        'padding:12px 16px;border-radius:8px;box-shadow:2px 2px 8px rgba(0,0,0,0.25);'
        'font-family:sans-serif;font-size:12px;line-height:1.9"><b>Genus Group</b><br>'
        + "".join(f'<span style="color:{v}">●</span> {k}<br>' for k,v in GENUS_GROUPS.items())
        + '<hr style="margin:6px 0"><b>Dot size</b> = DBH</div>'
    )

    # ── Chart helpers ─────────────────────────────────────────────────────────────
    def bar_chart(x_vals, y_vals, color_map=None, single_color="#388e3c", height=260, xlab=""):
        if color_map:
            colors = [color_map.get(y, "#607d8b") for y in y_vals]
            fig = go.Figure(go.Bar(
                x=x_vals, y=y_vals, orientation="h",
                marker_color=colors,
            ))
        else:
            fig = go.Figure(go.Bar(
                x=x_vals, y=y_vals, orientation="h",
                marker_color=single_color,
            ))
        fig.update_layout(
            margin=dict(l=160, r=20, t=10, b=30),
            height=height,
            xaxis_title=xlab,
            yaxis=dict(tickfont=dict(size=11)),
            xaxis=dict(tickfont=dict(size=10)),
        )
        return fig

    # ── Tabs ──────────────────────────────────────────────────────────────────────
    st.subheader("🗺️ Interactive Maps")
    tab1, tab2 = st.tabs(["🟢 Color by Condition", "🌳 Color by Genus"])

    with tab1:
        # Map — full width
        build_map("Condition", CONDITION_COLOR, cond_legend, "map1")

        # Charts — three columns below the map
        st.markdown("---")
        ch1, ch2 = st.columns(2)

        with ch1:
            st.markdown("**Condition**")
            cond_counts = (
                filtered["Condition"].value_counts()
                .reindex(["Good","Fair","Poor","Unknown"], fill_value=0)
            )
            st.plotly_chart(
                bar_chart(cond_counts.values, cond_counts.index.tolist(),
                          color_map=CONDITION_COLOR, height=280, xlab="Trees"),
                use_container_width=True
            )

        with ch2:
            st.markdown("**DBH Distribution**")
            fig_d = px.histogram(
                filtered["DBH"].dropna(), nbins=20,
                color_discrete_sequence=["#388e3c"],
                labels={"value":"DBH (in)","count":"Trees"},
            )
            fig_d.update_layout(
                showlegend=False,
                margin=dict(l=50, r=20, t=10, b=50),
                height=280, bargap=0.05,
                xaxis_title="DBH (in)", yaxis_title="Trees",
                xaxis=dict(tickfont=dict(size=11)),
                yaxis=dict(tickfont=dict(size=11)),
            )
            st.plotly_chart(fig_d, use_container_width=True)

        # Top 10 species — full width below
        st.markdown("**Top 10 Species**")
        top10 = filtered["Common Name"].value_counts().head(10).sort_values()
        fig_sp = go.Figure(go.Bar(
            x=top10.index, y=top10.values,
            orientation="v",
            marker_color="#388e3c",
        ))
        fig_sp.update_layout(
            margin=dict(l=60, r=20, t=10, b=160),
            height=380,
            yaxis_title="Count",
            xaxis=dict(tickfont=dict(size=12), tickangle=-35),
            yaxis=dict(tickfont=dict(size=12)),
        )
        st.plotly_chart(fig_sp, use_container_width=True)

    with tab2:
        # Map — full width
        build_map("genus_group", GENUS_GROUPS, genus_legend_html, "map2")

        # Charts — two columns below the map
        st.markdown("---")
        ch4, ch5 = st.columns(2)

        with ch4:
            st.markdown("**Trees by Genus Group**")
            gg = (
                filtered["genus_group"].value_counts()
                .reindex(list(GENUS_GROUPS.keys()), fill_value=0)
                .sort_values()
            )
            fig_gg = go.Figure(go.Bar(
                x=gg.values, y=gg.index,
                orientation="h",
                marker_color=[GENUS_GROUPS.get(g, "#607d8b") for g in gg.index],
            ))
            fig_gg.update_layout(
                margin=dict(l=220, r=20, t=10, b=40),
                height=400,
                xaxis_title="Trees",
                yaxis=dict(tickfont=dict(size=11)),
                xaxis=dict(tickfont=dict(size=11)),
            )
            st.plotly_chart(fig_gg, use_container_width=True)

        with ch5:
            st.markdown("**Stormwater Intercepted by Genus Group**")
            sw_by_g = (
                filtered.groupby("genus_group")["stormwater_gal"].sum()
                .reindex(list(GENUS_GROUPS.keys())).dropna()
                .sort_values()
            )
            fig_sw = go.Figure(go.Bar(
                x=sw_by_g.values, y=sw_by_g.index,
                orientation="h",
                marker_color=[GENUS_GROUPS.get(g, "#607d8b") for g in sw_by_g.index],
            ))
            fig_sw.update_layout(
                margin=dict(l=220, r=20, t=10, b=40),
                height=400,
                xaxis_title="Gallons / yr",
                yaxis=dict(tickfont=dict(size=11)),
                xaxis=dict(tickfont=dict(size=11), tickformat=".2s"),
            )
            st.plotly_chart(fig_sw, use_container_width=True)

    st.divider()

    # ── Data table ────────────────────────────────────────────────────────────────
    with st.expander("📋 View / download filtered data"):
        display_cols = [
            "Tag Number","Common Name","Scientific Name","Address",
            "Condition","DBH","DBH Range","Height Range",
            "genus_group","Land Use","Land Type",
            "Sidewalk Infringement","Tree Well Rating",
            "stormwater_gal","carbon_lbs","airquality_idx","energy_idx",
            "Observations-Biotic Pest","Observations-Abiotic",
            "Latitude","Longitude",
        ]
        display_cols = [c for c in display_cols if c in filtered.columns]
        st.dataframe(filtered[display_cols].reset_index(drop=True), use_container_width=True)
        st.download_button(
            "⬇️ Download filtered data as CSV",
            data=filtered[display_cols].to_csv(index=False),
            file_name="phoenixville_trees_filtered.csv",
            mime="text/csv",
        )
