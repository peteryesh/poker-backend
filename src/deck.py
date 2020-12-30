import random
from enum import Enum

CLUBS = 0
DIAMONDS = 1
HEARTS = 2
SPADES = 3

class Deck:
    def __init__(self):
        self.default = {
            CLUBS: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13],
            DIAMONDS: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13],
            HEARTS: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13],
            SPADES: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]
        }
        self.current = {
            CLUBS: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13],
            DIAMONDS: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13],
            HEARTS: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13],
            SPADES: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]
        }
    
    def deal_cards(self, num_players, num_cards):
        if num_players * num_cards > 52:
            raise ValueError("The deck does not hold enough cards")
        hands = []
        curr_hand = []
        for player in range(num_players):
            for hand in range(num_cards):
                curr_hand.append(self.random_card())
            hands.append(curr_hand)
            curr_hand = []
        return hands

    def random_card(self):
        suit = random.choice(list(self.current.keys()))
        idx = random.randint(0, len(self.current[suit]) - 1)
        value = self.current[suit].pop(idx)
        if len(self.current[suit]) == 0:
            self.current.pop(suit)
        return {"suit": suit, "value": value}

    def shuffle(self):
        self.current = self.default

    def current_deck(self):
        return self.current