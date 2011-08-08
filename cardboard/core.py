"""
Cardboard core

"""

from operator import attrgetter, methodcaller
from functools import wraps
import itertools

from cardboard.collaborate import collaborate
from cardboard.events import events
from cardboard import exceptions


def _make_color(name):

    _color = "_" + name
    negative_error = "{} mana pool would be negative.".format(name.title())
    color_events = getattr(events.player.mana, name)

    @property
    def color(self):
        return getattr(self, _color)

    @color.setter
    @collaborate()
    def color(self, amount):
        """
        Set the number of mana in the {color} mana pool.

        """.format(color=name)

        current = getattr(self, name)

        if amount < 0:
            raise ValueError(negative_error)
        elif amount == current:
            return

        pool = (yield)
        pool.update(amount=amount, color=name)

        if amount > current:
            event = color_events.added
        else:
            event = color_events.removed

        yield event
        yield
        setattr(self, "_" + pool["color"], pool["amount"])
        yield event

    return color


class ManaPool(object):
    COLORS = ("black", "green", "red", "blue", "white", "colorless")

    black = _make_color("black")
    green = _make_color("green")
    red = _make_color("red")
    blue = _make_color("blue")
    white = _make_color("white")
    colorless = _make_color("colorless")

    def __init__(self, owner):
        super(ManaPool, self).__init__()
        self.owner = owner
        self.game = self.owner.game

        for color in self.COLORS:
            setattr(self, "_" + color, 0)

    def __repr__(self):
        pool = (getattr(self, c) for c in self.COLORS)
        return "[{}B, {}G, {}R, {}U, {}W, {}]".format(*pool)


class Player(object):
    """
    A player.

    """

    def __init__(self, game, library, hand_size=7, life=20, name=""):
        super(Player, self).__init__()

        self.name = name

        self.game = game

        self.dead = False
        self._life = int(life)

        self.hand = set()
        self.library = library
        self.draw(hand_size)

        self.exiled = set()
        self.graveyard = []
        self.mana_pool = ManaPool(self)

    def __repr__(self):
        number = self.game.players.index(self)
        return "<Player {}: {.name}>".format(number, self)

    @property
    def life(self):
        return self._life

    @life.setter
    @collaborate()
    def life(self, amount):

        if amount == self.life:
            return

        pool = (yield)
        pool.update(player=self, amount=amount)

        if amount > self.life:
            event = events.player.life.gained
        else:
            event = events.player.life.lost

        yield event
        yield

        pool["player"]._life = amount
        yield event

        if pool["player"].life <= 0:
            pool["player"].die()

    @collaborate()
    def die(self, reason="life"):
        """
        End the player's sorrowful life.

        Arguments:

            * reason (default="life")
                * one of: "life", "library", "poison", <a card>

        """

        # FIXME: Make card valid
        if reason not in {"life", "library", "poison"}:
            err = "Oh come now, you can't die from '{}'"
            raise ValueError(err.format(reason))

        pool = (yield)
        pool.update(player=self, reason=reason)

        yield events.player.died
        yield

        self.dead = True
        yield events.player.died

    @collaborate()
    def draw(self, cards=1):
        """
        Draw cards from the library.


        """

        if not cards:
            return
        elif cards < 0:
            raise ValueError("Can't draw a negative number of cards.")

        if not self.library:
            self.die(reason="library")
            return

        # FIXME: We are dying multiple times here I think.
        if cards > 1:
            for i in range(cards):
                self.draw()
            return

        pool = (yield)
        pool.update(player=self, source=self.library,
                    destination=self.hand,
                    source_get=methodcaller("pop"),
                    destination_add=attrgetter("add"))

        yield events.player.draw
        yield

        card = pool["source_get"](pool["source"])
        pool["destination_add"](pool["destination"])(card)

        yield events.player.draw


def _game_ender(game):
    @game.events.subscribe(event=events.player.died, needs=["pool"])
    @collaborate()
    def end_game(pangler, pool):
        """
        End the game if there is only one living player left.

        """

        if sum(1 for player in game.players if player.dead) > 1:
            return

        # TODO: Stop all other events
        pool = (yield)

        yield events.game.ended
        yield

        self.game_over = True
        yield events.game.ended

    return end_game


def check_started(fn):
    @wraps(fn)
    def _check_started(self, *args, **kwargs):
        if not self.started:
            raise exceptions.RuntimeError("{} has not started.".format(self))
        return fn(self, *args, **kwargs)
    return _check_started


class Game(object):
    """
    The Game object maintains information about the current game state.

    """

    def __init__(self, handler):
        """
        Initialize a new game state object.

        """

        super(Game, self).__init__()

        self.events = handler

        self.end_game = _game_ender(self)

        self._phases = itertools.cycle(p.name for p in events.game.phases)
        self._subphases = iter([])  # Default value for first advance

        self.game_over = None
        self._phase = None
        self._subphase = None
        self._turn = None

        self.field = set()
        self.tapped = set()
        self.players = []

    def __repr__(self):
        return "<{} Player Game>".format(len(self.players))

    @property
    def phase(self):
        if self._phase is not None:
            return self._phase.name

    @phase.setter
    @collaborate()
    @check_started
    def phase(self, new):
        phase = getattr(events.game.phases, str(new), None)

        if phase is None:
            raise ValueError("No phase named {}".format(new))

        pool = (yield)
        yield phase
        yield

        while next(self._phases) != phase.name:
            pass

        self._phase = phase

        yield phase

        self._subphases = iter(s.name for s in phase)
        self.subphase = next(self._subphases, None)

    @property
    def subphase(self):
        if self._subphase is not None:
            return self._subphase.name

    @subphase.setter
    @collaborate()
    @check_started
    def subphase(self, new):
        if new is None:
            self._subphase = None
            return

        subphase = getattr(self._phase, str(new))

        pool = (yield)
        yield subphase
        yield

        self._subphase = subphase

        yield subphase

    @property
    def turn(self):
        return self._turn

    @turn.setter
    @collaborate()
    @check_started
    def turn(self, player):
        if player not in self.players:
            raise ValueError("{} has no player '{}'".format(self, player))

        pool = (yield)
        pool.update(player=player)

        yield events.game.turn.changed
        yield

        self._turn = player

        yield events.game.turn.changed

        self.phase = "beginning"

    def add_player(self, *args, **kwargs):
        player = Player(game=self, *args, **kwargs)
        self.players.append(player)
        return player

    def next_phase(self):
        """
        Advance a turn to the next phase.

        """

        if self.phase == "ending" and self.subphase == "cleanup":
            self.next_turn()
            return

        try:
            self.subphase = next(self._subphases)
        except StopIteration:
            self.phase = next(self._phases)

    @check_started
    def next_turn(self):
        """
        Advance the game to the next player's turn or to a specified player's.

        """

        self.turn = next(self._turns)

    @property
    def started(self):
        return self.game_over is not None

    def start(self):
        if not self.players:
            raise exceptions.RuntimeError("Starting the game requires at least"
                                          " one player.")

        self.events.trigger(event=events.game.started)

        self._turns = itertools.cycle(self.players)
        self.game_over = False

        self.next_turn()
