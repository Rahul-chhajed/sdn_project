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

Run these commands in Ubuntu inside the VM:

```bash
cd ~/sdn_project
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
sudo apt-get update
sudo apt-get install -y mininet openvswitch-switch curl
```

OS-Ken and Mininet require root privileges for the switch and network namespaces. Use the virtual environment's Python when starting OS-Ken, and use `sudo -E` so its environment is retained.

## Run manually

Terminal 1, from the activated virtual environment:

```bash
cd ~/sdn_project
source .venv/bin/activate
sudo -E osken-manager controller.py --ofp-tcp-listen-port 6653 --wsapi-port 8080
```

Terminal 2:

```bash
cd ~/sdn_project
source .venv/bin/activate
sudo -E python3 topology.py --cli
```

At the Mininet prompt, start the endpoint emulators:

```text
edge python3 /root/sdn_project/llm_server.py --name edge --inference-ms 120 > /tmp/edge.log 2>&1 &
cloud python3 /root/sdn_project/llm_server.py --name cloud --inference-ms 45 > /tmp/cloud.log 2>&1 &
client python3 /root/sdn_project/client.py --requests 10
```

Replace `/root/sdn_project` with the actual absolute path visible inside the VM. A request should return JSON with either `"backend": "edge"` or `"backend": "cloud"`.

Inspect controller state from a third terminal on the VM:

```bash
curl http://127.0.0.1:8080/status
curl -X POST http://127.0.0.1:8080/policy -H 'Content-Type: application/json' -d '{"mode":"static","backend":"cloud"}'
curl -X POST http://127.0.0.1:8080/policy -H 'Content-Type: application/json' -d '{"mode":"dynamic"}'
curl -X POST http://127.0.0.1:8080/load/edge -H 'Content-Type: application/json' -d '{"load":0.9}'
```

The load values are normalized from 0.0 to 1.0. Dynamic mode scores latency plus a load penalty; this keeps the policy transparent for a dissertation/demo and makes its decisions easy to reproduce.

## Automated comparison

Start the controller first, then run:

```bash
cd ~/sdn_project
source .venv/bin/activate
sudo -E python3 run_experiment.py --requests 20 --output results.csv
```

The runner starts Mininet, launches both emulators, runs a static-cloud phase and a dynamic phase, and writes per-request measurements to `results.csv`. It also prints a summary with mean end-to-end latency, inference latency, and selected backend counts.

## What to extend next

1. Replace `llm_server.py` with real edge and cloud inference adapters.
2. Feed real CPU/GPU utilization to `/load/{backend}` from an agent on each server.
3. Add a multi-switch topology and use port-stat deltas as a bandwidth estimator.
4. Add repeated trials and confidence intervals before reporting results.

## Troubleshooting

- `Unable to contact the remote controller`: start OS-Ken first and check `sudo ovs-vsctl show`.
- `Address already in use`: stop the old Mininet run with `sudo mn -c`, then restart the controller.
- No response from `10.0.0.50`: verify the server processes, the service alias with `edge ip addr`, and the controller flow with `sudo ovs-ofctl -O OpenFlow13 dump-flows s1`.
