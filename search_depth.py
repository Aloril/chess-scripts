#!/usr/bin/env python3
import time, sys, os
import chess.uci
import sqlite3

BREAK_SEARCH = "break_search.flag"
BEST_MOVE_ONLY = True
if BEST_MOVE_ONLY:
    print("BEST_MOVE_ONLY:", BEST_MOVE_ONLY)

standard_position_flag = True
if standard_position_flag:
    start_position = chess.Board().fen()
else:
    start_position = "1n2k1n1/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQ - 0 1"
stockfish7_id = 1
asmfish_id = 2
brainfish_id = 3
db_name = "chess.db"

COUNTER_END = chr(27) + "[K\r"
POS, FEN, PLY, MOVES, DEPTH, SELDEPTH, SCORE_TYPE, SCORE, NODES, TBHITS, TIME, PV, PROGRAM_ID = range(13)

def fen2key(fen):
    return " ".join(fen.split()[:-2])

def get_time_str():
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time()))

def get_list_dict(c):
    l = c.execute("SELECT * FROM analysis").fetchall()
    d = {info[0]: info for info in l}
    return l, d

def board2san(start_fen, board0):
    board = chess.Board(start_fen)
    san = []
    move_numbers = []
    first_move = True
    for move in board0.move_stack:
        move = board._from_chess960(move.from_square, move.to_square, move.promotion)
        san.append(board.san(move))
        if board.turn == chess.WHITE:
            move_numbers.append("{0}. ".format(board.fullmove_number))
        elif first_move:
            move_numbers.append("{0}...".format(board.fullmove_number))
        else:
            move_numbers.append("")
        first_move = False
        board.push(move)
    return " ".join(["{0}{1}".format(num, s) for (num, s) in zip(move_numbers, san)])

def str_info(start_fen, board, info):
    existing_moves = board2san(start_fen, board)
    if existing_moves: existing_moves += " "
    score = info["score"][1]
    if score.cp!=None:
        score = "%.2f" % (score.cp/100,)
    else:
        score = "M%i" % (score.mate,)
    if "seldepth" in info:
        s = "%s%i/%i %s n:%s tb:%s %.3fs %s" % (
            existing_moves, info["depth"], info["seldepth"],
            score, info["nodes"], info["tbhits"], info["time"]/1000,
            board.variation_san(info["pv"][1]))
    else:
        s = "%s%i %s n:%s tb:%s %.3fs %s" % (
            existing_moves, info["depth"],
            score, info["nodes"], info["tbhits"], info["time"]/1000,
            board.variation_san(info["pv"][1]))
    return s

def create_empty_chess_db(db_name):
    db = sqlite3.connect(db_name)
    c = db.cursor()
    c.execute('''CREATE TABLE analysis
             (pos TEXT KEY, fen TEXT, ply INTEGER, moves TEXT, depth INTEGER, seldepth INTEGER, score_type TEXT, score INTEGER, nodes INTEGER, tbhits INTEGER, time INTEGER, pv TEXT, program_id INTEGER)''')
    c.execute("CREATE INDEX analysis_pos_index ON analysis (pos)")
    return db, c

def create_chess_db():
    if os.path.exists(db_name): return
    db, c = create_empty_chess_db(db_name)
    if standard_position_flag:
        c.execute("INSERT INTO analysis(pos, fen, ply, moves, depth, seldepth, score_type, score, nodes, tbhits, time, pv, program_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (fen2key(start_position), start_position, 0, "", 50, 65, "cp", 15, 432633504141, 102, 402232934, "e2e4 e7e6 d2d4 d7d5 b1d2 f8e7 c2c3 c7c5 d4c5 g8f6 e4d5 d8d5 g1f3 d5c5 f1d3 e8g8 e1g1 b8d7 f1e1 c5c7 d2e4 b7b6 c1g5 c8b7 g5h4 c7d8 a2a4 h7h6 d3c2 a7a5 e4f6 d7f6 f3e5 e7c5 e5g4 d8d1 g4f6 g7f6 a1d1 g8g7 d1d7 b7c6 d7c7 f8c8 c7c6 c8c6 c2e4 c6c8 h4g3 c8d8 e4a8 d8a8 e1d1", stockfish7_id))
    else:
        c.execute("INSERT INTO analysis(pos, fen, ply, moves, depth, seldepth, score_type, score, nodes, tbhits, time, pv, program_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (fen2key(start_position), start_position, 0, "", 1, 1, "cp", 3000, 1, 0, 0, "e2e4", stockfish7_id))
    db.commit()
    db.close()

class Result: pass

class Log:
    def __init__(self, basename):
        if not os.path.exists("log"): os.mkdir("log")
        filename = "log/%s_%s.log" % (basename, get_time_str())
        self.fp = open(filename, "a")
        self.last_counter = ""
        self.print_s(filename)

    def write_counter(self, s):
        self.last_counter = s
        sys.stderr.write(s[:236] + COUNTER_END)

    def print_s(self, s=""):
        if self.last_counter:
            self.fp.write(self.last_counter)
            sys.stderr.write(self.last_counter + COUNTER_END)
            self.last_counter = ""
        self.fp.write(s + "\n")
        print(s)
        self.fp.flush()

    def close(self):
        self.print_s()
        self.fp.close()

class NodeHandler(chess.uci.InfoHandler):
    def __init__(self, nodes2search):
        super(NodeHandler, self).__init__()
        self.stop_flag = False
        self.nodes2search = nodes2search
        self.result = Result()

    def new_board(self, start_fen, board, count_info_prefix):
        self.start_fen = start_fen
        self.board = board
        self.count_info_prefix = count_info_prefix
        self.stop_flag = False

    def on_bestmove(self, bestmove, ponder):
        if 1 not in self.info["pv"]:
            self.info["pv"][1] = [bestmove]
            if ponder: self.info["pv"][1].append(ponder)
        self.break_search()

    def break_search(self):
        self.result.seldepth = self.info.get("seldepth", 0)
        self.result.tbhits = self.info.get("tbhits", 0)
        self.result.time = self.info.get("time", 0)
        self.result.pv = " ".join(map(str, self.info["pv"][1]))
        self.stop_flag = True
                
    def post_info(self):
        # Called whenever a complete *info* line has been processed.
        super(NodeHandler, self).post_info()
        score = self.info["score"]
        if not self.stop_flag and 1 in score and score[1].lowerbound==score[1].upperbound==False:
            score = score[1]
            if score.cp!=None:
                self.result.score_type = "cp"
                self.result.score = score.cp
            else:
                self.result.score_type = "mate"
                self.result.score = score.mate
            self.result.depth = self.info["depth"]
            self.result.nodes = self.info["nodes"]
            break_search = self.result.nodes>self.nodes2search or self.result.score_type=="mate" or self.result.depth>=127
            if break_search or self.result.nodes>=10000:
                info_str = self.count_info_prefix + ": " + str_info(self.start_fen, self.board, self.info)
                self.log.write_counter(info_str)
            if break_search:
                self.break_search()

class Analysis:
    def __init__(self, nodes2search):
        create_chess_db()
        self.infinite_mode = True
        self.nodes2search = nodes2search
        self.commit_interval = max(10**8//nodes2search, 1)
        self.db = sqlite3.connect(db_name, 60.0)
        self.c = self.db.cursor()
        self.existing = {pos: score_type for (pos, score_type) in self.c.execute("SELECT pos, score_type FROM analysis")}
        self.program_id = stockfish7_id
        self.engine = chess.uci.popen_engine("stockfish_log_time")
        self.engine.uci()
        self.info_handler = NodeHandler(self.nodes2search)
        self.engine.info_handlers.append(self.info_handler)
        self.engine.setoption({"Hash":1024, "SyzygyPath": "/usr/games/syzygy"})

    def analyse_pos(self, count_info_prefix, start_fen, moves):
        board = chess.Board(start_fen)
        for m in moves.split():
            board.push_uci(m)
        key = fen2key(board.fen())
        #res = self.c.execute("SELECT pos FROM analysis WHERE pos=?", (key,)).fetchall()
        #if res:
        if key in self.existing:
            score_type = self.existing[key]
            self.log.print_s(count_info_prefix + " " + moves + ": already done: " + score_type)
            return False, score_type
##        sys.stderr.write(count_info_prefix + " " + moves + ": fake result" + COUNTER_END)
##        self.c.execute("INSERT INTO analysis(pos, fen, ply, moves, depth, seldepth, score_type, score, nodes, tbhits, time, pv, program_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
##                       (fen2key(board.fen()), start_fen, len(moves.split()),
##                        moves, 1, 1,
##                        "cp", 0, 1, 0,
##                        0, "",
##                        self.program_id))
##        return True, False
        self.info_handler.new_board(start_fen, board, count_info_prefix)
        self.engine.position(board)

        if self.infinite_mode:
            command = self.engine.go(infinite=True, async_callback=True)
            prev_nodes = nodes = 0
            while not self.info_handler.stop_flag:
                time.sleep(0.0001)
            self.engine.stop()
            res = command.result()
        else:
            res = self.engine.go(nodes=self.nodes2search)
        mate_found = self.info_handler.result.score_type=="mate"
        self.log.print_s()
        self.store_result(board, start_fen, moves, self.info_handler.result)
        return True, mate_found
        
    def store_result(self, board, start_fen, moves, info):
        pos = fen2key(board.fen())
        self.existing[pos] = "new " + info.score_type
        self.c.execute("INSERT INTO analysis(pos, fen, ply, moves, depth, seldepth, score_type, score, nodes, tbhits, time, pv, program_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (pos, start_fen, len(moves.split()),
                        moves, info.depth, info.seldepth,
                        info.score_type, info.score, info.nodes, info.tbhits,
                        info.time, info.pv,
                        self.program_id))

    def search_depth(self, ply_depth, cp_limit):
        self.log = Log("search_depth%i_%i" % (ply_depth, self.nodes2search))
        self.info_handler.log = self.log
        if cp_limit==None:
            res = self.c.execute("SELECT fen, moves, pv FROM analysis WHERE ply=? AND score_type='cp'", (ply_depth,)).fetchall()
        else:
            res = self.c.execute("SELECT fen, moves, pv FROM analysis WHERE ply=? AND score_type='cp' AND score<?", (ply_depth, cp_limit)).fetchall()
        total_pos = len(res)
        current_pos = 0
        new_pos = 0
        old_mate = 0
        old_pos = 0
        mate_count = 0
        cp_limit_count = 0
        break_flag = False
        for start_fen, moves, pv in res:
            if break_flag:
                break
            current_pos += 1
            board = chess.Board(start_fen)
            if BEST_MOVE_ONLY:
                moves2 = moves + " " + pv.split()[0]
            else:
                moves2 = moves
            for m in moves2.split():
                board.push_uci(m)
            legal_moves = list(board.generate_legal_moves())
            if board.is_game_over():
                input("game is over, should not happen! " + start_fen + " " + moves2)
                continue
            i = 0
            for m in legal_moves:
                i += 1
                moves3 = moves2 + " " + str(m)
                if cp_limit==None:
                    cp_limit_s = ""
                else:
                    cp_limit_s = "(<%i)" % cp_limit_count
                count_info_prefix = "%i/%i %i/%i +%i%s(-%i-M%i)M%i D%s" % (current_pos, total_pos, i, len(legal_moves), new_pos, cp_limit_s, old_pos, old_mate, mate_count, len(moves.split()))
                res, score_type = self.analyse_pos(count_info_prefix, start_fen, moves3)
                if res:
                    if score_type:
                        mate_count += 1
                    else:
                        new_pos += 1
                        if cp_limit!=None and self.info_handler.result.score<cp_limit:
                            cp_limit_count += 1
                    if (mate_count+new_pos)%self.commit_interval==0:
                        self.log.print_s()
                        self.log.print_s("committing...")
                        self.db.commit()
                else:
                    if score_type.find('mate')>=0:
                        old_mate += 1
                    else:
                        old_pos += 1
                if os.path.exists(BREAK_SEARCH):
                    os.remove(BREAK_SEARCH)
                    break_flag = True
                    break
        self.db.commit()
        if cp_limit==None:
            cp_limit_s = ""
        else:
            cp_limit_s = "(<%i:%i)" % (cp_limit, cp_limit_count)
        self.log.print_s("new: %i%s, already: %i, already mate: %i, mate: %i" % (new_pos, cp_limit_s, old_pos, old_mate, mate_count))
        self.log.close()

if __name__=="__main__":
    depth = int(sys.argv[1])
    nodes2search = int(sys.argv[2])
    if len(sys.argv)>3: cp_limit = int(sys.argv[3])
    else: cp_limit = None
    an = Analysis(nodes2search)
    an.search_depth(depth, cp_limit)
