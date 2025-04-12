Copy# Automatización de Noticias para Notion

Este sistema permite automatizar la búsqueda de noticias sobre temas específicos y generar informes directamente en Notion.

## Características principales-**Búsqueda de noticias:** Encuentra noticias relacionadas con temas específicos
-**Informes en Notion:** Genera páginas estructuradas con la información encontrada
-**Interfaz web:** Permite ejecutar búsquedas desde una interfaz amigable
-**Integración con Notion:** Se incrusta directamente en tu espacio de trabajo
-**Programación:** Ejecución automática en horarios definidos
-**Notificaciones:** Alertas cuando se generan nuevos informes
-**Personalizable:** Configura el número de resultados, inclusión de imágenes, etc.

## Requisitos previos1. Python 3.7 o superior
2. Cuenta en Notion
3. API Key de NewsAPI (obtenible en [newsapi.org](https://newsapi.org/))
4. Token de integración de Notion

## Instalación1. Clona este repositorio o descarga los archivos
2. Instala las dependencias:

```bash
 python -m pip install -r requirements.txt

Copy# Generar un informe inmediatamente
python news_automation.py generar "Inteligencia Artificial" --max 20

# Programar una tarea diaria a las 8:00 AM
python news_automation.py programar "Economía" 08:00 --max 15

# Verificar conexión con las APIs
python news_automation.py prueba

# Verificar acceso a la base de datos de Notion
python news_automation.py verificar_db

# Generar archivos para instalar como servicio
python news_automation.py servicio

# Inicia la interfaz web
python news_automation.py web
# powershell
Copypython news_automation.py web


