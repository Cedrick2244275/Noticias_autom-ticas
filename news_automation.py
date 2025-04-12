# news_automation.py
import os
import requests
import json
import datetime
import time
import schedule
import argparse
import logging
from dotenv import load_dotenv
from newsapi import NewsApiClient
from notion_client import Client
import hashlib
import openai  # Para resúmenes con IA
import threading
import random

# Configuración de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def format_api_token(token, token_type):
    """
    Formatea un token de API según su tipo.

    Args:
        token (str): Token sin formato
        token_type (str): Tipo de token ('notion_db', 'notion_token', 'newsapi')

    Returns:
        str: Token formateado correctamente
    """
    if not token:
        logger.error(f"Token {token_type} no encontrado o vacío")
        return token

    # Limpiar el token de espacios en blanco
    clean_token = token.strip()

    if token_type == 'notion_db':
        # Formatear ID de base de datos de Notion
        # Eliminar guiones si ya están presentes
        clean_id = clean_token.replace("-", "")

        # Si la longitud no es 32, no es un ID válido
        if len(clean_id) != 32:
            logger.warning(f"El ID de base de datos '{clean_token}' no tiene 32 caracteres.")
            return clean_token

        # Insertar guiones en las posiciones correctas
        formatted_id = f"{clean_id[0:8]}-{clean_id[8:12]}-{clean_id[12:16]}-{clean_id[16:20]}-{clean_id[20:]}"
        logger.info(f"ID de base de datos formateado: {formatted_id}")
        return formatted_id

    elif token_type == 'newsapi':
        # Los tokens de NewsAPI suelen ser alfanuméricos sin formato especial
        # Solo verificamos que no sea demasiado corto
        if len(clean_token) < 10:
            logger.warning(f"El token de NewsAPI parece ser demasiado corto.")
        return clean_token

    elif token_type == 'notion_token':
        # Los tokens de Notion deben comenzar con 'secret_'
        if not clean_token.startswith('secret_'):
            logger.warning(f"El token de Notion debería comenzar con 'secret_'")
            # No modificamos el token aquí, solo advertimos
        return clean_token

    # Para otros tipos de token, devolver sin cambios
    return clean_token

# Cargar variables de entorno con formateo automático
load_dotenv()

# Configuración de Notion API
notion_token = format_api_token(os.getenv("NOTION_TOKEN"), 'notion_token')
notion_db_id = format_api_token(os.getenv("NOTION_DATABASE_ID"), 'notion_db')
NOTION_TOKEN = notion_token
NOTION_DATABASE_ID = notion_db_id
notion = Client(auth=NOTION_TOKEN)

# Configuración de NewsAPI
NEWS_API_KEY = format_api_token(os.getenv("NEWS_API_KEY"), 'newsapi')
newsapi = NewsApiClient(api_key=NEWS_API_KEY)

# Configuración de OpenAI (opcional, para resúmenes)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
if OPENAI_API_KEY:
    openai.api_key = OPENAI_API_KEY

def search_news(topic, language='es', max_results=10):
    """
    Busca noticias sobre un tema específico.

    Args:
        topic (str): Tema de búsqueda
        language (str): Idioma de las noticias (por defecto 'es' para español)
        max_results (int): Número máximo de resultados a devolver

    Returns:
        list: Lista de artículos de noticias
    """
    try:
        # Validar y convertir max_results a entero
        try:
            max_results = int(max_results)
        except (ValueError, TypeError):
            max_results = 10

        # Limitar max_results entre 5 y 100 (evitar abusar de la API)
        max_results = max(5, min(100, max_results))

        # Calcular fecha para la búsqueda (últimos 7 días)
        end_date = datetime.datetime.now().date()
        start_date = end_date - datetime.timedelta(days=7)

        # Imprimir los parámetros de búsqueda para depuración
        logger.info(f"Buscando noticias desde {start_date.isoformat()} hasta {end_date.isoformat()}")
        logger.info(f"Máximo de resultados solicitados: {max_results}")

        # ESTRATEGIA 1: Búsqueda con rango de fechas
        news_response = newsapi.get_everything(
            q=topic,
            language=language,
            from_param=start_date.isoformat(),
            to=end_date.isoformat(),
            sort_by='publishedAt',  # Ordenar por fecha de publicación
            page_size=max_results
        )

        # Si no hay resultados, intentar con una búsqueda más amplia
        if len(news_response['articles']) == 0:
            logger.info("No se encontraron resultados recientes. Ampliando búsqueda...")
            # ESTRATEGIA 2: Búsqueda sin restricción de fechas
            news_response = newsapi.get_everything(
                q=topic,
                language=language,
                sort_by='publishedAt',
                page_size=max_results
            )

        # Otra alternativa: buscar en los titulares principales
        if len(news_response['articles']) == 0:
            logger.info("Intentando con búsqueda de titulares principales...")
            # ESTRATEGIA 3: Buscar en titulares
            news_response = newsapi.get_top_headlines(
                q=topic,
                language=language,
                page_size=max_results
            )

        # Procesar cada artículo para añadir información adicional
        for article in news_response['articles']:
            # Generar un ID único para el artículo (útil para caché y referencia)
            article_id = hashlib.md5(f"{article.get('url', '')}{article.get('title', '')}".encode()).hexdigest()
            article['article_id'] = article_id

            # Añadir la imagen del artículo si existe
            if 'urlToImage' in article and article['urlToImage']:
                article['image_url'] = article['urlToImage']

            # Formatear la fecha
            if 'publishedAt' in article and article['publishedAt']:
                try:
                    date_obj = datetime.datetime.fromisoformat(article['publishedAt'].replace('Z', '+00:00'))
                    article['formatted_date'] = date_obj.strftime('%d-%m-%Y %H:%M')
                except:
                    article['formatted_date'] = article['publishedAt']

        logger.info(f"Se encontraron {len(news_response['articles'])} artículos sobre '{topic}'")

        # Aplicar límite de resultados
        return news_response['articles'][:max_results]

    except Exception as e:
        logger.error(f"Error al buscar noticias: {str(e)}")
        return []

def generate_ai_summary(text, max_length=250):
    """
    Genera un resumen de texto utilizando IA (OpenAI).

    Args:
        text (str): Texto a resumir
        max_length (int): Longitud máxima aproximada del resumen

    Returns:
        str: Resumen generado por IA
    """
    if not OPENAI_API_KEY or not text:
        return None

    try:
        response = openai.Completion.create(
            engine="text-davinci-003",  # Motor de OpenAI
            prompt=f"Resume el siguiente texto en español en aproximadamente {max_length} caracteres:\n\n{text}",
            max_tokens=150,  # Ajustar según necesidades
            temperature=0.3,  # Menor temperatura para resúmenes más precisos
            top_p=1.0
        )
        summary = response.choices[0].text.strip()
        return summary
    except Exception as e:
        logger.warning(f"Error al generar resumen con IA: {str(e)}")
        return None

def get_article_details(url):
    """
    Obtiene detalles adicionales de un artículo mediante web scraping básico.

    Args:
        url (str): URL del artículo

    Returns:
        dict: Diccionario con detalles adicionales (imagen, texto completo, etc.)
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=5)

        # Si la solicitud fue exitosa
        if response.status_code == 200:
            # Aquí podríamos implementar un parser más sofisticado con BeautifulSoup
            # Por ahora, devolvemos datos básicos
            details = {
                'full_content': None,
                'main_image': None,
                'status': 'success'
            }

            # Buscar imágenes en las meta tags (muy básico)
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.text, 'html.parser')

            # Buscar imagen en meta tags
            og_image = soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                details['main_image'] = og_image.get('content')

            # Intentar extraer el contenido principal (muy básico, necesitaría mejorarse)
            main_content = soup.find('article') or soup.find('main') or soup.find('div', class_='content')
            if main_content:
                # Extraer texto sin etiquetas HTML
                details['full_content'] = main_content.get_text(separator='\n', strip=True)

            return details
        else:
            return {'status': 'error', 'message': f'Error HTTP {response.status_code}'}

    except Exception as e:
        logger.error(f"Error al obtener detalles del artículo {url}: {str(e)}")
        return {'status': 'error', 'message': str(e)}

def convert_articles_to_notion_blocks(articles, include_images=True, include_ai_summary=True):
    """
    Convierte los artículos de noticias directamente a bloques de Notion.

    Args:
        articles (list): Lista de artículos de noticias
        include_images (bool): Si se deben incluir imágenes en los bloques
        include_ai_summary (bool): Si se debe incluir un resumen generado por IA

    Returns:
        list: Lista de bloques de Notion
    """
    # Bloques iniciales (título y fecha)
    blocks = [
        {
            "object": "block",
            "type": "heading_1",
            "heading_1": {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {
                            "content": "Informe de Noticias"
                        }
                    }
                ]
            }
        },
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {
                            "content": f"Fecha: {datetime.datetime.now().strftime('%d-%m-%Y')}"
                        }
                    }
                ]
            }
        },
        {
            "object": "block",
            "type": "divider",
            "divider": {}
        }
    ]

    # Si no hay artículos, agregar un bloque informativo
    if not articles:
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {
                            "content": "No se encontraron noticias relevantes para el tema solicitado."
                        }
                    }
                ]
            }
        })
        return blocks

    # Agregar una introducción
    blocks.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [
                {
                    "type": "text",
                    "text": {
                        "content": f"Se encontraron {len(articles)} artículos relevantes sobre el tema solicitado:"
                    }
                }
            ]
        }
    })

    # Agregar cada artículo como un conjunto de bloques
    for i, article in enumerate(articles, 1):
        title = article.get('title', 'Sin título')
        description = article.get('description', 'Sin descripción disponible.')
        url = article.get('url', '#')
        source = article.get('source', {}).get('name', 'Fuente desconocida')
        published_at = article.get('formatted_date', article.get('publishedAt', 'Fecha desconocida'))
        image_url = article.get('image_url', article.get('urlToImage', None))

        # Agregar título del artículo
        blocks.append({
            "object": "block",
            "type": "heading_3",
            "heading_3": {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {
                            "content": f"{i}. {title}"
                        }
                    }
                ]
            }
        })

        # Agregar metadatos (fuente y fecha)
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {
                            "content": f"Fuente: {source} | Publicado: {published_at}"
                        },
                        "annotations": {
                            "bold": True,
                            "italic": True
                        }
                    }
                ]
            }
        })

        # Agregar imagen si está disponible y se solicita
        if include_images and image_url:
            blocks.append({
                "object": "block",
                "type": "image",
                "image": {
                    "type": "external",
                    "external": {
                        "url": image_url
                    }
                }
            })

        # Agregar descripción
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {
                            "content": description if description else "Sin descripción disponible."
                        }
                    }
                ]
            }
        })

        # Agregar resumen de IA si está disponible y se solicita
        if include_ai_summary and OPENAI_API_KEY and description:
            ai_summary = generate_ai_summary(description)
            if ai_summary:
                blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {
                                    "content": "Resumen IA: "
                                },
                                "annotations": {
                                    "bold": True,
                                    "color": "blue"
                                }
                            },
                            {
                                "type": "text",
                                "text": {
                                    "content": ai_summary
                                }
                            }
                        ]
                    }
                })

        # Agregar enlace al artículo completo
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {
                            "content": "Leer artículo completo",
                            "link": {
                                "url": url
                            }
                        },
                        "annotations": {
                            "bold": True,
                            "underline": True
                        }
                    }
                ]
            }
        })

        # Agregar separador entre artículos
        blocks.append({
            "object": "block",
            "type": "divider",
            "divider": {}
        })

    return blocks

def create_notion_page(topic, articles, include_images=True, include_ai_summary=False):
    """
    Crea una nueva página en Notion con el informe de noticias.

    Args:
        topic (str): Tema de búsqueda
        articles (list): Lista de artículos de noticias
        include_images (bool): Si se deben incluir imágenes en el informe
        include_ai_summary (bool): Si se debe incluir resumen generado por IA

    Returns:
        str: URL de la página creada
    """
    try:
        # Crear una nueva página en la base de datos de Notion
        today = datetime.datetime.now().strftime('%d-%m-%Y')

        # Convertir los artículos directamente a bloques de Notion
        blocks = convert_articles_to_notion_blocks(
            articles,
            include_images=include_images,
            include_ai_summary=include_ai_summary
        )

        # Propiedades básicas de la página
        new_page = notion.pages.create(
            parent={"database_id": NOTION_DATABASE_ID},
            properties={
                "title": {
                    "title": [
                        {
                            "text": {
                                "content": f"Informe de Noticias: {topic} - {today}"
                            }
                        }
                    ]
                },
                # Se pueden añadir más propiedades aquí según la estructura de la base de datos
            },
            children=blocks
        )

        page_id = new_page['id']
        page_url = f"https://notion.so/{page_id.replace('-', '')}"

        logger.info(f"Página creada en Notion: {page_url}")
        return page_url

    except Exception as e:
        logger.error(f"Error al crear página en Notion: {str(e)}")
        return None

def send_notification(page_url, topic, method='console'):
    """
    Envía una notificación sobre el informe generado.

    Args:
        page_url (str): URL de la página creada
        topic (str): Tema del informe
        method (str): Método de notificación ('console', 'email', 'slack')

    Returns:
        bool: True si la notificación se envió correctamente
    """
    message = f"Nuevo informe de noticias sobre '{topic}' disponible en {page_url}"

    if method == 'console':
        # Notificación básica por consola
        print(f"\n📰 ¡INFORME GENERADO! 📰\n{message}\n")
        return True

    elif method == 'email':
        # Aquí implementaríamos el envío por email (requiere configuración adicional)
        # Por ejemplo con smtplib
        try:
            # Esta es una implementación de ejemplo que habría que completar
            import smtplib
            from email.mime.text import MIMEText

            # Configuración del servidor SMTP (ejemplo con Gmail)
            smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
            smtp_port = int(os.getenv("SMTP_PORT", 587))
            smtp_user = os.getenv("SMTP_USER", "")
            smtp_password = os.getenv("SMTP_PASSWORD", "")
            recipient = os.getenv("NOTIFICATION_EMAIL", "")

            if not (smtp_user and smtp_password and recipient):
                logger.warning("Configuración de email incompleta, no se envió notificación")
                return False

            # Crear mensaje
            msg = MIMEText(f"""
            <html>
            <body>
                <h2>Nuevo Informe de Noticias</h2>
                <p>Se ha generado un nuevo informe sobre el tema: <strong>{topic}</strong></p>
                <p><a href="{page_url}" style="background-color:#4CAF50;color:white;padding:10px 15px;text-decoration:none;border-radius:4px;">
                    Ver Informe en Notion
                </a></p>
            </body>
            </html>
            """, 'html')

            msg['Subject'] = f"Nuevo Informe de Noticias: {topic}"
            msg['From'] = smtp_user
            msg['To'] = recipient

            # Enviar email
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_password)
                server.send_message(msg)

            logger.info(f"Notificación enviada por email a {recipient}")
            return True

        except Exception as e:
            logger.error(f"Error al enviar notificación por email: {str(e)}")
            return False

    elif method == 'slack':
        # Implementación para Slack (requiere webhook configurado)
        try:
            slack_webhook = os.getenv("SLACK_WEBHOOK", "")

            if not slack_webhook:
                logger.warning("Webhook de Slack no configurado, no se envió notificación")
                return False

            # Preparar payload para Slack
            payload = {
                "text": "📰 *Nuevo Informe de Noticias* 📰",
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Nuevo informe sobre:* {topic}"
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"Ver el informe completo en Notion:"
                        }
                    },
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {
                                    "type": "plain_text",
                                    "text": "Ver en Notion"
                                },
                                "url": page_url
                            }
                        ]
                    }
                ]
            }

            # Enviar a Slack
            response = requests.post(
                slack_webhook,
                data=json.dumps(payload),
                headers={'Content-Type': 'application/json'}
            )

            if response.status_code == 200:
                logger.info("Notificación enviada a Slack")
                return True
            else:
                logger.warning(f"Error al enviar a Slack: {response.status_code} {response.text}")
                return False

        except Exception as e:
            logger.error(f"Error al enviar notificación a Slack: {str(e)}")
            return False

    else:
        logger.warning(f"Método de notificación '{method}' no implementado")
        return False

def generate_news_report(topic, max_results=10, include_images=True, include_ai_summary=False, notification_method='console'):
    """
    Función principal que genera un informe completo de noticias y lo publica en Notion.

    Args:
        topic (str): Tema de búsqueda
        max_results (int): Número máximo de resultados a incluir
        include_images (bool): Si se deben incluir imágenes en el informe
        include_ai_summary (bool): Si se debe incluir resumen generado por IA
        notification_method (str): Método para enviar notificaciones

    Returns:
        dict: Diccionario con información del resultado
    """
    result = {
        'success': False,
        'message': '',
        'page_url': None,
        'articles_count': 0
    }

    try:
        logger.info(f"Generando informe de noticias sobre: {topic}")

        # Paso 1: Buscar noticias
        articles = search_news(topic, max_results=max_results)
        result['articles_count'] = len(articles)

        if not articles:
            logger.warning(f"No se encontraron noticias sobre '{topic}'")
            result['message'] = f"No se encontraron noticias sobre '{topic}'"
            # Continuamos de todos modos para crear un informe "vacío"

        # Paso 2: Crear página en Notion directamente con los artículos
        page_url = create_notion_page(
            topic,
            articles,
            include_images=include_images,
            include_ai_summary=include_ai_summary
        )

        if not page_url:
            logger.error("No se pudo crear la página en Notion")
            result['message'] = "Error al crear la página en Notion"
            return result

        result['page_url'] = page_url

        # Paso 3: Enviar notificación
        send_notification(page_url, topic, method=notification_method)

        logger.info(f"Informe completo generado con éxito para el tema: {topic}")
        result['success'] = True
        result['message'] = f"Informe generado exitosamente con {len(articles)} artículos"

        return result

    except Exception as e:
        logger.error(f"Error al generar informe de noticias: {str(e)}")
        result['message'] = f"Error: {str(e)}"
        return result

def setup_scheduled_task(topic, time_str, max_results=10, include_images=True, notification_method='console'):
    """
    Configura una tarea programada para ejecutarse diariamente a la hora especificada.

    Args:
        topic (str): Tema de búsqueda
        time_str (str): Hora en formato 'HH:MM'
        max_results (int): Número máximo de resultados
        include_images (bool): Si se deben incluir imágenes
        notification_method (str): Método de notificación
    """
    def scheduled_job():
        logger.info(f"Ejecutando tarea programada para el tema: {topic}")
        generate_news_report(
            topic,
            max_results=max_results,
            include_images=include_images,
            notification_method=notification_method
        )

    schedule.every().day.at(time_str).do(scheduled_job)
    logger.info(f"Tarea programada configurada para ejecutarse diariamente a las {time_str}")

def run_scheduler():
    """
    Ejecuta el bucle principal del programador de tareas.
    """
    logger.info("Iniciando programador de tareas...")
    while True:
        schedule.run_pending()
        time.sleep(60)  # Verificar cada minuto

def verify_database():
    """
    Verifica que la base de datos exista y sea accesible.
    """
    try:
        # Intentar recuperar la base de datos
        database = notion.databases.retrieve(database_id=NOTION_DATABASE_ID)
        print(f"Base de datos encontrada: {database.get('title', [{'plain_text': 'Sin título'}])[0].get('plain_text', 'Sin título')}")
        return True
    except Exception as e:
        print(f"Error al acceder a la base de datos: {str(e)}")
        return False

def manage_api_limits(func):
    """
    Decorador para manejar límites de API.

    Args:
        func: La función a decorar

    Returns:
        function: Función decorada
    """
    def wrapper(*args, **kwargs):
        # Si se está realizando muchas solicitudes, añadir un retraso
        # para evitar bloqueos por límite de tasa
        time.sleep(random.uniform(0.5, 1.5))

        try:
            return func(*args, **kwargs)
        except Exception as e:
            error_message = str(e).lower()

            # Comprobar si el error está relacionado con límites de API
            if "rate limit" in error_message or "too many requests" in error_message:
                logger.warning(f"Límite de API alcanzado, esperando antes de reintentar...")

                # Esperar un tiempo antes de reintentar
                time.sleep(5)

                # Reintentar una vez
                try:
                    return func(*args, **kwargs)
                except Exception as retry_error:
                    logger.error(f"Error después de reintentar: {str(retry_error)}")
                    raise
            else:
                # Si no es un error de límite de API, simplemente relanzarlo
                raise

    return wrapper

def install_as_service():
    """
    Genera los archivos necesarios para instalar la aplicación como un servicio.

    Returns:
        bool: True si se generaron los archivos correctamente
    """
    try:
        # Determinar el sistema operativo
        import platform
        system = platform.system()

        # Obtener la ruta absoluta del directorio actual
        current_dir = os.path.abspath(os.path.dirname(__file__))

        if system == "Linux":
            # Crear archivo de servicio systemd
            service_content = f"""[Unit]
Description=Automatización de Noticias para Notion
After=network.target

[Service]
Type=simple
User={os.getenv('USER')}
WorkingDirectory={current_dir}
ExecStart=/usr/bin/python3 {os.path.join(current_dir, 'app.py')}
Restart=on-failure
RestartSec=10
StandardOutput=syslog
StandardError=syslog
SyslogIdentifier=news_automation

[Install]
WantedBy=multi-user.target
"""
            # Guardar el archivo de servicio
            service_path = os.path.join(current_dir, 'news_automation.service')
            with open(service_path, 'w') as f:
                f.write(service_content)

            # Generar instrucciones de instalación
            install_instructions = f"""
Para instalar como servicio en Linux (systemd):

1. Copiar el archivo de servicio al directorio systemd:
   sudo cp {service_path} /etc/systemd/system/

2. Recargar la configuración de systemd:
   sudo systemctl daemon-reload

3. Habilitar el servicio para que inicie con el sistema:
   sudo systemctl enable news_automation.service

4. Iniciar el servicio:
   sudo systemctl start news_automation.service

5. Verificar el estado del servicio:
   sudo systemctl status news_automation.service
"""
            install_path = os.path.join(current_dir, 'install_service_linux.txt')
            with open(install_path, 'w') as f:
                f.write(install_instructions)

            print(f"Archivos de servicio para Linux generados en:\n{service_path}\n{install_path}")

        elif system == "Windows":
            # Crear archivo batch para Windows Task Scheduler
            batch_content = f"""@echo off
cd /d {current_dir}
python {os.path.join(current_dir, 'app.py')}
"""
            # Guardar el archivo batch
            batch_path = os.path.join(current_dir, 'start_news_automation.bat')
            with open(batch_path, 'w') as f:
                f.write(batch_content)

            # Generar instrucciones para Task Scheduler
            install_instructions = f"""
Para configurar como tarea programada en Windows:

1. Abrir el Programador de tareas (Task Scheduler)
2. Crear una nueva tarea básica
3. Nombre: Automatización de Noticias para Notion
4. Configurar para que se ejecute al iniciar sesión
5. En Acción, seleccionar "Iniciar un programa"
6. Programa/script: {batch_path}
7. Finalizar la configuración

También puede ejecutar manualmente el archivo:
{batch_path}
"""
            install_path = os.path.join(current_dir, 'install_service_windows.txt')
            with open(install_path, 'w') as f:
                f.write(install_instructions)

            print(f"Archivos de servicio para Windows generados en:\n{batch_path}\n{install_path}")

        else:
            print(f"Sistema operativo no reconocido: {system}")
            return False

        return True

    except Exception as e:
        logger.error(f"Error al generar archivos de servicio: {str(e)}")
        return False

def main():
    parser = argparse.ArgumentParser(description='Automatización de informes de noticias para Notion')

    # Configurar los argumentos de línea de comandos
    subparsers = parser.add_subparsers(dest='command', help='Comandos disponibles')

    # Comando para generar un informe inmediatamente
    generate_parser = subparsers.add_parser('generar', help='Generar un informe inmediatamente')
    generate_parser.add_argument('tema', help='Tema de búsqueda')
    generate_parser.add_argument('--max', type=int, default=10, help='Número máximo de resultados (5-100)')
    generate_parser.add_argument('--no-images', action='store_true', help='No incluir imágenes en el informe')
    generate_parser.add_argument('--ai-summary', action='store_true', help='Incluir resumen generado por IA')
    generate_parser.add_argument('--notify', choices=['console', 'email', 'slack'], default='console',
                                help='Método de notificación')

    # Comando para programar una tarea diaria
    schedule_parser = subparsers.add_parser('programar', help='Programar una tarea diaria')
    schedule_parser.add_argument('tema', help='Tema de búsqueda')
    schedule_parser.add_argument('hora', help='Hora de ejecución (formato HH:MM)')
    schedule_parser.add_argument('--max', type=int, default=10, help='Número máximo de resultados (5-100)')
    schedule_parser.add_argument('--no-images', action='store_true', help='No incluir imágenes en el informe')
    schedule_parser.add_argument('--notify', choices=['console', 'email', 'slack'], default='console',
                                help='Método de notificación')

    # Comando para iniciar el programador
    start_parser = subparsers.add_parser('iniciar', help='Iniciar el programador de tareas')

    # Comando para pruebas
    test_parser = subparsers.add_parser('prueba', help='Probar la conexión con las APIs')

    # Comando para verificar la base de datos
    verify_parser = subparsers.add_parser('verificar_db', help='Verificar acceso a la base de datos')

    # Comando para iniciar la interfaz web
    web_parser = subparsers.add_parser('web', help='Iniciar la interfaz web')
    web_parser.add_argument('--port', type=int, default=5000, help='Puerto para la interfaz web (por defecto: 5000)')
    web_parser.add_argument('--host', default='0.0.0.0', help='Host para la interfaz web (por defecto: 0.0.0.0)')

    # Comando para generar archivos de instalación como servicio
    service_parser = subparsers.add_parser('servicio', help='Generar archivos para instalar como servicio')

    args = parser.parse_args()

    # Procesar los comandos
    if args.command == 'generar':
        include_images = not args.no_images
        result = generate_news_report(
            args.tema,
            max_results=args.max,
            include_images=include_images,
            include_ai_summary=args.ai_summary,
            notification_method=args.notify
        )
        if result['success']:
            print(f"✅ {result['message']}")
            print(f"📰 Ver informe en: {result['page_url']}")
        else:
            print(f"❌ Error: {result['message']}")

    elif args.command == 'programar':
        include_images = not args.no_images
        setup_scheduled_task(
            args.tema,
            args.hora,
            max_results=args.max,
            include_images=include_images,
            notification_method=args.notify
        )
        run_scheduler()

    elif args.command == 'iniciar':
        run_scheduler()

    elif args.command == 'prueba':
        try:
            # Probar NewsAPI
            response = newsapi.get_everything(
                q='tecnología',
                language='es',
                page_size=1
            )
            print(f"Conexión con NewsAPI: ✅ Status: {response['status']}")
            print(f"Total resultados: {response['totalResults']}")

            # Probar Notion API
            user = notion.users.me()
            print(f"Conexión con Notion API: ✅ Usuario: {user['name']}")

            print("\n✅ Prueba completa. Las APIs funcionan correctamente.")
        except Exception as e:
            print(f"❌ Error durante la prueba: {str(e)}")

    elif args.command == 'verificar_db':
        verify_database()

    elif args.command == 'web':
        try:
            from app import run_app
            print(f"Iniciando interfaz web en http://{args.host}:{args.port}")
            run_app(host=args.host, port=args.port)
        except ImportError:
            print("❌ No se encontró el módulo 'app.py'. Asegúrate de haber creado el archivo de la aplicación web.")

    elif args.command == 'servicio':
        if install_as_service():
            print("✅ Archivos para instalación como servicio generados correctamente.")
        else:
            print("❌ Hubo un error al generar los archivos de servicio.")

    else:
        parser.print_help()

if __name__ == "__main__":
    main()