import os
from app import create_app

app = create_app()

if __name__ == '__main__':
     # Railway injecte PORT; par défaut 5000 en local
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

#   en local  app.run(debug=True)