import itertools
import unittest

import mock

from cardboard import core as c, exceptions as exc
from cardboard.events import events
from cardboard.tests.util import ANY, last_events, pool


class TestManaPool(unittest.TestCase):
    def test_repr(self):
        o = mock.Mock()
        m = c.ManaPool(o)
        self.assertEqual(repr(m), "[0B, 0G, 0R, 0U, 0W, 0]")

        m.black, m.green, m.red, m.blue, m.white, m.colorless = range(1, 7)
        self.assertEqual(repr(m), "[1B, 2G, 3R, 4U, 5W, 6]")


class TestPlayer(unittest.TestCase):
    def setUp(self):
        self.game = mock.Mock()
        self.game.players = []

        def add_existing_player(p):
            self.game.players.append(p)
            p.game = self.game

        self.game.add_existing_player.side_effect = add_existing_player

    def test_repr_str(self):
        p1 = c.Player(library=[], name="Test")
        self.game.add_existing_player(p1)

        self.assertEqual(repr(p1), "<Player 1: Test>")

        p2 = c.Player(library=[], name="")
        self.game.add_existing_player(p2)

        self.assertEqual(repr(p2), "<Player 2>")

        p3 = c.Player(library=[], name="Test")
        self.assertEqual(repr(p3), "<Player (not yet in game): Test>")

        p4 = c.Player(library=[], name="")
        self.assertEqual(repr(p4), "<Player (not yet in game)>")


class TestSubscribers(unittest.TestCase):
    def setUp(self):
        self.events = mock.Mock()
        self.game = c.Game(self.events)

    def assertSubscribed(self, fn, pool=True, **kwargs):
        if pool:
            kwargs.update(needs=["pool"])

        self.assertIn(((fn,), kwargs), self.events.subscribe.call_args_list)

    def test_end(self):
        self.assertSubscribed(self.game.end_if_dead, event=events.player.died)


class TestBehavior(unittest.TestCase):
    def setUp(self):
        self.events = mock.Mock()
        self.game = c.Game(self.events)
        self.p1 = self.game.add_player(library=[], life=1, hand_size=0)
        self.p2 = self.game.add_player(library=[], life=1, hand_size=0)
        self.game.start()

    def test_initialize_turn_and_phase(self):
        self.assertIs(self.game.turn, self.p1)
        self.assertEqual(self.game.phase, "beginning")
        self.assertEqual(self.game.subphase, "untap")

    def test_next_phase(self):
        self.game.next_turn = mock.Mock()

        for phase, subphase in [("beginning", "draw"),
                                ("beginning", "upkeep"),
                                ("first_main", None),
                                ("combat", "beginning"),
                                ("combat", "declare_attackers"),
                                ("combat", "declare_blockers"),
                                ("combat", "combat_damage"),
                                ("combat", "end"),
                                ("second_main", None),
                                ("ending", "end"),
                                ("ending", "cleanup")]:

            self.game.next_phase()
            self.assertEqual(self.game.phase, phase)
            self.assertEqual(self.game.subphase, subphase)

        # check calls next_turn at end of last subphase
        self.assertFalse(self.game.next_turn.called)
        self.game.next_phase()
        self.assertTrue(self.game.next_turn.called)

    def test_phase_set(self):
        # just move to the middle of a turn somewhere
        for i in range(6):
            self.game.next_phase()

        self.assertIs(self.game.turn, self.p1)
        self.assertNotEquals(self.game.phase, "beginning")
        self.assertNotEquals(self.game.subphase, "untap")

        self.game.phase = "beginning"

        self.assertIs(self.game.turn, self.p1)
        self.assertEquals(self.game.phase, "beginning")
        self.assertEquals(self.game.subphase, "untap")

        # check that next_phase still works
        self.test_next_phase()

    def test_phase_set_nonexisting(self):
        self.assertRaises(ValueError, setattr, self.game, "phase", object())

    def test_next_turn(self):
        self.assertIs(self.game.turn, self.p1)
        self.game.next_turn()
        self.assertIs(self.game.turn, self.p2)
        self.assertEqual(self.game.phase, "beginning")
        self.assertEqual(self.game.subphase, "untap")

    def test_turn_set(self):
        events = mock.Mock()
        game = c.Game(events)
        p1 = game.add_player(library=[], life=1, hand_size=0)
        p2 = game.add_player(library=[], life=2, hand_size=0)
        p3 = game.add_player(library=[], life=3, hand_size=0)
        game.start()

        game.turn = p3

        self.assertIs(game.turn, p3)
        self.assertEqual(game.phase, "beginning")
        self.assertEqual(game.subphase, "untap")

    def test_turn_set_nonexisting(self):
        self.assertRaises(ValueError, setattr, self.game, "turn", object())

    def test_next_turn_from_middle(self):
        # just move to the middle of a turn somewhere
        for i in range(4):
            self.game.next_phase()

        self.game.next_turn()
        self.assertIs(self.game.turn, self.p2)
        self.assertEqual(self.game.phase, "beginning")
        self.assertEqual(self.game.subphase, "untap")

    def test_unstarted_game(self):
        game = c.Game(mock.Mock())

        self.assertIs(game.ended, None)

        self.assertIs(game.turn, None)
        self.assertIs(game.phase, None)
        self.assertIs(game.subphase, None)

        self.assertFalse(game.started)

        self.assertRaises(exc.RuntimeError, setattr, game, "phase", "ending")
        self.assertRaises(exc.RuntimeError, setattr, game, "turn", object())
        self.assertRaises(exc.RuntimeError, game.next_phase)
        self.assertRaises(exc.RuntimeError, game.next_turn)

    def test_no_player_game(self):
        game = c.Game(mock.Mock())
        self.assertRaises(exc.RuntimeError, game.start)

    def test_life(self):
        self.assertFalse(self.p1.dead)
        self.p1.life -= 2
        self.assertTrue(self.p1.dead)

    def test_die(self):
        self.assertFalse(self.p1.dead)
        self.p1.die()
        self.assertTrue(self.p1.dead)

    def test_die_nonexisting_reason(self):
        self.assertRaises(ValueError, self.p1.die, "something")

    def test_draw(self):
        self.p1.library = [0]
        self.p1.draw()
        self.assertEqual(self.p1.hand, {0})

        self.p2.library = range(5)
        self.p2.draw(5)
        self.assertEqual(self.p2.hand, set(range(5)))

    def test_dont_die_when_drawing_zero_cards(self):
        self.assertFalse(self.p1.dead)
        self.p1.draw(0)
        self.assertFalse(self.p1.dead)

    def test_negatives(self):
        self.assertRaises(ValueError, self.p1.draw, -1)
        self.assertRaises(ValueError, setattr, self.p1.mana_pool, "black", -1)

    def test_end(self):
        self.game.end()
        self.assertTrue(self.game.ended)

    def test_end_if_dead(self):
        events = mock.Mock()
        game = c.Game(events)
        p1 = game.add_player(library=[], life=1, hand_size=0)
        p2 = game.add_player(library=[], life=2, hand_size=0)
        p3 = game.add_player(library=[], life=3, hand_size=0)
        game.start()

        game.end_if_dead()
        self.assertFalse(game.ended)

        p1.die()
        game.end_if_dead()
        self.assertFalse(game.ended)

        p2.die()
        game.end_if_dead()
        self.assertTrue(game.ended)


class TestEvents(unittest.TestCase):
    def setUp(self):
        self.events = mock.Mock()
        self.game = c.Game(self.events)
        self.p1 = self.game.add_player(library=[], life=1, hand_size=0)
        self.p2 = self.game.add_player(library=[], life=2, hand_size=0)

    def assertHeard(self, event, request=False, handler=None):
        if handler is None:
            handler = self.events

        e = pool(event=event)
        r = pool(request=event)

        if not request:
            return handler.trigger.assert_called_with(**e)

        arg_list = handler.trigger.call_args_list
        self.assertEqual(handler.trigger.call_args_list[-2:], [[r], [e]])

    def assertNotHeard(self, event, request=False, handler=None):
        try:
            self.assertHeard(event, request, handler)
        except (AssertionError, IndexError):
            return
        else:
            self.fail("{} was triggered by {}.".format(event, handler))

    def test_game_started(self):
        self.game.start()
        self.assertEqual(self.events.trigger.call_args_list[0],
                         [{"event" : events.game.started}])

    def test_phase_set(self):
        self.game.start()

        self.game.phase = "combat"

        calls = [[pool(request=events.game.phases.combat)],
                 [pool(event=events.game.phases.combat)],
                 [pool(request=events.game.phases.combat.beginning)],
                 [pool(event=events.game.phases.combat.beginning)]]

        self.assertEqual(self.events.trigger.call_args_list[-4:], calls)

    def test_next_phase(self):
        t = self.events.trigger.call_args_list

        self.game.start()

        for _ in range(2):
            for phase in events.game.phases:
                calls = [[pool(request=phase)],
                         [pool(event=phase)]]

                phase = iter(phase)
                first_subphase = next(phase, None)

                if first_subphase is not None:
                    calls.extend([[pool(request=first_subphase)],
                                  [pool(event=first_subphase)]])

                self.assertEqual(t[-len(calls):], calls)

                for subphase in phase:
                    calls = [[pool(request=subphase)],
                             [pool(event=subphase)]]

                    self.game.next_phase()
                    self.assertEqual(t[-2:], calls)

                self.game.next_phase()

    def test_next_turn(self):
        self.game.start()
        self.game.next_turn()

        calls = [[pool(request=events.game.turn.changed)],
                 [pool(event=events.game.turn.changed)],
                 [pool(request=events.game.phases.beginning)],
                 [pool(event=events.game.phases.beginning)],
                 [pool(request=events.game.phases.beginning.untap)],
                 [pool(event=events.game.phases.beginning.untap)]]

        self.assertEqual(self.events.trigger.call_args_list[-6:], calls)

    def test_die(self):
        self.p1.die()
        self.assertHeard(events.player.died, request=True)

    def test_life_changed(self):
        self.p1.life += 2
        self.assertHeard(events.player.life.gained, request=True)

        self.p1.life -= 2
        self.assertHeard(events.player.life.lost, request=True)

    def test_life_not_changed(self):
        self.p1.life += 0
        self.assertNotHeard(events.player.life.gained, request=True)
        self.assertNotHeard(events.player.life.lost, request=True)

    def test_card_drawn(self):
        self.p1.library = [1]
        self.p1.draw()
        self.assertHeard(events.player.draw, request=True)

        def side_effect(*args, **kwargs):
            if events.player.draw in kwargs.viewvalues():
                self.fail("Unexpected card draw")
            return mock.DEFAULT

        self.events.trigger.side_effect = side_effect

        self.p1.draw()
        self.assertHeard(events.player.died)

    def test_mana_changed(self):
        self.p1.mana_pool.red += 0
        self.assertNotHeard(events.player.mana.red.added, request=True)

        self.p1.mana_pool.red += 1
        self.assertHeard(events.player.mana.red.added, request=True)

        self.p1.mana_pool.red -= 1
        self.assertHeard(events.player.mana.red.removed, request=True)

    def test_end(self):
        self.game.start()
        self.game.end()
        self.assertHeard(events.game.ended)
