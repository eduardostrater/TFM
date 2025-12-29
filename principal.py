
import sys
##if sys.stdout.encoding != 'utf-8':
##    sys.stdout.reconfigure(encoding='utf-8')

import pandas as pd
import numpy as np
import json
from typing import List, Dict, Any
import prompts

from typing import List, Dict, Any, Optional
import funciones
from datetime import datetime
from modelosIA import llm

####################################
###     LLM
#####################################

def run_llm(
    prompt: str,
    tools: Optional[List[Dict]] = None,
    tool_functions: Optional[Dict[str, Any]] = None,
) -> str:
    """
   Ejecuta una solicitud a un LLM que opcionalmente admite el uso de herramientas.

Argumentos:
    prompt (str): El prompt del sistema o del usuario que se enviará.
    tools (list[dict], opcional): Lista de esquemas de herramientas para la llamada a funciones del modelo.
    tool_functions (dict[str, callable], opcional): Mapeo de nombres de herramientas a funciones de Python.

Retorna:
    str: Texto final de la respuesta del LLM.
    """

    # Step 1: Initial LLM call
    from langchain_core.messages import SystemMessage
    messages = [SystemMessage(content=prompt)]
    
    if tools:
        llm_with_tools = llm.bind_tools(tools)
        response = llm_with_tools.invoke(messages)
    else:
        response = llm.invoke(messages)
    
    message = response

    # Si no hay herramientas, responder con LLM directamente
    if not getattr(message, "tool_calls", None):
        return message.content

    # En caso no existan herramientas definidas, no se puede proceder
    if not tool_functions:
        return message.content + "\n\n!!!!!! No se proporcionaron funciones de herramienta para ejecutar las llamadas a herramientas."

    tool_messages = []
    for tool_call in message.tool_calls:
        # Extraer el nombre de la función y los argumentos de tool_call - manejar tanto formatos dict como objeto
        func_name = None
        args = {}
        tool_call_id = None
        
        # Verificar si es un dict
        if isinstance(tool_call, dict):
            func_name = tool_call.get('name')
            args = tool_call.get('args', {})
            tool_call_id = tool_call.get('id')
        else:
            # Es un objeto - intentar diferentes nombres de atributos
            if hasattr(tool_call, 'function'):
                # Formato del Modelo con .function                
                func_name = tool_call.function.name
                args = json.loads(tool_call.function.arguments or "{}")
            elif hasattr(tool_call, 'name'):
                # Formato LangChain con .name directamente
                func_name = tool_call.name
                args = tool_call.args if hasattr(tool_call, 'args') else {}
            
            tool_call_id = tool_call.id if hasattr(tool_call, 'id') else None
        
        # Omitir si no pudimos extraer el nombre de la función
        if not func_name:
            continue
            
        tool_fn = tool_functions.get(func_name)

        try:
            result = tool_fn(**args) if tool_fn else {"error": f"Tool '{func_name}' not implemented."}
        except Exception as e:
            result = {"error": str(e)}

        tool_messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": json.dumps(result)
        })
    
    # Paso 4: Segunda pasada — enviar las salidas de las herramientas de vuelta al modelo
    from langchain_core.messages import SystemMessage, ToolMessage
    
    followup_messages = [
        SystemMessage(content=prompt),
        message,
    ]
    
    for tool_msg in tool_messages:
        followup_messages.append(ToolMessage(
            tool_call_id=tool_msg["tool_call_id"],
            content=tool_msg["content"]
        ))

    final = llm.invoke(followup_messages)
    return final.content



################################################
###         BITACORA de EVENTOS
################################################


import logging
from typing import Dict, Any, List

file_handler = logging.FileHandler('historial.log', encoding='utf-8')
stream_handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

file_handler.setFormatter(formatter)
stream_handler.setFormatter(formatter)

logging.basicConfig(
    level=logging.INFO,
    handlers=[file_handler, stream_handler]
)

logger = logging.getLogger(__name__)



################################################
###         TOOLS
################################################
# =====================================================
#  Definir las funciones de las herramientas
# =====================================================

    #return {"result": funciones.temperatura(fechainicial, fechafinal, region)}

   

def ask_user(question: str, missing_info: str = ""):
    """Consulta al usuario y espera la respuesta."""
    logger.info(f"Preguntando al usuario: {question}")
    if missing_info:
        print(f"---SE REQUIERE INFORMACIÓN---\nInformación faltante: {missing_info}")
    else:
        print(f"---SE REQUIERE INFORMACIÓN DEL USUARIO---")
    
    answer = input(f"{question}: ")
    logger.info(f"Respuesta del usuario: {answer}")
    return {"context": answer, "source": "Información del Usuario"}






################################################
###         AGENTES 
################################################



#   AGENTE SUPERVISOR
#########################################

def agente_supervisor(state):
    print("---AGENTE SUPERVISOR---")
    
    n_iter = state.get("n_iteration", 0) + 1
    state["n_iteration"] = n_iter
    print(f"Iteración del supervisor: {n_iter}")

    # Finalizar al llegar al límite de iteraciones

    if n_iter >= 3:
        print("!!!!! Se llegó al límite de iteraciones.")
        updated_history = (
            state.get("conversation_history", "")
            + "\nAsistente: Se llegó al límite de iteraciones. Finalizando."
        )
        return {
            "conversation_history": updated_history,
            "next_agent": "end",
            "n_iteration": n_iter
        }
    
    # ¿Requiere más información por parte del usuario?
    if state.get("needs_clarification", False):
        user_clarification = state.get("user_clarification", "")
        print(f"Procesando aclaración del usuario: {user_clarification}")
        
        # Actualizar el historial de conversación con el intercambio de aclaraciones
        clarification_question = state.get("clarification_question", "")
        updated_conversation = state.get("conversation_history", "") + f"\nAsistente: {clarification_question}\nUsuario: {user_clarification}"
        
        # Actualizar el estado para borrar los estados de la aclaración
        updated_state = state.copy()
        updated_state["needs_clarification"] = False
        updated_state["conversation_history"] = updated_conversation
        
        # Borrar los campos de aclaración
        if "clarification_question" in updated_state:
            del updated_state["clarification_question"]
        if "user_clarification" in updated_state:
            del updated_state["user_clarification"]
            
        return updated_state

    user_query = state["user_input"]
    conversation_history = state.get("conversation_history", "")
    
    print(f"Consulta del usuario: {user_query}")
    print(f"Historial de conversación: {conversation_history}")
    
    # Incluir el historial de la conversación en el prompt
    full_context = f"Conversación completa:\n{conversation_history}"
    
    prompt = prompts.SUPERVISOR_PROMPT.format(
        conversation_history=full_context,  # Usar el contexto completo en lugar de solo el historial
    )

    tools = [
        {
            "type": "function",
            "function": {
                "name": "ask_user",
                "description": "Preguntar al usuario para aclaración o información adicional cuando su consulta no esté clara o falten detalles importantes. USAR SOLO si falta información esencial como número de póliza o ID de cliente.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "La pregunta específica para hacer al usuario para aclaración"
                        },
                        "missing_info": {
                            "type": "string", 
                            "description": "Información específica que esté faltando o que necesite aclaración"
                        }
                    },
                    "required": ["question", "missing_info"]
                }
            }
        }
    ]

    print("... Llamando al LLM para la decisión del supervisor...")
    from langchain_core.messages import SystemMessage
    messages = [SystemMessage(content=prompt)]
    llm_with_tools = llm.bind_tools(tools)
    response = llm_with_tools.invoke(messages)

    message = response

    # Comprobar si el supervisor quiere pedir aclaración al usuario
    if getattr(message, "tool_calls", None):
        print (getattr(message, "tool_calls", None))
        print("🛠️ Supervisor solicitando aclaración del usuario")
        for tool_call in message.tool_calls:
            # Verificar los formatos para la llamada a tools
            tool_name = None
            tool_args = {}
            
            if isinstance(tool_call, dict):
                # Formato DICT
                tool_name = tool_call.get("name")
                tool_args = tool_call.get("args", {})
            else:
                # Formato OBJETO
                if hasattr(tool_call, 'name'):
                    tool_name = tool_call.name
                    tool_args = tool_call.args if hasattr(tool_call, 'args') else {}
                elif hasattr(tool_call, 'function'):
                    # Formato Modelo
                    tool_name = tool_call.function.name
                    tool_args = json.loads(tool_call.function.arguments or "{}")
            
            print("🛠️ Nombre del tool: " + tool_name)

            if tool_name == "ask_user":
                question = tool_args.get("question", "Por favor proporcione más detalles.")
                missing_info = tool_args.get("missing_info", "información adicional")
                
                print(f"Preguntando al usuario: {question}")
                
                user_response_data = ask_user(question, missing_info)
                user_response = user_response_data["context"]
                
                print(f"Respuesta del usuario: {user_response}")
                
                # Actualizar el historial de la conversación con la pregunta y la respuesta
                updated_history = conversation_history + f"\nAsistente: {question}"
                updated_history = updated_history + f"\nUsuario: {user_response}"
                
                return {
                    "needs_clarification": True,
                    "clarification_question": question,
                    "user_clarification": user_response,
                    "conversation_history": updated_history
                }

    # Si no hay llamadas a herramientas, proceder con la decisión normal del supervisor
    message_content = message.content.strip()
    
    print(f"***** Respuesta del LLM (primeros 300 chars):\n{message_content[:500]}\n")
    
    import re
    parsed = None
    
    try:
        # Primer intento: análisis directo de JSON
        parsed = json.loads(message_content)
        print("******** Salida del supervisor analizada con éxito")
    except json.JSONDecodeError:
        print("!!!!!! El análisis directo de JSON falló, intentando extraer JSON...")
        print(f"Respuesta completa:\n{message_content}\n")
        
        # Segundo intento: buscar el JSON más cuidadosamente
        # Buscar desde la primera { hasta la última }
        start_idx = message_content.find('{')
        if start_idx != -1:
            # Contar llaves para encontrar el final del objeto JSON
            brace_count = 0
            end_idx = -1
            for i in range(start_idx, len(message_content)):
                if message_content[i] == '{':
                    brace_count += 1
                elif message_content[i] == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end_idx = i + 1
                        break
            
            if end_idx != -1:
                json_str = message_content[start_idx:end_idx]
                try:
                    parsed = json.loads(json_str)
                    print(f"✅ JSON extraído: {parsed}")
                except json.JSONDecodeError as e:
                    print(f"!!!!!! JSON extraído es inválido: {e}")
                    print(f"Texto extraído: {json_str[:200]}")
                    parsed = {}
            else:
                print("!!!!!!! No se encontró JSON válido (llaves no balanceadas)")
                parsed = {}
        else:
            print("!!!!!! No se encontró { en la respuesta")
            parsed = {}

    next_agent = parsed.get("next_agent", "agente_ayuda_general")
    task = parsed.get("task", "Ayudar al usuario con su consulta")
    justification = parsed.get("justification", "")

    print(f"---DECISIÓN DEL SUPERVISOR: {next_agent}---")
    print(f"Tarea: {task}")
    print(f"Razón: {justification}")

    # Actualizar el historial de la conversación con el intercambio actual
    updated_conversation = conversation_history + f"\nAsistente: Enrutando a {next_agent} para: {task}"

    print(f"➡️ Enrutando a: {next_agent}")
    return {
        "next_agent": next_agent,
        "task": task,
        "justification": justification,
        "conversation_history": updated_conversation,
        "n_iteration": n_iter
    }



# AGENTE Climático
####################################3

def agente_climatico(state):
    logger.info("************* Agente Climático")
    logger.debug(f"Estado del Agente Climático: { {k: v for k, v in state.items() if k != 'messages'} }")
    
    prompt = prompts.PROMPT_CLIMATICO.format(
        task=state.get("task"),
        conversation_history=state.get("conversation_history", "")
    )

    tools = [
        {"type": "function", "function": {
            "name": "temperatura_old",
            "description": "Obtiene el clima de un rango de fechas de una región geográficoa dada.",
            "parameters": {
                "type": "object",
                "properties": {
                    "fechainicial": {
                        "type": "string",
                        "description": "Fecha de inicio del rango (formato: YYYY-MM-DD)"
                    },
                    "fechafinal": {
                        "type": "string",
                        "description": "Fecha de fin del rango (formato: YYYY-MM-DD)"
                    },
                    "region": {
                        "type": "string",
                        "description": "Región geográfica"
                    }
                },
                "required": ["fechainicial", "fechafinal", "region"]
            }
        }},
         {"type": "function", "function": {
            "name": "temperatura",
            "description": "Obtiene el clima de un rango de fechas de una región geográfica dada.",
            "parameters": {
                "type": "object",
                "properties": {
                    "peticion": {
                        "type": "string",
                        "description": "Es la petición en lenguaje natural para obtener la temperatura"
                    },
                },
                "required": ["peticion"]
            }
        }}
    ]


    result = run_llm(prompt, tools, tool_functions={"temperatura_old": funciones.temperatura, "temperatura": funciones.temperatura_libre})
    print ("Resultado de funciones.temperatura_libre:", result)

        
    # Actualizar el historial de la conversación
    current_history = state.get("conversation_history", "")
    updated_state = {"messages": [("assistant", result)]}
    updated_state["conversation_history"] = current_history + f"\nAgente Climático: {result}"

    logger.info("********* Agente climático completado")

    return updated_state



#   AGENTE DE AYUDA
#########################################
def nodo_agente_ayuda_general(state):
    print("---AGENTE DE AYUDA GENERAL---")

    print("✅ Agente de ayuda general completado")
    respuesta_final = "Sin respuesta"
    conversation_history = state.get("conversation_history", "")
    updated_state = state.copy()


    updated_state["conversation_history"] = conversation_history + f"\nAgente de Ayuda General: {respuesta_final}"

    return updated_state



#   AGENTE DE RESPUESTA FINAL
#########################################

def agente_respuesta_final(state):
    """Generar un resumen final antes de terminar la conversación"""
    print("---AGENTE DE RESPUESTA FINAL---")
    logger.info("Agente de respuesta final iniciado")
    
    user_query = state["user_input"]
    conversation_history = state.get("conversation_history", "")
    
    # Extraer la respuesta más reciente del especialista
    recent_responses = []
    for msg in reversed(state.get("messages", [])):
        if hasattr(msg, 'content') and "clarification" not in msg.content.lower():
            recent_responses.append(msg.content)
            if len(recent_responses) >= 2:  # Obtener las últimas 2 respuestas que no sean aclaraciones
                break
    
    specialist_response = recent_responses[0] if recent_responses else "No hay respuesta disponible."
    
    prompt = prompts.PROMPT_RESPUESTA_FINAL.format(

        specialist_response=specialist_response,  
        user_query=user_query,
    )
    
    print("... Generando resumen final...")
    from langchain_core.messages import SystemMessage
    messages = [SystemMessage(content=prompt)]
    response = llm.invoke(messages)
    
    respuesta_final = response.content
    
    print(f"Respuesta final: {respuesta_final}")
    
    # Reemplazar todos los mensajes anteriores con solo la respuesta final
    clean_messages = [("assistant", respuesta_final )]

    state["respuesta_final"] = respuesta_final
    state["end_conversation"] = True
    state["conversation_history"] = conversation_history + f"\nAsistente: {respuesta_final}"
    state["messages"] = clean_messages
    
    return state


from langgraph.graph import StateGraph, END
from typing import TypedDict, List, Annotated, Dict, Any, Optional
from langgraph.graph import add_messages
from datetime import datetime


class GraphState(TypedDict):
    # Datos básicos del mensaje
    messages: Annotated[List[Any], add_messages]
    user_input: str
    conversation_history: Optional[str]
    n_iteration: Optional[int]

    # Gestión del supervisor
    next_agent: Optional[str]             
    task: Optional[str]                   # Tarea actual determinada por el supervisor
    justification: Optional[str]          # Razonamiento/explicación del supervisor
    end_conversation: Optional[bool]      # Indicador para la terminación ordenada de la conversación
    
      
    # Metadatos a nivel de sistema
    timestamp: Optional[str]     # Registrar la hora del último mensaje del usuario o actualización del estado
    respuesta_final: Optional[str]


# Decisión de cambio de agente
########################################

def decide_next_agent(state):
    # Manejar primero el caso de aclaración
    if state.get("needs_clarification"):
        return "agente_supervisor"  # Volver al supervisor para procesar la aclaración
    
    if state.get("end_conversation"):
        return "end"
    
    next_agent = state.get("next_agent", "agente_ayuda_general")
    
    return next_agent


# Actualizar el flujo de trabajo para incluir el agente de respuesta final
#############################################################################


workflow = StateGraph(GraphState)

workflow.add_node("agente_climatico", agente_climatico)
workflow.add_node("agente_supervisor", agente_supervisor)
workflow.add_node("agente_ayuda_general", nodo_agente_ayuda_general)
workflow.add_node("agente_respuesta_final", agente_respuesta_final)  # Add this

workflow.set_entry_point("agente_supervisor")



workflow.add_conditional_edges(
    "agente_supervisor",
    decide_next_agent,
    {
        "agente_supervisor": "agente_supervisor",
        "agente_climatico": "agente_climatico",
        "agente_ayuda_general": "agente_ayuda_general",
        "end": "agente_respuesta_final"
    }
)

# Volver al supervisor después de cada especialista
#######################################################

workflow.add_edge("agente_ayuda_general", "agente_supervisor")
workflow.add_edge("agente_climatico", "agente_supervisor")
workflow.add_edge("agente_respuesta_final", END)  # Respuesta Final lleva al END

app = workflow.compile()


def run_test_query(query):
    estado_inicial = {

        "messages": [],
        "user_input": query,
        "conversation_history": f"User: {query}", 
        "n_iteration":0,
        
        "next_agent": "agente_supervisor",
        "task": "Atender las peticiones del usuario",
        "respuesta_final": ""
    }
    
    print(f"\n{'='*50}")
    print(f"QUERY: {query}")
    print(f"\n{'='*50}")
    
    # iniciar el grafo
    estado_final = app.invoke(estado_inicial)
    
    # Imprimir la respuesta
    print("\n---RESPUESTA FINAL---")
    respuesta_final = estado_final.get("respuesta_final", "No se generó una respuesta final.")
    print(respuesta_final)
    
    
    return estado_final



# Prueba del sistema con una consulta de ejemplo
# Pide un dato al usuario

peticion = input("Ingrese la consulta de prueba para el sistema de agentes: ")
#Ejemplo: "Dame el promedio de la temperatura de la ciudad de Canta durante el 1er semestre 2025"
final_output =  run_test_query(peticion)



