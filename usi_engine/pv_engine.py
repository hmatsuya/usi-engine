import cshogi
from cshogi.usi import Engine

import re

import logging

# logging.basicConfig(
#     format='%(asctime)s[%(levelname)s] %(message)s',
#     level=logging.DEBUG,
#     datefmt='%Y-%m-%d %H:%M:%S')


class PVEngine(cshogi.usi.Engine):
    engine_count = 0

    def __init__(self, *args, **kwargs):
        logging.debug("in PVEngine.__init__()")
        self.multipv = kwargs.pop('multipv', None)
        self.print = kwargs.pop('print', False)
        self.debug = kwargs.pop('debug', False)
        self.info= kwargs.pop('info', False)
        self.id = kwargs.pop('id', 'na')
        self.options = {} # for crash recovery
        super().__init__(*args, **kwargs)

        self.scores = [None]
        self.pvs = [None]
        # self.pv_prog = re.compile('^info .*pv (.*)')
        self.pv_prog = re.compile('^info.*? pv (?P<pv>.*)')
        self.multipv_prog = re.compile(r'multipv (?P<pvnum>\d+)')
        self.clear_result()
        if self.multipv:
            self.setoption('multipv', self.multipv)

        self.score_prog = re.compile(r'score (cp|mate) ((-|\+)?\d+)')

        self.id = self.engine_count
        self.engine_count += 1

    def clear_result(self):
        if self.multipv:
            self.scores = [None] * self.multipv
            self.pvs = [None] * self.multipv
        else:
            self.scores = [None]
            self.pvs = [None]

    def setoption(self, *args, **kwargs):
        # save option for crash recovery
        self.options[args[0]] = args[1]

        super().setoption(*args, **kwargs)
        logging.debug(f'in setoption(): {args}: {kwargs}')

        # multipv settings
        if args[0].strip().lower() == 'multipv' and int(args[1]) > 1:
            logging.debug(f'"multipv" option found: {args}')
            self.multipv = int(args[1])
            self.clear_result()

    def position(self, *args, **kwargs):
        self.current_position = kwargs
        # restart proc if it's dead
        if self.proc.poll() is not None:
            logging.warning('the engine proc is dead in position(). restarting...')
            self.restart_engine()
            return # position is set when restarting engine
        super().position(*args, **kwargs)

    def pv_listener(self, line):
        logging.debug(f"in PVEngine.pv_listener(): engine={self.id}")
        logging.debug(f"line: {line}")

        # if (self.print or self.debug) and not line.startswith('bestmove'):
        if (self.print or self.debug) or (self.info and line.startswith('info')):
            if len(line.strip()) > 0:
                print(line, flush=True)

        # check if pv is in line
        match = self.pv_prog.match(line)
        if match is None:
            return
        logging.debug(f'match.groups(): {match.groups()}')

        # if self.multipv:
        #     if match.group('pvnum'):
        #         pvnum = int(match.group('pvnum')) - 1
        #     else:
        #         pvnum = 0
        #     assert(pvnum >= 0)
        #     assert(pvnum < self.multipv)
        #     self.pvs[pvnum] = match.group('pv').strip()
        # else:
        #     pvnum = 0
        #     self.pvs[pvnum] = match.group(1).strip()

        multipv_match = self.multipv_prog.search(line)
        logging.debug(f'muitipv_match: {multipv_match}')
        if multipv_match:
            pvnum = int(multipv_match.group('pvnum')) - 1
        else:
            pvnum = 0
        logging.debug(f'pvnum: {pvnum}')
        assert(pvnum >= 0)
        assert(self.multipv is None or pvnum < self.multipv)
        self.pvs[pvnum] = match.group('pv').strip()

        # extract score
        score_match = self.score_prog.search(line)
        # assert (score_match is not None), f'score_match is None: {line}'
        if score_match is None:
            self.scores[pvnum] = min(score for score in self.scores if score is not None)
        else:
            logging.debug(f'score_match.groups(): {score_match.groups()}')
            if score_match.group(1) == 'cp':
                self.scores[pvnum] = int(score_match.group(2))
                assert(isinstance(self.scores[pvnum], int))
            elif score_match.group(1) == 'mate':
                if score_match.group(2).find('-') == -1:
                    self.scores[pvnum] = 30000
                else:
                    self.scores[pvnum] = -30000

        assert(isinstance(self.scores[pvnum], int))

    def go(self, ponder=False, btime=None, wtime=None, byoyomi=None, binc=None, winc=None, nodes=None, listener=None):
        self.clear_result()

        # if self.debug: listener = print
        listener = self.pv_listener

        cmd = 'go'
        if ponder:
            cmd += ' ponder'
        else:
            if btime is not None:
                cmd += ' btime ' + str(btime)
            if wtime is not None:
                cmd += ' wtime ' + str(wtime)
            if byoyomi is not None:
                cmd += ' byoyomi ' + str(byoyomi)
            else:
                if binc is not None:
                    cmd += ' binc ' + str(binc)
                if winc is not None:
                    cmd += ' winc ' + str(winc)
            if nodes is not None:
                cmd += ' nodes ' + str(nodes)
        if listener:
            listener(cmd)
        self.proc.stdin.write(cmd.encode('ascii') + b'\n')
        self.proc.stdin.flush()

        while True:

            # restart proc if it's dead
            if self.proc.poll() is not None:
                logging.warning('the engine proc is dead in go(). restarting...')
                self.restart_engine()
                self.proc.stdin.write(cmd.encode('ascii') + b'\n')
                self.proc.stdin.flush()

            self.proc.stdout.flush()
            line = self.proc.stdout.readline()
            if line == '':
                raise EOFError()
            line = line.strip().decode('ascii')
            if listener:
                listener(line)
            if line[:8] == 'bestmove':
                items = line[9:].split(' ')
                if len(items) == 3 and items[1] == 'ponder':
                    return items[0], items[2]
                else:
                    return items[0], None

    def restart_engine(self):
        self.connect(listener=logging.debug)
        for name, value in self.options.items():
            self.setoption(name, value)
        self.isready(listener=logging.debug)
        logging.debug(f'setting position again: {self.current_position}')
        self.position(**self.current_position)

    def stop(self, listener=None):
        if self.debug: listener = print
        cmd = 'stop'
        if listener:
            listener(cmd)
        self.proc.stdin.write(cmd.encode('ascii') + b'\n')
        self.proc.stdin.flush()

        while True:
            self.proc.stdout.flush()
            line = self.proc.stdout.readline()
            if line == '':
                raise EOFError()
            line = line.strip().decode('ascii')
            if listener:
                listener(line)
            if line[:8] == 'bestmove':
                items = line[9:].split(' ')
                if len(items) == 3 and items[1] == 'ponder':
                    return items[0], items[2]
                else:
                    return items[0], None