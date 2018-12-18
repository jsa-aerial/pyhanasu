import asyncio
import websockets
import msgpack
import json
import gochans as gc

from contextlib import suppress
from gochans import Chan,select,go,ChannelClosed


class keyword:
    val = None
    def __init__(self, val):
        self.val = val
    def __eq__(self, x):
        return type(x) is keyword and self.val == x.val
    def __hash__(self):
        return hash(self.val)
    def __str__(self):
        return ":" + self.val
    def __repr__(self):
        return ":" + self.val

def default(obj):
    if type(obj) is keyword:
        pks = msgpack.packb(obj.val, default=default, use_bin_type=True)
        return msgpack.ExtType(3, pks)
    raise TypeError("Non packable type: %r" % (obj,))

def ext_hook(code, data):
    #print("CODE: ", code, "DATA: ", data, " TYPE: ", type(data))
    if code == 3:
        x = keyword(msgpack.unpackb(data, raw=False))
        return x
    return msgpack.ExtType(code, data)


## Envelope keys
op = keyword("op")
set = keyword("set")
reset = keyword("reset")
payload = keyword("payload")
msgrcv = keyword("msgrcv")
msgsnt = keyword("msgsnt")
bpsize = keyword("bpsize")
## operators
open = keyword("open")
close = keyword("close")
msg = keyword("msg")
bpwait = keyword("bpwait")
bpresume = keyword("bpresume")
sent = keyword("sent")
error = keyword("error")
stop = keyword("stop")



rmv = keyword("rmv")
cli_db = {}

def get_db(x,keys):
    val = x
    for key in keys:
        val = val[key]
    return val

def update_db (x, keys, val):
    l = len(keys)
    finkey = keys[l-1]
    dbval = x
    for key in keys[0:l-1]:
        if key not in dbval:
            dbval[key] = {}
        dbval = dbval[key]
    if val == rmv:
        del dbval[finkey]
    else:
        dbval[finkey] = val
    return x



def get_msg_op (msg):
    if op in msg:
        return msg[op]
    elif 'op' in msg:
        return msg['op']
    else:
        return 'no_op'

def get_msg_payload (msg):
    if payload in msg:
        return msg[payload]
    elif 'payload' in msg:
        return msg['payload']
    else:
        return 'no_payload'

def goloop (ic, dispatchfn):
    fin = False
    while (not fin):
        f = gc.go(ic.recv)
        msg = f.result()
        mop = get_msg_op(msg)
        mpload = get_msg_payload(msg)
        if mop == stop or mop == "stop":
            fin = True
        elif mop == 'no_op':
            print("WARNING Recv: bad msg envelope no 'op' field: ", msg)
        elif mpload == 'no_payload':
            print("WARNING Recv: bad msg envelope no 'payload' field: ", msg)
        else:
            dispatchfn(ic, mop, mpload)
    print("GOLOOP exit")

def gofn(ic, dispatchfn):
    goloop(ic=ic, dispatchfn=dispatchfn)
    print("gofn exit ...")

def gorun (chan, dispatchfn):
    gc.loop.run_in_executor(None, gofn, chan, dispatchfn)


@asyncio.coroutine
def send (ws, enc, msg):
    #print("MSG: ", msg)
    if enc == "binary":
        encmsg = msgpack.packb(msg, default=default, use_bin_type=True)
    else:
        encmsg = json.dumps(msg)
    yield from ws.send(encmsg)

def send_msg (ws, msg, encode="binary"):
    kwmsg = keyword("msg")
    msntcnt = get_db(cli_db, [ws, msgsnt])
    ch = get_db(cli_db, [ws, "chan"])
    if msntcnt >= get_db(cli_db, [ws, bpsize]):
        go(ch.send,
           {op: bpwait,
            payload: {"ws": ws, kwmsg: msg, "encode": encode,
                      msgsnt: msntcnt}})
    else:
        hmsg = {op: kwmsg, payload: msg}
        line_loop.run_until_complete(send(ws, encode, hmsg))
        update_db(cli_db, [ws, msgsnt], msntcnt+1)
        go(ch.send, {op: sent,
                     payload: {"ws": ws, kwmsg: hmsg,
                               msgsnt: get_db(cli_db, [ws, msgsnt])}})


def receive (ws, msg):
    kwmsg = keyword("msg")
    if op in msg:
        mop = msg[op]
    else:
        mop = msg["op"]
    if mop == set:
        print("INIT MSG: ", msg)
        mbpsize = msg[payload][bpsize]
        mmsgrcv = msg[payload][msgrcv]
        update_db(cli_db, [ws, msgrcv], mmsgrcv)
        update_db(cli_db, [ws, bpsize], mbpsize)
    elif mop == reset:
        update_db(cli_db, [ws, msgsnt], msg[payload][msgsnt])
        go(get_db(cli_db, [ws, "chan"]).send, {op: bpresume, payload: msg})
    elif mop == "msg" or mop == kwmsg:
        rcvd = get_db(cli_db, [ws, msgrcv])
        if payload in msg:
            data = msg[payload]
        else:
            data = msg["payload"]
        if rcvd+1 >= get_db(cli_db, [ws, bpsize]):
            update_db(cli_db, [ws, msgrcv], 0)
            line_loop.run_until_complete(
                send(ws, "binary", {op: reset, payload: {msgsnt: 0}}))
        else:
            update_db(cli_db, [ws, msgrcv], get_db(cli_db, [ws, msgrcv])+1)
        go(get_db(cli_db, [ws, "chan"]).send,
           {op: kwmsg, payload: {"ws": ws, "data": data}})
    else:
        print("Client Receive Handler - unknown OP ", msg)




### Loops for running line reads/writes
loop2 = asyncio.new_event_loop()
line_loop = asyncio.new_event_loop()

@asyncio.coroutine
def read_line (ws):
    try:
        msg = yield from ws.recv()
        msg = msgpack.unpackb(msg, ext_hook=ext_hook, raw=False)
        update_db(cli_db, ['msg'], msg)
    except websockets.exceptions.ConnectionClosed as e:
        rmtclose(ws,e)
        update_db(cli_db, ['msg'], stop)
    except Exception as e:
        onerror(ws,e)
        update_db(cli_db, ['msg'], stop)

def line_goloop (ws):
    print("Line Goloop called ...")
    fin = False
    while (not fin):
        try:
            loop2.run_until_complete(read_line(ws))
            msg = get_db(cli_db, ['msg'])
            #print("MSG: ", msg)
            mop = get_msg_op(msg)
            if mop == "stop" or mop == keyword("stop"):
                fin = True
            else:
                receive(ws, msg)
        except Exception as e:
            fin = True
            onerror(ws,e)
    print("Line GOLOOP exit")

def line_gorun (ws):
    print("Line Gorun called ...")
    gc.loop.run_in_executor(None, line_goloop, ws)


def rmtclose (ws, e):
    ch = get_db(cli_db, [ws, "chan"])
    print("Close: {0}".format(e))
    go(ch.send, {op: close, payload: {"code": e.code, "reason": e.reason}})

def onerror (ws, e):
    ch = get_db(cli_db, [ws, "chan"])
    print("Error: ", e)
    go(ch.send, {op: error, payload: {"ws": ws, "err": e}})


# 'ws://localhost:8765/ws'
@asyncio.coroutine
def connect (url):
    ws = yield from websockets.connect(url)
    client_chan =  gc.Chan(size=19)
    client_rec = {"url": url, "ws": ws, "chan": client_chan,
                  bpsize: 0, msgrcv: 0, msgsnt: 0}
    update_db(cli_db, [client_chan], client_rec)
    update_db(cli_db, [ws], client_rec)
    update_db(cli_db, [ws, "chan"], client_chan)
    gc.go(client_chan.send, {op: open, payload: ws})
    return client_chan

def open_connection (url):
    ch = loop2.run_until_complete(connect(url))
    ws = get_db(cli_db, [ch, 'ws'])
    line_gorun(ws)
    return ch


@asyncio.coroutine
def closeit (websocket):
    yield from websocket.close()

def cancel_tasks (ws):
    ch = get_db(cli_db, [ws, "chan"])
    gc.go(ch.send, {op: stop, payload: {}})
    pending = asyncio.Task.all_tasks()
    for task in pending:
        task.cancel()
        #with suppress(asyncio.CancelledError):
        #    loop2.run_until_complete(task)

async def sleep (s): await asyncio.sleep(s)

def close_connection (ws):
    ch = get_db(cli_db, [ws, "chan"])
    send_msg(ws, {op: 'done', payload: {}})
    go(ch.send, {op: stop, payload: {}})
    line_loop.run_until_complete(sleep(1))
    loop2.run_until_complete(closeit(ws))
    loop2.close()
    line_loop.close()
    gc.loop.close()



def echo_test(websocket):
    ch = get_db(cli_db, [websocket, 'chan'])
    try:
        name = input("What's your name? ")
        msg = {'op': "msg", 'payload': name}
        print("> {}".format(name))

        send_msg(websocket, msg)
        f = gc.go(ch.recv)
        res = f.result()
        echo = get_db(cli_db, ['msg', cli.payload, cli.op])
        print("< {}".format(echo))

    finally:
        print("done one msg")


## from client import rmv,cli_db,get_db,update_db,echo_test,gorun
##
## gorun()
## go(ic.send,"Hi")
## f = go(oc.recv)
## f.result() => "Hi"
## go(ic.send,client.stop)
## GOLOOP exit
## gofn exit ...
##
## loop2 = asyncio.new_event_loop()
## asyncio.set_event_loop(loop2)
## ws = loop2.run_until_complete(connect('ws://localhost:8765/ws'))
## loop2.run_until_complete(hello(ws))
## loop2.run_until_complete(close(ws))

## s = 'key2.key21.key211'
## print get_db(cli_db,s.split('.'))

