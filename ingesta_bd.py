import psycopg2
from psycopg2.extras import execute_batch
from shapely.geometry import box, Point
from shapely import wkt
from typing import List, Dict

import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import ee
import os


try:
    import ingesta_ee
    print("✅ Módulo ingesta cargado correctamente")
except Exception as e:
    print(f"⚠️ Advertencia: No se pudo cargar ingesta: {str(e)}")
    print("⚠️ Algunas funcionalidades pueden no estar disponibles")


# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler('ingesta_terreno.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
registrador = logging.getLogger(__name__)




# --- 1. CONFIGURACIÓN DE GOOGLE EARTH ENGINE ---
# Intenta inicializar. Si es la primera vez, te pedirá autenticación en el navegador

gee_project = os.getenv("GEE_PROJECT", "")

# Sesion en Google Earth Engine - Import ONLY when needed
_ee_initialized = False

def gee_inicializar():
    """Autentica e inicializa la API de Google Earth Engine."""
    global _ee_initialized
    if _ee_initialized:
        print("✅ GEE ya está inicializado")
        return
    
    print("🔐 Abriendo navegador para autenticación de GEE...")
    ee.Authenticate()
    ee.Initialize(project=gee_project)
    print (gee_project)
    print(f"✅ GEE inicializado")
    ee_initialized = True

gee_inicializar()


def generar_id_celda(lat: float, lon: float, pais: str, departamento: str, ciudad: str, 
                     tamaño_grilla: int = 500) -> str:
    """
    Genera un id_celda único y descriptivo
    
    Formato: {PAIS}_{DEPARTAMENTO}_{CIUDAD}_{TAMAÑO_GRILLA}m_{LAT}_{LON}
    Ejemplo: PE_CAJ_500m_-7.1234_-78.5678
    """
    # Redondear a la grilla
    lat_redondeado = round(lat, 4)
    lon_redondeado = round(lon, 4)
    
    id_celda = f"{pais}_{departamento}_{ciudad}_{tamaño_grilla}m_{lat_redondeado}_{lon_redondeado}"
    return id_celda




class IngestionCeldasTerreno:
    def __init__(self, config_bd: dict):
        self.conexion = psycopg2.connect(**config_bd)
        self.cursor = self.conexion.cursor()
    
    def crear_celdas_grilla(self, limites: tuple, tamaño_celda_m: int = 250) -> List[Dict]:
        """
        Crea una grilla de celdas para una región
        
        limites: (lon_min, lat_min, lon_max, lat_max)
        tamaño_celda_m: tamaño de celda en metros
        """
        lon_min, lat_min, lon_max, lat_max = limites
        
        # Convertir metros a grados (aproximado)
        # 1 grado ≈ 111km en el ecuador
        tamaño_celda_grados = tamaño_celda_m / (111000/1)
        
        print (tamaño_celda_grados)
        print (limites)

        celdas = []
        lat = lat_min
        
        while lat < lat_max:
            lon = lon_min
            while lon < lon_max:
                # Crear polígono de la celda
                poligono_celda = box(lon, lat, 
                                  lon + tamaño_celda_grados, 
                                  lat + tamaño_celda_grados)
                
                centroide = poligono_celda.centroid
                
                celda = {
                    'id_celda': generar_id_celda(
                        centroide.y, centroide.x, 
                        'PE', 'LIM', tamaño_celda_m
                    ),
                    'geometria': poligono_celda.wkt,
                    'centroide': centroide.wkt,
                    'centroide_lat': centroide.y,
                    'centroide_lon': centroide.x,
                    'area_m2': tamaño_celda_m * tamaño_celda_m
                }
                
                celdas.append(celda)
                lon += tamaño_celda_grados
            lat += tamaño_celda_grados
        
        return celdas
    
    def enriquecer_con_datos_clima(self, celda: Dict) -> Dict:
        """
        Enriquece la celda con datos climáticos mensuales desde Google Earth Engine
        Retorna diccionario con datos por mes
        """
        lat = celda['centroide_lat']
        lon = celda['centroide_lon']

        try:
            import ee
            from shapely.wkt import loads as wkt_loads
            
            # Convertir WKT a geometría de GEE
            geometria_shapely = wkt_loads(celda['geometria'])
            coords = list(geometria_shapely.exterior.coords)
            geometria = ee.Geometry.Polygon([coords])
            
            # Obtener datos mensuales de GEE
            datos_mensuales = ingesta_ee.enriquecer_celda_gee(geometria, '2023-01-01', '2023-12-31')
            
            # Convertir formato de datos mensuales a formato para inserción
            # Estructura: {'2023-01': {...datos...}, '2023-02': {...}, ..., 'elevacion': X}
            celda['datos_mensuales'] = datos_mensuales
            
            return celda
        except Exception as e:
            registrador.error(f"Error enriquecimiento GEE para ({lat},{lon}): {e}")
            celda['datos_mensuales'] = {}
            return celda
        
    def insertar_celdas(self, celdas: List[Dict], tamaño_lote: int = 100):
        """
        Inserta celdas mensuales en lotes con manejo robusto de errores
        Convierte cada celda en 12 registros (uno por mes) con fechas
        """
        #eliminar_registros = "DELETE FROM celdas_terreno"
        #self.cursor.execute(eliminar_registros)
        #self.conexion.commit()
        
        # Expandir células a registros mensuales
        registros_mensuales = []
        
        for celda in celdas:
            if 'datos_mensuales' not in celda or not celda['datos_mensuales']:
                registrador.warning(f"Celda {celda['id_celda']} no tiene datos mensuales")
                continue
            
            datos = celda['datos_mensuales']
#            elevacion_promedio = datos.get('elevacion', None)
            
            # Iterar sobre los 12 meses
            for mes_str, datos_mes in datos.items():
                if mes_str == 'elevacion':
                    continue
                
                try:
                    # Convertir '2023-01' → datetime(2023, 1, 1)
                    partes = mes_str.split('-')
                    año = int(partes[0])
                    mes = int(partes[1])
                    objeto_fecha = datetime(año, mes, 1)
                    
                    registro = {
                        'id_celda': celda['id_celda'],
                        'pais_region': celda.get('pais_region', 'PERU'),
                        'departamento_region': celda.get('departamento_region', 'LIM'),
                        'ciudad_region': celda.get('ciudad_region', 'LIMA'),
                        'geometria': celda['geometria'],
                        'centroide': celda['centroide'],
                        'area_m2': celda['area_m2'],
                        'fecha': objeto_fecha,
                        'temp_promedio': datos_mes.get('temp_avg', None),
                        'precipitacion_promedio': datos_mes.get('precip_promedio', None),
                        'humedad_promedio': datos_mes.get('humedad_promedio', None),
                        'elevacion_promedio': datos.get('elevacion', None),
                        'viento_promedio': datos_mes.get('viento_promedio', None),
                        'puntuacion_calidad_datos': celda.get('puntuacion_calidad_datos', 0.8),
                    }
                    registros_mensuales.append(registro)
                except Exception as e:
                    registrador.error(f"Error conversión mes {mes_str} para celda {celda['id_celda']}: {e}")
                    continue
        
        # Insertar registros mensuales
        consulta_insertar = """
        INSERT INTO celdas_terreno (
            id_celda, pais_region, departamento_region, ciudad_region,
            geometria, centroide, lat, lon,
            area_m2, fecha,
            temp_promedio, precipitacion_promedio, humedad_promedio, elevacion_promedio, viento_promedio,
            puntuacion_calidad_datos, ultima_actualizacion
        ) VALUES (
            %(id_celda)s, %(pais_region)s, %(departamento_region)s, %(ciudad_region)s,
            ST_GeomFromText(%(geometria)s, 4326),
            ST_GeomFromText(%(centroide)s, 4326),
            ST_Y(ST_GeomFromText(%(centroide)s, 4326)), ST_X(ST_GeomFromText(%(centroide)s, 4326)),
            %(area_m2)s, %(fecha)s,
            %(temp_promedio)s, %(precipitacion_promedio)s, %(humedad_promedio)s,  %(elevacion_promedio)s, %(viento_promedio)s,    
            %(puntuacion_calidad_datos)s, NOW()
        )
        ON CONFLICT (id_celda, fecha) DO UPDATE SET
            temp_promedio = EXCLUDED.temp_promedio,
            precipitacion_promedio = EXCLUDED.precipitacion_promedio,
            humedad_promedio = EXCLUDED.humedad_promedio,
            elevacion_promedio = EXCLUDED.elevacion_promedio,
            viento_promedio = EXCLUDED.viento_promedio,
            ultima_actualizacion = NOW();
        """
        
        total_registros = len(registros_mensuales)
        insertados = 0
        fallidos = 0
        
        for idx_lote in range(0, total_registros, tamaño_lote):
            lote = registros_mensuales[idx_lote:idx_lote + tamaño_lote]
            try:
                execute_batch(self.cursor, consulta_insertar, lote, page_size=tamaño_lote)
                self.conexion.commit()
                insertados += len(lote)
                registrador.info(f"✅ Lote {idx_lote // tamaño_lote + 1}: {len(lote)} registros mensuales insertados")
            except Exception as e:
                self.conexion.rollback()
                fallidos += len(lote)
                registrador.error(f"❌ Error de lote en índice {idx_lote}: {e}")
        
        registrador.info(f"📊 Resumen inserción en BD: {insertados} registros insertados, {fallidos} fallidos de {total_registros} total")
    


    
    def enriquecer_celda(self, celda: Dict, idx_celda: int, total_celdas: int) -> Dict:
        """
        Enriquece una celda individual con datos mensuales desde GEE
        """
        try:
            # Obtener datos mensuales completos (12 meses + elevación)
            celda = self.enriquecer_con_datos_clima(celda)
            
            # Calcular score de calidad (basado en disponibilidad de datos)
            celda['puntuacion_calidad_datos'] = self.calcular_puntuacion_calidad(celda)
            
            if (idx_celda + 1) % 10 == 0 or idx_celda == 0:
                registrador.info(f"   ✓ Progreso: {idx_celda + 1}/{total_celdas} celdas enriquecidas")
            
            return celda
        except Exception as e:
            registrador.error(f"Error al prerparar celda {idx_celda}: {e}")
            celda['datos_mensuales'] = {}
            return celda
    
    def ingestar_region(self, pais: str, departamento: str, ciudad: str,  
                     tamaño_celda_m: int = 5000):
        
        limites = obtener_region(pais, departamento, ciudad)
        """
        Pipeline completo de ingesta para una región con enriquecimiento paralelo y GEE
        """
        registrador.info(f"\n{'='*70}")
        registrador.info(f"🚀 INICIANDO INGESTA DE TERRENO PARA: {ciudad}, {departamento}, {pais}")
        registrador.info(f"Límites: {limites} | Tamaño celda: {tamaño_celda_m}m")
        if _ee_initialized:
            registrador.info(f"⚡ MODO: Google Earth Engine ")        
        try:
            # Inicializar GEE si está disponible
            if _ee_initialized:
                registrador.info("🔌 Inicializando Google Earth Engine...")
                gee_inicializar()
            
            # Paso 1: Crear grid
            registrador.info("📍 Creando celdas de grilla...")
            celdas = self.crear_celdas_grilla(limites, tamaño_celda_m)
            registrador.info(f"✅ Se crearon {len(celdas)} celdas de grilla\n")
            
            # Agregar datos básicos a todas las celdas
            for celda in celdas:
                celda['pais_region'] = pais
                celda['departamento_region'] = departamento
                celda['ciudad_region'] = ciudad
            
            # Paso 2: Enriquecer con datos EN PARALELO (12 workers)
            registrador.info(f"📡 Enriqueciendo {len(celdas)} celdas con datos clima y elevación (MODO PARALELO)...")
            tiempo_inicio = time.time()
            
            celdas_enriquecidas = []
            with ThreadPoolExecutor(max_workers=4) as ejecutor:
                # Enviar todas las celdas para enriquecimiento paralelo
                futuros = {
                    ejecutor.submit(self.enriquecer_celda, celda, idx, len(celdas)): idx 
                    for idx, celda in enumerate(celdas)
                }
                
                # Recopilar resultados a medida que se completan
                for futuro in as_completed(futuros):
                    celdas_enriquecidas.append(futuro.result())
            
            tiempo_transcurrido = time.time() - tiempo_inicio
            registrador.info(f"✅ Enriquecimiento completado para {len(celdas_enriquecidas)} celdas en {tiempo_transcurrido:.1f} segundos\n")
            
            # Paso 3: Insertar en BD
            registrador.info("💾 Insertando celdas en base de datos PostgreSQL...")
            self.insertar_celdas(celdas_enriquecidas)
            tiempo_total = time.time() - tiempo_inicio
            registrador.info(f"\n{'='*70}")
            registrador.info(f"🎉 ¡INGESTA COMPLETADA EXITOSAMENTE!")
            registrador.info(f"Tiempo total: {tiempo_total:.1f} segundos ({tiempo_total/60:.1f} minutos)")
            
        except Exception as e:
            registrador.error(f"\n❌ ERROR CRÍTICO DURANTE INGESTA: {e}")
            raise
    

    def calcular_puntuacion_calidad(self, celda: Dict) -> float:
        """
        Calcula un score de calidad basado en completitud de datos mensuales
        """
        if 'datos_mensuales' not in celda or not celda['datos_mensuales']:
            return 0.0
        
        datos = celda['datos_mensuales']
        
        # Contar meses con datos completos
        meses_completos = 0
        campos_requeridos = ['temp_avg', 'precip_avg', 'humidity_avg']
        
        for mes_str, datos_mes in datos.items():
            if mes_str == 'elevacion':
                continue
            
            # Verificar si el mes tiene todos los campos requeridos
            if all(datos_mes.get(campo) is not None for campo in campos_requeridos):
                meses_completos += 1
        
        # Score: proporción de meses completos / 12 meses
        return min(1.0, (meses_completos / 12.0) if meses_completos > 0 else 0.8)


def existe_region (pais: str, departamento: str, ciudad: str) -> bool:
    """
    Consulta rápida para saber si ya existen celdas de esa ciudad.
    Retorna True si hay datos, False si no.
    """
    import psycopg2
    from dotenv import load_dotenv
    import os
    
    load_dotenv(dotenv_path="_mientorno.env")
    
    # Configuración de conexión (Asegúrate de que coincida con la tuya)
    config_bd = {
        'host': 'localhost',
        'database': 'postgres',
        'user': 'postgres',
        'password': 'postgres',
        'port': 5432
    }
    
    existe = False
    try:
        conn = psycopg2.connect(**config_bd)
        cur = conn.cursor()
        
        # Consulta optimizada: SELECT 1 ... LIMIT 1 es muy rápido
        # Normalizamos a mayúsculas para evitar errores de "Lima" vs "LIMA"
        consulta = """
            SELECT 1 FROM celdas_terreno 
            WHERE UPPER(pais_region) = UPPER(%s)
              AND UPPER(departamento_region) = UPPER(%s)
              AND UPPER(ciudad_region) = UPPER(%s)
            LIMIT 1;
        """
        cur.execute(consulta, (pais, departamento, ciudad))
        
        if cur.fetchone():
            existe = True
            
        cur.close()
        conn.close()

    except Exception as e:
        print(f"⚠️ Error verificando existencia: {e}")
        # En caso de error, asumimos False para no bloquear, o maneja según prefieras
        return False
        
    return existe


def obtener_region(adm0, adm1, adm2):
    """
    Recibe País (adm0), Región/Depto (adm1) y Ciudad/Provincia (adm2).
    """
    import ee

    print(f"🌍 Buscando límites para: {adm0} > {adm1} > {adm2} ...")

    # Usamos la colección GAUL Nivel 2 (Distrital/Provincial)
    dataset = ee.FeatureCollection("FAO/GAUL/2015/level2")

    region = dataset.filter(
        ee.Filter.And(
            ee.Filter.eq("ADM0_NAME", adm0),
            ee.Filter.eq("ADM1_NAME", adm1),
            ee.Filter.eq("ADM2_NAME", adm2)
        )
    )
    
    # Verificamos si existe la región
    if region.size().getInfo() == 0:
        print("❌ No se encontró la región en GAUL. Verifica la ortografía (ej: 'Peru' vs 'Perú').")
        return None

    # Obtenemos el rectángulo envolvente (Bounding Box)
    geom = region.geometry().bounds()
    
    # Extraemos las coordenadas del polígono rectangular
    coords_info = geom.coordinates().get(0).getInfo()
    
    lons = [p[0] for p in coords_info]
    lats = [p[1] for p in coords_info]
    
    lon_min, lat_min = min(lons), min(lats)
    lon_max, lat_max = max(lons), max(lats)
    
    print(f"✅ Bounds encontrados: {lon_min:.4f}, {lat_min:.4f}, {lon_max:.4f}, {lat_max:.4f}")
    
    return (lon_min, lat_min, lon_max, lat_max)


# Uso:
def ingestar(pais, departamento, ciudad):
    from dotenv import load_dotenv
    import os

    load_dotenv(dotenv_path="_mientorno.env") 
    try:

        config_bd = {
        'host': 'localhost',
        'database': 'postgres',
        'user': 'postgres',
        'password': 'postgres',
        'port': 5432
        }
        
        ingestion = IngestionCeldasTerreno(config_bd)
        ingestion.ingestar_region(pais, departamento, ciudad, tamaño_celda_m=2500)
        ingestion.conexion.close()


    except Exception as e:
        registrador.error(f"Error fatal: {e}")
        raise


if __name__ == "__main__":
    ingestar("Peru", "Lima", "Huarochirí")
