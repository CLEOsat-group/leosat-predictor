import logging
import os
from pathlib import Path

from flask import Flask, send_from_directory, redirect, render_template

from .config import Config
from .routes import register_routes

app = Flask(__name__, static_folder="../frontend", template_folder="templates")
# app = Flask(__name__, static_folder='../static')
app.config.from_object(Config)

logger = logging.getLogger(__name__)
logger.info("App initialized with environment: %s", Config().get("FLASK_ENV", "production"))

# Register API routes
register_routes(app)

# Serve the main index page using render_template
@app.route('/')
def index():
    return render_template('index.html')  # Jinja templates are processed here

# Serve static files (e.g., CSS, JS, images)
@app.route('/static/<path:filename>')
def serve_static_files(filename):
    static_path = Path(app.root_path).resolve().parent / 'static'
    return send_from_directory(str(static_path), filename)

# Redirect to root for specific paths (optional cleanup)
@app.route('/frontend/index.html')
def redirect_to_root():
    return redirect('/')

# Define the path to the root-level frontend directory
FRONTEND_PATH = Path(app.root_path).resolve().parent / 'frontend'

# Serve static files from /frontend/
@app.route('/frontend/<path:filename>')
def serve_frontend_files(filename):
    return send_from_directory(str(FRONTEND_PATH), filename)

# Route to serve preferences.html
@app.route("/templates/preferences.html")
def preferences_template():
    return render_template("preferences.html")

@app.route("/templates/map_popup.html")
def map_popup_template():
    return render_template("map_popup.html")

@app.route('/node_modules/<path:filename>')
def serve_node_modules(filename):
    node_modules_path = Path(app.root_path).resolve().parent / 'node_modules'
    return send_from_directory(str(node_modules_path), filename)

# # Serve index.html from /frontend/html/index.html
# @app.route('/')
# def index():
#     return send_from_directory(os.path.join(FRONTEND_PATH, 'html'), 'index.html')
#
# # Serve other HTML files (like map.html)
# @app.route('/frontend/html/<path:filename>')
# def serve_frontend_html(filename):
#     return send_from_directory(os.path.join(FRONTEND_PATH, 'html'), filename)
#
# @app.route('/frontend/index.html')
# def redirect_to_root():
#     return redirect('/')
#
# @app.route('/frontend/html/includes/<path:filename>')
# def serve_includes(filename):
#     return send_from_directory(os.path.join(FRONTEND_PATH, 'html/includes'), filename)

if __name__ == "__main__":
    context = ('certs/localhost.crt', 'certs/localhost.key')  # Path to SSL certs
    app.run(debug=Config().get("FLASK_ENV", "development"), ssl_context=context)
