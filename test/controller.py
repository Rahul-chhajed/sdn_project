from os_ken.base import app_manager

from os_ken.controller import ofp_event
from os_ken.controller.handler import CONFIG_DISPATCHER
from os_ken.controller.handler import MAIN_DISPATCHER
from os_ken.controller.handler import set_ev_cls

from os_ken.ofproto import ofproto_v1_3


class SimpleController(app_manager.OSKenApp):

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(SimpleController, self).__init__(*args, **kwargs)

    # Called when a switch connects
    @set_ev_cls(
        ofp_event.EventOFPSwitchFeatures,
        CONFIG_DISPATCHER
    )
    def switch_features_handler(self, ev):

        datapath = ev.msg.datapath

        self.logger.info(
            "Switch connected! DPID=%s",
            datapath.id
        )

    # Called when OVS sends an unknown packet to controller
    @set_ev_cls(
        ofp_event.EventOFPPacketIn,
        MAIN_DISPATCHER
    )
    def packet_in_handler(self, ev):

        msg = ev.msg
        datapath = msg.datapath

        ofp = datapath.ofproto
        parser = datapath.ofproto_parser

        # Flood the packet to all switch ports
        actions = [
            parser.OFPActionOutput(ofp.OFPP_FLOOD)
        ]

        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=msg.buffer_id,
            in_port=msg.match['in_port'],
            actions=actions
        )

        datapath.send_msg(out)

        self.logger.info(
            "Packet received from switch DPID=%s",
            datapath.id
        )
