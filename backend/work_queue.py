"""One shared two-slot queue for imports and question reconstruction."""
from concurrent.futures import ThreadPoolExecutor
from threading import Lock,RLock
pool=ThreadPoolExecutor(max_workers=2,thread_name_prefix='question-work')
submission_lock=RLock()
session_lock=Lock()
