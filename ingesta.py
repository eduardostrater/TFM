from random import random
from neo4j import GraphDatabase
from dotenv import load_dotenv
from openai import OpenAI
from typing import List, Dict, Any, Optional
import os
from modelosIA import llm

# Cargar variables de entorno
#################################

load_dotenv(dotenv_path="_mientorno.env") 
neo4j_apikey = os.getenv("NEO4J_PASSWORD")
neo4j_uri = os.getenv("NEO4J_URI")
gee_project = os.getenv("GEE_PROJECT", "pelagic-cat-476623-u0")


# Sesion en Google Earth Engine
#################################
_ee_inicializado = False

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



#    Sesión en Neo4j
###########################
if not neo4j_apikey:
    raise ValueError("No se encontró la API Key en las variables de entorno. Por favor, revisa _mientorno.env")
if not neo4j_uri:
    raise ValueError("No se encontró la URI de Neo4j en las variables de entorno. Por favor, revisa _mientorno.env")

driver = GraphDatabase.driver(
    neo4j_uri,
    auth=("neo4j", neo4j_apikey)
)

with driver.session() as s:
    print(s.run("RETURN 1").single()[0])

def crear_estructura(tx, filas):
    print (filas)

    try:
        """Inserta un batch de temperaturas en Neo4j"""
        tx.run("""
        UNWIND $filas AS fila
        MERGE (f:Fuente {name: 'GEOGRAFIA'})              
        MERGE (p:Pais {name: fila.pais})
        MERGE (d:Departamento {name: fila.departamento})
        MERGE (c:Ciudad {name: fila.ciudad})
        MERGE (o:Observacion {fecha: fila.fecha})
        SET o.temperatura = fila.temperatura

        MERGE (f)-[:CONTIENE]->(p)
        MERGE (p)-[:CONTIENE]->(d)
        MERGE (d)-[:CONTIENE]->(c)
        MERGE (c)-[:ES_OBSERVADO]->(o)
        """,
        filas=filas
        )
    except Exception as e:
        log(f"Error al insertar estructura: {e}")

def crear_restricciones(tx):
    tx.run("CREATE CONSTRAINT IF NOT EXISTS FOR (c:Ciudad) REQUIRE c.nombre IS UNIQUE")
#    tx.run("CREATE CONSTRAINT IF NOT EXISTS FOR (o:Observacion) REQUIRE o.fecha IS UNIQUE")
#    tx.run("CREATE CONSTRAINT IF NOT EXISTS FOR (m:Medida) REQUIRE .nombre IS UNIQUE")

def limpiar_temperaturas(tx):
    """Eliminar todas las temperaturas y sus relaciones"""
    result = tx.run("MATCH (t:Temperatura) DETACH DELETE t RETURN count(*) as deleted")
    deleted = result.single()["deleted"]
    log(f" {deleted} temperaturas eliminadas")

def limpiar_geografia(tx):
    # Eliminar todos los nodos conectados a la Fuente = "GEOGRAFIA"
    result = tx.run("""
    MATCH (f:Fuente {name: 'GEOGRAFIA'})-[:CONTIENE*]->(n)    
    DETACH DELETE n
    RETURN count(*) as deleted
    """)
    deleted = result.single()["deleted"]
    print(f" {deleted} nodos eliminadas")
    log(f" {deleted} nodos eliminadas")


# Crear la Jerarquia de tiempo
##################################

import pandas as pd




# Geometria y funciones de GEE
###################################

def carga_geometria() -> List[Dict[str, Any]]:
    """
    Carga la geometría de todas las regiones administrativas nivel 2 (ciudades) de Perú.
    Retorna un arreglo con diccionarios: {ciudad, departamento, geometria}
    """
    import ee

    # Obtener geometría desde Google Earth Engine usando GADM (Global Administrative Divisions)
    # GADM es una base de datos de límites administrativos disponible en GEE
    gadm = ee.FeatureCollection("FAO/GAUL/2015/level2")
    
    # Filtrar por Perú (ADM0_NAME = 'Peru')
    #peru_features = gadm.filter(ee.Filter.eq("ADM0_NAME", "Peru")) 
    # agregar otro filtro para lima
    peru_features = gadm.filter(ee.Filter.eq("ADM1_NAME", "Lima"))
    
    # Convertir a información Python
    features_info = peru_features.getInfo()["features"]
    
    # Arreglo para guardar geometrías
    geometrias = []
    
    # Iterar sobre todas las ciudades/municipios (nivel 2)
    for feature in features_info:
        props = feature["properties"]
        pais = props.get("ADM0_NAME", "Desconocido")
        departamento = props.get("ADM1_NAME", "Desconocido")
        ciudad = props.get("ADM2_NAME", "Desconocido")
        
        # Obtener geometría
        geometry = feature["geometry"]
        # Simplificar la geometría si es necesario
        geometry = ee.Geometry(geometry).simplify(10000)    
        
        geometrias.append({
            "ciudad": ciudad,
            "pais": pais,
            "departamento": departamento,
            "geometria": ee.Geometry(geometry)
        })
        
        log(f"Cargada geometría: {ciudad} ({departamento})")
    
    log(f"Total de ciudades cargadas: {len(geometrias)}")
    
    return geometrias



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
    print (collection.size().getInfo())

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


# Descargar serie temporal a python
#####################################

def ee_to_python(feature_collection):
    log ("Descargando datos de EE a Python")
    data = feature_collection.getInfo()["features"]
    return [
        {
            "fecha": f["properties"]["date"],
            "valor": f["properties"]["temp_c"]
        }
        for f in data if f["properties"]["temp_c"] is not None
    ]


# Pipeline

def inserta_temperaturas_ciudad(pais, departamento, ciudad, geometria, fecha_inicio, fecha_fin):
    log (f"Iniciando ingesta de temperatura para {ciudad} desde {fecha_inicio} hasta {fecha_fin}")
    fc = obtener_temperatura_diaria(geometria, fecha_inicio, fecha_fin)
    temperaturas = ee_to_python(fc)
    print (f"  {len(temperaturas)} registros de temperatura obtenidos")

    filas = [
        {   "pais": pais,
            "departamento": departamento,
            "ciudad": ciudad,
            "fecha": r["fecha"],
            "temperatura": round(float(r["valor"]), 2)
        }
        for r in temperaturas
    ]

    with driver.session() as s:
        for i in range(0, len(filas), 200):
            s.execute_write(
                crear_estructura,
                filas[i:i+200]
            )


#########################################

def inicializar(fecha_inicio="2025-01-01", fecha_fin="2025-12-31"):

    print("\n================ Iniciando Pipeline de Ingesta ================")
    # Inicializa
    print("\n1  Inicializando Google Earth Engine...")
    gee_inicializar()

    #  Inicializa el NEO4J
    with driver.session() as s:
        s.execute_write(crear_restricciones)
        s.execute_write(limpiar_geografia)
#       s.execute_write(limpiar_temperaturas)


    #  Inicializa el Pipeline de GEE
    print("2️  Configurando geometría y funciones de GEE...")
    geometrias = carga_geometria()
    
    for g in geometrias[:2]: # Limitar solo primeras 2 ciudades       
        geometria = g["geometria"]
        pais = g["pais"]
        ciudad = g["ciudad"]
        departamento = g["departamento"]
        print (f"  → Geometría encontrada para {ciudad} en {departamento}")
            # Crear en Neo4j
        print("3️  Creando nodo Ciudad en Neo4j...")


        # Ejecutar la ingesta de la temperatura de la ciudad
        print("4  Ejecutando ingesta de temperatura...")
        inserta_temperaturas_ciudad(
            pais=pais,
            departamento=departamento,
            ciudad=ciudad,
            geometria=geometria,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin
        )

    
    print("\n###### Pipeline completado!")
    print("="*60)
   



# Cargar la información al Grafo
fecha_inicial = '2025-01-01'
fecha_final = '2025-12-31'


inicializar(fecha_inicial, fecha_final)


