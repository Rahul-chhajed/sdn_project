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

    # ---------------------------------------------------
    # SWITCH CONNECTED
    # ---------------------------------------------------

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

        ofp = datapath.ofproto
        parser = datapath.ofproto_parser

        # Send unmatched packets to the controller
        match = parser.OFPMatch()

        actions = [
            parser.OFPActionOutput(
                ofp.OFPP_CONTROLLER,
                ofp.OFPCML_NO_BUFFER
            )
        ]

        instructions = [
            parser.OFPInstructionActions(
                ofp.OFPIT_APPLY_ACTIONS,
                actions
            )
        ]

        flow_mod = parser.OFPFlowMod(
            datapath=datapath,
            priority=0,
            match=match,
            instructions=instructions
        )

        datapath.send_msg(flow_mod)

        self.logger.info(
            "Table-miss flow installed on DPID=%s",
            datapath.id
        )

    # ---------------------------------------------------
    # PACKET IN
    # ---------------------------------------------------

    @set_ev_cls(
        ofp_event.EventOFPPacketIn,
        MAIN_DISPATCHER
    )
    def packet_in_handler(self, ev):

        msg = ev.msg

        datapath = msg.datapath
        ofp = datapath.ofproto
        parser = datapath.ofproto_parser

        in_port = msg.match['in_port']

        self.logger.info(
            "Packet-In: DPID=%s IN_PORT=%s",
            datapath.id,
            in_port
        )

        # Flood packet to all ports
        actions = [
            parser.OFPActionOutput(ofp.OFPP_FLOOD)
        ]

        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=actions
        )

        datapath.send_msg(out)

        self.logger.info(
            "Packet-Out sent: DPID=%s",
            datapath.id
        )
