

from flask import Flask
import os
from config import app_config


#webapp = Flask(__name__)




config_name = os.getenv('FLASK_CONFIG')
webapp = Flask(__name__, instance_relative_config=True)
webapp.config.from_object(app_config[config_name])
webapp.config.from_pyfile('config.py')

from app import main





