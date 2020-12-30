import json
import asyncio
import time
from threading import Thread, Event

import gevent
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
    app.config["MONGO_DBNAME"] = "pokerdb"
    app.config["MONGO_URI"] = "mongodb://localhost:27017/pokerdb"
    app.config["SECRET_KEY"] = "supersecret"
    app.config["CORS_HEADERS"] = "Content-Type"

    CORS(app, resources={r"/*": {"origins": "*"}})
    mongo = PyMongo(app)
    socketio = SocketIO(app, cors_allowed_origins="*")

    ## Initialize database
    mongo.db.players.drop()
    mongo.db.table.drop()
    mongo.db.players.replace_one({"_id": "player_count"}, {"_id": "player_count", "count": 0}, upsert=True)
    mongo.db.settings.replace_one({"_id": "blinds"}, {"_id": "blinds" , "small": 10, "big": 20, "increase": True, "interval": 1200, "double": True, "amount": 0}, upsert=True)
    mongo.db.settings.replace_one({"_id": "ante"}, {"_id": "ante", "active": False, "amount": 30}, upsert=True)
    mongo.db.settings.replace_one({"_id": "player_settings"}, {"_id": "player_settings", "starting_chips": 5000, "rebuys_allowed": False, "time_per_hand": 60}, upsert=True)
    
    print(mongo.db.players.find_one({"_id": "player_count"}))

    ## HELPER FUNCTIONS ##
    def player_exists(player):
        i = 0
        for obj in mongo.db.players.find({"_id": player}):
            i += 1
        return i

    ## APP ROUTE FUNCTIONS ##

    @app.route('/', methods=["GET"])
    def default():
        all_data = {}
        deck = Deck()
        all_data["cards"] = deck.deal_cards(26, 2)
        print(deck.current_deck())
        deck.shuffle()
        print(deck.current_deck())
        socketio.emit("game_time", {"time": 555}, broadcast=True)
        
        return jsonify(all_data)

    ## SOCKET METHODS ##

    ## Triggers whenever new client connects
    @socketio.on("connect")
    def connected():
        print("New Websocket client: ", request.sid)
    
    ## Triggers whenever client disconnects
    @socketio.on("disconnect")
    def disconnected():
        print("Websocket client disconnected")

    @socketio.on("current_time")
    def broadcast_current_player_time(msg):
        print("sending time")
        print("user sid: ", request.sid)
        json_data = json.loads(msg)
        print(json_data["playerTime"])
        emit("game_time", {"time": json_data["playerTime"]}, broadcast=True)

    @socketio.on("set_player_name")
    def set_player_name(msg):
        player_name = json.loads(msg)["name"]
        if(not player_exists(player_name)):
            player_position = mongo.db.players.find_one({"_id": "player_count"})["count"]
            starting_chips = mongo.db.settings.find_one({"_id": "player_settings"})["starting_chips"]
            permissions = {}
            if(player_position == 0):
                permissions["host"] = True
            mongo.db.players.insert_one({
                "_id": player_name, 
                "sessionid": request.sid,
                "chips": starting_chips, 
                "cards": {},
                "position": player_position,
                "player_status": 0,
                "bet_size": 0,
                "permissions": permissions,
                "rebuys": 0})
            emit("player_info", {
                "accepted": True,
                "chips": starting_chips,
                "position": player_position,
                "permissions": permissions
            })
            mongo.db.players.update_one({"_id": "player_count"}, {"$inc": {"count": 1}})
        else:
            emit("player_info", {"accepted": False})
            # Think of a way to separate returning player from new player using same name
    
    @socketio.on("start_game")
    def start_game():
        emit("deal_cards", {"gamestate": "goes here"}, broadcast=True)

    return (app, socketio)

def main():
    poker_url = "http://localhost:5000"
    (app, socketio) = create_app(poker_url)
    socketio.run(app, host="localhost", port=5000, debug=True)

if __name__ == "__main__":
    main()
