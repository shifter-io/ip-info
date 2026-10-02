#!/usr/bin/env python3
"""Run the release server locally, sample process resources, preserve raw evidence."""
import argparse, json, os, socket, subprocess, time, urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
os.chdir(ROOT)
OUT=ROOT/'artifacts/stress'; OUT.mkdir(parents=True,exist_ok=True)
def snapshot(pid):
    fields=subprocess.check_output(['ps','-p',str(pid),'-o','rss=,%cpu=,time='],text=True).split()
    parts=fields[2].replace('-',':').split(':'); cpu=0
    for p in parts: cpu=cpu*60+float(p)
    return {'t':time.time(),'rss_mib':int(fields[0])/1024,'ps_cpu_percent':float(fields[1]),'cpu_seconds':cpu}
def health():
    with urllib.request.urlopen('http://127.0.0.1:18080/readyz',timeout=3) as r:return json.load(r)
def safe_health():
    try:return health()
    except Exception as error:return {'probe_error':str(error), 'server_alive':server.poll() is None}
parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--follow-up',action='store_true',help='Run only soak and overload diagnostics');args=parser.parse_args()
scenarios=[('varied',128,120),('varied',512,20),('churn',64,20)] if args.follow_up else [('varied',1,15),('varied',16,20),('varied',64,20),('varied',256,20),('varied',512,20),('hot',64,20),('mixed',128,20),('varied',128,120),('churn',64,20)]
report={'started':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'host':subprocess.check_output(['sysctl','hw.model','hw.memsize','hw.logicalcpu'],text=True),'phases':[]}
# Fail before starting if another service already owns our test port.
with socket.socket() as probe:
    probe.bind(('127.0.0.1',18080))
p=None
log=open(OUT/'server.log','w');server=subprocess.Popen(['target/release/ip-info'],env={**os.environ,'BIND_ADDR':'127.0.0.1:18080'},stdout=log,stderr=log)
try:
    for _ in range(100):
        if server.poll() is not None:raise RuntimeError('server exited during startup')
        try:report['initial_health']=health();break
        except Exception:time.sleep(.1)
    else:raise RuntimeError('server failed readiness')
    report['baseline']=snapshot(server.pid)
    for mode,workers,seconds in scenarios:
        before=snapshot(server.pid);p=subprocess.Popen(['target/release/examples/stress',str(workers),str(seconds),mode],stdout=subprocess.PIPE,text=True);samples=[]
        while p.poll() is None:
            samples.append(snapshot(server.pid));time.sleep(1)
        out=p.stdout.read()
        if p.returncode:raise RuntimeError(out)
        row=json.loads(out);after=snapshot(server.pid);row.update(samples=samples,before=before,after=after,server_cpu_core_percent=100*(after['cpu_seconds']-before['cpu_seconds'])/(after['t']-before['t']),peak_rss_mib=max(x['rss_mib'] for x in samples),readiness=safe_health());report['phases'].append(row)
        (OUT/'results.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in row.items() if k not in ['samples','before','after']}),flush=True)
    report['cooldown']=[]
    for _ in range(20):report['cooldown'].append(snapshot(server.pid));time.sleep(1)
    report['final_health']=safe_health()
finally:
    if p is not None and p.poll() is None:
        p.terminate()
        try:p.wait(timeout=6)
        except subprocess.TimeoutExpired:p.kill();p.wait()
    server.terminate()
    try:server.wait(timeout=15)
    except subprocess.TimeoutExpired:server.kill();server.wait()
    report['server_exit']=server.returncode;(OUT/'results.json').write_text(json.dumps(report,indent=2));log.close()
