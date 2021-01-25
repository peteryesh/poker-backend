## Card Ranks ##
# 0: high card
# 1: pair
# 2: two pair
# 3: trips
# 4: straight
# 5: flush
# 6: full house
# 7: quads
# 8: straight flush
# 9: royal flush

class PokerHand:
    def __init__(self, cards):
        # assumed to be sorted
        self.cards = sorted(cards, key=lambda x: x["value"])
        self.rank = 0
        self.value = 0
        self.tiebreaker = 0

        self.rank, self.value, self.tiebreaker = self.check_match()

        straight_rank, straight_val, straight_tie = self.check_straight(self.cards)
        if straight_rank > self.rank:
            self.rank = straight_rank
            self.value = straight_val
            self.tiebreaker = straight_tie
        sf_rank, sf_val, sf_tie = self.check_straight_flush(self.cards)
        if sf_rank > self.rank:
            self.rank = sf_rank
            self.value = sf_val
            self.tiebreaker = sf_tie
    
    def __str__(self):
        return "rank: " + str(self.rank) + ", value: " + str(self.value) + ", tiebreaker: " + str(self.tiebreaker)
    
    def __eq__(self, opp):
        if isinstance(opp, PokerHand):
            return self.rank == opp.rank and self.value == opp.value and self.tiebreaker == opp.tiebreaker
        return NotImplemented
    
    def __lt__(self, opp):
        if isinstance(opp, PokerHand):
            if self.rank < opp.rank or self.rank == opp.rank and self.value < opp.value or self.rank == opp.rank and self.value == opp.value and self.tiebreaker < opp.tiebreaker:
                return True
            return False 
        return NotImplemented
    
    def __gt__(self, opp):
        if isinstance(opp, PokerHand):
            if self.rank > opp.rank or self.rank == opp.rank and self.value > opp.value or self.rank == opp.rank and self.value == opp.value and self.tiebreaker > opp.tiebreaker:
                return True
            return False 
        return NotImplemented
    
    def check_match(self):
        # "suit": suit, "value": value, "revealed": False
        rank = 0
        val = 0
        sec = 0
        high = 0

        curr = 0
        count = 0
        for i in range(len(self.cards)+1):
            if i == len(self.cards):
                if count == 1:
                    high = curr
                elif count == 2 and rank < 2:
                    rank += 1
                    sec = val
                    val = curr
                elif count == 2 and rank == 2:
                    if sec > high:
                        high = sec
                    sec = val
                    val = curr
                elif count == 2 and rank == 3 or count == 2 and rank == 6:
                    rank = 6
                    sec = curr
                elif count == 3 and rank < 7 and val:
                    rank = 6
                    sec = val
                    val = curr
                elif count == 3 and rank < 7:
                    rank = 3
                    sec = val
                    val = curr
                elif count == 4:
                    rank = 7
                    sec = val
                    val = curr
            elif self.cards[i]["value"] == curr:
                count += 1
            else:
                if count == 1:
                    high = curr
                elif count == 2 and rank < 2:
                    rank += 1
                    sec = val
                    val = self.cards[i-1]["value"]
                elif count == 2 and rank == 2:
                    if sec > high:
                        high = sec
                    sec = val
                    val = self.cards[i-1]["value"]
                elif count == 2 and rank == 3 or count == 2 and rank == 6:
                    rank = 6
                    sec = self.cards[i-1]["value"]
                elif count == 3 and rank < 7 and val:
                    rank = 6
                    sec = val
                    val = self.cards[i-1]["value"]
                elif count == 3 and rank < 7:
                    rank = 3
                    sec = val
                    val = self.cards[i-1]["value"]
                elif count == 4:
                    rank = 7
                    sec = val
                    val = self.cards[i-1]["value"]
                
                curr = self.cards[i]["value"]
                count = 1
        if rank == 0:
            return (rank, high, 0)
        elif rank == 2:
            tb = sec * 14 + high
            return (rank, val, tb)
        elif rank == 6:
            return (rank, val, sec)
        else:
            return (rank, val, high)
    
    def check_straight(self, cards):
        val = 0
        count = 0
        prev = 0
        if cards[-1]["value"] == 14:
            count += 1
            prev = 1
        for i in range(len(cards)):
            if cards[i]["value"] - prev == 1:
                count += 1
            elif cards[i]["value"] - prev == 0:
                pass
            else:
                count = 1
            if count >= 5:
                val = cards[i]["value"]
            prev = cards[i]["value"]
        if val > 0:
            return (4, val, 0)
        else:
            return (0, 0, 0)

    def check_straight_flush(self, cards):
        suits = {}
        for card in cards:
            if card["suit"] not in suits:
                suits[card["suit"]] = []
                suits[card["suit"]].append(card)
            else:
                suits[card["suit"]].append(card)
        for suit in suits:
            if len(suits[suit]) >= 5:
                rank, val, tie = self.check_straight(suits[suit])
                if rank > 0 and val == 14:
                    return (9, 14, 0)
                elif rank > 0 and val < 14:
                    return (8, val, 0)
                else:
                    return (5, suits[suit][-1]["value"], 0)
        return (0, 0, 0)