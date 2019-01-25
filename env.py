import os
import json
import types
import datetime
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.ticker import FuncFormatter
from mpl_finance import candlestick_ochl
from gym.core import GoalEnv
import logging


logger = logging.getLogger('gym-trading')


class Observation(object):
    __slots__ = ["open", "close", "high", "low", "index",
                 "date", "date_string", "format_string"]

    def __init__(self, **kwargs):
        self.index = kwargs.get('index', 0)
        self.open = kwargs.get('open', 0)
        self.close = kwargs.get('close', 0)
        self.high = kwargs.get('high', 0)
        self.low = kwargs.get('low', 0)
        self.date_string = kwargs.get('date', '')
        self.date = self._format_time(self.date_string)

    @property
    def math_date(self):
        return mdates.date2num(self.date)

    def _format_time(self, date):
        d_f = date.count('-')
        t_f = date.count(':')
        if d_f == 2:
            date_format = "%Y-%m-%d"
        elif d_f == 1:
            date_format = "%m-%d"
        else:
            date_format = ''

        if t_f == 2:
            time_format = '%H:%M:%s'
        elif t_f == 1:
            time_format = '%H:%M'
        else:
            time_format = ''
        self.format_string = " ".join([date_format, time_format]).rstrip()
        return datetime.datetime.strptime(date, self.format_string)

    def to_ochl(self):
        return [self.open, self.close, self.high, self.low]

    def to_list(self):
        return [self.index] + self.to_ochl()

    def __str__(self):
        return "date: {self.date}, open: {self.open}, close:{self.close}," \
            " high: {self.high}, low: {self.low}".format(self=self)

    @property
    def latest_price(self):
        return self.close


class DataManager(object):

    def __init__(self, data=None,
                 data_path=None,
                 data_func=None,
                 previous_steps=None):
        if data is not None:
            if isinstance(data, list):
                data = data
            elif isinstance(data, types.GeneratorType):
                data = list(data)
            else:
                raise ValueError('data must be list or generator')
        elif data_path is not None:
            data = self.load_data(data_path)
        elif data_func is not None:
            data = self.data_func()
        else:
            raise ValueError(
                "The argument `data_path` or `data_func` is required.")
        self.data = list(self._to_observations(data))
        self.index = 0
        self.max_steps = len(self.data)

    def _to_observations(self, data):
        for i, item in enumerate(data):
            item['index'] = i
            yield Observation(**item)

    def _load_json(self, path):
        with open(path) as f:
            data = json.load(f)
        return data

    def _load_pd(self, path):
        pass

    def load_data(self, path=None):
        filename, extension = os.path.splitext(path)
        if extension == '.json':
            data = self._load_json(path)
        return data

    @property
    def current_step(self):
        return self.data[self.index]

    @property
    def history(self):
        return self.data[:self.index]

    @property
    def total(self):
        return self.history + [self.current_step]

    def step(self):
        observation = self.current_step
        self.index += 1
        done = self.index >= self.max_steps
        return observation, done


class Exchange(object):

    class ACTION:
        PUT = -1
        HOLD = 0
        PUSH = 1

    class Positions:

        def __init__(self, symbol=''):
            self.symbol = symbol
            self.amount = 0
            self.avg_price = 0

        @property
        def principal(self):
            return self.avg_price * self.amount

        @property
        def is_empty(self):
            return self.amount == 0

        @property
        def is_do_long(self):
            return self.amount > 0

        @property
        def is_do_short(self):
            return self.amount < 0

        def get_profit(self, latest_price, unit):
            if self.is_empty:
                return 0
            else:
                diff = 0
                if self.is_do_short:
                    diff = abs(self.avg_price) - latest_price
                else:
                    diff = latest_price - abs(self.avg_price)
                profit = diff * unit
                return profit

        def update(self, action, latest_price, unit):
            if action * self.amount < 0:
                profit = self.get_profit(latest_price, unit)
            else:
                profit = 0

            amount = action * unit
            if self.amount + amount != 0:
                self.avg_price = (self.avg_price * self.amount +
                                  amount * latest_price) / (self.amount + amount)
            else:
                self.avg_price = 0
            self.amount += amount

            return profit

    def __init__(self, nav=50000, end_loss=None):
        self.position = self.Positions()
        self.nav = nav
        self.fixed_profit = 0
        self.floating_profit = 0
        self.unit = 100
        self._end_loss = end_loss

    @property
    def start_action(self):
        return self.ACTION.HOLD

    @property
    def available_funds(self):
        return self.nav - self.position.principal

    @property
    def profit(self):
        return self.fixed_profit + self.floating_profit

    @property
    def available_actions(self):
        if self.position.is_do_short:
            return [self.ACTION.PUSH, self.ACTION.HOLD]
        elif self.position.is_do_long:
            return [self.ACTION.PUT, self.ACTION.HOLD]
        else:
            return [self.ACTION.PUT, self.ACTION.HOLD, self.ACTION.PUSH]

    @property
    def cost_action(self):
        return [self.ACTION.PUT, self.ACTION.PUSH]

    @property
    def end_loss(self):
        if self._end_loss is not None:
            return self._end_loss
        return - self.latest_price * self.unit * 0.3

    @property
    def is_over_loss(self):
        return self.profit < self.end_loss

    def get_profit(self, observation, symbol='default'):
        latest_price = observation.latest_price
        positions = self.positions.values()
        positions_profite = sum([position.get_profit(
            latest_price) for position in positions])
        return self.profit + positions_profite

    def draw_title(self, observation):
        formatting = """
        profit: {} \t fixed-profit: {} \t floating-profit:{} \t
        amount: {} \t latest-price: {} \t time: {} \n
        """

        def r(x): return round(x, 2)
        title = formatting.format(r(self.profit),
                                  r(self.fixed_profit),
                                  r(self.floating_profit),
                                  self.position.amount,
                                  observation.latest_price,
                                  observation.date_string)
        plt.suptitle(title)

    def get_charge(self, action, observation):
        """
            rewrite if inneed.
        """
        return 3

    def step(self, action, observation, symbol='default'):
        latest_price = observation.latest_price
        self.latest_price = latest_price

        if action in self.available_actions:
            fixed_profit = self.position.update(
                action, latest_price, self.unit)
        else:
            fixed_profit = 0
        if action in self.cost_action:
            fixed_profit -= self.get_charge(action, observation)
        self.floating_profit = self.position.get_profit(
            latest_price, self.unit)
        self.fixed_profit += fixed_profit

        self.draw_title(observation)
        logger.debug("observation:{} action:{}".format(observation, action))
        print("observation:{} action:{}".format(observation, action))
        logger.debug("fixed_profit: {}, floating_profit: {}".format(
            self.fixed_profit, self.floating_profit))
        print("fixed_profit: {}, floating_profit: {}, profit: {}".format(
            self.fixed_profit, self.floating_profit, self.profit))
        return self.profit


class Arrow(object):

    def __init__(self, coord, color):
        self.coord = coord
        self.color = color


class Render(object):

    def __init__(self, bar_width=0.5):
        plt.ion()
        self.figure, self.ax = plt.subplots()
        self.figure.set_size_inches((12, 6))
        self.bar_width = 0.5
        self.arrow_body_len = self.bar_width / 1000
        self.arrow_head_len = self.bar_width / 50
        self.arrow_width = self.bar_width
        self.max_windows = 60

        self.arrows = []

    @property
    def arrow_len(self):
        return self.arrow_body_len + self.arrow_head_len

    def take_action(self, action, observation):
        if action == Exchange.ACTION.PUT:
            y_s = observation.high + self.arrow_body_len + self.arrow_head_len
            y_e = - self.arrow_body_len
            color = 'gray'
        elif action == Exchange.ACTION.PUSH:
            y_s = observation.high
            y_e = self.arrow_body_len
            color = 'black'
        else:
            return
        x = observation.index
        self.arrows.append(Arrow((x, y_s, 0, y_e), color))

    def draw_arrow(self, data):
        first = data[0]
        arrows = list(filter(lambda x: x.coord[0] > first[0], self.arrows))
        for arrow in arrows:
            self.ax.arrow(*arrow.coord,
                          color=arrow.color,
                          head_width=self.arrow_width,
                          head_length=self.arrow_head_len)

        self.arrows = arrows

    def xaxis_format(self, history):
        def formator(x, pos=None):
            for h in history:
                if h.index == x:
                    return h.date.strftime("%H:%M")
            return ""
        return formator

    def render(self, history, mode='human', close=False):
        """
            If it plot one by one will cache many point
            that will cause OOM and work slow.
        """
        self.ax.clear()
        history = history[-self.max_windows:]
        data = [obs.to_list() for obs in history]
        candlestick_ochl(self.ax, data, colordown='g',
                         colorup='r', width=self.bar_width)
        self.draw_arrow(data)

        self.ax.xaxis.set_major_formatter(
            FuncFormatter(self.xaxis_format(history)))
        self.ax.set_ylabel('price')
        self.figure.autofmt_xdate()
        plt.show()
        plt.pause(0.0001)


class TradeEnv(GoalEnv):

    def __init__(self,
                 data=None,
                 data_path=None,
                 data_func=None,
                 previous_steps=60,
                 max_episode=200):
        self.init_env_fn = self.__init_env_fn(
            data, data_path, data_func, previous_steps)
        self.init_env_fn()

    def __init_env_fn(self, data, data_path, data_func, previous_steps):
        def init():
            self.data = DataManager(data, data_path, data_func, previous_steps)
            self.exchange = Exchange()
            self._render = Render()
        return init

    def _step(self, action):
        observation, done = self.data.step()
        if action in self.exchange.available_actions:
            self._render.take_action(action, observation)
        reward = self.exchange.step(action, observation)

        if self.exchange.is_over_loss:
            done = True

        return observation, reward, done

    def step(self, action):
        observation, reward, done = self._step(action)

        info = {}
        return observation, reward, done, info

    def reset(self):
        return self.step(self.exchange.start_action)

    def render(self):
        history = self.data.history
        self._render.render(history)

    def close(self):
        return