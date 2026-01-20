from random import random
from dotenv import load_dotenv
from typing import List, Dict, Any, Optional
import os
from modelosIA import llm
import pandas as pd


# Cargar variables de entorno
#################################

load_dotenv(dotenv_path="_mientorno.env") 
gee_project = os.getenv("GEE_PROJECT", "pelagic-cat-476623-u0")
GEE_DISPONIBLE = False

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
    ee.Initialize(project=gee_project)
    print(f"... GEE inicializado con proyecto: {gee_project}")
    _ee_inicializado = True
    


def log (evento: str):
    # imprimir la hora y el evento
    from datetime import datetime
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print (f"[{ahora}] {evento}")
    return

# Consulta de Viento
################################
def obtener_viento_diaria(geometria, fecha_inicio, fecha_fin):

    import ee
    log("Obteniendo viento diario desde EE")

    collection = (
        ee.ImageCollection("ECMWF/ERA5_LAND/DAILY_AGGR")
        .filterDate(fecha_inicio, fecha_fin)
        .select("u_component_of_wind_10m", "v_component_of_wind_10m")
    )

    def viento(img):
        u_wind = img.select("u_component_of_wind_10m").reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geometria,
            scale=10000,
            maxPixels=1e9
        )
        v_wind = img.select("v_component_of_wind_10m").reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geometria,
            scale=10000,
            maxPixels=1e9
        )
        
    
        
        # Calcular magnitud del viento
        u_value = ee.Number(u_wind.get("u_component_of_wind_10m"))
        v_value = ee.Number(v_wind.get("v_component_of_wind_10m"))
        wind_speed = u_value.pow(2).add(v_value.pow(2)).sqrt()

        return ee.Feature(None, {
            "date": img.date().format("YYYY-MM-dd"),
            "wind_speed": wind_speed
        })

    return collection.map(viento)

# Consulta de Temperatura
################################

def obtener_temperatura_diaria(geometria, fecha_inicio, fecha_fin):
    import ee
    log("Obteniendo temperatura diaria desde EE")

    collection = (
        ee.ImageCollection("ECMWF/ERA5_LAND/DAILY_AGGR")
        .filterDate(fecha_inicio, fecha_fin)
        .select("temperature_2m")
    )

    def temp(img):
        temp = img.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geometria,
            scale=10000, # 
            maxPixels=1e4
        )
        
        # Obtener el valor - la clave es el nombre de la banda seleccionada
        temp_value = ee.Number(temp.get("temperature_2m")) 

        return ee.Feature(None, {
            "date": img.date().format("YYYY-MM-dd"),
            "temp_c": temp_value.subtract(273.15) # Convertir de Kelvin a Celsius
        })

    return collection.map(temp)


# Consulta de Precipitación
################################

def obtener_precipitacion_diaria(geometria, fecha_inicio, fecha_fin):
    """
    Obtiene precipitación diaria desde GEE usando CHIRPS
    Retorna FeatureCollection con datos de precipitación
    """
    import ee
    log("Obteniendo precipitación diaria desde EE")

    try:
        collection = (
            ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY")
            .filterDate(fecha_inicio, fecha_fin)
            .select("precipitation")
        )
        
        def precip(img):
            try:
                precip_value = img.reduceRegion(
                    reducer=ee.Reducer.sum(),
                    geometry=geometria,
                    scale=5000,
                    maxPixels=1e4
                )
                
                precip_mm = ee.Number(precip_value.get("precipitation"))

                return ee.Feature(None, {
                    "date": img.date().format("YYYY-MM-dd"),
                    "precip_mm": precip_mm
                })
            except Exception as e:
                log(f"Error procesando imagen precipitación: {e}")
                return None

        result = collection.map(precip)
        # Filtrar nulos
        return result.filterMetadata('date', 'not_equals', None)
    except Exception as e:
        log(f"Error en obtener_precipitacion_diaria: {e}")
        raise


# Consulta de Humedad
################################

def obtener_humedad_diaria(geometria, fecha_inicio, fecha_fin):
    """
    Obtiene humedad relativa diaria desde GEE usando ERA5-Land
    Calcula a partir de temperatura y punto de rocío
    Retorna FeatureCollection con datos de humedad
    """
    import ee
    log("Obteniendo humedad diaria desde EE")

    collection = (
        ee.ImageCollection("ECMWF/ERA5_LAND/DAILY_AGGR")
        .filterDate(fecha_inicio, fecha_fin)
        .select(["temperature_2m", "dewpoint_temperature_2m"])
    )

    def humedad(img):
        # Extraer promedios de T y Td usando reduceRegion
        temp_value = img.select("temperature_2m").reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geometria,
            scale=10000,
            maxPixels=1e9
        )
        
        dewpoint_value = img.select("dewpoint_temperature_2m").reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geometria,
            scale=10000,
            maxPixels=1e9
        )
        
        # Obtener valores numéricos
        temp_k = ee.Number(temp_value.get("temperature_2m"))
        dewpoint_k = ee.Number(dewpoint_value.get("dewpoint_temperature_2m"))
        
        # Convertir Kelvin a Celsius
        temp_c = temp_k.subtract(273.15)
        dewpoint_c = dewpoint_k.subtract(273.15)
        
        # Calcular humedad relativa usando la fórmula de Magnus
        # RH = 100 * (exp((b*Td)/(c+Td)) / exp((b*T)/(c+T)))
        b = ee.Number(17.27)
        c = ee.Number(237.7)
        
        numerador = b.multiply(temp_c).divide(c.add(temp_c)).exp()
        denominador = b.multiply(dewpoint_c).divide(c.add(dewpoint_c)).exp()
        humidity_pct = denominador.divide(numerador).multiply(100)

        return ee.Feature(None, {
            "date": img.date().format("YYYY-MM-dd"),
            "humidity_pct": humidity_pct
        })

    return collection.map(humedad)


# Consulta de Elevación
################################

def obtener_elevacion(geometria):
    """
    Obtiene elevación promedio desde SRTM en GEE
    Retorna valor escalar (promedio de elevación en metros)
    """
    import ee
    log("Obteniendo elevación desde EE")
    
    try:
        # Usar CGIAR/SRTM90_V4 que es más confiable
        srtm = ee.Image("CGIAR/SRTM90_V4")
        elevation = srtm.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geometria,
            scale=90,
            maxPixels=1e9
        )
        
        elevation_m = ee.Number(elevation.get("elevation"))
        return elevation_m.getInfo()
    except Exception as e:
        log(f"Error obteniendo elevación: {e}")
        # Retornar None si hay error
        return None


# Descargar serie temporal a python
#####################################

def ee_to_python(feature_collection):
    log ("Descargando datos de EE a Python")
    try:
        data = feature_collection.getInfo()["features"]
        result = []
        for f in data:
            try:
                temp_val = f["properties"].get("temp_c")
                if temp_val is not None:
                    # Manejo robusto de diferentes formatos de GEE
                    if isinstance(temp_val, dict):
                        # Si es diccionario, extraer el valor
                        temp_val = temp_val.get("value", list(temp_val.values())[0] if temp_val else None)
                    
                    if temp_val is not None:
                        temp_val = float(temp_val)
                        # si el día de la fecha es el primero del mes
                        if f["properties"]["date"].endswith("-01"):     # Si es el 1er día del mes
                            result.append({
                                "fecha": f["properties"]["date"],
                                "valor": temp_val
                        })
            except Exception as e:
                log(f"Error procesando valor de temperatura: {e}")
                continue
        log(f"✅ Se obtuvieron {len(result)} registros de temperatura")
        return result
    except Exception as e:
        log(f"Error en ee_to_python: {e}")
        return []


def ee_to_python_viento(feature_collection):
    """Convierte FeatureCollection de viento a diccionario Python"""
    log("Descargando datos de viento de EE a Python")
    try:
        data = feature_collection.getInfo()["features"]
        result = []
        for f in data:
            try:
                viento_val = f["properties"].get("wind_speed")
                if viento_val is not None:
                    # Convertir a float directamente
                    # GEE puede retornar: float, dict, o None
                    if isinstance(viento_val, dict):
                        viento_val = viento_val.get("value", list(viento_val.values())[0] if viento_val else None)
                    
                    if viento_val is not None:
                        viento_val = float(viento_val)
                        result.append({
                            "fecha": f["properties"]["date"],
                            "valor": viento_val
                        })
            except Exception as e:
                log(f"Error procesando valor de viento: {e}")
                continue
        log(f"✅ Se obtuvieron {len(result)} registros de viento")
        return result
    except Exception as e:
        log(f"Error en ee_to_python_viento: {e}")
        return []
    

def ee_to_python_precip(feature_collection):
    """Convierte FeatureCollection de precipitación a diccionario Python"""
    log("Descargando datos de precipitación de EE a Python")
    try:
        data = feature_collection.getInfo()["features"]
        if not data:
            log("⚠️ No hay datos de precipitación disponibles")
            return []
        
        result = []
        for f in data:
            try:
                precip_val = f["properties"].get("precip_mm")
                if precip_val is not None:
                    # Manejo robusto de diferentes formatos de GEE
                    if isinstance(precip_val, dict):
                        # Si es diccionario, extraer el valor
                        precip_val = precip_val.get("value", list(precip_val.values())[0] if precip_val else None)
                    
                    if precip_val is not None:
                        precip_val = float(precip_val)
                        result.append({
                            "fecha": f["properties"]["date"],
                            "valor": precip_val
                        })
            except Exception as e:
                log(f"Error procesando feature de precipitación: {e}")
                continue
        
        log(f"✅ Se obtuvieron {len(result)} registros de precipitación")
        return result
    except Exception as e:
        log(f"Error crítico en ee_to_python_precip: {e}")
        return []


def ee_to_python_humedad(feature_collection):
    """Convierte FeatureCollection de humedad a diccionario Python"""
    log("Descargando datos de humedad de EE a Python")
    try:
        data = feature_collection.getInfo()["features"]
        result = []
        for f in data:
            try:
                humedad_val = f["properties"].get("humidity_pct")
                if humedad_val is not None:
                    # Convertir a float directamente
                    # GEE puede retornar: float, dict, o None
                    if isinstance(humedad_val, dict):
                        humedad_val = humedad_val.get("value", list(humedad_val.values())[0] if humedad_val else None)
                    
                    if humedad_val is not None:
                        humedad_val = float(humedad_val)
                        result.append({
                            "fecha": f["properties"]["date"],
                            "valor": humedad_val
                        })
            except Exception as e:
                log(f"Error procesando valor de humedad: {e}")
                continue
        log(f"✅ Se obtuvieron {len(result)} registros de humedad")
        return result
    except Exception as e:
        log(f"Error en ee_to_python_humedad: {e}")
        return []



def enriquecer_celda_gee(geometria, fecha_inicio='2023-01-01', fecha_fin='2023-12-31'):

    import pandas as pd
    log("Enriqueciendo celda con datos mensuales de GEE...")
    datos_mensuales = {}
    
    try:
        # Temperatura diaria
        log("  Procesando temperatura...")
        fc_temp = obtener_temperatura_diaria(geometria, fecha_inicio, fecha_fin)
        temp_data = ee_to_python(fc_temp)
        
        # Precipitación diaria
        log("  Procesando precipitación...")
        fc_precip = obtener_precipitacion_diaria(geometria, fecha_inicio, fecha_fin)
        precip_data = ee_to_python_precip(fc_precip)
        
        # Humedad diaria
        log("  Procesando humedad...")
        fc_humedad = obtener_humedad_diaria(geometria, fecha_inicio, fecha_fin)
        humedad_data = ee_to_python_humedad(fc_humedad)

        log("  Procesando viento...")
        fc_viento = obtener_viento_diaria(geometria, fecha_inicio, fecha_fin)
        viento_data = ee_to_python_viento(fc_viento)
        
        # Convertir a DataFrames para procesamiento mensual
        df_temp = pd.DataFrame(temp_data)
        if not df_temp.empty:
            df_temp['fecha'] = pd.to_datetime(df_temp['fecha'])
            df_temp['mes'] = df_temp['fecha'].dt.strftime('%Y-%m')
        
        df_precip = pd.DataFrame(precip_data)
        if not df_precip.empty:
            df_precip['fecha'] = pd.to_datetime(df_precip['fecha'])
            df_precip['mes'] = df_precip['fecha'].dt.strftime('%Y-%m')

        df_humedad = pd.DataFrame(humedad_data)
        if not df_humedad.empty:
            df_humedad['fecha'] = pd.to_datetime(df_humedad['fecha'])
            df_humedad['mes'] = df_humedad['fecha'].dt.strftime('%Y-%m')

        df_viento = pd.DataFrame(viento_data)
        if not df_viento.empty:
            df_viento['fecha'] = pd.to_datetime(df_viento['fecha'])
            df_viento['mes'] = df_viento['fecha'].dt.strftime('%Y-%m')
        
        # Obtener todos los meses únicos
        meses_unicos = set()
        if not df_temp.empty:
            meses_unicos.update(df_temp['mes'].unique())
        if not df_precip.empty:
            meses_unicos.update(df_precip['mes'].unique())
        if not df_humedad.empty:
            meses_unicos.update(df_humedad['mes'].unique())
        if not df_viento.empty:
            meses_unicos.update(df_viento['mes'].unique())
        
        # Agregar por mes
        for mes in sorted(meses_unicos):
            datos_mes = {}
            
            # Temperatura: promedio, mín y máx del mes
            if not df_temp.empty:
                temp_mes = df_temp[df_temp['mes'] == mes]['valor'].values
                if len(temp_mes) > 0:
                    datos_mes['temp_avg'] = round(float(temp_mes.mean()), 2)
                    datos_mes['temp_min'] = round(float(temp_mes.min()), 2)
                    datos_mes['temp_max'] = round(float(temp_mes.max()), 2)
            
            # Precipitación: total del mes
            if not df_precip.empty:
                precip_mes = df_precip[df_precip['mes'] == mes]['valor'].values
                if len(precip_mes) > 0:
                    datos_mes['precip_total'] = round(float(precip_mes.sum()), 2)
                    datos_mes['precip_promedio'] = round(float(precip_mes.mean()), 2)
                    datos_mes['precip_total'] = round(float(precip_mes.sum()), 2)   # ESF : Nuevo
            
            # Humedad: promedio del mes
            if not df_humedad.empty:
                humedad_mes = df_humedad[df_humedad['mes'] == mes]['valor'].values
                if len(humedad_mes) > 0:
                    datos_mes['humedad_promedio'] = round(float(humedad_mes.mean()), 2)

            # Humedad: promedio del mes
            if not df_viento.empty:
                viento_mes = df_viento[df_viento['mes'] == mes]['valor'].values
                if len(viento_mes) > 0:
                    datos_mes['viento_promedio'] = round(float(viento_mes.mean()), 2)
            
            if datos_mes:
                datos_mensuales[mes] = datos_mes
        
        # Elevación (constante para toda la celda)
        log("  Procesando elevación...")
        elevacion = obtener_elevacion(geometria)
        if elevacion is not None:
            datos_mensuales['elevacion'] = round(float(elevacion), 2)
        
        log(f"✅ Celda enriquecida con datos de {len(datos_mensuales)-1} meses")
        return datos_mensuales
        
    except Exception as e:
        log(f"❌ Error enriqueciendo celda: {e}")
        return {}




#########################################

def inicializar(fecha_inicio="2025-01-01", fecha_fin="2025-12-31"):

    print("\n================ Iniciando Pipeline de Ingesta ================")
    # Inicializa
    print("\n1  Inicializando Google Earth Engine...")
    gee_inicializar()


    #  Inicializa el Pipeline de GEE
    print("2️  Configurando geometría y funciones de GEE...")
    #geometrias = carga_geometria()
    

