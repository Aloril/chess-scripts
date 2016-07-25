#!/usr/bin/env python3
import sys
import chess.uci

if __name__=="__main__":
    brainfish_log = sys.argv[1]
    alpha_beta_log = sys.argv[2]
    book_set = set()
    position_flag = False
    for line in open(brainfish_log):
        l = line.split()
        if len(l)>=4 and l[1]=="position" and l[2]=="startpos" and l[3]=="moves":
            moves = " ".join(l[4:])
            position_flag = True
        if len(l)>=2 and l[1]=="info":
            position_flag = False
        if len(l)>=3 and l[1]=="bestmove" and position_flag:
            book_set.add(moves + " " +l[2])
            #print(position_flag, moves, l[2])
    for line in open(alpha_beta_log):
        l = line.split()
        if len(l)>=3 and l[2]=="1.":
            l_out = l[:3]
            board = chess.Board()
            moves_lst = []
            book_flag = False
            for san in l[3:]:
                l_out.append(san)
                if san[-1]=='.': continue
                m = board.push_san(san)
                moves_lst.append(str(m))
                moves = " ".join(moves_lst)
                if moves in book_set:
                    l_out[-1] += "@"
            print(" ".join(l_out))
        else:
            print(line[:-1])
        
