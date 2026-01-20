import os
import sys
import builtins
import gradio as gr
import json
from typing import Annotated, TypedDict, List
import uuid
import os

# Cargar variables de entorno
from dotenv import load_dotenv
load_dotenv()

# Importamos MemorySaver para la persistencia
from langgraph.checkpoint.memory import MemorySaver 
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, BaseMessage
from langgraph.graph import StateGraph, END, START
from langgraph.graph.message import add_messages

# Importaciones locales
from modelosIA import llm
import prompts
import funciones
import bd
from langsmith import traceable

from ingesta_bd import ingestar, existe_region
import ingesta_ref  
import folium

from langchain_core.tools import tool



# --- REVISAR SI QUEDARÁ ESTA CONFIGURACIÓN GLOBAL UTF-8 ---

os.environ["PYTHONUTF8"] = "1"
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except AttributeError:
    pass

if not hasattr(builtins, "_original_open_seguro"):
    builtins._original_open_seguro = builtins.open

def open_utf8_safe(*args, **kwargs):
    original = builtins._original_open_seguro
    if 'encoding' in kwargs: return original(*args, **kwargs)
    mode = kwargs.get('mode')
    if mode is None and len(args) > 1: mode = args[1]
    if mode is None or 'b' not in str(mode): kwargs['encoding'] = 'utf-8'
    return original(*args, **kwargs)
builtins.open = open_utf8_safe




conexion = bd.conexion_bd()

# --- 2. CONFIGURACIÓN DEL ESTADO ---
AgentState = TypedDict("AgentState", {
    "mensajes": Annotated[List[BaseMessage], add_messages],
    "siguiente_nodo": str,
    "ultimo_agente": str,
    "caracteristicas_geoclimaticas": str,
    "pais": str,
    "departamento": str,
    "ciudad": str,
    "resultados_evaluacion": list,
    "datos_celdas": str,
    "capas_referencia": list
})

def formatear_reglas_html(reglas):
    """
    Genera una tabla HTML.
    - Si 'reglas' es una lista (mes a mes): Tabla matricial (Param x Meses) con scroll.
    - Si 'reglas' es un dict (resumen): Tabla vertical simple.
    """
    if not reglas: 
        return "<div style='padding:10px; color:#666;'>Esperando definición de cultivo...</div>"

    # ==========================================
    # CASO A: LISTA DE MESES (Visión Anual)
    # ==========================================
    if isinstance(reglas, list):
        # 1. Organizar datos por mes (1..12) y recolectar parámetros únicos
        datos_por_mes = {m: {} for m in range(1, 13)}
        all_params = set()
        
        datos_validos = False
        
        for item in reglas:
            if not isinstance(item, dict): continue
            
            # Intentar obtener el número de mes
            mes_raw = item.get('mes')
            if mes_raw is None: continue 
            
            try:
                m_idx = int(mes_raw)
                if 1 <= m_idx <= 12:
                    datos_por_mes[m_idx] = item
                    datos_validos = True
                    # Recolectar claves (excepto 'mes')
                    for k in item.keys():
                        if k.lower() != 'mes':
                            all_params.add(k)
            except: continue
        
        # Si no se pudo estructurar como matriz mensual, hacer fallback a merge
        if not datos_validos:
            merged = {}
            for item in reglas:
                if isinstance(item, dict): merged.update(item)
            reglas = merged # Pasar al bloque de dict
        else:
            # Construir Tabla Matriz con Scroll Horizontal
            html = """
            <div style='max-height: 200px; overflow: auto; border: 1px solid #eee; border-radius: 8px; background: white;'>
                <table style='width:100%; border-collapse: collapse; font-family: sans-serif; font-size: 11px; white-space: nowrap;'>
                    <thead>
                        <tr style='background-color: #2b3137; color: white;'>
                            <th style='padding: 6px; position: sticky; top: 0; left: 0; z-index: 2; background-color: #2b3137; border-right: 1px solid #555;'>Param</th>
            """
            # Cabeceras 1..12
            for m in range(1, 13):
                html += f"<th style='padding: 4px 8px; text-align:center; position: sticky; top: 0; z-index: 1; background-color: #2b3137;color: white;'>{m}</th>"
            
            html += "</tr></thead><tbody>"
            
            # Filas por Parámetro
            for i, param in enumerate(sorted(list(all_params))):
                bg = "#f9f9f9" if i % 2 == 0 else "#ffffff"
                
                # Icono
                icon = "🔹"
                p_lower = param.lower()
                if "temp" in p_lower: icon = "🌡️"
                elif "humedad" in p_lower: icon = "💧"
                elif "precip" in p_lower: icon = "🌧️"
                elif "suelo" in p_lower: icon = "🌱"
                elif "alt" in p_lower or "elev" in p_lower: icon = "⛰️"
                elif "viento" in p_lower: icon = "💨"
                
                html += f"""
                <tr style='background-color: {bg}; border-bottom: 1px solid #eee;'>
                    <td style='padding: 5px 8px; font-weight: bold; position: sticky; left: 0; background-color: {bg}; z-index: 1; border-right: 1px solid #ddd;'>
                        {icon} {param.capitalize()}
                    </td>
                """
                
                # Celdas Mes 1..12
                for m in range(1, 13):
                    val_obj = datos_por_mes[m].get(param)
                    val_str = "-"
                    
                    if isinstance(val_obj, dict):
                        if 'min' in val_obj and 'max' in val_obj:
                            val_str = f"{val_obj['min']}-{val_obj['max']}"
                        else:
                            val_str = "..."
                    elif val_obj is not None:
                        val_str = str(val_obj)
                        
                    html += f"<td style='padding: 4px; text-align: center; color: #444;'>{val_str}</td>"
                
                html += "</tr>"
            
            html += "</tbody></table></div>"
            return html
# """ 
#     # ==========================================
#     # CASO B: DICCIONARIO SIMPLE (Resumen)
#     # ==========================================

#     if isinstance(reglas, dict):

#         html = """
#         <div style='max-height: 200px; overflow-y: auto; border: 1px solid #eee; border-radius: 8px; background: white;'>
#             <table style='width:100%; border-collapse: collapse; font-family: sans-serif; font-size: 12px;'>
#                 <thead>
#                     <tr style='background-color: #2b3137; color: white; text-align: left;'>
#                         <th style='padding: 6px 10px; position: sticky; top: 0;'>Parámetro</th>
#                         <th style='padding: 6px 10px; position: sticky; top: 0;'>Valor</th>
#                     </tr>
#                 </thead>
#                 <tbody>
#         """
#         for i, (k, v) in enumerate(reglas.items()):
#             if k == 'mes': continue 
#             bg_color = "#f9f9f9" if i % 2 == 0 else "#ffffff"
            
#             val_str = str(v)
#             if isinstance(v, dict) and 'min' in v and 'max' in v:
#                 val_str = f"<span style='color:#d9534f;'>{v['min']}</span> - <span style='color:#5cb85c;'>{v['max']}</span>"
            
#             icon = "🔹"
#             k_l = k.lower()
#             if "temp" in k_l: icon = "🌡️"
#             elif "humedad" in k_l: icon = "💧"
#             elif "precip" in k_l: icon = "🌧️"
#             elif "suelo" in k_l: icon = "🌱"
            
#             html += f"""
#                 <tr style='background-color: {bg_color}; border-bottom: 1px solid #eee;'>
#                     <td style='padding: 6px 10px; font-weight: 500;'>{icon} {k.capitalize()}</td>
#                     <td style='padding: 6px 10px; color: #444;'>{val_str}</td>
#                 </tr>
#             """
#         html += "</tbody></table></div>"
#         return html """

    return f"<div>{str(reglas)}</div>"

# TOOLS 


@tool
def tool_analisis_referencias(criterios: List[dict], pais, departamento, ciudad: str):
    """
    Realiza un análisis espacial combinatorio.
    La referencia solo puede ser "rios"
    La condicion puede ser "cerca" o "lejos"
    La distancia la tiene que dar el usuario en metros. Si no la da, entonces no uses esta tool.

    Args:
        criterios: Lista de dicts. Ejemplo: 
                   [{"referencia": "rios", "condicion": "cerca", "distancia": 500}]
                   Valores válidos referencia: 'rios', 'carreteras', 'puntos_interes'.
                   Valores válidos condicion: 'cerca', 'lejos'.
                   Distancia en metros.
        ciudad: Nombre de la ciudad (ej: 'Canta').
        pais: Nombre del país (ej: 'Perú').
        departamento: Nombre del departamento o estado (ej: 'Lima').
    """
    print(f"🛠️ EJECUTANDO TOOL ANÁLISIS: {criterios} en {ciudad}")
    try:
        pais = bd.normalizar_texto(pais)

        resultado = ingesta_ref.analisis_postgis(pais, departamento, ciudad, criterios)
        return resultado
    except Exception as e:
        return f"Error en análisis: {str(e)}"
# """
#         # Formateamos un resumen texto para el LLM
#         num_celdas = len(resultado['celdas_filtradas'])
#         logs = "\n".join(resultado['logs'])
        
#         msg = f"Análisis completado.\nLogs de Ingesta: {logs}\nSe encontraron {num_celdas} celdas que cumplen TODOS los criterios."
        
#         # RETORNAMOS UN OBJETO RICO (Texto + Datos Ocultos)
#         return {
#             "mensaje": msg, 
#             "datos_celdas": resultado['celdas_filtradas'],
#             "datos_ref": resultado['referencias_mapa']
#         }

# """

    

# --- NODOS (AGENTES) ---

def agente_supervisor(state: AgentState):
    print('--- Nodo Supervisor Ejecutado ---')
    ultimo_activo = state.get("ultimo_agente", "")
    
    if ultimo_activo == "nodo_region": return {"siguiente_nodo": "nodo_region"}
    if ultimo_activo == "nodo_negocio": return {"siguiente_nodo": "nodo_negocio"}
    
    mensajes = [SystemMessage(content=prompts.PROMPT_SUPERVISOR)] + state['mensajes']
    respuesta = llm.invoke(mensajes)
    contenido = respuesta.content.strip()
    
    if "NEGOCIO" in contenido: return {"siguiente_nodo": "nodo_negocio"}
    else: return {"mensajes": [respuesta], "siguiente_nodo": "end"}

def agente_negocio(state: AgentState):
    print('--- Nodo Negocio Ejecutado ---')
    mensajes = [SystemMessage(content=prompts.PROMPT_NEGOCIO)] + state['mensajes']
    respuesta = llm.invoke(mensajes)
    contenido = respuesta.content

    if "##PASAR_A_AGENTE_REGION##" in contenido:
        contenido_limpio = contenido.replace("##PASAR_A_AGENTE_REGION##", "").strip()
        return {"mensajes": [AIMessage(content=contenido_limpio)], "siguiente_nodo": "nodo_region", "ultimo_agente": ""}
    else:
        return {"mensajes": [respuesta], "siguiente_nodo": "end", "ultimo_agente": "nodo_negocio"}

def agente_region(state: AgentState):
    print('--- Nodo Región Ejecutado ---')
    mensajes = [SystemMessage(content=prompts.PROMPT_REGION)] + state['mensajes']
    respuesta = llm.invoke(mensajes)
    contenido = respuesta.content

    if "##PASAR_A_AGENTE_CARACTERISTICAS##" in contenido:
        contenido_limpio = contenido.replace("##PASAR_A_AGENTE_CARACTERISTICAS##", "").strip()
        try:
            contenido_dict = json.loads(contenido_limpio)
            tabla_md = "\n\n" + funciones.diccionario_a_tabla_md(contenido_dict)
            resultado = "Se identificó la siguiente ubicación. Cargando mapa...: " + tabla_md

            pais = contenido_dict.get('pais', '')
            departamento = contenido_dict.get('departamento', '')
            ciudad = contenido_dict.get('ciudad', '')

            pais = bd.normalizar_texto(pais)
            #departamento = bd.normalizar_texto(departamento)
            #ciudad = bd.normalizar_texto(ciudad)

            if not existe_region(pais, departamento, ciudad):
                print ("⚠️ Región no existe en BD, iniciando ingesta...")
                ingestar(pais, departamento, ciudad)       
        except json.JSONDecodeError:
            tabla_md = contenido_limpio
            contenido_dict = {}
            resultado = contenido_limpio
            print ("⚠️ Error al cargar la Región de la BD...")
        return {
            "mensajes": [AIMessage(content=resultado)], 
            "siguiente_nodo": "nodo_caracteristicas",
            "ultimo_agente": "",
            "pais": contenido_dict.get('pais', ''),
            "departamento": contenido_dict.get('departamento', ''),
            "ciudad": contenido_dict.get('ciudad', '')
        }
    
    else:
        return {"mensajes": [respuesta], "siguiente_nodo": "end", "ultimo_agente": "nodo_region"}
    

def agente_carateristicas(state: AgentState):
    print('--- Nodo Características Ejecutado ---')
    mensajes = [SystemMessage(content=prompts.PROMPT_CARACTERISTICAS)] + state['mensajes']
    respuesta = llm.invoke(mensajes)
    contenido = respuesta.content

    if "##PASAR_A_AGENTE_GEOCLIMATICO##" in contenido:
        contenido_limpio = contenido.replace("##PASAR_A_AGENTE_GEOCLIMATICO##", "").strip()
        try:
            json_str = contenido_limpio.replace("```json", "").replace("```", "").strip()
            if "{" in json_str or "[" in json_str:
                contenido_dict = json_str 
            else:
                contenido_dict = json_str
        except:
            contenido_dict = contenido_limpio
        
        return {
            "mensajes": [AIMessage(content="Analizando requerimientos del cultivo...")],
            "siguiente_nodo": "nodo_geoclimatico",
            "ultimo_agente": "",
            "caracteristicas_geoclimaticas": contenido_dict
        }
    else:
        return {"mensajes": [respuesta], "siguiente_nodo": "end", "ultimo_agente": "nodo_caracteristicas"}


def agente_geoclimatico(state: AgentState):
    import pandas as pd
    import json

    print('--- Nodo Geoclimatico Ejecutado ---')
    
    # 1. RECUPERAR REGLAS
    raw_rules = state.get("caracteristicas_geoclimaticas", "[]")
    reglas_terreno = {}

    try:
        if isinstance(raw_rules, str):
            texto = raw_rules.replace("```json", "").replace("```", "").strip()
            idx_inicio = texto.find("[")
            idx_fin = texto.rfind("]")
            
            if idx_inicio != -1 and idx_fin != -1:
                json_str = texto[idx_inicio : idx_fin + 1]
                lista_datos = json.loads(json_str)
            else:
                lista_datos = []
        elif isinstance(raw_rules, list):
            lista_datos = raw_rules
        else:
            lista_datos = []

        for item in lista_datos:
            if isinstance(item, dict):
                reglas_terreno.update(item)

    except Exception as e:
        print(f"⚠️ Error reglas: {e}")
        reglas_terreno = {}

    print(f"📋 Reglas aplicadas: {reglas_terreno}")

    # 2. TRAER DATOS
    pais = state.get("pais", "")
    departamento = state.get("departamento", "")
    ciudad = state.get("ciudad", "")
    print(f"🕵️ Buscando datos para: {ciudad}...")
    
    data = bd.obtener_datos_celda(conexion, pais, departamento, ciudad, limit=10000)

    if data.empty:
        return {
            "mensajes": [AIMessage(content=f"No hay datos para {ciudad}.")],
            "siguiente_nodo": "end",
            "resultados_evaluacion": []
        }

    # 3. EVALUACIÓN
    try:
        df_evaluado = funciones.evaluar_idoneidad_terreno(data.copy(), reglas_terreno)
    except Exception as e:
        print(f"❌ Error evaluación: {e}")
        return {
            "mensajes": [AIMessage(content="Error técnico en evaluación.")],
            "siguiente_nodo": "end",
            "resultados_evaluacion": []
        }
    
    # 4. REPORTE
    texto_top_ranking = funciones.generar_reporte_top_celdas(df_evaluado, top_n=5)
    
    # 5. LLM
    prompt_narrativo = f"""
    Actúa como Ingeniero experto.
    CONTEXTO: Evaluación de {len(df_evaluado)} sectores en {ciudad}.

    HERRAMIENTAS: 'tool_analisis_referencias'.
    
    TAREA:
    SI el usuario pregunta por cercanía a ríos, carreteras o puntos de interés:
    1. Usa la herramienta 'tool_analisis_referencias' solo cuando pida distancias a alguna referencia  y explica qué celdas cumplen la condición de referencias.
    2. Genera los criterios adecuados (ej: "cerca" 500m, "lejos" 1000m).
    3. Como "referencia" solo puedes usar "rios".
    4. Como "condicion" solo puedes usar "cerca" o "lejos".
    5. La "distancia" debe ser en metros y debe ser proporcionada por el usuario.
    
    Si no pregunta por infraestructura, haz tu evaluación agrónoma normal basada en clima.
    Finalmente indica cuántas celdas cumplen los criterios.

    {texto_top_ranking}
    """

    
    mensajes_para_llm = state['mensajes'] + [SystemMessage(content=prompt_narrativo)]
    # NUEVO
    llm_con_tools = llm.bind_tools([tool_analisis_referencias])
    respuesta_llm = llm_con_tools.invoke(mensajes_para_llm)

    # ==============================================================================
    # Invocar al Tool
    # ==============================================================================
    if respuesta_llm.tool_calls:
        
        # 1. Capturamos los argumentos que generó el LLM
        call = respuesta_llm.tool_calls[0]
        args = call['args']
        resultado_tool = tool_analisis_referencias.invoke(args)
        
        # 3. Procesamos el resultado para actualizar el mapa
        if isinstance(resultado_tool, dict):
            celdas_filtradas = resultado_tool.get('celdas_filtradas', [])
            nuevas_capas = resultado_tool.get('referencias_mapa', [])

            ids_permitidos = [c.get('id_celda') for c in celdas_filtradas if c.get('id_celda')]
            df_filtrado_final = df_evaluado[df_evaluado['id_celda'].isin(ids_permitidos)]
            datos_para_mapa = df_filtrado_final.to_dict(orient='records')

#            logs = resultado_tool.get('logs', [])
            
#            msg_texto = f"*** Análisis espacial: Se encontraron **{len(nuevas_celdas)} sectores** cerca de {args.get('criterios', 'lo solicitado')}."
            msg_texto = respuesta_llm.content 


            # RETORNAMOS EL ESTADO ACTUALIZADO CON LOS NUEVOS DATOS
            return {
                "mensajes": [AIMessage(content=msg_texto)],
                "siguiente_nodo": "end",
                "ultimo_agente": "nodo_geoclimatico",
                "resultados_evaluacion": datos_para_mapa, # <--- MAPA FILTRADO
                "capas_referencia": nuevas_capas        # <--- RIOS PINTADOS
            }
        

    datos_para_mapa = df_evaluado.to_dict(orient='records')
    
    return {
        "mensajes": [respuesta_llm],
        "siguiente_nodo": "end",
        "ultimo_agente": "nodo_geoclimatico",
        "resultados_evaluacion": datos_para_mapa
    }

# --- 5. GRAFO ---
def create_workflow():
    workflow = StateGraph(AgentState)

    workflow.add_node("nodo_supervisor", agente_supervisor)
    workflow.add_node("nodo_negocio", agente_negocio)
    workflow.add_node("nodo_region", agente_region)
    workflow.add_node("nodo_caracteristicas", agente_carateristicas)
    workflow.add_node("nodo_geoclimatico", agente_geoclimatico)

    workflow.add_edge(START, "nodo_supervisor")

    def route_supervisor(state: AgentState):
        if state["siguiente_nodo"] in ("nodo_negocio", "nodo_region", "nodo_caracteristicas", "nodo_geoclimatico"):
            return state["siguiente_nodo"]
        return END    
    
    workflow.add_conditional_edges("nodo_supervisor", route_supervisor, 
        {"nodo_negocio": "nodo_negocio", "nodo_region": "nodo_region", "nodo_caracteristicas": "nodo_caracteristicas", "nodo_geoclimatico": "nodo_geoclimatico", END: END})
    workflow.add_conditional_edges("nodo_negocio", lambda x: "nodo_region" if x["siguiente_nodo"] == "nodo_region" else END, {"nodo_region": "nodo_region", END: END})
    workflow.add_conditional_edges("nodo_region", lambda x: "nodo_caracteristicas" if x["siguiente_nodo"] == "nodo_caracteristicas" else END, {"nodo_caracteristicas": "nodo_caracteristicas", END: END})
    workflow.add_conditional_edges("nodo_caracteristicas", lambda x: "nodo_geoclimatico" if x["siguiente_nodo"] == "nodo_geoclimatico" else END, {"nodo_geoclimatico": "nodo_geoclimatico", END: END})

    workflow.add_edge("nodo_geoclimatico", END)

    memory = MemorySaver()
    return workflow.compile(checkpointer=memory)




app_graph = create_workflow()

# --- 6. LOGICA CHAT Y DATOS ---

def logica_chat(mensaje, history, session_id):
    config = {"configurable": {"thread_id": session_id} }
    inputs = {"mensajes": [HumanMessage(content=mensaje)]}
    
    texto_acumulado = ""
    datos_mapa_final = None
    html_esperada = None # Variable para el HTML
    info_actual = None
    
    capas_visuales = [] # Inicializar

    try:
        for chunk in app_graph.stream(inputs, config=config, stream_mode="updates"):
            
            for nombre_nodo, valores in chunk.items():
                
                # A) REGLAS -> CONVERTIR A HTML
                if "caracteristicas_geoclimaticas" in valores:
                    raw = valores["caracteristicas_geoclimaticas"]
                    info_dict = {}
                    if isinstance(raw, str):
                        try:
                            clean = raw.replace("```json", "").replace("```", "").strip()
                            if "[" in clean:
                                info_dict = json.loads(clean[clean.find("["):clean.rfind("]")+1])
                            elif "{" in clean:
                                info_dict = json.loads(clean[clean.find("{"):clean.rfind("}")+1])
                            else:
                                info_dict = {"Info": raw}
                        except:
                            info_dict = {"Info": raw}
                    else:
                        info_dict = raw
                    
                    # Convertimos a HTML aquí mismo
                    html_esperada = formatear_reglas_html(info_dict)

                # B) RESULTADOS (CONDICIONES ACTUALES)
                if "resultados_evaluacion" in valores and valores["resultados_evaluacion"]:
                    datos_mapa_final = valores["resultados_evaluacion"]
                    top_5 = datos_mapa_final[:5]
                    info_actual = []
                    for d in top_5:
                        info_actual.append({
                            "ID": d.get("id", "?"),
                            "Score": d.get("score", 0),
                            "Temp": f"{d.get('temp_promedio',0):.1f}",
                            "Diagnostico": d.get("explicacion", "")[:60] + "..."
                        })

                # C) CHAT
                if "mensajes" in valores:
                    mensajes_nuevos = valores["mensajes"]
                    for msg in mensajes_nuevos:
                        if isinstance(msg, AIMessage) and msg.content:
                            if nombre_nodo == "nodo_caracteristicas": continue
                            bloque_nuevo = f"\n\n{msg.content}"
                            texto_acumulado += bloque_nuevo
                
                if "capas_referencia" in valores:
                    capas_visuales = valores["capas_referencia"]

                yield texto_acumulado, datos_mapa_final, html_esperada, info_actual, capas_visuales

    except Exception as e:
        yield f"❌ Error: {str(e)}", None, None, None, []

def interaccion_usuario(mensaje, history):
    if not mensaje: return "", history
    if history is None: history = []
    history.append({"role": "user", "content": mensaje})
    return "", history

def interaccion_bot(history, state_datos, session_id):
    if not history: yield [], None, None, None; return

    try:
        ultimo_mensaje = history[-1].get("content", "")
    except (IndexError, AttributeError):
        yield history, gr.update(), gr.update(), gr.update(), state_datos
        return
    
    history.append({"role": "assistant", "content": ""})
    
    try:
        # Recibimos html_esp en lugar de dict_esp
        for resp_txt, datos_mapa, html_esp, info_act, capas_extra in logica_chat(ultimo_mensaje, history[:-1], session_id):
            
            history[-1]["content"] = resp_txt
            
            update_mapa = gr.update()
            if datos_mapa or capas_extra:
                html_mapa = funciones.generar_mapa_resultados(datos_mapa if datos_mapa else [], 
                    capas_extra=capas_extra)
                update_mapa = gr.HTML(value=html_mapa)
            
            # Actualizamos el HTML de esperadas
            update_esp = gr.HTML(value=html_esp, visible=True) if html_esp else gr.update()
                        
            yield history, update_mapa, update_esp #, update_act
                
    except Exception as e:
        history[-1]["content"] = f"❌ Error: {str(e)}"
        yield history, gr.update(), gr.update(), gr.update()

# --- 7. GEE MAPA BASE ---
import geemap.foliumap as geemap
import ee


# gee_project = os.getenv("GEE_PROJECT", "")
# _ee_initialized = False

# def gee_inicializar():
#     global _ee_initialized
#     if _ee_initialized: return
#     try:
#         ee.Initialize(project=gee_project)
#         _ee_initialized = True
#     except:
#         try:
#             ee.Authenticate()
#             ee.Initialize(project=gee_project)
#             _ee_initialized = True
#         except: pass

# gee_inicializar()


def generar_mapa_html():
    """
    Genera el mapa base inicial usando Folium y Esri Satellite 
    para que sea IDÉNTICO al mapa de resultados.
    """
    try:
        # 1. Crear mapa centrado en Perú (Mismo zoom y centro que funciones.py)
        m = folium.Map(
            location=[-12.0464, -77.0428], 
            zoom_start=6,
            tiles='Esri.WorldImagery' # <--- CLAVE: El mismo fondo satelital
        )
        
        # 2. Agregar etiquetas (Fronteras y Nombres)
        # Esto hace que el mapa satelital tenga nombres de ciudades encima
        folium.TileLayer(
            tiles='https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',
            attr='Esri',
            name='Etiquetas',
            overlay=True
        ).add_to(m)

        # 3. Control de Capas
        folium.LayerControl().add_to(m)

        # 4. Retornar HTML (Sin iframes extraños, directo de Folium)
        return m._repr_html_()
        
    except Exception as e:
        return f"<div style='padding:20px; color:red;'>Error cargando mapa base: {str(e)}</div>"

# --- 8. INTERFAZ GRÁFICA ---

with gr.Blocks(title="Geo-Agente") as interfaz:
    
    mensaje_inicial = [{"role": "assistant", "content": "Hola, soy tu asesor Geo-Climático. Dime ¿qué actividad estás interesado en emprender?"}]
    
    gr.Markdown("## 🌍 Sistema Geoespacial Inteligente")

    session_id = gr.State(lambda: str(uuid.uuid4()))
    estado_datos = gr.State([])
    
    with gr.Row():
        # --- COLUMNA 1: MAPA (40%) ---
        with gr.Column(scale=4, min_width=400):
            gr.Markdown("### 🗺️ Visualización Geográfica")
            mapa_view = gr.HTML(value=generar_mapa_html())

        # --- COLUMNA 2: CARACTERÍSTICAS (30%) ---
        with gr.Column(scale=3, min_width=300):
            gr.Markdown("### 📊 Características")
            
            # FILA SUPERIOR: Condiciones Esperadas (HTML Tabla)
            with gr.Group():
                gr.Markdown("**Condiciones Esperadas (Reglas):**")
                # CAMBIO IMPORTANTE: gr.HTML en vez de gr.JSON
                view_esperadas = gr.HTML(label="Reglas del Cultivo")

            # FILA INFERIOR: Condiciones Actuales (JSON Top 5)
            #with gr.Group():
                #gr.Markdown("**Condiciones Actuales (Top Resultados):**")
                #view_actuales = gr.JSON(label="Datos Detectados", value={}, max_height=500, visible=False)

        # --- COLUMNA 3: CHAT (30%) ---
        with gr.Column(scale=3, min_width=300):
            gr.Markdown("### 💬 Asistente IA")
            
            chatbot = gr.Chatbot(value=mensaje_inicial, height=550, label="Chat")
            msg = gr.Textbox(placeholder="Escribe tu consulta...", container=False)
            
            with gr.Row():
                submit_btn = gr.Button("Enviar", variant="primary")
                clear_btn = gr.Button("Limpiar")

    # --- EVENTOS ---
    lista_outputs = [chatbot, mapa_view, view_esperadas]  # Retirado view_actuales

    msg.submit(
        interaccion_usuario, [msg, chatbot], [msg, chatbot], queue=False
    ).then(
        interaccion_bot, [chatbot, estado_datos, session_id], lista_outputs
    )

    submit_btn.click(
        interaccion_usuario, [msg, chatbot], [msg, chatbot], queue=False
    ).then(
        interaccion_bot, [chatbot, estado_datos, session_id], lista_outputs
    )
    
    def limpiar_todo():
        nuevo_id = str(uuid.uuid4())
        return mensaje_inicial, generar_mapa_html(), None, nuevo_id
    
    
    clear_btn.click(limpiar_todo, None, lista_outputs + [session_id], queue=False)


if __name__ == "__main__":
    interfaz.launch(css=".gradio-container {max_width: 98% !important}")