# coding=utf8

__author__ = 'Alexander.Li'

import traceback
import json
import sys
sys.path.append('../')
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from persistedrmq2 import PersistedRmq
import asyncio
import logging


app = FastAPI()


html = """
<!DOCTYPE html>
<html>
    <head>
        <title>Chat</title>
    </head>
    <body>
        <h1>WebSocket Chat</h1>
        <form onsubmit="init_queue(event)">
            <input type="text" id="my_id" autocomplete="off"/>
            <input type="text" id="to_id" autocomplete="off"/>
            <button>Start</button>
        </form>
        <form onsubmit="sendMessage(event)">
            <input type="text" id="messageText" autocomplete="off"/>
            <button>Send</button>
        </form>
        <ul id='messages'>
        </ul>
        <script>
            var ws = null;
            
            function init_queue(event) {
               var meId = document.getElementById("my_id").value
               ws = new WebSocket("ws://localhost:8000/ws/"+meId);
               ws.onmessage = function(event) {
                    console.log('get replay', event)
                    var msgs_txt = event.data
                    var msgs_obj = JSON.parse(msgs_txt)['msgs']
                    var ids = []
                    for(var i=0; i<msgs_obj.length;i++){
                        var msg_obj = msgs_obj[i]
                        var msg_id = msg_obj["id"]
                        var messages = document.getElementById('messages')
                        var message = document.createElement('li')
                        var content = document.createTextNode(msg_obj['payload'])
                        message.appendChild(content)
                        messages.appendChild(message)
                        ids.push(msg_id)
                    }
                    var rply_msg = {
                        tp:'reply',
                        rms: ids
                    }
                    ws.send(JSON.stringify(rply_msg));
                    console.log('send reply')
                };
               event.preventDefault()
            }
            
            function sendMessage(event) {
                var input = document.getElementById("messageText")
                //postMessage(input.value)
                var toId = document.getElementById("to_id").value
                var msg_id = Date.now().toString();
                var msg = {
                    id: msg_id,
                    tp: 'msg',
                    payload: input.value,
                    to: toId
                };
                ws.send(JSON.stringify(msg));
                input.value = ''
                event.preventDefault()
            }
        </script>
    </body>
</html>
"""

PersistedRmq.init('redis://localhost/0')


@app.get("/")
async def get():
    return HTMLResponse(html)


async def wait_text(client: PersistedRmq, websocket: WebSocket):
    while True:
        try:
            message = await websocket.receive_text()
            message_obj = json.loads(message)
            logging.error(f'msg:{message_obj}')
            message_type = message_obj.get('tp')
            if message_type == 'reply':
                message_ids = message_obj.get('rms')
                await client.comfirm_issued(message_ids)
            else:
                await client.publish(message_obj.get('to'), message)
        except Exception as e:
            logging.error(f'error:{traceback.print_exc()}')
            logging.error(f'{client.persisted_key} 连接断了！')
            raise e


async def wait_queue(client: PersistedRmq):
    await client.subscribe(timeout=360)


@app.websocket("/ws/{cid}")
async def websocket_endpoint(cid: str, websocket: WebSocket):
    await websocket.accept()

    async def dispatch_message(message):
        logging.error(f'{cid}获取到了消息：{message}')
        await websocket.send_text(message)

    async with PersistedRmq(cid, client_id='web', client_types=['web'], on_message=dispatch_message) as client:
        tasks = [
            wait_text(client, websocket),
            wait_queue(client)
        ]
        try:
            await asyncio.wait(tasks)
        except Exception as e:
            logging.error(f'外层错误：{e}')
