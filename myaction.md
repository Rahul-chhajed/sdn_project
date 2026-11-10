## 1. Project Explanation

The project implements a software-defined cloud-edge LLM placement system.

The client always sends requests to the same virtual service:

```text
10.0.0.50:8000
```

The SDN controller decides where the request should execute:

```text
Client -> OpenFlow switch -> Edge or Cloud
```

The controller evaluates:

- Network latency
- Backend load
- Available models
- Available adapters
- Quality requirement
- Reasoning level
- Privacy restriction
- Session/KV-cache location
- Estimated latency

The main components are:

- `topology.py`: Creates the Mininet network.
- `controller.py`: Runs the OS-Ken SDN controller.
- `orchestration.py`: Makes the model-placement decision.
- `llm_server.py`: Simulates edge and cloud inference.
- `client.py`: Sends requests.
- `run_experiment.py`: Runs static and dynamic experiments.
- `analyze_results.py`: Calculates mathematical metrics.

## 2. Experiment Phases

### Static-cloud phase

All 30 requests were sent to:

```text
Backend: cloud
Model: large
Adapter: none
Reasoning level: 0
Quality: 0.91
```

This is the baseline where every request uses the large cloud model.

### Dynamic phase

All 30 requests were sent to:

```text
Backend: edge
Model: small
Adapter: networking
Reasoning level: 1
Reasoning tokens: 128
Quality: 0.74
```

This happened because the backend loads were reset to zero before the dynamic phase. The controller therefore preferred the lower-latency edge.

## 3. Exact Mathematical Results

Using a deadline of `500 ms`:

| Metric | Static Cloud | Dynamic Edge |
|---|---:|---:|
| Requests | 30 | 30 |
| Backend distribution | Cloud: 30 | Edge: 30 |
| Model | Large | Small |
| Mean end-to-end latency | 393.85 ms | 247.45 ms |
| Standard deviation | 38.48 ms | 35.11 ms |
| p95 latency | 466.81 ms | 290.06 ms |
| Mean inference time | 215.02 ms | 183.12 ms |
| SLA violation rate | 3.33% | 0% |
| Mean quality | 0.91 | 0.74 |
| Mean reasoning tokens | 0 | 128 |
| KV migration | 0 | 1 |
| Local KV reuse | 30 | 29 |

### Mean latency improvement

The analyzer uses:

$$
\text{Latency reduction} =
\frac{T_{\text{static}} - T_{\text{dynamic}}}
{T_{\text{static}}}
\times 100
$$

Substituting the measured values:

$$
\frac{393.85 - 247.45}{393.85}
\times 100
= 37.17\%
$$

Therefore, dynamic edge orchestration reduced average end-to-end latency by:

```text
37.17%
```

### p95 improvement

$$
\frac{466.81 - 290.06}
{466.81}
\times 100
= 37.86\%
$$

The dynamic strategy reduced p95 latency by approximately:

```text
37.86%
```

### SLA violations

The SLA deadline was:

```text
D_i = 500 ms
```

Static cloud:

```text
1 of 30 requests exceeded 500 ms
SLA violation rate = 1 / 30 = 3.33%
```

Dynamic edge:

```text
0 of 30 requests exceeded 500 ms
SLA violation rate = 0%
```

## 4. Meaning Of Every CSV Variable

| CSV variable | Meaning |
|---|---|
| `phase` | Experiment mode: `static_cloud` or `dynamic` |
| `request` | Request number. It is currently always `1` because the runner starts the client once per request |
| `backend` | Actual selected execution location: edge or cloud |
| `model` | Selected model size: small, medium, or large |
| `adapter` | Domain adapter, such as networking |
| `reasoning_level` | Reasoning effort from 0 to 3 |
| `reasoning_tokens` | Extra reasoning tokens allocated |
| `state_action` | `local_reuse`, `kv_migrate`, or `context_recompute` |
| `quality` | Simulated predicted answer quality |
| `inference_ms` | Time spent by the backend emulator |
| `end_to_end_ms` | Full client-observed latency, including network and inference |

The `request` column does not affect the mathematical analysis. The number of rows is the actual request count.

## 5. PDF Variables Mapped To The Project

The PDF defines a request as:

$$
R_i = (P_i, H_i, D_i, Q_i^{min}, \rho_i, c_i)
$$

The prototype maps these variables as follows:

| PDF variable | Project variable |
|---|---|
| $P_i$ | Prompt text |
| $H_i$ | `context_tokens` |
| $D_i$ | `deadline_ms` |
| $Q_i^{min}$ | `quality_min` |
| $\rho_i$ | `privacy` |
| $c_i$ | `task` and `complexity` |

The decision variables in the PDF are:

$$
(n_i, m_i, a_i, b_i, \mu_i)
$$

They map to:

| PDF variable | Project meaning |
|---|---|
| $n_i$ | Selected backend |
| $m_i$ | Selected model |
| $a_i$ | Selected adapter |
| $b_i$ | Reasoning level |
| $\mu_i$ | KV migration or context recomputation decision |

## 6. Quality Equation

The prototype calculates quality using:

$$
Q_i =
\min
\left(
1,\;
Q_m + Q_a + Q_b
\right)
$$

For the static cloud phase:

```text
Large model quality = 0.91
Adapter bonus = 0
Reasoning bonus = 0
```

Therefore:

$$
Q_{\text{static}} = 0.91
$$

For the dynamic edge phase:

```text
Small model quality = 0.58
Networking adapter bonus = 0.10
Reasoning level 1 bonus = 0.06
```

Therefore:

$$
Q_{\text{dynamic}}
=
0.58 + 0.10 + 0.06
=
0.74
$$

This explains the tradeoff:

```text
Static cloud: higher quality, higher latency
Dynamic edge: lower simulated quality, lower latency
```

## 7. Latency Equation

The PDF defines total latency as:

$$
T_i =
T_i^{UL}
+
T_i^{queue}
+
T_i^{state}
+
T_i^{inf}
+
T_i^{DL}
$$

The prototype approximates this with:

$$
T_i =
T_{\text{network}}
+
T_{\text{model}}
+
T_{\text{reasoning}}
+
T_{\text{state}}
$$

The measured `end_to_end_ms` additionally includes real Mininet, TCP, HTTP, and operating-system overhead.

That is why measured latency is not exactly equal to the synthetic model inference time.

## 8. KV-State Equations

The PDF defines three possibilities.

### Local reuse

If the session remains on the same backend:

$$
T_i^{state} = 0
$$

This is represented by:

```text
state_action = local_reuse
```

Your result contains:

```text
29 local_reuse requests during dynamic execution
```

### KV migration

The prototype uses:

$$
T_i^{mig}
=
8
+
\frac{V_s \times 8}
{R_{j,n} \times 1000}
$$

where:

- $V_s$ is KV size in bytes.
- $R_{j,n}$ is state-transfer bandwidth in Mbps.
- `8 ms` is the simulated transfer protocol overhead.

Your CSV contains:

```text
kv_migrate: 1
```

This means the first dynamic request moved the session state from a previous backend to the edge.

### Context recomputation

The prototype uses:

$$
T_i^{rec}
=
\max
\left(
5,\;
\frac{H_i \times L_m}{1000}
\right)
$$

where:

- $H_i$ is the number of context tokens.
- $L_m$ is model latency.

Your current run did not use context recomputation:

```text
context_recompute: 0
```

## 9. Controller Score Equation

The controller selects the feasible configuration with the lowest score:

$$
\text{Score}
=
T
+
80L
+
20C_m
+
15C_b
+
0.25T^{state}
$$

where:

- $T$: estimated total latency.
- $L$: backend load.
- $C_m$: model cost.
- $C_b$: reasoning cost.
- $T^{state}$: migration or recomputation delay.

Under normal load, edge has lower network latency, so it wins.

Under high edge load, the load penalty increases and the controller can select cloud.

## 10.Conclusion

> We implemented a stateful SDN-based cloud-edge LLM placement prototype. In the baseline experiment, all requests were sent to a large cloud model. In the dynamic experiment, the controller selected a small networking-adapted model at the edge with light reasoning. The dynamic strategy reduced mean end-to-end latency from 393.85 ms to 247.45 ms, corresponding to a 37.17% improvement. The p95 latency decreased by 37.86%, and the SLA violation rate decreased from 3.33% to 0%. The dynamic phase maintained a simulated quality of 0.74 compared with 0.91 for the large cloud model, demonstrating the latency-quality tradeoff described in the RACE-LM problem statement. One KV migration and 29 local KV reuses were observed.
