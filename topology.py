"""Mininet topology for the SDN-controlled edge/cloud LLM service."""
import argparse
import os
import time

from mininet.cli import CLI
from mininet.link import TCLink
from mininet.log import info, setLogLevel
from mininet.net import Mininet
from mininet.node import OVSKernelSwitch, RemoteController
from mininet.topo import Topo

SERVICE_IP = "10.0.0.50"
VIRTUAL_MAC = "00:00:00:00:00:fe"
CLIENT_IP = "10.0.0.100"
CLIENT_MAC = "00:00:00:00:00:01"


class LLMTopo(Topo):
    def build(self):
        switch = self.addSwitch("s1", cls=OVSKernelSwitch, protocols="OpenFlow13")
        client = self.addHost("client", ip=f"{CLIENT_IP}/24", mac=CLIENT_MAC)
        edge = self.addHost("edge", ip="10.0.0.10/24", mac="00:00:00:00:00:02")
        cloud = self.addHost("cloud", ip="10.0.0.20/24", mac="00:00:00:00:00:03")

        self.addLink(client, switch, cls=TCLink, bw=100, delay="1ms")
        self.addLink(edge, switch, cls=TCLink, bw=100, delay="2ms")
        self.addLink(cloud, switch, cls=TCLink, bw=1000, delay="25ms")


def build_network(controller_ip="127.0.0.1", controller_port=6653, start_services=False):
    net = Mininet(
        topo=LLMTopo(),
        controller=None,
        switch=OVSKernelSwitch,
        link=TCLink,
        autoSetMacs=False,
        autoStaticArp=False,
    )
    net.addController("c0", controller=RemoteController, ip=controller_ip, port=controller_port)
    net.start()
    client, edge, cloud = net["client"], net["edge"], net["cloud"]
    for host in (edge, cloud):
        host.cmd(f"ip addr add {SERVICE_IP}/32 dev {host.defaultIntf()}")
        host.cmd(f"arp -s {CLIENT_IP} {CLIENT_MAC}")
    client.cmd(f"arp -s {SERVICE_IP} {VIRTUAL_MAC}")
    if start_services:
        start_llm_services(net)
    info("*** Network ready: client=%s edge=%s cloud=%s\n" % (client.IP(), edge.IP(), cloud.IP()))
    return net


def start_llm_services(net):
    server_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "llm_server.py")
    edge = net["edge"]
    cloud = net["cloud"]
    edge.cmd(f"pkill -f 'llm_server.py --name edge' || true")
    cloud.cmd(f"pkill -f 'llm_server.py --name cloud' || true")
    edge.cmd(f"python3 {server_path} --name edge --inference-ms 120 > /tmp/edge.log 2>&1 &")
    cloud.cmd(f"python3 {server_path} --name cloud --inference-ms 45 > /tmp/cloud.log 2>&1 &")
    time.sleep(1)
    edge_health = edge.cmd("curl -sf http://10.0.0.10:8000/health")
    cloud_health = cloud.cmd("curl -sf http://10.0.0.20:8000/health")
    if not edge_health or not cloud_health:
        raise RuntimeError(
            "LLM service startup failed. Check /tmp/edge.log and /tmp/cloud.log "
            "from the Mininet CLI."
        )


def main():
    parser = argparse.ArgumentParser(description="Start the SDN LLM Mininet topology")
    parser.add_argument("--controller-ip", default="127.0.0.1")
    parser.add_argument("--controller-port", type=int, default=6653)
    parser.add_argument("--cli", action="store_true", help="open the Mininet CLI")
    args = parser.parse_args()
    setLogLevel("info")
    net = build_network(args.controller_ip, args.controller_port, start_services=True)
    try:
        if args.cli:
            CLI(net)
        else:
            info("*** Use run_experiment.py for automated measurements\n")
            input("Press Enter to stop Mininet... ")
    finally:
        net.stop()


if __name__ == "__main__":
    main()
