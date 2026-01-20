import bd
import json
import os
from dotenv import load_dotenv
import ee
import osmnx as ox
from shapely.geometry import shape, LineString, Point, MultiLineString
from shapely import wkt
from typing import List, Dict
from ingesta_bd import obtener_region

# =============================================================================
# ⚙️ CONFIGURACIÓN CRÍTICA DE OSMNX
# =============================================================================
ox.settings.use_cache = True
ox.settings.log_console = False
ox.settings.timeout = 180  # 3 minutos de timeout para evitar cortes

# SOLUCIÓN AL ERROR "12,840 times":
# Aumentamos el límite de área permitida a 25,000 km2 (suficiente para Lima Región)
# El valor está en metros cuadrados. 25,000,000,000 m2.
ox.settings.max_query_area_size = 25 * 1000 * 1000 * 1000 * 1000    

# =============================================================================

# Cargar variables de entorno
#################################

load_dotenv(dotenv_path="_mientorno.env") 
gee_project = os.getenv("GEE_PROJECT", "pelagic-cat-476623-u0")
GEE_DISPONIBLE = False
_ee_inicializado = False

# Sesion en Google Earth Engine
#################################

def gee_inicializar():
    """Autentica e inicializa la API de Google Earth Engine."""
    global _ee_inicializado
    
    if _ee_inicializado:
        print("✅ GEE ya está inicializado")
        return
    
    import ee
    print("... Abriendo navegador para autenticación de GEE...")
    ee.Authenticate()
    try:
        ee.Initialize(project=gee_project)
        print(f"... GEE inicializado con proyecto: {gee_project}")
        _ee_inicializado = True
    except Exception as e:
        print(f"❌ Error al inicializar GEE: {e}")
        _ee_inicializado = False

# Catálogo actualizado con fuentes reales
CATALOGO_REFERENCIAS = {
    "rios": {
        "fuente": "GEE: WWF/HydroSHEDS", 
        "descripcion": "Ríos reales obtenidos de Google Earth Engine"
    },
    "carreteras": {
        "fuente": "OpenStreetMap (OSMnx)", 
        "descripcion": "Red vial real transitable"
    },
    "puntos_interes": {
        "fuente": "OpenStreetMap (OSMnx)", 
        "descripcion": "Infraestructura real (Mercados, Escuelas, etc)"
    }
}

def verificar_existencia_referencia(conexion, pais, departamento, ciudad, tipo):
    """Retorna True si ya tenemos datos de ese tipo para esa ciudad"""
    try:
        cur = conexion.cursor()
        cur.execute("""
            SELECT 1 FROM referencias_geo 
            WHERE pais_region = %s AND departamento_region = %s AND ciudad_region = %s AND tipo = %s LIMIT 1
        """, (pais, departamento, ciudad, tipo))
        res = cur.fetchone()
        cur.close()
        return bool(res)
    except:
        return False


def geojson_a_wkt(geojson_geom):
    """Convierte geometría GeoJSON a WKT para PostGIS"""
    try:
        g = shape(geojson_geom)
        return g.wkt
    except:
        return None

def ingestar_referencia_demanda(pais, departamento, ciudad, tipo):
    """
    INGESTA REAL:
    - Rios -> Google Earth Engine (WWF/HydroSHEDS)
    - Carreteras/POIs -> OpenStreetMap (OSMnx)
    """

    bbox = obtener_region(pais, departamento, ciudad)
    if bbox is None:
        return f"Error: No hay celdas base para {ciudad}. Ejecuta ingesta de terreno primero."

    min_lon, min_lat, max_lon, max_lat = bbox
    datos_a_insertar = []
    print(f"📥 INGESTANDO {tipo.upper()} REAL para {ciudad}")
    print(f"   📐 Bounding Box: [{min_lon}, {min_lat}] a [{max_lon}, {max_lat}]")

    try:
        # ---------------------------------------------------------
        # CASO 1: RÍOS (Fuente: Google Earth Engine)
        # ---------------------------------------------------------
        if tipo == "rios":
            # Region
            roi = ee.Geometry.Rectangle([min_lon, min_lat, max_lon, max_lat])
            
            # Colección de ríos de WWF
            rios_fc = ee.FeatureCollection("WWF/HydroSHEDS/v1/FreeFlowingRivers").filterBounds(roi)
            
            # Descargar datos al cliente (limitamos a 50 para no saturar)
            features = rios_fc.limit(2000).getInfo()['features']
            
            if not features:
                return f"⚠️ No se encontraron ríos en GEE para {ciudad}."

            for f in features:
                props = f['properties']
                nombre = props.get('RIV_ORD', 'Rio Sin Nombre') # O usar otro campo disponible
                geom_geojson = f['geometry']
                
                wkt_geom = geojson_a_wkt(geom_geojson)
                if wkt_geom:
                    # Guardamos el orden del río como nombre o una etiqueta genérica
                    etiqueta = f"Río (Orden {nombre})"
                    datos_a_insertar.append((pais, departamento, ciudad, 'rios', etiqueta, wkt_geom))

        # ---------------------------------------------------------
        # CASO 2: CARRETERAS (Fuente: OpenStreetMap via OSMnx)
        # ---------------------------------------------------------
        elif tipo == "carreteras":
            print("   ↳ Consultando OpenStreetMap (puede tardar unos segundos)...")
            # Descargar grafo de carreteras a 5km a la redonda

            filtro_vial = '["highway"~"motorway|trunk|primary|secondary"]'

            try:
                G = ox.graph_from_bbox(bbox=(max_lat, min_lat, max_lon, min_lon), custom_filter=filtro_vial)
                # Convertir a GeoDataframe de aristas (líneas)
                gdf_edges = ox.graph_to_gdfs(G, nodes=False, edges=True)
                
                if len(G.edges) > 0:
                    gdf_edges = ox.graph_to_gdfs(G, nodes=False, edges=True)
                    print(f"     ✅ Se encontraron {len(gdf_edges)} tramos principales.")

                # Tomar las carreteras principales (limitadas para demo)
                for _, row in gdf_edges.head(200).iterrows():
                    nombre = row.get('name', 'Vía Desconocida')
                    if isinstance(nombre, list): nombre = nombre[0] # A veces viene lista
                    
                    wkt_geom = row['geometry'].wkt
                    datos_a_insertar.append((ciudad, 'carreteras', str(nombre), wkt_geom))
            except Exception as e:
                return f"Error OSM Carreteras: {str(e)}"

        # ---------------------------------------------------------
        # CASO 3: PUNTOS DE INTERÉS (Fuente: OpenStreetMap via OSMnx)
        # ---------------------------------------------------------
        elif tipo == "puntos_interes":
            print("   ↳ Buscando zonas de conservación en OpenStreetMap...")
            # Tags para buscar SOLO zonas de conservación
            tags = {
                'leisure': 'nature_reserve',
                'boundary': 'protected_area'
            }
            try:
                gdf_pois = ox.features_from_bbox(bbox=(max_lat, min_lat, max_lon, min_lon), tags=tags)
                
                for _, row in gdf_pois.head(200).iterrows():
                    nombre = row.get('name', 'Área Protegida')
                    tipo_conservacion = row.get('protect_class', 'Zona de Conservación')
                    
                    # Asegurar que sea punto (a veces vienen polígonos de edificios)
                    geom = row['geometry']
                    if geom.geom_type != 'Point':
                        geom = geom.centroid # Convertir polígono a punto
                    
                    datos_a_insertar.append((ciudad, 'puntos_interes', f"{tipo_conservacion}: {nombre}", geom.wkt))
            except Exception as e:
                # A veces no encuentra nada y lanza error
                print(f"Info OSM: {e}")
                pass

        # ---------------------------------------------------------
        # INSERCIÓN EN BASE DE DATOS
        # ---------------------------------------------------------
        if not datos_a_insertar:
            return f"⚠️ No se encontraron datos reales de {tipo} en la zona."

        conn = bd.conexion_bd()
        cur = conn.cursor()
        
        # Usamos ST_GeomFromText para convertir el WKT de Python a Geometría PostGIS
        cur.executemany("""
            INSERT INTO referencias_geo (pais_region, departamento_region, ciudad_region, tipo, nombre, geometria)
            VALUES (%s, %s, %s, %s, %s, ST_SetSRID(ST_GeomFromText(%s), 4326))
        """, datos_a_insertar)
        
        conn.commit()
        cur.close()
        conn.close()
        
        return f"✅ INGESTA REAL: Se guardaron {len(datos_a_insertar)} elementos de {tipo}."

    except Exception as e:
        return f"❌ Error crítico en ingesta real: {str(e)}"

# ... (El resto del archivo, como ejecutar_analisis_combinatorio, se mantiene igual) ...

def analisis_postgis(pais, departamento, ciudad, criterios):
    """
    Construye una QUERY DINÁMICA DE POSTGIS basada en N criterios.
    (Misma lógica que tenías, solo asegura que ingestar_referencia_demanda sea la nueva)
    """
    conn = bd.conexion_bd()
    
    # 1. Asegurar ingesta
    logs_ingesta = []
    for crit in criterios:
        tipo = crit['referencia']
        # Forzamos re-check o ingesta si no existe
        if not verificar_existencia_referencia(conn, pais, departamento, ciudad, tipo):
            res = ingestar_referencia_demanda(pais, departamento, ciudad, tipo)
            logs_ingesta.append(res)

    # 2. Construir Query (Igual que antes)
    sql_base = """
        SELECT c.id_celda, c.lat, c.lon, round(puntuacion_calidad_datos::numeric, 2) as puntuacion_calidad, c.temp_promedio, c.humedad_promedio
        FROM celdas_terreno c
        WHERE c.ciudad_region = %s
    """
    params = [ciudad]
    
    for crit in criterios:
        tipo = crit['referencia']
        dist_metros = crit['distancia']
        
        # Query optimizada espacialmente
        subquery = """
        EXISTS (
            SELECT 1 FROM referencias_geo r 
            WHERE r.ciudad_region = c.ciudad_region 
            AND r.tipo = %s 
            AND ST_DWithin(c.geometria::geography, r.geometria::geography, %s)
        )
        """
        
        if crit['condicion'] == 'cerca':
            sql_base += f" AND {subquery}"
        else:
            sql_base += f" AND NOT {subquery}"
            
        params.extend([tipo, dist_metros])
        
    sql_base += " ORDER BY round(puntuacion_calidad_datos::numeric, 2) DESC;"
    
    # 3. Ejecutar y devolver
    try:
        import pandas as pd
        cursor = conn.cursor()
        cursor.execute(sql_base, tuple(params))
        cols = [desc[0] for desc in cursor.description]
        filas = cursor.fetchall()
        df = pd.DataFrame(filas, columns=cols)
        
        # Recuperar geometrías para mapa
        tipos_usados = list(set([c['referencia'] for c in criterios]))
        sql_ref = "SELECT tipo, ST_AsGeoJSON(geometria) as geojson FROM referencias_geo WHERE ciudad_region = %s AND tipo = ANY(%s)"
        cursor.execute(sql_ref, (ciudad, tipos_usados))
        filas_ref = cursor.fetchall()
        
        referencias_visuales = []
        if filas_ref:
            for row in filas_ref:
                # Detectamos si es Tupla o Diccionario para evitar errores
                if isinstance(row, (tuple, list)):
                    tipo_val = row[0]
                    geo_val = row[1]
                else:
                    # Es un Diccionario (RealDictRow)
                    tipo_val = row['tipo']
                    geo_val = row['geojson']

                # Si geo_val es string, decodificamos; si ya es dict, lo usamos directo
                if isinstance(geo_val, str):
                    geojson_obj = json.loads(geo_val)
                else:
                    geojson_obj = geo_val
                    
                referencias_visuales.append({
                    "tipo": tipo_val,
                    "geojson": geojson_obj
                })
            
        cursor.close()
        conn.close()
        
        return {
            "logs": logs_ingesta,
            "celdas_filtradas": df.to_dict(orient='records'),
            "referencias_mapa": referencias_visuales
        }
    except Exception as e:
        return {"logs": logs_ingesta + [f"Error SQL: {e}"], "celdas_filtradas": [], "referencias_mapa": []}


    #################################################


def tool_analisis_referencias_test (criterios: List[dict], pais: str, departamento: str, ciudad: str):
    """
    Realiza un análisis espacial combinatorio.
    Args:
        criterios: Lista de dicts. Ejemplo: 
                   [{"referencia": "rios", "condicion": "cerca", "distancia": 500},
                    {"referencia": "carreteras", "condicion": "lejos", "distancia": 2000}]
                   Valores válidos referencia: 'rios', 'carreteras', 'puntos_interes'.
                   Valores válidos condicion: 'cerca', 'lejos'.
                   Distancia en metros.
        ciudad: Nombre de la ciudad (ej: 'Canta').
    """
    print(f"🛠️ EJECUTANDO TOOL ANÁLISIS: {criterios} en {ciudad}")
    try:
        resultado = analisis_postgis(pais, departamento, ciudad, criterios)
        print (resultado)
        # Formateamos un resumen texto para el LLM
        num_celdas = len(resultado['celdas_filtradas'])
        logs = "\n".join(resultado['logs'])
        
        msg = f"Análisis completado.\nLogs de Ingesta: {logs}\nSe encontraron {num_celdas} celdas que cumplen TODOS los criterios."
        
        # RETORNAMOS UN OBJETO RICO (Texto + Datos Ocultos)
        return {
            "mensaje": msg, 
            "datos_celdas": resultado['celdas_filtradas'],
            "datos_ref": resultado['referencias_mapa']
        }
    except Exception as e:
        return f"Error en análisis: {str(e)}"    
    
if __name__ == "__main__":
    gee_inicializar()
    resultado = tool_analisis_referencias_test([{"referencia": "rios", "condicion": "cerca", "distancia": 100}], "Peru", "Lima", "Lima")
    print (resultado)