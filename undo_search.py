#!/usr/bin/env python3
import time, sys, os
import chess.uci, chess.pgn
import sqlite3
from search_depth import *
import collections

ONE_SIDE_ONLY_FLAG = True
UNDO_COLOR = chess.WHITE
TABLEBASE31_FLAG = False
TABLEBASE31_DRAW_LOST_COLOR = chess.BLACK
TABLEBASE31_CAPTURE_SEARCH_FLAG = False

WORST_SCORE = -1*10**7
MATE_SCORE = 10**6
TABLEBASE_SCORE = 10**4
USE_LINKS_FLAG = True

def color2string(turn):
    if turn==chess.WHITE: return "white"
    else: return "black"

class LinkBoard:
    def __init__(self, pos, turn):
        self.pos = pos
        self.turn = turn
        self.transpositions = collections.Counter()
        self.transpositions.update((self.pos,))
        self.pos_stack = collections.deque()

    def push(self, pos2):
        self.pos_stack.append(self.pos)
        self.pos = pos2
        self.transpositions.update((pos2,))
        self.turn = not self.turn
        return pos2

    def pop(self):
        pos2 = self.pos
        self.transpositions.subtract((pos2,))
        self.pos = self.pos_stack.pop()
        self.turn = not self.turn
        return pos2
                

class UndoSearch:
    def __init__(self, nodes2search):
        self.nodes2search = nodes2search
        self.log = Log("variation_%i" % (self.nodes2search,))
        if TABLEBASE31_FLAG:
            self.log.print_s("tablebase31, draw lost color: " + color2string(TABLEBASE31_DRAW_LOST_COLOR))
            if TABLEBASE31_CAPTURE_SEARCH_FLAG:
                self.log_print_s("tablebase31 capture search enabled")
        if ONE_SIDE_ONLY_FLAG:
            self.log.print_s("one side only undo, color: " + color2string(UNDO_COLOR))
        create_chess_db()
        self.db = sqlite3.connect(db_name, 60.0)
        self.c = self.db.cursor()
        self.positions = {info[POS]: list(info) for info in self.c.execute("SELECT * FROM analysis")}
        self.starting_pos = self.c.execute("SELECT fen FROM analysis WHERE ply=0").fetchall()[0][0]
        self.nodes = 0
        self.link_to = {}
        self.link_from = {}
        self.build_links()
        self.info_handler = NodeHandler(self.nodes2search)
        self.engine_dict = {}
        for engine_id, engine_script in ((asmfish_id, "stockfish_log_time"),
                                         (brainfish_id, "brainfish_log")):
            self.program_id = engine_id
            self.engine = chess.uci.popen_engine(engine_script)
            self.engine.uci()
            self.engine.info_handlers.append(self.info_handler)
            self.engine.setoption({"Hash":1024, "SyzygyPath": "/usr/games/syzygy"})
            self.engine_dict[engine_id] = (self.program_id, self.engine)
        
        self.positions2store = []
        self.history_moves = {}

    def add_link_dict(self, link_dict, move, pos1, pos2):
        d = link_dict.get(pos1, {})
        d[pos2] = move
        link_dict[pos1] = d
        self.link_count += 1

    def add_link(self, move, pos1, pos2):
        self.add_link_dict(self.link_to, move, pos1, pos2)
        #self.add_link(self.link_from, pos2, pos1)

    def build_links(self):
        self.link_count = 0
        if not USE_LINKS_FLAG:
            return
        t0 = time.time()
        for pos in self.positions:
            board = chess.Board(pos + " 0 1")
            pos2_lst = []
            if ONE_SIDE_ONLY_FLAG and board.turn!=UNDO_COLOR:
                info = self.positions[pos]
                m = info[PV].split()[0]
                board.push_uci(m)
                pos2 = fen2key(board.fen())
                if pos2 in self.positions:
                    pos2_lst = [(m, pos2)]
                #board.pop()
            else:
                for m in board.generate_legal_moves():
                    board.push(m)
                    pos2 = fen2key(board.fen())
                    if pos2 not in self.positions:
                        pos2_lst = []
                        #board.pop()
                        break
                    pos2_lst.append((str(m), pos2))
                    board.pop()
            for m, pos2 in pos2_lst:
                self.add_link(m, pos, pos2)
        time_elapsed = time.time() - t0
        self.log.print_s("%i links build in %.3fs" % (self.link_count, time_elapsed))

    def best_position(self):
        return fen2key(self.starting_pos)

    def draw_score(self, turn):
        if TABLEBASE31_FLAG:
            if turn==TABLEBASE31_DRAW_LOST_COLOR:
                #print("tablebase lost repetition")
                return -TABLEBASE_SCORE
            else:
                #print("tablebase won repetition")
                return TABLEBASE_SCORE
        else:
            return 0

    def capture_search(self, board, info):
        1/0 #not implemented
        score_now = info[SCORE]
        for move in board.generate_legal_moves():
            if board.is_capture(move):
                board.push(move)
                info2 = self.analyse_position(board, info, store_flag=False)
                board.pop()
                score2 = info2[SCORE]
                if info2[SCORE_TYPE]=="mate":
                    if score2<0:
                        return score_now - TABLEBASE_SCORE
                else:
                    if board.turn==TABLEBASE31_DRAW_LOST_COLOR: limit = 50
                    else: limit = -50
                    if score2<limit:
                        return score_now - TABLEBASE_SCORE
        return score_now

    def analyse_position(self, board, info0, store_flag=True, only_pv=False):
        if only_pv:
            self.program_id, self.engine = self.engine_dict[brainfish_id]
        else:
            self.program_id, self.engine = self.engine_dict[asmfish_id]
        info = info0[:]
        self.nodes += 1
        count_info_prefix = str(self.nodes)
        if only_pv: count_info_prefix = "PV " + count_info_prefix
        self.info_handler.new_board(info[FEN], board, count_info_prefix)
        self.engine.position(board)
        #command = self.engine.go(infinite=True, async_callback=True)
        #command = self.engine.go(nodes=self.nodes2search, async_callback=True)
        command = self.engine.go(movetime=self.nodes2search*1000/1000000, async_callback=True)
        while not self.info_handler.stop_flag:
            time.sleep(0.0001)
        self.engine.stop()
        res = command.result()
        ires = self.info_handler.result
        if not self.log.last_counter and only_pv:
            self.log.last_counter = "only PV: " + ires.pv
        self.log.print_s()
        info[POS] = fen2key(board.fen())
        info[PLY] += 1
        info[DEPTH] = ires.depth
        info[SELDEPTH] = ires.seldepth
        info[SCORE_TYPE] = ires.score_type
        info[SCORE] = ires.score
        info[NODES] = ires.nodes
        info[TBHITS] = ires.tbhits
        info[TIME] = ires.time
        info[PV] = ires.pv
        if TABLEBASE31_FLAG and ires.score_type=="cp":
            if count_pieces(board)<32:
                score = ires.score
                if board.turn==TABLEBASE31_DRAW_LOST_COLOR:
                    if score<50: score -= TABLEBASE_SCORE
                    else: score += TABLEBASE_SCORE
                else:
                    if score<-50: score -= TABLEBASE_SCORE
                    else: score += TABLEBASE_SCORE
                self.log.print_s("tablebase31: %s -> %s" % (ires.score, score))
                info[SCORE] = score
            elif TABLEBASE31_CAPTURE_SEARCH_FLAG:
                info[SCORE] = self.capture_search(board, info)

        #analyse again to get true pv, previous is scoring for alpha-beta undo side
        if not only_pv and board.turn!=UNDO_COLOR:
            info2 = self.analyse_position(board, info0, store_flag=False, only_pv=True)
            info[PV] = info2[PV]
        if store_flag:
            self.store_result(info)
        else:
            return info

    def analyse_1_move(self, board, info):
        self.log.print_s("-"*60)
        pos = fen2key(board.fen())
        moves0 = info[MOVES]
        m = info[PV].split()[0]
        board.push_uci(m)
        info[MOVES] = " ".join((moves0, m))
        self.analyse_position(board, info)
        self.add_link(m, pos, fen2key(board.fen()))
        board.pop()

    def analyse_all_moves(self, board, info):
        self.log.print_s("-"*60)
        pos = fen2key(board.fen())
        moves0 = info[MOVES]
        for m in board.generate_legal_moves():
            board.push(m)
            info[MOVES] = " ".join((moves0, str(m)))
            self.analyse_position(board, info)
            self.add_link(str(m), pos, fen2key(board.fen()))
            board.pop()

    def store_result(self, info):
        self.positions[info[POS]] = info
        self.positions2store.append(info)

    def search(self):
        while True:
            pos = self.best_position()
            info = self.positions[pos]
            board = chess.Board(info[FEN])
            self.analyse_position(board, info)
            m = info[PV].split()[0]
            self.analyse_all_moves(board, info)
            board.push_uci(m)
            self.analyse_all_moves(board, info)
##            self.analyse_position(board, info)
##            board.push_uci("e7e5")
##            self.analyse_position(board, info)
##            board.pop()
##            for m in board.generate_legal_moves():
##                if str(m)=="e7e5": continue
##                board.push(m)
##                self.analyse_position(board, info)
##                board.pop()
            self.commit()
            break

    def commit(self):
        q_marks = ",".join(["?"]*len(self.positions2store[0]))
        statement = "INSERT INTO analysis VALUES(%s)" % (q_marks,)
        self.c.executemany(statement, self.positions2store)
        self.db.commit()
        self.positions2store = []

    def manual_search(self, moves):
        board = chess.Board(self.starting_pos)
        info = self.positions[fen2key(self.starting_pos)]
        for m in moves:
            if m=="all":
                self.analyse_all_moves(board, info)
                break
            else:
                board.push_uci(m)
        else:
            self.analyse_position(board, info)

    def search_variation(self, moves):
        self.info_handler.log = self.log
        board = chess.Board(self.starting_pos)
        for m in moves:
            board.push_uci(m)
        info = self.positions[fen2key(board.fen())]
        if ONE_SIDE_ONLY_FLAG and board.turn!=UNDO_COLOR:
            self.analyse_1_move(board, info)
        else:
            self.analyse_all_moves(board, info)

    def get_score(self, pos):
        info = self.positions[pos]
        score = info[SCORE]
        if info[SCORE_TYPE]=="mate":
            if score<0: return -MATE_SCORE-score
            else: return MATE_SCORE-score
        return score

    def alpha_beta_recursive(self, board, alpha, beta, print_flag):
        self.alpha_beta_nodes += 1
        pos = fen2key(board.fen())
        #print("%i POS: %s" % (self.alpha_beta_nodes, pos))
        if pos not in self.positions: return
        if board.transpositions[board.zobrist_hash()] >= 2:
            return self.draw_score(board.turn), []
        res = board.result(claim_draw=True)
        if res!="*":
            score = {"1/2-1/2": self.draw_score(board.turn), "1-0": MATE_SCORE, "0-1": -MATE_SCORE}[res]
            if board.turn==chess.BLACK: score = -score
            return score, []
        best_score = WORST_SCORE
        best_pv = []
        score_moves = []
        if ONE_SIDE_ONLY_FLAG and board.turn!=UNDO_COLOR:
            info = self.positions[pos]
            m = info[PV].split()[0]
            board.push_uci(m)
            pos2 = fen2key(board.fen())
            board.pop()
            if pos2 not in self.positions:
                return self.get_score(pos), []
            score_moves.append((self.get_score(pos2), m))
        else:
            history_move = self.history_moves.get(pos, "")
            for m in board.generate_legal_moves():
                board.push(m)
                pos2 = fen2key(board.fen())
                board.pop()
                if pos2 not in self.positions:
                    return self.get_score(pos), []
                score = self.get_score(pos2)
                if history_move==str(m):
                    score -= 100
                score_moves.append((score, str(m)))
        if not score_moves:
            return self.get_score(pos), []
        for mscore, m in sorted(score_moves):
            board.push_uci(m)
            score, pv = self.alpha_beta_recursive(board, -beta, -alpha, print_flag)
            board.pop()
            score = -score
            if score + 1000 > MATE_SCORE: score -= 1
            if print_flag: print(self.alpha_beta_nodes, mscore, " ".join(map(str, board.move_stack)), m, score, pv, alpha, beta)
            if score > best_score:
                if print_flag: print("new best_score")
                best_score = score
                best_pv = [m] + pv
                if score >= alpha:
                    if print_flag: print("new alpha")
                    alpha = score
                    if score >= beta:
                        if print_flag: print("beta cut")
                        break
        if print_flag: print("-"*60)
        self.history_moves[pos] = best_pv[0]
        return best_score, best_pv

    def alpha_beta_link_recursive(self, lboard, alpha, beta, print_flag):
        self.alpha_beta_nodes += 1
        pos = lboard.pos
        #print("%i POS: %s" % (self.alpha_beta_nodes, pos))
        if lboard.transpositions[pos] >= 2:
            return self.draw_score(lboard.turn), []
        best_score = WORST_SCORE
        best_pv = []
        score_moves = []
        if pos not in self.link_to:
            return self.get_score(pos), []
        history_move = self.history_moves.get(pos, "")
        pos2_dict = self.link_to[pos]
        for pos2 in pos2_dict:
            m = pos2_dict[pos2]
            score = self.get_score(pos2)
            if history_move==str(m):
                score -= 100
            score_moves.append((score, m, pos2))
        for mscore, m, pos2 in sorted(score_moves):
            lboard.push(pos2)
            score, pv = self.alpha_beta_link_recursive(lboard, -beta, -alpha, print_flag)
            lboard.pop()
            score = -score
            if score + 1000 > MATE_SCORE: score -= 1
            if print_flag: print(self.alpha_beta_nodes, mscore, len(lboard.pos_stack), m, score, pv, alpha, beta)
            if score > best_score:
                if print_flag: print("new best_score")
                best_score = score
                best_pv = [m] + pv
                if score >= alpha:
                    if print_flag: print("new alpha")
                    alpha = score
                    if score >= beta:
                        if print_flag: print("beta cut")
                        break
        if print_flag: print("-"*60)
        self.history_moves[pos] = best_pv[0]
        return best_score, best_pv

    def search_alpha_beta(self, print_flag=False, alpha_beta_log=None):
        self.alpha_beta_nodes = 0
        board = chess.Board(self.starting_pos)
        t0 = time.time()
        if USE_LINKS_FLAG:
            lboard = LinkBoard(fen2key(board.fen()), board.turn)
            score, pv = self.alpha_beta_link_recursive(lboard, WORST_SCORE, -WORST_SCORE, print_flag)
        else:
            score, pv = self.alpha_beta_recursive(board, WORST_SCORE, -WORST_SCORE, print_flag)
        time_elapsed = time.time() - t0
        with open("t.pgn", "w") as fp: fp.write(moves2pgn(self.starting_pos, pv))
        alpha_beta_s = "%i(%in/%ip) %.3fs %s" % (score, self.alpha_beta_nodes, len(self.positions), time_elapsed, moves2san(self.starting_pos, pv))
        self.log.print_s(alpha_beta_s)
        if alpha_beta_log: alpha_beta_log.print_s(alpha_beta_s)
        return score, pv

    def loop(self):
        self.alpha_beta_log = Log("alpha_beta_%i" % (self.nodes2search,))
        while not os.path.exists(BREAK_SEARCH):
            score, pv = self.search_alpha_beta(False, self.alpha_beta_log)
            if abs(score)+1000 > MATE_SCORE:
                board = moves2board(self.starting_pos, pv)
                pv2 = self.positions[fen2key(board.fen())][PV]
                s = "mating score with pv: %s" % (pv2,)
                self.log.print_s(s)
                self.alpha_beta_log.print_s(s)
                with open("game.pgn", "w") as fp:
                    fp.write(moves2pgn(self.starting_pos, pv + pv2.split()))
                return
            self.search_variation(pv)
            self.commit()
        score, pv = self.search_alpha_beta(False, self.alpha_beta_log)
        if os.path.exists(BREAK_SEARCH): os.remove(BREAK_SEARCH)

def moves2board(startpos, moves):
    b = chess.Board(startpos)
    for m in moves:
        b.push_uci(m)
    return b

def moves2pgn(startpos, moves):
    b = moves2board(startpos, moves)
    return str(chess.pgn.Game().from_board(b))

def moves2san(startpos, moves):
    b = moves2board(startpos, moves)
    return board2san(startpos, b)

def count_pieces(board):
    count = 0
    for color in chess.COLORS:
        for piece_type in chess.PIECE_TYPES:
            count += len(board.pieces(piece_type, color))
    return count

if __name__=="__main__":
    if not os.path.exists("log"): os.mkdir("log")
    nodes2search = int(sys.argv[1])
    s = UndoSearch(nodes2search)
    s.loop()
    #score, pv = s.search_alpha_beta(True)
    #s.search_variation(pv); s.commit(); s.search_alpha_beta(True); s.search_alpha_beta(False)
    #s.search()
    #s.manual_search(sys.argv[2:])
    
