# coding=utf8

__author__ = 'Alexander.Li'

import json
import traceback
import aioredis
import logging


class PersistedRmq(object):
    redis_uri: str
    conn: aioredis.connection
    timestamp: int

    @classmethod
    def init(cls, uri):
        cls.redis_uri = uri

    def __init__(self, channel, client_id=None, client_types=[], on_message=None):
        self.client_types = client_types
        self.channel = channel
        self.client_id = client_id
        self.on_message = on_message
        self.client_map_key = f'CM:{self.channel}-{self.client_id}'
        self.persisted_key = f'P:{self.channel}-{self.client_id}'
        self.subscribe_chn = f'CHN:{self.channel}'
        self.persisted_timeout = 3600 * 24 * 3

    async def __aenter__(self):
        await self.init_mq()
        return self

    async def __aexit__(self, *args):
        await self.close()

    def __await__(self):
        return self.__aenter__().__await__()

    async def close(self):
        self.conn.close()
        await self.conn.wait_closed()

    async def connect(self):
        self.conn = await aioredis.create_redis_pool(self.__class__.redis_uri)

    async def init_mq(self):
        await self.connect()

    async def persisted_message(self, channel, cid, message_id, msg):
        persisted_key = f'P:{channel}-{cid}'
        await self.conn.hset(persisted_key, message_id, msg)
        if self.persisted_timeout:
            await self.conn.expire(persisted_key, self.persisted_timeout)
        logging.error(f'persisted:{persisted_key} {message_id}')

    async def get_persisted_message(self, message_id):
        logging.error(f'will load:{self.persisted_key} {message_id}')
        return await self.conn.hget(self.persisted_key, message_id)

    async def comfirm_issued(self, message_ids=[]):
        for message_id in message_ids:
            for cid in self.client_types:
                persisted_key = f'P:{self.channel}-{cid}'
                await self.conn.hdel(persisted_key, message_id)

    async def unread_all(self):
        return await self.conn.hgetall(self.persisted_key)

    async def subscribe(self, timeout=None):
        if timeout:
            self.persisted_timeout = timeout
        old_messages = await self.unread_all()
        if old_messages:
            try:
                msgs = []
                for k, v in old_messages.items():
                    msgs.append(json.loads(v))
                await self.on_message(json.dumps({'msgs': msgs}))
                logging.error(f'{self.persisted_key} 未读消息{len(old_messages)}条已经顺利下发')
            except Exception as e:
                await self.conn.unsubscribe(self.subscribe_chn)
                await self.close()
                logging.error(traceback.print_exc())
                return
        logging.error(f'进入订阅:{self.subscribe_chn}')
        chs = await self.conn.subscribe(self.subscribe_chn)
        while True:
            while await chs[0].wait_message():
                msg_id = await chs[0].get()
                try:
                    logging.error(f'got msg: id is {msg_id}')
                    msg = await self.get_persisted_message(str(msg_id, encoding='utf8'))
                    await self.on_message(json.dumps({'msgs': [json.loads(str(msg, encoding='utf8')), ]}))
                    logging.error(f'{self.persisted_key} 消息已经顺利下发')
                except Exception as e:
                    logging.error(e)
                    await self.conn.unsubscribe(self.subscribe_chn)
                    await self.close()
                    logging.error(traceback.print_exc())
                    return

    async def publish(self, channel, msg):
        cb_chn = f'CHN:{channel}'
        msg_obj = json.loads(msg)
        msg_id = msg_obj.get('id')
        for cid in self.client_types:
            await self.persisted_message(channel, cid, msg_id, msg)
        await self.conn.publish(cb_chn, msg_id)
        logging.error(f'published to {channel}!')


