import json
import asyncio
import time

from gevent import monkey
monkey.patch_all()

from flask import Flask, request, jsonify
from flask_pymongo import PyMongo
from flask_socketio import SocketIO, disconnect, emit
from flask_cors import CORS, cross_origin
from flask_jwt_extended import verify_jwt_in_request, JWTManager

from deck import Deck

def create_app(poker_url):

    app = Flask(__name__)
    CORS(app)

    app.config["MONGO_DBNAME"] = "pokerdb"
    app.config["MONGO_URI"] = "mongodb://localhost:27017/pokerdb"
    app.config["SECRET_KEY"] = "supersecret"

    mongo = PyMongo(app)
    socketio = SocketIO(app, cors_allowed_origins="*")

    @app.route('/', methods=['GET'])
    def default():
        all_data = {}
        deck = Deck("poker")
        all_data["cards"] = deck.deal_cards(26, 2)
        print(deck.current_deck())
        deck.shuffle()
        print(deck.current_deck())
        return jsonify(all_data)

    @socketio.on("connect")
    def connected():
        print("New Websocket client: ", request.sid)
    
    @socketio.on("disconnect")
    def disconnected():
        print("Websocket client disconnected")

    @socketio.on("start_timer")
    def start_timer(json):
        currentTime = json["time"]
        while currentTime >= 0:
            emit('timer', {'time': currentTime}, broadcast=True)
            socketio.sleep(1)
            currentTime -= 1
        return None

    return (app, socketio)

poker_url = "http://localhost:5000"
(app, socketio) = create_app(poker_url)

if __name__ == '__main__':
    socketio.run(app, host="localhost", port=5000, debug=True)