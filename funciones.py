from neo4j import GraphDatabase
from dotenv import load_dotenv
from typing import List, Dict, Any, Optional
import os
from modelosIA import llm

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
#   FUNCIONES DE TOOLS
####################################

def temperatura (peticion  : str, fecha_inicial: str, fecha_final: str, region: str)-> Dict[str, Any]:
    """
    Obtiene la temperatura promedio de una región en un rango de fechas desde Neo4j.
    
    Args:
        peticion: petición en lenguaje natural
        fecha_inicial: fecha inicio (ej: '2023-01-01')
        fecha_final: fecha fin (ej: '2024-12-31')
        region: nombre de la región (ej: 'Lima')
    """
    a=1
    return {"Temperatura": f"{a:.2f}"}


def temperatura_libre(peticion  : str)-> Dict[str, Any]:

    # Convertir el texto a Cypher
    query = texto_a_cypher(peticion + ' Devuelve solo un valor numérico de temperatura promedio en formato float expresado en Celsius, sin la unidad de medida; sollo el número.')

    print(f"... Obteniendo temperatura de {peticion}")

    with driver.session() as session:
        # Extraer el valor numérico del primer campo del registro
        record = session.run(query).single()
        print ("Record: ", record)

        temperature_value = record.value() if record is not None else None

    return {
        "Temperatura": f"{temperature_value:.2f}" if isinstance(temperature_value, (int, float)) else temperature_value
    }



########################################
#   PRUEBA DE LA FUNCION
########################################

#t = temperatura_libre("Obtener la temperatura promedio entre enero y marzo 2023 de Lima")
#print (t)
