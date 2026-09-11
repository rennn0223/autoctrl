"""Manual live Isaac Sim UI acceptance: python3 tests/navigation_ui_acceptance.py.
Requires pexpect, Isaac Sim Play, and a clear scene. Drives /sim only.
"""
import pexpect,os,time,json
from pathlib import Path
root=Path('results/navigation-ui');root.mkdir(parents=True,exist_ok=True)
child=pexpect.spawn('scripts/start-sim-ui',['-p','doctor_timeout_s:=0.2'],encoding='utf-8',timeout=30,env={**os.environ,'TERM':'xterm-256color'},dimensions=(45,150))
log=(root/'terminal.log').open('w');child.logfile=log
results={}
try:
 child.expect('›')
 for name,text,match,timeout in [('waypoints','先到（0.7, 0），再到（1.4, 0.3）','導航完成',70),('figure8','走八字，半徑 0.8 公尺','導航完成',240),('vision','看看前面','正在看前方畫面',15)]:
  started=time.monotonic();child.sendline(text)
  if name == 'waypoints':child.expect('依序前往',timeout=15)
  if name == 'figure8':child.expect('八字：半徑',timeout=15)
  child.expect(match,timeout=timeout)
  if name == 'figure8':assert time.monotonic()-started > 30, 'stale completion text matched'
  results[name]={'input':text,'ui_match':match,'elapsed_s':time.monotonic()-started}
  print(name,results[name],flush=True)
  if name=='vision':
   child.expect('›');child.sendline('走八字');child.expect('以目前位置為原點');child.sendline('停止');child.expect('已停止並取消導航')
   results['stop_while_vision']={'passed':True}
   child.expect('(?:方塊|立方體|錐體|車輛|小車|地面|畫面中|賽車)',timeout=120)
   results['vision']['description_received']=True
 child.sendline('/exit');child.expect('AutoCtrl 已安全停止');child.expect(pexpect.EOF,timeout=20)
finally:
 if child.isalive():
  child.sendcontrol('c')
  try:child.expect(pexpect.EOF,timeout=10)
  except pexpect.TIMEOUT:child.terminate(force=True)
 log.close();(root/'acceptance.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
