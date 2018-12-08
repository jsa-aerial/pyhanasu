import asyncio
import websockets
import msgpack
import json
import gochans as gc

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
        return msgpack.ExtType(3,bytes(obj.val,'UTF-8','strict'))
    raise TypeError("Non packable type: %r" % (obj,))

def ext_hook(code, data):
    ##print("CODE: ", code, "DATA: ", data)
    if code == 3:
        x = keyword(msgpack.unpackb(data, raw=False))
        ##x = msgpack.unpackb(data, raw=False)
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
done = keyword("done")



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



#@asyncio.coroutine
#def send_msg (ws, msg, encode='binary'):
#    if


def make_chans (icnm, isz, ocnm, osz):
    update_db(cli_db, [icnm], gc.Chan(size=isz))
    update_db(cli_db, [ocnm], gc.Chan(size=osz))

def goloop (ic,oc):
    fin = False
    while (not fin):
        f = gc.go(ic.recv)
        res = f.result()
        if res == done:
            fin = True
        else:
            gc.go(oc.send, res)
    print("GOLOOP exit")

def gofn(icnm, ocnm):
    ic = get_db(cli_db, [icnm])
    oc = get_db(cli_db, [ocnm])
    goloop(ic=ic,oc=oc)
    print("gofn exit ...")

def gorun (inchan_name, otchan_name):
    make_chans(inchan_name, 19, otchan_name, 19)
    gc.loop.run_in_executor(None, gofn, inchan_name, otchan_name)


def send (ws, enc, msg):
    if enc == "binar":
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
        send(ws, encode, hmsg)
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
            send(ws, "binary", {op: reset, payload: {msgsnt: 0}})
        else:
            update_db(cli_db, [ws, msgrcv], get_db(cli_db, [ws, msgrcv])+1)
        go(get_db(cli_db, [ws, "chan"]).send,
           {op: kwmsg, payload: {"ws": ws, "data": data}})
    else:
        print("Client Receive Handler - unknown OP ", msg)




### Loop for running line reads/writes
loop2 = asyncio.new_event_loop()

def line_goloop (ws):
    fin = False
    while (not fin):
        try:
            msg = yield from ws.recv()
            msg = msgpack.unpackb(msg, ext_hook=ext_hook, raw=False)
            if op in msg:
                mop = msg[op]
            else:
                mop = msg["op"]
            if mop == "stop" or keyword("stop"):
                fin = True
            else:
                receive(ws, msg)
        except websockets.exceptions.ConnectionClosed as e:
            rmtclose(ws,e)
            fin = True
        except Exception as e:
            onerror(ws,e)
    print("Line GOLOOP exit")

def line_gorun (ws):
    loop2.run_in_executor(None, line_goloop, ws)

def open (client_rec):
    ws = client_rec["ws"]
    return line_gorun(ws)

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
    open(client_rec)
    update_db(cli_db, [client_chan], client_rec)
    update_db(cli_db, [ws], client_rec)
    update_db(cli_db, [ws, "chan"], client_chan)
    gc.go(client_chan.send, {op: open, payload: ws})
    return client_chan

def open_connection (url):
    return loop2.run_until_complete(connect(url))

@asyncio.coroutine
def close_connection (websocket):
    yield from websocket.close()


@asyncio.coroutine
def hello(websocket):

    try:
        name = input("What's your name? ")
        msg = {'op': "msg", 'payload': name}

        yield from websocket.send(json.dumps(msg))
        print("> {}".format(name))

        greeting = yield from websocket.recv()
        greeting = msgpack.unpackb(greeting, ext_hook=ext_hook, raw=False)
        print("< {}".format(greeting))

    finally:
        print("done one msg")


## from client import rmv,cli_db,get_db,update_db,connect,close,hello,gorun
##
## gorun()
## go(ic.send,"Hi")
## f = go(oc.recv)
## f.result() => "Hi"
## go(ic.send,client.done)
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

