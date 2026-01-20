from neo4j import GraphDatabase
from dotenv import load_dotenv
from typing import List, Dict, Any, Optional
import os
from modelosIA import llm
import pandas as pd

from branca.colormap import LinearColormap
import geemap.foliumap as geemap
import numpy as np


# ✅ Variables de entorno
load_dotenv(dotenv_path="_mientorno.env") 
neo4j_apikey = os.getenv("NEO4J_PASSWORD")
neo4j_uri = os.getenv("NEO4J_URI")
gee_project = os.getenv("GEE_PROJECT", "pelagic-cat-476623-u0")


# Sesión en Neo4j
if not neo4j_apikey:
    raise ValueError("Neo API Key not found in environment variables. Please check _mientorno.env")
if not neo4j_uri:
    raise ValueError("Neo4j URI not found in environment variables. Please check _mientorno.env")

driver = GraphDatabase.driver(
    neo4j_uri,
    auth=("neo4j", neo4j_apikey)
)




####################################
#   FUNCIONES BASICAS
####################################


def texto_a_cypher(peticion: str) -> str:
    prompt = f"""
    Eres un experto en Neo4j y Cypher.
    Convierte la siguiente petición en lenguaje natural a una consulta Cypher válida.
    NO expliques nada, solo devuelve Cypher.
    El mes representalo como YYYY-MM (por ejemplo, 2023-01 para enero de 2023).
    No uses los separadores de linea en la consulta.
    Si aparece \n en la consulta, reemplazalos por un espacio ' '

    Esquema del grafo:
    
    Nodos:
        (f:Fuente {{name: string}}) # Ejemplo: "GEOGRAFIA"
        (p:Pais {{name: string}})
        (d:Departamento {{name: string}})
        (c:Ciudad {{name: string}})
        (o:Observacion {{fecha:string, temperatura:float}}) # Fecha YYYY-MM-DD , Temperatura en Celsius
    Relaciones:
        (f)-[:CONTIENE]->(p)
        (p)-[:CONTIENE]->(d)
        (d)-[:CONTIENE]->(c)
        (c)-[:ES_OBSERVADO]->(o)
 
    
    Petición:
    "{peticion}"
    """

    from langchain_core.messages import HumanMessage
    
    response = llm.invoke([HumanMessage(content=prompt)])
    print ("Respuesta LLM: " , response)
    return response.content.strip()



####################################
#   FUNCIONES DE FORMATEO


def diccionario_a_tabla_md(datos_dict):
    """
    Convierte {'clave': 'valor'} en una tabla Markdown vertical.
    """
    # Encabezado de la tabla
    tabla = "| Campo | Detalle |\n| :--- | :--- |\n"
    tabla = ""
    
    # Rellenar filas
    for clave, valor in datos_dict.items():
        # Truco visual: Capitalizar la primera letra (pais -> Pais)
        clave_bonita = clave.capitalize() 
        tabla += f"| **{clave_bonita}** | {valor} |\n"
        
    return tabla






def generar_mapa_resultados(datos_mapa, capas_extra=None):
    """
    Genera un mapa HTML con Folium y lo devuelve encapsulado en un IFRAME.
    """
    import folium
    from folium import plugins
    import json
    from branca.colormap import LinearColormap
    import math
    import html

    if not datos_mapa:
        return "<div style='padding:20px;'>No hay datos para mostrar en el mapa.</div>"

    # 1. Configurar Centro
    try:
        lat_cen = float(datos_mapa[0].get('lat', -12.0))
        lon_cen = float(datos_mapa[0].get('lon', -77.0))
    except:
        lat_cen, lon_cen = -12.0464, -77.0428

    m = folium.Map(location=[lat_cen, lon_cen], zoom_start=10, tiles='Esri.WorldImagery')

    # Agregamos una capa de ciudades sobre el satélite
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',
        attr='Esri',
        name='Etiquetas',
        overlay=True
    ).add_to(m)

    # 2. Colores
    colormap = LinearColormap(
        colors=['red', 'orange', 'yellow', 'green'],
        index=[0, 40, 70, 100],
        vmin=0, vmax=100,
        caption='Idoneidad del Terreno (Score)'
    )
    m.add_child(colormap)


    # 2. Capa de Puntos de interés

    if capas_extra:
        print(f"🗺️ Pintando {len(capas_extra)} elementos de referencia en el mapa...")
        for capa in capas_extra:
            tipo = capa.get('tipo', 'desconocido')
            geo_data = capa.get('geojson')
            
            # Definir estilos según el tipo
            color_linea = 'gray'
            grosor = 2
            
            if tipo == 'rios':
                color_linea = '#0077BE' # Azul Río
                grosor = 3
            elif tipo == 'carreteras':
                color_linea = '#333333' # Gris Oscuro Carretera
                grosor = 2
            elif tipo == 'puntos_interes':
                color_linea = '#DC143C' # Rojo
                grosor = 4 # N/A para puntos, pero sirve de ref
            
            # Función de estilo para GeoJSON
            def style_function(feature=None, color=color_linea, w=grosor):
                return {
                    'color': color,
                    'weight': w,
                    'opacity': 0.7
                }

            # Agregar al mapa
            folium.GeoJson(
                geo_data,
                name=tipo,
                style_function=style_function,
                tooltip=f"{tipo.upper()}" # Muestra tipo al pasar mouse
            ).add_to(m)


    # 3. Dibujar Celdas
    for celda in datos_mapa:
        try:
           
            # Puntaje
            puntaje = float(celda.get('score', 0))
            score = 0.0 if math.isnan(puntaje) else puntaje
            
            # Función auxiliar para floats
            def safe_float(val):
                try: return float(val)
                except: return 0.0

            # CORRECCIÓN ID: Busca 'id' O 'id_celda' para evitar el "N/A"
            id_celda = str(celda.get('id', celda.get('id_celda', 'N/A')))
            
            temp = safe_float(celda.get('temp_promedio', 0))
            humedad = safe_float(celda.get('humedad_promedio', 0))
            precip = safe_float(celda.get('precipitacion_promedio', 0))
            altitud = safe_float(celda.get('elevacion_promedio', 0))
            viento = safe_float(celda.get('viento_promedio', 0))
            suelo = str(celda.get('tipo_suelo', 'Sin Dato'))
            explicacion = str(celda.get('explicacion', 'Sin diagnóstico'))

            geom = celda.get('geometry')
            if isinstance(geom, str):
                geom = json.loads(geom)

            color_relleno = colormap(score)

            # --- TOOLTIP CORREGIDO (CSS) ---
            tooltip_html = f"""
            <div style="font-family: Arial, sans-serif; font-size: 11px; width: 240px;">
                
                <div style="background-color: #333; color: white; padding: 8px; border-radius: 4px; margin-bottom: 6px;">
                    <div style="font-size: 10px; color: #ddd; margin-bottom: 2px;">
                        ID: {id_celda}
                    </div>
                    <div style="font-size: 15px; font-weight: bold; color: {color_relleno};">
                        Score: {score:.0f} / 100
                    </div>
                </div>

                <table style="width: 100%; border-collapse: collapse; font-size: 11px; margin-bottom: 5px;">
                    <tr style="border-bottom: 1px solid #eee;"><td style="padding: 3px;">🌡️ <b>Temp:</b></td><td style="text-align: right;">{temp:.1f} °C</td></tr>
                    <tr style="border-bottom: 1px solid #eee;"><td style="padding: 3px;">💧 <b>Humedad:</b></td><td style="text-align: right;">{humedad:.1f} %</td></tr>
                    <tr style="border-bottom: 1px solid #eee;"><td style="padding: 3px;">🌧️ <b>Precip:</b></td><td style="text-align: right;">{precip:.1f} mm</td></tr>
                    <tr style="border-bottom: 1px solid #eee;"><td style="padding: 3px;">⛰️ <b>Altitud:</b></td><td style="text-align: right;">{altitud:.0f} msnm</td></tr>
                    <tr style="border-bottom: 1px solid #eee;"><td style="padding: 3px;">💨 <b>Viento:</b></td><td style="text-align: right;">{viento:.1f} km/h</td></tr>
                    <tr><td style="padding: 3px;">🌱 <b>Suelo:</b></td><td style="text-align: right;">{suelo}</td></tr>
                </table>

                <div style="
                    margin-top: 8px; 
                    padding-top: 5px; 
                    border-top: 2px solid {color_relleno}; 
                    max-height: 80px;         /* Un poco más de altura */
                    overflow-y: auto;         /* Scroll vertical si es necesario */
                    white-space: normal !important; /* IMPORTANTE: Fuerza el salto de línea */
                    word-wrap: break-word;    /* Rompe palabras largas */
                    overflow-wrap: break-word;
                    line-height: 1.3; 
                    color: #444;
                    font-style: italic;
                ">
                    {explicacion}
                </div>
            </div>
            """

            folium.GeoJson(
                geom,
                style_function=lambda x, color=color_relleno: {
                    'fillColor': color, 'color': 'black', 'weight': 0.5, 'fillOpacity': 0.6
                },
                tooltip=folium.Tooltip(tooltip_html, sticky=True)
            ).add_to(m)

        except Exception as e:
            continue


    #  4. EMPAQUETADO EN IFRAME ---
    map_html = m.get_root().render()
    
    iframe = f"""
    <iframe
        srcdoc="{html.escape(map_html)}"
        width="100%"
        height="500px"
        style="border:none; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);"
    ></iframe>
    """
    
    return iframe

########################################
#   ANALISIS DE BASE DE DATOS
########################################

def calcular_score_ponderado(valor, min_val, max_val):
    """
    Calcula un puntaje de 0 a 100.
    Reglas:
    - Dentro del rango [min_val, max_val] = 100 pts
    - Fuera del rango = disminuye proporcionalmente según la distancia al rango
    """
    
    try:
        val = float(valor)
        min_v = float(min_val)
        max_v = float(max_val)
        
        rango_total = max_v - min_v
        if rango_total == 0:
            return 100.0
        
        # 1. Dentro del rango -> 100
        if min_v <= val <= max_v:
            return 100.0
        
        # 2. Fuera del rango -> reducir proporcionalmente
        if val < min_v:
            distancia = min_v - val
        else:  # val > max_v
            distancia = val - max_v
        
        # Reducir el score: cada unidad de distancia reduce proporcionalmente
        reduccion = (distancia / rango_total) * 100.0
        score = max(0.0, 100.0 - reduccion * 3)  # casigo por 3 para penalizar más rápido
        
        return score
        
    except (ValueError, TypeError):
        return 0.0

def evaluar_idoneidad_terreno(df_celdas, reglas):
    """
    Evalúa celdas en formato 'Long' (una fila por fecha).
    Evalúa cada mes individualmente (detectando 'fecha').
    Promedia los meses para obtener el score anual.
    Agrupa por id_celda devolviendo geometrías únicas.
    """
    import pandas as pd
    import numpy as np

    print(f"⚙️ Iniciando Evaluación Cronológica (por columna 'fecha')...")

    # Validar que exista la columna fecha
    if 'fecha' not in df_celdas.columns:
        print("⚠️ Error: No se encontró la columna 'fecha' en los datos.")
        df_celdas['score'] = 0
        df_celdas['explicacion'] = "Faltan datos temporales."
        return df_celdas

    # Asegurar formato fecha
    df_celdas['fecha_dt'] = pd.to_datetime(df_celdas['fecha'], errors='coerce')
    df_celdas['mes'] = df_celdas['fecha_dt'].dt.month

    # Mapeo de reglas a columnas de la BD
    mapa_cols = {
        'temp': 'temp_promedio', 'temperatura': 'temp_promedio',
        'humedad': 'humedad_promedio',
        'precipitacion': 'precipitacion_promedio',
        'viento': 'viento_promedio',
        'altitud': 'elevacion_promedio', 'elevacion': 'elevacion_promedio',
        'suelo': 'tipo_suelo'
    }

    # Inicializamos una columna de score global para cada fila (mes)
    df_celdas['score_mes'] = 0.0
    df_celdas['cont_factores'] = 0
    df_celdas['motivo_fallo'] = ""

    # --- 1. EVALUACIÓN FILA POR FILA (MES A MES) ---
    for parametro, rango in reglas.items():
        col_db = mapa_cols.get(parametro.lower())
        
        if not col_db or col_db not in df_celdas.columns:
            continue
            
        # Lógica Numérica (Rangos)
        if isinstance(rango, dict) and 'min' in rango and 'max' in rango:
            vmin = float(rango['min'])
            vmax = float(rango['max'])
            
            # Aplicar función triangular a toda la columna
            score_param = df_celdas[col_db].apply(
                lambda x: calcular_score_ponderado(x, vmin, vmax)
            )
            
            # Acumular
            df_celdas['score_mes'] += score_param
            df_celdas['cont_factores'] += 1
            
            # Registrar fallos (si score es 0) para explicar luego
            # "Fallo en temp (valor X)"
            mask_fallo = score_param == 0
            df_celdas.loc[mask_fallo, 'motivo_fallo'] += (
                f"{parametro} fuera de rango (" + df_celdas.loc[mask_fallo, col_db].astype(str) + "); "
            )

        # Lógica Cualitativa (Suelo)
        elif isinstance(rango, str) and col_db == 'tipo_suelo':
            score_suelo = df_celdas[col_db].astype(str).str.contains(rango, case=False, na=False) * 100.0
            df_celdas['score_mes'] += score_suelo
            df_celdas['cont_factores'] += 1

    # Promediar los factores para obtener el score del MES
    mask_ok = df_celdas['cont_factores'] > 0
    df_celdas.loc[mask_ok, 'score_mes'] /= df_celdas.loc[mask_ok, 'cont_factores']
    
    # --- 2. AGRUPACIÓN POR CELDA (RESUMEN ANUAL) ---
    # Resumir los 12 meses a una fila por celda
    
    try:
        aggregation = {
            'score_mes': 'mean',           # El score final es el promedio del año
            'lat': 'first',                # Coordenadas no cambian
            'lon': 'first',
            'geometry': 'first',           # Geometría no cambia
            'temp_promedio': 'mean',       # Guardamos promedios referenciales
            'precipitacion_promedio': 'mean', # Precipitación anual acumulada
            'elevacion_promedio': 'mean',
            'humedad_promedio': 'mean',
            'viento_promedio': 'mean',
            'motivo_fallo': lambda x: " ".join(set([s for s in x if s])) # Concatenar fallos únicos
        }
        
        # Aseguramos que existan las columnas antes de agrupar
        agg_final = {k: v for k, v in aggregation.items() if k in df_celdas.columns}
        
        # Verificar ID correcto
        col_id = 'id_celda' if 'id_celda' in df_celdas.columns else 'id'
        
        # Limpiar
        df_celdas['score_mes'] = df_celdas['score_mes'].fillna(0.0).round(1)
        df_celdas['explicacion'] = "Datos insuficientes." # Default pesimista

        df_resultado = df_celdas.groupby(col_id, as_index=False).agg(agg_final)
        
        # Renombrar score_mes -> score
        df_resultado.rename(columns={'score_mes': 'score'}, inplace=True)
        df_resultado['score'] = df_resultado['score'].round(1)
        df_resultado['explicacion'] = "Datos insuficientes." # Default pesimista
        
        # Generar explicación final
        # Si el score es bajo pero no hay "motivo_fallo" grave, es por inestabilidad
        #df_resultado['explicacion'] = "Condiciones óptimas todo el año."
        
        # Lógica de explicación
        mask_bajo = df_resultado['score'] < 60
        mask_medio = (df_resultado['score'] >= 60) & (df_resultado['score'] < 80)
        mask_alto = df_resultado['score'] >= 80
        mask_con_fallos = df_resultado['motivo_fallo'] != ""
        
        df_resultado.loc[mask_bajo & mask_con_fallos, 'explicacion'] = \
            "Problemas estacionales detectados: " + df_resultado['motivo_fallo'].str.slice(0, 100) + "..."
            
        df_resultado.loc[mask_bajo & ~mask_con_fallos, 'explicacion'] = \
            "Condiciones variables o inestables reducen el potencial."

        df_resultado.loc[mask_medio, 'explicacion'] = "Condiciones aceptables con variaciones."
        df_resultado.loc[mask_alto, 'explicacion'] = "Condiciones adecuadas y estables."
        
        df_resultado['score'] = df_resultado['score'].fillna(0.0)

    except Exception as e:
        print(f"⚠️ Error durante la agrupación final: {e}")
        df_resultado = pd.DataFrame()
    return df_resultado

def generar_reporte_top_celdas(df_evaluado, top_n=5):
    """
    Toma el DataFrame evaluado, extrae los Top N ganadores y
    genera un texto comparativo para que el LLM lo explique.
    """
    # 1. Ordenar por score descendente
    top_df = df_evaluado.sort_values(by='score', ascending=False).head(top_n)
    
    if top_df.empty:
        return "No hay celdas aptas para reportar."

    reporte_texto = f"TOP {top_n} MEJORES ZONAS IDENTIFICADAS:\n"
    reporte_texto += "-" * 40 + "\n"

    ranking = 1
    for index, row in top_df.iterrows():
        # Extraer datos clave (redondeados)
        id_celda = row.get('id', row.get('id_celda', 'Desc'))
        score = row.get('score', 0)
        temp = row.get('temp_promedio', 0)
        precip = row.get('precipitacion_promedio', 0)
        altura = row.get('elevacion_promedio', 0)
        
        # Construir una ficha técnica legible para la IA
        reporte_texto += f"#{ranking} [ID: {id_celda}] -> SCORE: {score}/100\n"
        reporte_texto += f"   - Clima: {temp:.1f}°C, {precip:.1f}mm lluvia\n"
        reporte_texto += f"   - Geografía: {altura:.0f} msnm\n"
        reporte_texto += f"   - Diagnóstico Auto: {row.get('explicacion', '')}\n"
        reporte_texto += "\n"
        ranking += 1
        
    return reporte_texto

