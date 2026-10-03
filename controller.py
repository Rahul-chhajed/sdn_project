"""OS-Ken controller for dynamic edge/cloud LLM service steering."""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from os_ken.base import app_manager
from os_ken.controller import ofp_event
from os_ken.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from os_ken.ofproto import ofproto_v1_3
from os_ken.lib import hub
from os_ken.lib.packet import arp, ethernet, ipv4, packet, tcp

SERVICE_IP = "10.0.0.50"
SERVICE_PORT = 8000
VIRTUAL_MAC = "00:00:00:00:00:fe"

BACKENDS = {
    "edge": {
        "ip": "10.0.0.10",
        "mac": "00:00:00:00:00:02",
        "port": 2,
        "latency_ms": 4.0,
        "bandwidth_mbps": 100.0,
        "load": 0.0,
    },
    "cloud": {
        "ip": "10.0.0.20",
        "mac": "00:00:00:00:00:03",
        "port": 3,
        "latency_ms": 35.0,
        "bandwidth_mbps": 1000.0,
        "load": 0.0,
    },
}


class SteeringState:
    def __init__(self):
        self.mode = "dynamic"
        self.static_backend = "cloud"
        self.last_backend = "edge"
        self.last_scores = {}
        self.packet_count = 0
        self.byte_count = 0
        self.port_stats = {}
        self.lock = threading.Lock()

    def choose_backend(self):
        with self.lock:
            if self.mode == "static":
                return self.static_backend
            scores = {}
            for name, backend in BACKENDS.items():
                load_penalty = backend["load"] * 45.0
                bandwidth_penalty = max(0.0, 100.0 - backend["bandwidth_mbps"]) / 10.0
                scores[name] = backend["latency_ms"] + load_penalty + bandwidth_penalty
            selected = min(scores, key=scores.get)
            self.last_scores = scores
            self.last_backend = selected
            return selected

    def snapshot(self):
        with self.lock:
            scores = {}
            for name, backend in BACKENDS.items():
                load_penalty = backend["load"] * 45.0
                bandwidth_penalty = max(0.0, 100.0 - backend["bandwidth_mbps"]) / 10.0
                scores[name] = round(backend["latency_ms"] + load_penalty + bandwidth_penalty, 2)
            return {
                "mode": self.mode,
                "static_backend": self.static_backend,
                "last_backend": self.last_backend,
                "last_scores": self.last_scores or scores,
                "current_scores": scores,
                "packet_count": self.packet_count,
                "byte_count": self.byte_count,
                "backends": BACKENDS,
                "port_stats": self.port_stats,
            }


class DynamicLLMController(app_manager.OSKenApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.state = SteeringState()
        self.mac_to_port = {}
        self.datapaths = {}
        self.monitor_thread = hub.spawn(self._monitor)
        self.api_thread = self._start_api_server()

    def _start_api_server(self):
        host = os.getenv("SDN_API_HOST", "127.0.0.1")
        port = int(os.getenv("SDN_API_PORT", "8080"))
        SteeringAPIHandler.app = self
        server = ThreadingHTTPServer((host, port), SteeringAPIHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return thread

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        self.datapaths[datapath.id] = datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)

    def add_flow(self, datapath, priority, match, actions, idle_timeout=0, hard_timeout=0):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        instructions = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        request = parser.OFPFlowMod(
            datapath=datapath,
            priority=priority,
            match=match,
            instructions=instructions,
            idle_timeout=idle_timeout,
            hard_timeout=hard_timeout,
        )
        datapath.send_msg(request)

    def _clear_service_flows(self):
        for datapath in list(self.datapaths.values()):
            parser = datapath.ofproto_parser
            ofproto = datapath.ofproto
            for priority in (200, 201):
                request = parser.OFPFlowMod(
                    datapath=datapath,
                    command=ofproto.OFPFC_DELETE,
                    out_port=ofproto.OFPP_ANY,
                    out_group=ofproto.OFPG_ANY,
                    priority=priority,
                    match=parser.OFPMatch(),
                )
                datapath.send_msg(request)

    def _install_service_flow(self, datapath, in_port, backend_name):
        backend = BACKENDS[backend_name]
        parser = datapath.ofproto_parser
        match = parser.OFPMatch(
            in_port=in_port,
            eth_type=0x0800,
            ipv4_dst=SERVICE_IP,
            ip_proto=6,
            tcp_dst=SERVICE_PORT,
        )
        actions = [
            parser.OFPActionSetField(eth_dst=backend["mac"]),
            parser.OFPActionOutput(backend["port"]),
        ]
        self.add_flow(datapath, 200, match, actions, idle_timeout=20)
        reverse_match = parser.OFPMatch(
            in_port=backend["port"],
            eth_type=0x0800,
            ipv4_src=SERVICE_IP,
            ip_proto=6,
            tcp_src=SERVICE_PORT,
        )
        reverse_actions = [
            parser.OFPActionSetField(eth_src=VIRTUAL_MAC),
            parser.OFPActionOutput(1),
        ]
        self.add_flow(datapath, 201, reverse_match, reverse_actions, idle_timeout=20)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        message = ev.msg
        datapath = message.datapath
        in_port = message.match["in_port"]
        parsed = packet.Packet(message.data)
        eth = parsed.get_protocol(ethernet.ethernet)
        if eth is None:
            return
        self.mac_to_port.setdefault(datapath.id, {})[eth.src] = in_port
        self.state.packet_count += 1
        self.state.byte_count += len(message.data)

        arp_packet = parsed.get_protocol(arp.arp)
        if arp_packet and arp_packet.opcode == arp.ARP_REQUEST and arp_packet.dst_ip == SERVICE_IP:
            self._reply_to_arp(datapath, in_port, eth, arp_packet)
            return

        ip_packet = parsed.get_protocol(ipv4.ipv4)
        tcp_packet = parsed.get_protocol(tcp.tcp)
        if ip_packet and tcp_packet and ip_packet.dst == SERVICE_IP and tcp_packet.dst_port == SERVICE_PORT:
            backend_name = self.state.choose_backend()
            self._install_service_flow(datapath, in_port, backend_name)
            self._forward(datapath, message, backend_name)
            return

        destination_port = self.mac_to_port[datapath.id].get(eth.dst, datapath.ofproto.OFPP_FLOOD)
        self._send_packet_out(datapath, message, destination_port)

    def _forward(self, datapath, message, backend_name):
        parser = datapath.ofproto_parser
        backend = BACKENDS[backend_name]
        actions = [
            parser.OFPActionSetField(eth_dst=backend["mac"]),
            parser.OFPActionOutput(backend["port"]),
        ]
        self._send_packet_out(datapath, message, actions=actions)

    def _send_packet_out(self, datapath, message, out_port=None, actions=None):
        if actions is None:
            actions = [datapath.ofproto_parser.OFPActionOutput(out_port)]
        request = datapath.ofproto_parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=message.buffer_id,
            in_port=message.match.get("in_port", datapath.ofproto.OFPP_CONTROLLER),
            actions=actions,
            data=None if message.buffer_id != datapath.ofproto.OFP_NO_BUFFER else message.data,
        )
        datapath.send_msg(request)

    def _reply_to_arp(self, datapath, in_port, eth, request):
        reply = packet.Packet()
        reply.add_protocol(ethernet.ethernet(ethertype=0x0806, dst=eth.src, src=VIRTUAL_MAC))
        reply.add_protocol(arp.arp(
            opcode=arp.ARP_REPLY,
            src_mac=VIRTUAL_MAC,
            src_ip=SERVICE_IP,
            dst_mac=request.src_mac,
            dst_ip=request.src_ip,
        ))
        reply.serialize()
        action = datapath.ofproto_parser.OFPActionOutput(in_port)
        packet_out = datapath.ofproto_parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=datapath.ofproto.OFP_NO_BUFFER,
            in_port=datapath.ofproto.OFPP_CONTROLLER,
            actions=[action],
            data=reply.data,
        )
        datapath.send_msg(packet_out)

    def _monitor(self):
        while True:
            for datapath in list(self.datapaths.values()):
                datapath.send_msg(datapath.ofproto_parser.OFPPortStatsRequest(datapath, 0, datapath.ofproto.OFPP_ANY))
            hub.sleep(2)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_handler(self, ev):
        stats = {}
        for item in ev.msg.body:
            stats[str(item.port_no)] = {
                "rx_bytes": item.rx_bytes,
                "tx_bytes": item.tx_bytes,
                "rx_packets": item.rx_packets,
                "tx_packets": item.tx_packets,
            }
        with self.state.lock:
            self.state.port_stats[str(ev.msg.datapath.id)] = stats


class SteeringAPIHandler(BaseHTTPRequestHandler):
    app = None

    def log_message(self, format_string, *args):
        return

    def _json_response(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_payload(self):
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length).decode("utf-8") or "{}")

    def do_GET(self):
        if self.path == "/status":
            self._json_response(200, self.app.state.snapshot())
        else:
            self._json_response(404, {"error": "not found"})

    def do_POST(self):
        try:
            payload = self._read_payload()
        except (TypeError, ValueError, json.JSONDecodeError):
            self._json_response(400, {"error": "request body must be valid JSON"})
            return

        if self.path == "/policy":
            self._policy(payload)
        elif self.path.startswith("/load/"):
            self._load(self.path.split("/", 2)[-1], payload)
        else:
            self._json_response(404, {"error": "not found"})

    def _policy(self, payload):
        mode = payload.get("mode", "dynamic")
        if mode not in ("dynamic", "static"):
            self._json_response(400, {"error": "mode must be dynamic or static"})
            return
        with self.app.state.lock:
            self.app.state.mode = mode
            if payload.get("backend") in BACKENDS:
                self.app.state.static_backend = payload["backend"]
        self.app._clear_service_flows()
        self._json_response(200, self.app.state.snapshot())

    def _load(self, backend, payload):
        if backend not in BACKENDS:
            self._json_response(404, {"error": "unknown backend"})
            return
        try:
            value = max(0.0, min(1.0, float(payload.get("load", 0.0))))
        except (TypeError, ValueError):
            self._json_response(400, {"error": "load must be a number from 0.0 to 1.0"})
            return
        with self.app.state.lock:
            BACKENDS[backend]["load"] = value
            if "latency_ms" in payload:
                BACKENDS[backend]["latency_ms"] = max(0.1, float(payload["latency_ms"]))
        self.app._clear_service_flows()
        self._json_response(200, self.app.state.snapshot())
