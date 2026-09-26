"""Read-only change notifications; browsers do not poll full task/catalog payloads."""
import asyncio,sqlite3,time,threading
from . import store

def signature(conn):
    # Ignore request budgets and logs: only changes visible in the interface matter.
    result=[]
    for table,fields,where in [
        ('questions',['revision','review_status'],''),
        ('tasks',['status','stage','saved_count','finished_at','error'],''),
        ('settings',['status','stage','revision','finished_at']," WHERE id LIKE 'review-%'"),
    ]:
        columns=','.join("json_extract(body,'$."+field+"')" for field in fields)
        result.append(tuple(conn.execute('SELECT id,'+columns+' FROM '+table+where+' ORDER BY id').fetchall()))
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='trash'").fetchone():
        result.append(tuple(conn.execute('SELECT id FROM trash ORDER BY id').fetchall()))
    return tuple(result)

class ChangeReader:
    """Own the SSE connection until any in-flight worker query has finished."""
    def __init__(self):
        self.lock=threading.Lock();self.closing=threading.Event()
        self.conn=sqlite3.connect(store.DATA/'bank.sqlite',check_same_thread=False)
        self.conn.execute('PRAGMA query_only=ON')

    def snapshot(self,previous_version=None):
        with self.lock:
            if self.closing.is_set() or self.conn is None:return None
            version=self.conn.execute('PRAGMA data_version').fetchone()[0]
            return version,signature(self.conn) if version!=previous_version else None

    def close(self):
        self.closing.set()
        with self.lock:
            if self.conn is not None:
                self.conn.close();self.conn=None

async def stream(request):
    reader=ChangeReader()
    try:
        version,previous=await asyncio.to_thread(reader.snapshot);last=time.monotonic()
        # Reconnection always resynchronizes the client, including changes while offline.
        yield 'event: changed\ndata: {}\n\n'
        while not await request.is_disconnected():
            await asyncio.sleep(1)
            result=await asyncio.to_thread(reader.snapshot,version)
            if result is None:return
            current,latest=result
            if latest is not None:
                version=current
                if latest!=previous:
                    previous=latest;last=time.monotonic()
                    yield 'event: changed\ndata: {}\n\n'
            if time.monotonic()-last>=15:
                last=time.monotonic();yield ': keep-alive\n\n'
    finally:
        # Cancelling to_thread does not stop its SQLite call. Mark queued reads
        # closed immediately, then wait for the active read under the same lock.
        # Schedule close before awaiting, so repeated cancellation cannot skip it.
        reader.closing.set()
        closing=asyncio.get_running_loop().run_in_executor(None,reader.close)
        await asyncio.shield(closing)
