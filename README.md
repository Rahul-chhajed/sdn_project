# SDN Dynamic LLM Placement Prototype

This project is a runnable Mininet prototype for steering a virtual LLM service between an edge and cloud backend with OS-Ken, OpenFlow 1.3, and Open vSwitch.

## Architecture

- `client` sends HTTP requests to the virtual service `10.0.0.50:8000`.
- `s1` is an OpenFlow 1.3 OVS switch. Its ports are client=1, edge=2, cloud=3.
- `edge` has a 2 ms link and a 120 ms synthetic inference time.
- `cloud` has a 25 ms link and a 45 ms synthetic inference time.
- `controller.py` chooses a backend using latency, bandwidth, and reported load, then installs forward and reverse OpenFlow flows for the service IP.
- `llm_server.py` is a deterministic HTTP emulator, so the experiment does not need a real model or GPU.

The virtual service IP is intentionally shared by the two backend hosts. The controller changes only the destination MAC and output port, so the client uses the same URL in every experiment.

## VM setup

Run once in Ubuntu. This example uses the actual project path shown in the VM terminal; replace it if your path is different.

```bash
cd ~/Desktop/sdn_project
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
sudo apt-get update
sudo apt-get install -y mininet openvswitch-switch curl
sudo systemctl enable --now openvswitch-switch
```

OS-Ken 4.2.2 uses `OSKenApp` and does not support `--wsapi-port`. The controller starts its REST API itself on `127.0.0.1:8080`.

## Manual test

Use three terminals. Keep Terminals 1 and 2 running.

### Terminal 1: OS-Ken controller

```bash
cd ~/Desktop/sdn_project
source .venv/bin/activate
sudo -E "$VIRTUAL_VENV/bin/osken-manager" controller.py \
	--ofp-tcp-listen-port 6653
```

Do not add `--wsapi-port` and do not run `osken-manager --help`; this OS-Ken version treats `--help` as an app name.

### Terminal 3: Verify the controller API

```bash
curl http://127.0.0.1:8080/status
sudo ss -ltnp | grep -E ':6653|:8080'
```

The first command should return JSON. If it fails, OS-Ken is not running correctly.

### Terminal 2: Start Mininet

```bash
cd ~/Desktop/sdn_project
source .venv/bin/activate
sudo mn -c
sudo -E "$VIRTUAL_VENV/bin/python3" topology.py --cli
```

The topology automatically starts the edge and cloud HTTP emulators. At the `mininet>` prompt, verify both services:

```text
edge curl http://10.0.0.10:8000/health
cloud curl http://10.0.0.20:8000/health
```

Expected results:

```json
{"backend": "edge", "active": 0, "completed": 0}
{"backend": "cloud", "active": 0, "completed": 0}
```

Send a user prompt through the virtual service:

```text
client python3 /home/vboxuser/Desktop/sdn_project/client.py --requests 1 --prompt "Explain software defined networking"
```

The response includes the selected backend, inference time, and end-to-end time:

```json
{"request": 1, "backend": "edge", "response": "synthetic LLM response", "inference_ms": 120.0, "end_to_end_ms": 200.0}
```

The request goes to `10.0.0.50:8000`. The controller changes the OVS output path: port 2 is edge and port 3 is cloud. The reverse flow rewrites the response source MAC to the virtual service MAC and sends the response back through port 1.

The topology also installs a static ARP entry for the client on both backend hosts. This is required because the client uses the virtual service MAC, so the backend cannot learn the client's MAC from a normal ARP exchange.

## Demonstrate decisions

Use Terminal 3 to set the routing policy. The controller automatically removes only its old forward and reverse service flows when policy or load changes. The table-miss flow remains installed, so the next request is evaluated again.

### Dynamic mode selects edge

```bash
curl -X POST http://127.0.0.1:8080/policy \
	-H 'Content-Type: application/json' \
	-d '{"mode":"dynamic"}'
curl -X POST http://127.0.0.1:8080/load/edge \
	-H 'Content-Type: application/json' \
	-d '{"load":0.0}'
```

At the Mininet prompt:

```text
client python3 /home/vboxuser/Desktop/sdn_project/client.py --requests 1 --prompt "Test low latency edge inference"
```

Expected field:

```json
"backend": "edge"
```

### High edge load causes cloud selection

```bash
curl -X POST http://127.0.0.1:8080/load/edge \
	-H 'Content-Type: application/json' \
	-d '{"load":0.9}'
```

At the Mininet prompt:

```text
client python3 /home/vboxuser/Desktop/sdn_project/client.py --requests 1 --prompt "Test cloud inference under edge load"
```

Expected field:

```json
"backend": "cloud"
```

Show the controller decision:

```bash
curl http://127.0.0.1:8080/status
```

Show the OpenFlow rule installed by the controller:

```bash
sudo ovs-ofctl -O OpenFlow13 dump-flows s1
```

An edge rule outputs to port 2 and a cloud rule outputs to port 3.

## Automated comparison

Stop the Mininet CLI with `exit`, but leave OS-Ken running. Then run:

```bash
cd ~/Desktop/sdn_project
source .venv/bin/activate
sudo -E "$VIRTUAL_ENV/bin/python" run_experiment.py \
	--requests 20 \
	--prompt "Explain the benefits of edge AI" \
	--output results.csv
```

The runner starts Mininet, starts both emulators, runs static-cloud and dynamic phases, writes per-request measurements to `results.csv`, and prints average latency and backend counts.

## What to extend next

1. Replace `llm_server.py` with real edge and cloud inference adapters.
2. Feed real CPU/GPU utilization to `/load/{backend}` from an agent on each server.
3. Add a multi-switch topology and use port-stat deltas as a bandwidth estimator.
4. Add repeated trials and confidence intervals before reporting results.

## Troubleshooting and cleanup

- `Unable to contact the remote controller`: start OS-Ken first, then run `sudo ovs-vsctl show` and confirm the switch has controller `tcp:127.0.0.1:6653`.
- `Connection refused` on port 8000: at the Mininet prompt run `edge cat /tmp/edge.log`, `cloud cat /tmp/cloud.log`, `edge ps`, and `cloud ps`.
- A policy change appears ineffective: confirm that the latest `controller.py` is copied into the VM, restart OS-Ken and Mininet, then send a new request.
- `Address already in use`: stop old processes with `Ctrl+C`, then run `sudo mn -c`.

When finished, exit Mininet and clean up:

```text
mininet> exit
```


result.csv
```text
phase,request,backend,model,adapter,reasoning_level,reasoning_tokens,state_action,quality,inference_ms,end_to_end_ms
static_cloud,1,cloud,large,none,0,0,local_reuse,0.91,195.86,386.6
static_cloud,1,cloud,large,none,0,0,local_reuse,0.91,196.19,377.67
static_cloud,1,cloud,large,none,0,0,local_reuse,0.91,206.29,417.87
static_cloud,1,cloud,large,none,0,0,local_reuse,0.91,195.35,360.28
static_cloud,1,cloud,large,none,0,0,local_reuse,0.91,195.96,365.56
static_cloud,1,cloud,large,none,0,0,local_reuse,0.91,300.86,497.99
static_cloud,1,cloud,large,none,0,0,local_reuse,0.91,204.35,391.81
static_cloud,1,cloud,large,none,0,0,local_reuse,0.91,201.29,403.42
static_cloud,1,cloud,large,none,0,0,local_reuse,0.91,271.53,466.64
static_cloud,1,cloud,large,none,0,0,local_reuse,0.91,195.07,372.63
static_cloud,1,cloud,large,none,0,0,local_reuse,0.91,212.98,385.41
static_cloud,1,cloud,large,none,0,0,local_reuse,0.91,249.31,458.54
static_cloud,1,cloud,large,none,0,0,local_reuse,0.91,221.48,442.89
static_cloud,1,cloud,large,none,0,0,local_reuse,0.91,201.09,423.84
static_cloud,1,cloud,large,none,0,0,local_reuse,0.91,212.22,377.6
static_cloud,1,cloud,large,none,0,0,local_reuse,0.91,195.89,353.92
static_cloud,1,cloud,large,none,0,0,local_reuse,0.91,333.19,566.9
static_cloud,1,cloud,large,none,0,0,local_reuse,0.91,626.17,1058.56
static_cloud,1,cloud,large,none,0,0,local_reuse,0.91,285.88,490.8
static_cloud,1,cloud,large,none,0,0,local_reuse,0.91,260.92,470.9
static_cloud,1,cloud,large,none,0,0,local_reuse,0.91,326.23,568.37
static_cloud,1,cloud,large,none,0,0,local_reuse,0.91,844.82,1463.56
static_cloud,1,cloud,large,none,0,0,local_reuse,0.91,213.76,594.43
static_cloud,1,cloud,large,none,0,0,local_reuse,0.91,234.94,576.95
static_cloud,1,cloud,large,none,0,0,local_reuse,0.91,256.44,495.61
static_cloud,1,cloud,large,none,0,0,local_reuse,0.91,235.11,427.9
static_cloud,1,cloud,large,none,0,0,local_reuse,0.91,199.02,368.68
static_cloud,1,cloud,large,none,0,0,local_reuse,0.91,195.56,363.19
static_cloud,1,cloud,large,none,0,0,local_reuse,0.91,195.82,408.68
static_cloud,1,cloud,large,none,0,0,local_reuse,0.91,200.69,390.03
dynamic,1,cloud,small,networking,1,128,local_reuse,0.74,110.81,305.06
dynamic,1,cloud,small,networking,1,128,local_reuse,0.74,102.08,328.51
dynamic,1,cloud,small,networking,1,128,local_reuse,0.74,106.53,335.68
dynamic,1,cloud,small,networking,1,128,local_reuse,0.74,103.22,318.36
dynamic,1,cloud,small,networking,1,128,local_reuse,0.74,143.2,313.56
dynamic,1,cloud,small,networking,1,128,local_reuse,0.74,100.7,267.86
dynamic,1,cloud,small,networking,1,128,local_reuse,0.74,193.11,384.25
dynamic,1,cloud,small,networking,1,128,local_reuse,0.74,135.33,320.22
dynamic,1,cloud,small,networking,1,128,local_reuse,0.74,116.62,315.11
dynamic,1,cloud,small,networking,1,128,local_reuse,0.74,101.59,290.91
dynamic,1,cloud,small,networking,1,128,local_reuse,0.74,188.19,389.02
dynamic,1,cloud,small,networking,1,128,local_reuse,0.74,108.01,264.82
dynamic,1,cloud,small,networking,1,128,local_reuse,0.74,278.76,501.85
dynamic,1,cloud,small,networking,1,128,local_reuse,0.74,137.02,449.11
dynamic,1,cloud,small,networking,1,128,local_reuse,0.74,194.25,453.35
dynamic,1,cloud,small,networking,1,128,local_reuse,0.74,130.32,354.39
dynamic,1,cloud,small,networking,1,128,local_reuse,0.74,100.63,323.42
dynamic,1,cloud,small,networking,1,128,local_reuse,0.74,149.58,638.88
dynamic,1,cloud,small,networking,1,128,local_reuse,0.74,101.38,497.35
dynamic,1,cloud,small,networking,1,128,local_reuse,0.74,100.2,467.16
dynamic,1,cloud,small,networking,1,128,local_reuse,0.74,104.94,375.17
dynamic,1,cloud,small,networking,1,128,local_reuse,0.74,139.65,337.31
dynamic,1,cloud,small,networking,1,128,local_reuse,0.74,101.07,298.96
dynamic,1,cloud,small,networking,1,128,local_reuse,0.74,100.72,329.63
dynamic,1,cloud,small,networking,1,128,local_reuse,0.74,101.19,314.25
dynamic,1,cloud,small,networking,1,128,local_reuse,0.74,105.5,330.66
dynamic,1,cloud,small,networking,1,128,local_reuse,0.74,108.17,333.81
dynamic,1,cloud,small,networking,1,128,local_reuse,0.74,101.31,333.16
dynamic,1,cloud,small,networking,1,128,local_reuse,0.74,175.33,386.87
dynamic,1,cloud,small,networking,1,128,local_reuse,0.74,100.51,508.33

```
sudo mn -c
```
