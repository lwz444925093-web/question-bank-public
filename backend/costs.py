"""Estimated Flash 4.1 CNY charges; official rate card checked 2026-09-18."""
from datetime import datetime,timezone,timedelta
RATE_URL='https://api-docs.deepseek.com/zh-cn/quick_start/pricing/'
def flash_cost(tokens,when):
 t=datetime.fromtimestamp(when,timezone(timedelta(hours=8)))
 peak=t.weekday()<5 and (9<=t.hour<12 or 14<=t.hour<18)
 factor=2 if peak else 1
 # OpenCode separates non-cached input, cache reads, output text and reasoning.
 uncached=tokens.get('input',0);cached=tokens.get('cache',{}).get('read',0)
 output=tokens.get('output',0)+tokens.get('reasoning',0)
 amount=(uncached+cached*.02+output*4)*factor/1_000_000
 return dict(currency='CNY',estimated=True,amount=round(amount,6),period='高峰' if peak else '空闲',input_uncached=uncached,input_cached=cached,output_including_reasoning=output,rate_url=RATE_URL,rate_date='2026-09-18')
