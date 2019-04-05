import trio
import time
import client as cli
from client import close, error, bpwait, bpresume, sent, stop, rmv

udb = {}

def get_udb (keys):
    return cli.get_db(udb, keys)

def update_udb (keys, val):
    cli.update_db(udb, keys, val)


dsdict = lambda dict, *keys: list((dict[key] for key in keys))

def dispatcher (ch, op, payload):
    #print("DISPATCH:", op, payload)

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
    elif op == error:
        ws, err = dsdict(payload, 'ws', 'err')
        print("CLIENT :error/payload = ", payload)
        update_udb([ws, 'errcnt'], get_udb([ws, 'errcnt'])+1)
    elif op == bpwait:
        ws, msg, encode = dsdict(payload, 'ws', cli.msg, 'encode')
        print("CLIENT, Waiting to send msg ", msg)
        v = udb["bpwait"] if "bpwait" in udb else []
        v.append([ws, msg, encode])
        update_udb(["bpwait"], v)
        time.sleep(0.1)
    elif op == bpresume:
        print("CLIENT, BP Resume ", payload)
        update_udb(["resume"], payload)
    elif op == stop:
        ws, cause = dsdict(payload, 'ws', 'cause')
        print("CLIENT, Stopping reads... Cause ", cause)
        update_udb([ws], rmv)
    else:
        print("CLIENT :WTF/op = ", op, " payload = ", payload)


async def bpretry ():
    return "bpwait" in udb and udb["bpwait"]

async def resume ():
    while "resume" not in udb:
        await trio.sleep(0.1)
    return True

async def sendem (info):
    ws = info["ws"]
    cnt = info["appinfo"]["cnt"]
    for i in range(cnt):
        await cli.send_msg(
            ws, {cli.op: "msg",
                 cli.payload: "message number {}".format(i)})
        retry = await bpretry()
        if retry:
            await resume()
            retries = udb["bpwait"]
            while retries:
                # Yes, there are holes in this...
                ws, msg, encode = retries.pop(0)
                update_udb(["bpwait"], retries)
                print("CLIENT, Trying resend:", msg)
                await cli.send_msg(ws, msg, encode=encode)
    await cli.send_msg(ws, {cli.op: "done", cli.payload: {}})



# 'ws://localhost:8765/ws'
def startit (url, cnt=3):
    trio.run(cli.open_connection, url, dispatcher, sendem, {"cnt": cnt})

## import example as ex
## ex.startit('ws://localhost:8765/ws', 100)
