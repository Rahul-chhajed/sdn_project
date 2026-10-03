# SDN Dynamic LLM Placement Prototype

This project is a runnable Mininet prototype for steering a virtual LLM service between an edge and cloud backend with OS-Ken, OpenFlow 1.3, and Open vSwitch.

## Architecture

- `client` sends HTTP requests to the virtual service `10.0.0.50:8000`.
- `s1` is an OpenFlow 1.3 OVS switch. Its ports are client=1, edge=2, cloud=3.
- `edge` has a 2 ms link and a 120 ms synthetic inference time.
- `cloud` has a 25 ms link and a 45 ms synthetic inference time.
- `controller.py` chooses a backend using latency, bandwidth, and reported load, then installs an OpenFlow flow for the service IP.
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
sudo -E "$VIRTUAL_ENV/bin/osken-manager" controller.py \
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
sudo -E "$VIRTUAL_ENV/bin/python" topology.py --cli
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

The request goes to `10.0.0.50:8000`. The controller changes the OVS output path: port 2 is edge and port 3 is cloud.

## Demonstrate decisions

Use Terminal 3 to set the routing policy. The controller automatically removes its old service flow whenever policy or load changes, so the next request is evaluated immediately.

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
- A policy change appears ineffective: confirm that the updated `controller.py` is copied into the VM, restart OS-Ken, and send a new request.
- `Address already in use`: stop old processes with `Ctrl+C`, then run `sudo mn -c`.

When finished, exit Mininet and clean up:

```text
mininet> exit
```

```bash
sudo mn -c
```
