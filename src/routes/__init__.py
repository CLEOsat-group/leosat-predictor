from .predict_routes import predict_bp
from .plot_routes import plot_bp
from .observatory_routes import observatory_bp
from .save_routes import save_bp
from .tle_routes import tle_bp
from .preferences_routes import preferences_bp
from .results_routes import results_bp

def register_routes(app):
    """Register all Flask routes (blueprints) with the app."""
    app.register_blueprint(predict_bp, url_prefix='/api')
    app.register_blueprint(plot_bp, url_prefix='/api')
    app.register_blueprint(observatory_bp, url_prefix='/api')
    app.register_blueprint(save_bp, url_prefix='/api')
    app.register_blueprint(tle_bp, url_prefix='/api')
    app.register_blueprint(preferences_bp, url_prefix='/api')
    app.register_blueprint(results_bp, url_prefix='/api')

