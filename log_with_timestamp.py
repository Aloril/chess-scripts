#!/usr/bin/env python3
import sys, time

def get_time_str():
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time()))

if __name__=="__main__":
    log_file = sys.argv[1]
    fp = open(log_file, "a")
    pass_date = len(sys.argv)>2 and sys.argv[2]=="--pass_date"
    while True:
        line = sys.stdin.readline()
        if not line: break
        stamp = get_time_str()
        fp.write(stamp + " " + line)
        fp.flush()
        if pass_date: sys.stdout.write(stamp + " ")
        sys.stdout.write(line)
        sys.stdout.flush()
        if line.startswith("quit"): break
