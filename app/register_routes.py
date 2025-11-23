"""
Register all routes for the Flask app.
This function is called from __init__.py after the app is created.
"""

def register_routes(app):
    """Register all routes by importing routes module inside app context"""
    from app import routes
