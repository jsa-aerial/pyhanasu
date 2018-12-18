import time
import gochans as gc
import client as cli
from client import close, error, bpwait, bpresume, sent, stop, rmv

udb = {}

def get_udb (keys):
    return cli.get_db(udb, keys)

def update_udb (keys, val):
    cli.update_db(udb, keys, val)


dsdict = lambda dict, *keys: list((dict[key] for key in keys))

def dispatcher (ch, op, payload):
    print("DISPATCH:", op, payload)

    if op == cli.msg or op == 'msg':
        ws, data = dsdict(payload, 'ws', 'data')
        print('CLIENT :msg/payload = ', payload)
        update_udb([ws, 'lastrcv'], data)
        update_udb([ws, 'rcvcnt'], get_udb([ws, 'rcvcnt'])+1)
    elif op == cli.sent:
        ws, msg = dsdict(payload, 'ws', cli.msg)
        print("CLIENT, Sent msg ", msg)
        update_udb([ws, 'lastsnt'], msg)
        update_udb([ws, 'sntcnt'], get_udb([ws, 'sntcnt'])+1)
    elif op == cli.open:
        ws = payload
        print("CLIENT :open/ws = ", ws)
        update_udb([ws], {'chan': ch, 'rcvcnt': 0, 'sntcnt': 0, 'errcnt': 0})
        update_udb(['com'], [ch, ws])
    elif op == close:
        ws, code, reason = dsdict(payload, 'ws', 'code', 'reason')
        print("CLIENT RMTclose/payload = ", payload)
        go(ch.send, {cli.op: stop,
                     cli.payload: {'ws': ws, 'cause': 'rmtclose'}})
    elif op == error:
        ws, err = dsdict(payload, 'ws', 'err')
        print("CLIENT :error/payload = ", payload)
        update_udb([ws, 'errcnt'], get_udb([ws, 'errcnt'])+1)
    elif op == bpwait:
        ws, msg, encode = dsdict(payload, 'ws', cli.msg, 'encode')
        print("CLIENT, Waiting to send msg ", msg)
        time.sleep(2)
        print("CLIENT, Trying resend ...")
        cli.send_msg(ws, msg, encode=encode)
    elif op == bpresume:
        print("CLIENT, BP Resume ", payload)
    elif op == stop:
        ws, cause = dsdict(payload, 'ws', 'cause')
        print("CLIENT, Stopping reads... Cause ", cause)
        cli.close_connection(ws)
        sleep_loop.close()
        update_udb([ws], rmv)
    else:
        print("CLIENT :WTF/op = ", op, " payload = ", payload)


# 'ws://localhost:8765/ws'
def startit (url):
    ch = cli.open_connection(url)
    cli.gorun(ch, dispatcher)

# from client import get_db, cli_db, msgsnt, msgrcv
# ex.startit('ws://localhost:8765/ws')
# ch,ws = ex.udb['com']
# for i in range(95): cli.send_msg(ws, {'op': "msg", 'payload': 'testing'})
# [ex.get_udb([ws, 'sntcnt']), ex.get_udb([ws, 'rcvcnt'])]
# [get_db(cli_db, [ws, msgsnt]), get_db(cli_db, [ws, msgrcv])]
