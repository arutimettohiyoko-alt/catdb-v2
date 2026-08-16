from flask import Flask
from blueprints.ally import ally_bp
from blueprints.enemy import enemy_bp

app = Flask(__name__)

app.register_blueprint(ally_bp, url_prefix='/')
app.register_blueprint(enemy_bp, url_prefix='/enemy')

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
