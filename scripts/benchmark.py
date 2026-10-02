#!/usr/bin/env python3
"""Local HTTP benchmark. Does not send traffic to IPs being looked up."""
import argparse, concurrent.futures, http.client, ipaddress, json, math, random, statistics, subprocess, time
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit, quote

def resource(container):
    if not container: return None
    result={}
    for name in ['memory.current','memory.peak','memory.stat','cpu.stat']:
        text=subprocess.check_output(['docker','exec',container,'cat','/sys/fs/cgroup/'+name],text=True)
        if '\n' not in text.strip(): result[name]=int(text.strip())
        else: result[name]={a:int(b) for a,b in (line.split() for line in text.splitlines())}
    return result

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--base',default='http://127.0.0.1:8080')
    parser.add_argument('--requests',type=int,default=10000)
    parser.add_argument('--workers',type=int,default=16)
    parser.add_argument('--container')
    parser.add_argument('--output',default='artifacts/benchmark.json')
    args=parser.parse_args(); target=urlsplit(args.base)
    if target.hostname not in ['127.0.0.1','localhost','::1']: parser.error('This benchmark is intentionally local-only.')
    if args.requests<1 or args.workers<1: parser.error('Positive requests and workers required.')
    rng=random.Random(20260929); ips=[]
    while len(ips)<args.requests:
        if len(ips)%4==0:
            ip=ipaddress.ip_address((int(ipaddress.ip_address('2606:4700::')) | rng.getrandbits(96)))
        else:
            ip=ipaddress.ip_address(rng.getrandbits(32))
        if ip.is_global and not ip.is_multicast: ips.append(str(ip))
    batches=[ips[i::args.workers] for i in range(args.workers)]
    def worker(batch):
        conn=(http.client.HTTPSConnection if target.scheme=='https' else http.client.HTTPConnection)(target.hostname,target.port,timeout=10)
        latencies=[]; statuses=Counter()
        for ip in batch:
            start=time.perf_counter()
            try:
                conn.request('GET','/json?ip='+quote(ip)); response=conn.getresponse(); response.read(); statuses[str(response.status)]+=1
            except Exception:
                statuses['transport_error']+=1;conn.close()
            latencies.append((time.perf_counter()-start)*1000)
        conn.close(); return latencies,statuses
    report={'base':args.base,'requests_per_pass':args.requests,'workers':args.workers,'unique_ips':len(set(ips)), 'conditions':'First pass is process-cold only if the operator restarted the service; host/VM file cache may already be warm. Client and server share the local device. Python load generation and Docker networking affect results.','passes':[]}
    for label in ['first_pass','warm_repeat']:
        before=resource(args.container); started=time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool: results=list(pool.map(worker,batches))
        elapsed=time.perf_counter()-started; after=resource(args.container)
        times=sorted(t for durations,_ in results for t in durations); statuses=sum((s for _,s in results),Counter())
        percentile=lambda p:round(times[min(len(times)-1,math.ceil(p*len(times))-1)],3)
        row={'name':label,'seconds':round(elapsed,3),'requests_per_second':round(len(times)/elapsed,1),'p50_ms':percentile(.5),'p95_ms':percentile(.95),'p99_ms':percentile(.99),'statuses':dict(statuses),'resource_before':before,'resource_after':after}
        if before and after: row['cpu_core_percent']=round((after['cpu.stat']['usage_usec']-before['cpu.stat']['usage_usec'])/(elapsed*10000),2)
        report['passes'].append(row); print(json.dumps({k:v for k,v in row.items() if not k.startswith('resource_')},indent=2))
    Path(args.output).parent.mkdir(parents=True,exist_ok=True);Path(args.output).write_text(json.dumps(report,indent=2)+'\n')
if __name__=='__main__':main()
