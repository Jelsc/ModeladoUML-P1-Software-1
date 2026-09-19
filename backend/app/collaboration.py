import asyncio, json, uuid
from collections import defaultdict
from redis.asyncio import Redis
from .config import settings

class Collaboration:
    def __init__(self):
        self.redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        self.clients = defaultdict(dict)
        self.tasks = {}
        self.user_clients = defaultdict(set)
        self.user_tasks = {}
    async def join(self, diagram, websocket):
        connection_id = uuid.uuid4().hex
        await websocket.accept(); self.clients[diagram][websocket] = connection_id
        if diagram not in self.tasks: self.tasks[diagram] = asyncio.create_task(self.listen(diagram))
        return connection_id
    async def listen(self, diagram):
        pubsub = self.redis.pubsub(); await pubsub.subscribe(f"diagram:{diagram}")
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message": continue
                event = json.loads(message["data"])
                source = event.get("source_connection_id")
                for client, connection_id in tuple(self.clients[diagram].items()):
                    if connection_id == source: continue
                    try: await client.send_text(message["data"])
                    except Exception: self.clients[diagram].pop(client, None)
        finally: await pubsub.close()
    async def publish(self, diagram, event): await self.redis.publish(f"diagram:{diagram}", json.dumps(event))
    async def leave(self, diagram, websocket):
        self.clients[diagram].pop(websocket, None)
        if not self.clients[diagram]:
            task = self.tasks.pop(diagram, None)
            if task: task.cancel()
    async def join_user(self, user_id, websocket):
        await websocket.accept()
        self.user_clients[user_id].add(websocket)
        if user_id not in self.user_tasks: self.user_tasks[user_id] = asyncio.create_task(self.listen_user(user_id))
    async def listen_user(self, user_id):
        pubsub = self.redis.pubsub(); await pubsub.subscribe(f"user:{user_id}")
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message": continue
                for client in tuple(self.user_clients[user_id]):
                    try: await client.send_text(message["data"])
                    except Exception: self.user_clients[user_id].discard(client)
                if not self.user_clients[user_id]: break
        finally:
            await pubsub.close()
            if self.user_tasks.get(user_id) is asyncio.current_task(): self.user_tasks.pop(user_id, None)
    async def publish_user(self, user_id, event): await self.redis.publish(f"user:{user_id}", json.dumps(event))
    async def leave_user(self, user_id, websocket):
        self.user_clients[user_id].discard(websocket)
        if not self.user_clients[user_id]:
            task = self.user_tasks.pop(user_id, None)
            if task: task.cancel()
collaboration = Collaboration()
