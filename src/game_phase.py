from enum import Enum

class GamePhase(Enum):
    INITIAL = 0,
    FLOP = 1,
    TURN = 2,
    RIVER = 3,
    SHOWDOWN = 4