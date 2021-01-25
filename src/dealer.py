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
from poker_hand import PokerHand
from game_phase import GamePhase

def create_app(poker_url):

    app = Flask(__name__)
    app.config["MONGO_DBNAME"] = "pokerdb"
    app.config["MONGO_URI"] = "mongodb://localhost:27017/pokerdb"
    app.config["SECRET_KEY"] = "supersecret"
    app.config["CORS_HEADERS"] = "Content-Type"

    CORS(app, resources={r"/*": {"origins": "*"}})
    mongo = PyMongo(app)
    socketio = SocketIO(app, cors_allowed_origins="*")

    ## Collections
    players = mongo.db.players
    settings = mongo.db.settings
    table = mongo.db.table
    ## Initialize database
    players.drop()
    table.drop()
    # Settings
    settings.replace_one({"_id": "blinds"}, {"_id": "blinds" , "small": 10, "big": 20, "increase": True, "interval": 1200, "double": True, "amount": 0}, upsert=True)
    settings.replace_one({"_id": "ante"}, {"_id": "ante", "active": False, "amount": 30}, upsert=True)
    settings.replace_one({"_id": "player_settings"}, {"_id": "player_settings", "starting_chips": 5000, "rebuys_allowed": False, "time_per_hand": 15}, upsert=True)
    # Table
    table.replace_one({"_id": "player_count"}, {"_id": "player_count", "count": 0, "folded": 0, "eliminated": 0}, upsert=True)
    small_blind = settings.find_one({"_id": "blinds"})["small"]
    big_blind = settings.find_one({"_id": "blinds"})["big"]
    table.replace_one({"_id": "positions"}, {"_id": "positions", "dealer": 0, "bb": 0, "sb": 0, "utg": 0, "current_player": 0, "action": -1}, upsert=True)
    table.replace_one({"_id": "table_chips"}, {"_id": "table_chips", "pot": 0, "small_blind": small_blind, "big_blind": big_blind, "current_bet": 0}, upsert=True)
    table.replace_one({"_id": "game_time"}, {"_id": "game_time", "time": 0}, upsert=True)
    table.replace_one({"_id": "game_phase"}, {"_id": "game_phase", "phase": 0}, upsert=True)

    ## HELPER FUNCTIONS ##
    def player_exists(player):
        i = 0
        for obj in players.find({"_id": player}):
            i += 1
        return i
    
    def get_player_count():
        return table.find_one({"_id": "player_count"})["count"]

    def get_all_players(show_cards):
        all_players = []
        for player in players.find():
            cards = []
            if len(player["cards"]) > 0:
                for key in player["cards"]:
                    if show_cards:
                        cards.append(player["cards"][key])
                    else:
                        cards.append({"value": None, "suit": None, "revealed": False})
            all_players.append(
                {
                    "name": player["_id"], 
                    "position": player["position"],
                    "status": player["status"],
                    "chips": player["chips"], 
                    "cards": cards,
                    "betSize": player["betSize"],
                    "rebuys": player["rebuys"],
                    "permissions": player["permissions"]
                }
            )
        return all_players
    
    # Gets the position of the next player to receive action
    def get_next_active_player():
        current_pos = table.find_one({"_id": "positions"})["current_player"]
        pos = current_pos + 1
        while True:
            if pos >= get_player_count():
                pos = 0
            if pos == current_pos:
                return pos
            player_status = players.find_one({"position": pos})["status"]
            if player_status == 3:
                return pos
            pos += 1
    
    # Counts players still waiting for action
    def count_active_players():
        active_players = 0
        for player in players.find():
            if player["status"] >= 3:
                active_players += 1
        return active_players

    def count_playing_players():
        playing_players = 0
        for player in players.find():
            if player["status"] >= 2:
                playing_players += 1
        return playing_players
    
    def get_table_info():
        table_info = {}
        table_info["pot"] = table.find_one({"_id": "table_chips"})["pot"]
        table_info["minBet"] = settings.find_one({"_id": "blinds"})["big"]
        table_info["currentBet"] = table.find_one({"_id": "table_chips"})["current_bet"]
        table_info["phase"] = table.find_one({"_id": "game_phase"})["phase"]
        table_info["dealer"] = table.find_one({"_id": "positions"})["dealer"]
        table_info["sb"] = table.find_one({"_id": "positions"})["sb"]
        table_info["bb"] = table.find_one({"_id": "positions"})["bb"]
        table_info["utg"] = table.find_one({"_id": "positions"})["utg"]
        table_info["currentPlayer"] = table.find_one({"_id": "positions"})["current_player"]
        table_info["action"] = table.find_one({"_id": "positions"})["action"]
        table_info["playerCount"] = table.find_one({"_id": "player_count"})["count"]
        table_info["folded"] = table.find_one({"_id": "player_count"})["folded"]
        table_info["eliminated"] = table.find_one({"_id": "player_count"})["eliminated"]
        table_cards = table.find_one({"_id": "table_cards"})
        table_info["tableCards"] = []
        if table_info["phase"] >= 1:
            for i in range(3):
                table_info["tableCards"].append(table_cards[str(i)])
        if table_info["phase"] >= 2:
            table_info["tableCards"].append(table_cards[str(3)])
        if table_info["phase"] >= 3:
            table_info["tableCards"].append(table_cards[str(4)])
        return table_info

    def emit_game_state(show_cards):
        socketio.emit("game_state", {"players": get_all_players(show_cards), "table": get_table_info()}, broadcast=True)

    # Sets initial dealer position
    def dealer_position(player_count):
        dealer = player_count - 3
        if dealer < 0:
            dealer = 0
        return dealer
    # Sets initial sb position
    def sb_position(player_count):
        dealer = dealer_position(player_count)
        if player_count == 2:
            return dealer
        elif dealer + 1 > player_count - 1:
            return 0
        else:
            return dealer + 1
    # Sets initial bb position
    def bb_position(player_count):
        sb = sb_position(player_count)
        if player_count == 2:
            return int(not sb)
        elif sb + 1 > player_count - 1:
            return 0
        else:
            return sb + 1
    # Sets initial utg position
    def utg_position(player_count):
        bb = bb_position(player_count)
        if player_count == 2:
            return int(not bb)
        elif bb + 1 > player_count - 1:
            return 0
        else:
            return bb + 1

    # Rotates positions for the new round !!! FIX THIS !!!
    def set_new_positions():
        positions = []
        for player in players.find():
            if player["status"] > 1 or player["b_elim"]:
                positions.append(player["position"])

        positions = sorted(positions)

        new_dealer = -1
        new_sb = -1
        new_bb = -1
        new_utg = -1

        bb_found = 0
        ct = 0
        while new_bb == -1:
            if ct == len(positions):
                ct = 0
            elif positions[ct] == table.find_one({"_id": "positions"})["bb"]:
                bb_found = 1
                ct += 1
            elif bb_found and players.find_one({"position": positions[ct]})["status"] >= 2:
                new_bb = ct
            else:
                ct += 1
        
        new_sb = new_bb - 1
        if new_sb < 0:
            new_sb = len(positions) - 1
        
        if count_playing_players() > 2:
            new_dealer = new_sb - 1
        elif count_playing_players() <= 2:
            new_dealer = new_bb - 1
        if new_dealer < 0:
            new_dealer = len(positions) - 1
        if players.find_one({"position": positions[new_dealer]})["b_elim"]:
            players.update_one({"position": positions[new_dealer]}, [{"$set": {"b_elim": 0}}], upsert=True)    
        
        new_utg = new_bb + 1
        if new_utg == len(positions):
            new_utg = 0

        print(new_dealer, new_sb, new_bb, new_utg)
        table.update_one({"_id": "positions"}, 
            [{"$set": 
                {   "dealer": positions[new_dealer], 
                    "sb": positions[new_sb], 
                    "bb": positions[new_bb], 
                    "utg": positions[new_utg],
                    "action": -1
                }
            }])
    
    # Returns player that should act first
    def first_to_act():
        phase = table.find_one({"_id": "game_phase"})["phase"]
        if(phase > 0):
            if players.find_one({"position": table.find_one({"_id": "positions"})["sb"]})["status"] > 2:
                return table.find_one({"_id": "positions"})["sb"]
            else:
                i = table.find_one({"_id": "positions"})["sb"] + 1
                for _ in range(table.find_one({"_id": "player_count"})["count"]):
                    if i >= table.find_one({"_id": "player_count"})["count"]:
                        i = 0
                    if players.find_one({"position": i})["status"] > 2:
                        return i
                    i += 1
        else:
            return table.find_one({"_id": "positions"})["utg"]

    def set_blinds():
        big_blind = table.find_one({"_id": "table_chips"})["big_blind"]
        small_blind = table.find_one({"_id": "table_chips"})["small_blind"]
        positions = table.find_one({"_id": "positions"})
        place_bet(positions["sb"], small_blind)
        place_bet(positions["bb"], big_blind)
    
    def add_chips(pos, new_chips):
        chips = players.find_one({"position": pos})["chips"]
        players.update_one({"position": pos}, [{"$set": {"chips": chips + new_chips}}], upsert=True)

    def place_bet(pos, bet):
        active_bet = players.find_one({"position": pos})["betSize"]
        add_chips(pos, -(bet - active_bet))
        players.update_one({"position": pos}, [{"$set": {"betSize": bet}}], upsert=True)
        pot = table.find_one({"_id": "table_chips"})["pot"]
        table.update_one({"_id": "table_chips"}, [{"$set": {"pot": pot + bet - active_bet, "current_bet": bet}}], upsert=True)

    def start_round():
        print("round started")
        # Reset table info
        table.update_one({"_id": "player_count"}, {"$set": {"folded": 0}}, upsert=True)
        table.update_one({"_id": "game_phase"}, {"$set": {"phase": 0}}, upsert=True)
        # Reset option selection for players
        socketio.emit("reset_option", broadcast=True)
        # Deal the cards
        deck = Deck()
        deck.shuffle()
        player_cards = deck.deal_cards(get_player_count(), 2)
        # Deal the table cards
        for i in range(5):
            table.update_one({"_id": "table_cards"}, [{"$set": {str(i): deck.random_card()}}], upsert=True)
        # Check if player is eliminated, else send cards to players
        for player in players.find():
            # if big blind was recently eliminated
            if player["chips"] <= 0 and player["position"] == table.find_one({"_id": "positions"})["bb"] or player["chips"] <= 0 and player["position"] == table.find_one({"_id": "positions"})["sb"]:
                players.update_one({"_id": player["_id"]},
                    [{"$set": {
                        "status": 1,
                        "betSize": 0,
                        "b_elim": 1
                    }}], upsert=True)
            # if player was eliminated normally
            elif player["chips"] <= 0:
                players.update_one({"_id": player["_id"]},
                    [{"$set": {
                        "status": 1,
                        "betSize": 0,
                        "b_elim": 0
                    }}], upsert=True)
            # deal the cards
            else:
                cards = player_cards[player["position"]]
                card_dict = {}
                for j in range(len(cards)):
                    card_dict[str(j)] = cards[j]
                players.update_one({"_id": player["_id"]},
                    [{"$set": {
                        "cards": card_dict,
                        "status": 3,
                        "betSize": 0
                    }}], upsert=True)
                socketio.emit("deal_cards", {"cards": cards}, room=player["sessionid"])

        # Update player positions
        set_new_positions()
        first = first_to_act()
        print(first)
        table.update_one({"_id": "positions"}, {"$set": {"current_player": first}}, upsert=True)
        # Set the blinds
        set_blinds()
        
        emit_game_state(show_cards=False)

        socketio.emit("start_turn", {"time": settings.find_one({"_id": "player_settings"})["time_per_hand"]}, room=players.find_one({"position": first})["sessionid"])

    def next_phase():
        # INITIAL = 0,
        # FLOP = 1,
        # TURN = 2,
        # RIVER = 3
        # SHOWDOWN = 4
        # table.replace_one({"_id": "game_phase"}, {"_id": "game_phase", "phase": 0}, upsert=True)
        
        # go to next phase, if next phase is the end, decide the winner of the hand
        print("next phase")
        socketio.emit("reset_option", broadcast=True)
        next_phase = table.find_one({"_id": "game_phase"})["phase"] + 1
        if next_phase == 4:
            print("declare winner of hand")
            table.update_one({"_id": "positions"}, {"$set": {"action": -1}})
            # do some stuff, set things up for the next round
            winners = appraise_hands()
            print(winners)
            pot = table.find_one({"_id": "table_chips"})["pot"]
            pot = pot/len(winners)
            rem = pot%len(winners)
            for winner in winners:
                players.update_one({"_id": winner},
                    {"$inc": {
                        "chips": pot
                    }})
            table.update_one({"_id": "table_chips"}, {"$set": {"pot": 0}})
            emit_game_state(show_cards=True)
            socketio.emit("declare_winners", {"winners": winners}, broadcast=True)
            start_round()
        else:
            table.update_one({"_id": "game_phase"}, {"$set": {"phase": next_phase}})
            first = first_to_act()
            table.update_one({"_id": "positions"}, {"$set": {"current_player": first, "action": -1}})
            table.update_one({"_id": "table_chips"}, {"$set": {"current_bet": 0}})
            for player in players.find():
                players.update_one({"_id": player["_id"]}, {"$set":{"betSize": 0}})
            emit_game_state(show_cards=False)
            socketio.emit("start_turn", {"time": settings.find_one({"_id": "player_settings"})["time_per_hand"]}, room=players.find_one({"position": first})["sessionid"])

    def appraise_hands():
        test_hands = [
            # high card
            [{"value": 2, "suit": 0}, {"value": 4, "suit": 1}, {"value": 5, "suit": 2}, {"value": 8, "suit": 3}, {"value": 9, "suit": 1}, {"value": 12, "suit": 0}, {"value": 13, "suit": 0}],
            # pair
            [{"value": 2, "suit": 0}, {"value": 3, "suit": 1}, {"value": 4, "suit": 2}, {"value": 4, "suit": 3}, {"value": 5, "suit": 0}, {"value": 8, "suit": 1}, {"value": 9, "suit": 2}],
            # two pair
            [{"value": 2, "suit": 0}, {"value": 3, "suit": 1}, {"value": 3, "suit": 2}, {"value": 4, "suit": 2}, {"value": 5, "suit": 3}, {"value": 5, "suit": 0}, {"value": 8, "suit": 2}],
            [{"value": 2, "suit": 0}, {"value": 2, "suit": 1}, {"value": 7, "suit": 2}, {"value": 7, "suit": 2}, {"value": 12, "suit": 3}, {"value": 12, "suit": 0}, {"value": 14, "suit": 2}],
            [{"value": 2, "suit": 0}, {"value": 7, "suit": 1}, {"value": 7, "suit": 2}, {"value": 12, "suit": 2}, {"value": 12, "suit": 3}, {"value": 14, "suit": 0}, {"value": 14, "suit": 2}],
            # trips
            [{"value": 2, "suit": 0}, {"value": 3, "suit": 1}, {"value": 4, "suit": 2}, {"value": 4, "suit": 0}, {"value": 4, "suit": 3}, {"value": 5, "suit": 0}, {"value": 9, "suit": 2}],
            # straight
            [{"value": 2, "suit": 0}, {"value": 3, "suit": 1}, {"value": 4, "suit": 2}, {"value": 5, "suit": 3}, {"value": 6, "suit": 1}, {"value": 10, "suit": 0}, {"value": 12, "suit": 2}],
            [{"value": 2, "suit": 0}, {"value": 3, "suit": 1}, {"value": 4, "suit": 2}, {"value": 5, "suit": 3}, {"value": 6, "suit": 1}, {"value": 7, "suit": 0}, {"value": 8, "suit": 2}],
            [{"value": 2, "suit": 0}, {"value": 3, "suit": 1}, {"value": 4, "suit": 2}, {"value": 5, "suit": 3}, {"value": 10, "suit": 1}, {"value": 12, "suit": 0}, {"value": 14, "suit": 2}],
            [{"value": 2, "suit": 0}, {"value": 3, "suit": 1}, {"value": 4, "suit": 2}, {"value": 5, "suit": 3}, {"value": 6, "suit": 1}, {"value": 7, "suit": 0}, {"value": 14, "suit": 2}],
            [{"value": 2, "suit": 0}, {"value": 3, "suit": 1}, {"value": 3, "suit": 2}, {"value": 4, "suit": 3}, {"value": 5, "suit": 1}, {"value": 5, "suit": 0}, {"value": 6, "suit": 2}],
            # flush
            [{"value": 2, "suit": 0}, {"value": 4, "suit": 0}, {"value": 5, "suit": 2}, {"value": 8, "suit": 0}, {"value": 9, "suit": 0}, {"value": 12, "suit": 0}, {"value": 13, "suit": 2}],
            [{"value": 2, "suit": 0}, {"value": 4, "suit": 0}, {"value": 5, "suit": 0}, {"value": 8, "suit": 0}, {"value": 9, "suit": 0}, {"value": 12, "suit": 0}, {"value": 13, "suit": 0}],
            # full house
            [{"value": 2, "suit": 0}, {"value": 2, "suit": 1}, {"value": 5, "suit": 2}, {"value": 5, "suit": 3}, {"value": 5, "suit": 1}, {"value": 12, "suit": 0}, {"value": 14, "suit": 2}],
            [{"value": 2, "suit": 0}, {"value": 2, "suit": 1}, {"value": 5, "suit": 2}, {"value": 5, "suit": 3}, {"value": 5, "suit": 1}, {"value": 12, "suit": 0}, {"value": 12, "suit": 2}],
            [{"value": 2, "suit": 0}, {"value": 2, "suit": 1}, {"value": 2, "suit": 2}, {"value": 5, "suit": 3}, {"value": 5, "suit": 1}, {"value": 12, "suit": 0}, {"value": 12, "suit": 2}],
            [{"value": 2, "suit": 0}, {"value": 2, "suit": 1}, {"value": 2, "suit": 2}, {"value": 6, "suit": 3}, {"value": 7, "suit": 1}, {"value": 12, "suit": 0}, {"value": 12, "suit": 2}],
            # quads
            [{"value": 2, "suit": 0}, {"value": 2, "suit": 1}, {"value": 2, "suit": 2}, {"value": 2, "suit": 3}, {"value": 5, "suit": 1}, {"value": 5, "suit": 0}, {"value": 6, "suit": 2}],
            [{"value": 2, "suit": 0}, {"value": 2, "suit": 1}, {"value": 2, "suit": 2}, {"value": 2, "suit": 3}, {"value": 5, "suit": 1}, {"value": 5, "suit": 0}, {"value": 5, "suit": 2}],
            [{"value": 3, "suit": 0}, {"value": 3, "suit": 1}, {"value": 3, "suit": 2}, {"value": 5, "suit": 3}, {"value": 5, "suit": 1}, {"value": 5, "suit": 0}, {"value": 5, "suit": 2}],
            # straight flush
            [{"value": 2, "suit": 0}, {"value": 3, "suit": 0}, {"value": 4, "suit": 0}, {"value": 5, "suit": 0}, {"value": 6, "suit": 0}, {"value": 10, "suit": 0}, {"value": 12, "suit": 0}],
            [{"value": 2, "suit": 0}, {"value": 3, "suit": 0}, {"value": 4, "suit": 0}, {"value": 5, "suit": 0}, {"value": 6, "suit": 0}, {"value": 7, "suit": 0}, {"value": 8, "suit": 0}],
            [{"value": 2, "suit": 0}, {"value": 3, "suit": 0}, {"value": 4, "suit": 0}, {"value": 5, "suit": 0}, {"value": 6, "suit": 0}, {"value": 7, "suit": 2}, {"value": 8, "suit": 3}],
            [{"value": 2, "suit": 0}, {"value": 3, "suit": 0}, {"value": 4, "suit": 0}, {"value": 5, "suit": 2}, {"value": 6, "suit": 0}, {"value": 7, "suit": 0}, {"value": 8, "suit": 0}],
            [{"value": 2, "suit": 0}, {"value": 3, "suit": 0}, {"value": 4, "suit": 0}, {"value": 5, "suit": 0}, {"value": 10, "suit": 1}, {"value": 12, "suit": 3}, {"value": 14, "suit": 0}],
            [{"value": 2, "suit": 0}, {"value": 3, "suit": 0}, {"value": 4, "suit": 0}, {"value": 5, "suit": 0}, {"value": 6, "suit": 0}, {"value": 7, "suit": 0}, {"value": 14, "suit": 0}],
            [{"value": 2, "suit": 0}, {"value": 3, "suit": 0}, {"value": 3, "suit": 2}, {"value": 4, "suit": 0}, {"value": 5, "suit": 1}, {"value": 5, "suit": 0}, {"value": 6, "suit": 0}],
            # royal flush
            [{"value": 2, "suit": 0}, {"value": 2, "suit": 0}, {"value": 10, "suit": 0}, {"value": 11, "suit": 0}, {"value": 12, "suit": 0}, {"value": 13, "suit": 0}, {"value": 14, "suit": 0}],
            [{"value": 8, "suit": 0}, {"value": 9, "suit": 0}, {"value": 10, "suit": 0}, {"value": 11, "suit": 0}, {"value": 12, "suit": 0}, {"value": 13, "suit": 0}, {"value": 14, "suit": 0}],
        ]
        # for test_hand in test_hands:
        #     hand = PokerHand(test_hand)
        #     print(hand)

        hands = {}

        # test
        # test_player_cards = [
        #     [{"value": 14, "suit": 3}, {"value": 14, "suit": 2}],
        #     [{"value": 2, "suit": 1}, {"value": 3, "suit": 1}],
        #     [{"value": 4, "suit": 1}, {"value": 8, "suit": 1}],
        #     [{"value": 12, "suit": 0}, {"value": 5, "suit": 2}],
        #     [{"value": 11, "suit": 1}, {"value": 5, "suit": 1}],
        #     [{"value": 13, "suit": 3}, {"value": 11, "suit": 0}],
        #     [{"value": 5, "suit": 3}, {"value": 6, "suit": 0}]
        # ]
        # test_table_cards = [
        #     {"value": 2, "suit": 0}, 
        #     {"value": 3, "suit": 2}, 
        #     {"value": 4, "suit": 0}, 
        #     {"value": 8, "suit": 2},
        #     {"value": 14, "suit": 0}
        # ]
        # for i in range(len(test_player_cards)):
        #     cards = []
        #     for j in range(2):
        #         cards.append(test_player_cards[i][j])
        #     for k in range(5):
        #         cards.append(test_table_cards[k])
        #     print(cards)
        #     hand = PokerHand(cards)
        #     hands[i] = hand
        # print(hands)
        for player in players.find():
            if player["status"] > 2:
                cards = []
                for key in player["cards"]:
                    cards.append(player["cards"][key])
                table_cards = table.find_one({"_id": "table_cards"}, {"_id": False})
                for card in table_cards:
                    cards.append(table_cards[card])
                hand = PokerHand(cards)
                hands[player["_id"]] = hand
        top = []
        for curr in hands:
            if top == []:
                top.append(curr)
                print("first hand")
            elif hands[curr] == hands[top[0]]:
                print(hands[curr], hands[top[0]])
                top.append(curr)
                print("hands equal")
            elif hands[curr] > hands[top[0]]:
                print(hands[curr], hands[top[0]])
                top = []
                top.append(curr)
                print("hand stronger")
            else:
                print(hands[curr], hands[top[0]])
                print("hand weaker")

        return top

    ## APP ROUTE FUNCTIONS ##

    @app.route('/', methods=["GET"])
    def default():
        start_game()
        start_round()
        return jsonify({"hello": world})
    ## SOCKET METHODS ##

    ## Triggers whenever new client connects
    @socketio.on("connect")
    def connected():
        print("New Websocket client: ", request.sid)
    
    ## Triggers whenever client disconnects
    @socketio.on("disconnect")
    def disconnected():
        print("Websocket client disconnected")

    ## Receives current time 
    @socketio.on("current_time")
    def broadcast_current_player_time(msg):
        json_data = json.loads(msg)
        table.update_one({"_id": "game_time"}, {"$inc": {"time": 1}})
        emit("game_time", {"time": json_data["playerTime"]}, broadcast=True)

    @socketio.on("set_player_name")
    def set_player_name(msg):
        player_name = json.loads(msg)["name"]
        if(not player_exists(player_name)):
            player_position = table.find_one({"_id": "player_count"})["count"]
            starting_chips = settings.find_one({"_id": "player_settings"})["starting_chips"]
            permissions = "player"
            if(player_position == 0):
                permissions = "host"
            players.insert_one({
                "_id": player_name, 
                "position": player_position,
                "status": 0,
                "chips": starting_chips, 
                "cards": {},
                "betSize": 0,
                "rebuys": 0,
                "permissions": permissions,
                "sessionid": request.sid,
                "b_elim": 0
            })
            # Increment player count by one
            table.update_one({"_id": "player_count"}, {"$inc": {"count": 1}})
            # returns player position as response
            emit("player_info", {"accepted": True, "position": player_position})
            emit_game_state(show_cards=False)
        else:
            emit("player_info", {"accepted": False})
            # Think of a way to separate returning player from new player using same name
    
    @socketio.on("start_game")
    def start_game():
        print("getting everything ready...")
        player_count = get_player_count()
        table.update_one({"_id": "positions"}, 
            [{"$set": 
                {   "dealer": dealer_position(player_count), 
                    "sb": sb_position(player_count), 
                    "bb": bb_position(player_count), 
                    "utg": utg_position(player_count)
                }
            }], upsert=True)
        table.update_one({"_id": "game_phase"}, 
            [{"$set": 
                {"phase": 0}
            }], upsert=True)
        print("game time started")
        start_round()

    @socketio.on("next_turn")
    def next_turn(info):
        print("next turn")
        player_info = json.loads(info)
        # player folded
        if player_info["option"] == 4:
            players.update_one({"position": player_info["position"]}, {"$set": {"status": 2}})
            table.update_one({"_id": "player_count"}, {"$inc": {"folded": 1}})
        # player placed bet or went all in or first to act, place action on player
        elif player_info["option"] == 3 or player_info["option"] == 7 or table.find_one({"_id": "positions"})["action"] == -1:
            place_bet(player_info["position"], player_info["betSize"])
            table.update_one({"_id": "positions"}, {"$set": {"action": player_info["position"]}})
        # handles player check
        else:
            place_bet(player_info["position"], player_info["betSize"])
        
        # Go to next active player
        next_player_pos = get_next_active_player()
        if count_active_players() == 1:
            pot = table.find_one({"_id": "table_chips"})["pot"]
            players.update_one({"position": next_player_pos},
                {"$inc": {
                    "chips": pot
                }})
            table.update_one({"_id": "table_chips"}, {"$set": {"pot": 0}})
            start_round()
        elif next_player_pos == table.find_one({"_id": "positions"})["action"]:
            next_phase()
        else:
            table.update_one({"_id": "positions"}, {"$set": {"current_player": next_player_pos}})
            emit_game_state(show_cards=False)
            emit("start_turn", {"time": settings.find_one({"_id": "player_settings"})["time_per_hand"]}, room=players.find_one({"position": next_player_pos})["sessionid"])

    @socketio.on("gather_chips")
    def gather_chips(info):
        pot = table.find_one({"_id": "table_chips"})["pot"]
        winners = json.loads(info)["winners"]
        pot = pot/winners
        rem = pot%winners

        players.update_one({"sessionid": request.sid},
                {"$inc": {
                    "chips": pot
                }})
        table.update_one({"_id": "table_chips"}, {"$set": {"pot": 0}})
        
        emit_game_state(show_cards=True)
    
    return (app, socketio)

def main():
    poker_url = "http://localhost:5000"
    (app, socketio) = create_app(poker_url)
    socketio.run(app, host="localhost", port=5000, debug=True)

if __name__ == "__main__":
    main()
