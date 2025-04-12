# app.py
from flask import Flask, render_template, request, jsonify, redirect, url_for
import os
import time
import threading
from werkzeug.serving import run_simple
from dotenv import load_dotenv
import logging
import json

# Importar el módulo de automatización de noticias
from news_automation import generate_news_report, search_news, create_notion_page, format_api_token

# Configuración de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Cargar variables de entorno
load_dotenv()

app = Flask(__name__)

# Variable global para almacenar el estado de las tareas
task_status = {}

@app.route('/')
def index():
    """Página principal con formulario para generar informes"""
    return render_template('index.html')

@app.route('/generate', methods=['POST'])
def generate():
    """Endpoint para generar un informe de noticias"""
    # Obtener parámetros del formulario
    topic = request.form.get('topic', '')
    max_results = request.form.get('max_results', 10)

    try:
        max_results = int(max_results)
    except ValueError:
        max_results = 10

    if not topic:
        return jsonify({'status': 'error', 'message': 'Se requiere un tema de búsqueda'})

    # Crear un ID único para esta tarea
    task_id = f"task_{int(time.time())}"
    task_status[task_id] = {
        'status': 'running',
        'topic': topic,
        'max_results': max_results,
        'message': 'Iniciando búsqueda de noticias...',
        'page_url': None
    }

    # Iniciar la generación en un hilo separado
    thread = threading.Thread(target=process_report_generation, args=(task_id, topic, max_results))
    thread.daemon = True
    thread.start()

    return jsonify({'status': 'started', 'task_id': task_id})

def process_report_generation(task_id, topic, max_results):
    """Procesa la generación del informe en segundo plano"""
    try:
        # Actualizar estado
        task_status[task_id]['message'] = 'Buscando noticias...'

        # Buscar noticias
        articles = search_news(topic, max_results=max_results)

        if not articles:
            task_status[task_id]['status'] = 'warning'
            task_status[task_id]['message'] = f"No se encontraron noticias sobre '{topic}'"
        else:
            task_status[task_id]['message'] = f"Se encontraron {len(articles)} artículos. Creando página en Notion..."

        # Crear página en Notion
        page_url = create_notion_page(topic, articles)

        if not page_url:
            task_status[task_id]['status'] = 'error'
            task_status[task_id]['message'] = 'Error al crear la página en Notion'
        else:
            task_status[task_id]['status'] = 'completed'
            task_status[task_id]['message'] = 'Informe generado con éxito'
            task_status[task_id]['page_url'] = page_url

    except Exception as e:
        task_status[task_id]['status'] = 'error'
        task_status[task_id]['message'] = f"Error: {str(e)}"
        logger.error(f"Error en generación de informe: {str(e)}")

@app.route('/status/<task_id>')
def task_status_check(task_id):
    """Endpoint para verificar el estado de una tarea"""
    if task_id in task_status:
        return jsonify(task_status[task_id])
    else:
        return jsonify({'status': 'error', 'message': 'Tarea no encontrada'})

@app.route('/embed')
def embed():
    """Versión simplificada para incrustar en Notion"""
    return render_template('embed.html')

@app.route('/mini')
def mini():
    """Versión mínima para botones en Notion"""
    return render_template('mini.html')

@app.route('/config')
def config():
    """Página de configuración"""
    # Verificar si los tokens están configurados
    notion_token = os.getenv("NOTION_TOKEN", "")
    notion_db_id = os.getenv("NOTION_DATABASE_ID", "")
    news_api_key = os.getenv("NEWS_API_KEY", "")

    # Si están vacíos, mostrar mensaje de configuración pendiente
    tokens_configured = bool(notion_token and notion_db_id and news_api_key)

    return render_template('config.html',
                          tokens_configured=tokens_configured,
                          notion_db_id=notion_db_id)

@app.route('/save_config', methods=['POST'])
def save_config():
    """Guardar configuración en .env"""
    try:
        notion_token = request.form.get('notion_token', '')
        notion_db_id = request.form.get('notion_db_id', '')
        news_api_key = request.form.get('news_api_key', '')

        # Formatear tokens
        notion_token = format_api_token(notion_token, 'notion_token')
        notion_db_id = format_api_token(notion_db_id, 'notion_db')
        news_api_key = format_api_token(news_api_key, 'newsapi')

        # Leer el archivo .env actual (si existe)
        env_content = ""
        if os.path.exists('.env'):
            with open('.env', 'r') as file:
                env_content = file.read()

        # Función para actualizar una variable en el contenido
        def update_env_var(content, var_name, var_value):
            if f"{var_name}=" in content:
                # La variable ya existe, actualizarla
                lines = content.split('\n')
                for i, line in enumerate(lines):
                    if line.startswith(f"{var_name}="):
                        lines[i] = f"{var_name}={var_value}"
                return '\n'.join(lines)
            else:
                # La variable no existe, añadirla
                return content + f"\n{var_name}={var_value}"

        # Actualizar variables
        if notion_token:
            env_content = update_env_var(env_content, "NOTION_TOKEN", notion_token)
        if notion_db_id:
            env_content = update_env_var(env_content, "NOTION_DATABASE_ID", notion_db_id)
        if news_api_key:
            env_content = update_env_var(env_content, "NEWS_API_KEY", news_api_key)

        # Guardar el archivo .env actualizado
        with open('.env', 'w') as file:
            file.write(env_content.strip())

        # Recargar variables de entorno
        load_dotenv()

        return jsonify({'status': 'success', 'message': 'Configuración guardada correctamente'})

    except Exception as e:
        logger.error(f"Error al guardar configuración: {str(e)}")
        return jsonify({'status': 'error', 'message': f"Error: {str(e)}"})

def run_app(host='0.0.0.0', port=5000):
    """Ejecuta la aplicación Flask"""
    run_simple(host, port, app, use_reloader=True, use_debugger=True)

if __name__ == '__main__':
    # Crear un hilo para la aplicación web
    app_thread = threading.Thread(target=run_app)
    app_thread.daemon = True
    app_thread.start()

    print(f"Aplicación web iniciada en http://127.0.0.1:5000")

    # Mantener el proceso principal vivo
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Aplicación detenida")
