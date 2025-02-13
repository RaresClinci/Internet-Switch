#!/usr/bin/python3
import sys
import struct
import wrapper
import threading
import time
from wrapper import recv_from_any_link, send_to_link, get_switch_mac, get_interface_name

# defining STP constants
BLOCKING = 0
LISTENING = 1
DESIGNATED_PORT = 2

def parse_ethernet_header(data):
    # Unpack the header fields from the byte array
    #dest_mac, src_mac, ethertype = struct.unpack('!6s6sH', data[:14])
    dest_mac = data[0:6]
    src_mac = data[6:12]
    
    # Extract ethertype. Under 802.1Q, this may be the bytes from the VLAN TAG
    ether_type = (data[12] << 8) + data[13]

    vlan_id = -1
    # Check for VLAN tag (0x8100 in network byte order is b'\x81\x00')
    if ether_type == 0x8200:
        vlan_tci = int.from_bytes(data[14:16], byteorder='big')
        vlan_id = vlan_tci & 0x0FFF  # extract the 12-bit VLAN ID
        ether_type = (data[16] << 8) + data[17]

    return dest_mac, src_mac, ether_type, vlan_id

def create_vlan_tag(vlan_id):
    # 0x8100 for the Ethertype for 802.1Q
    # vlan_id & 0x0FFF ensures that only the last 12 bits are used
    return struct.pack('!H', 0x8200) + struct.pack('!H', vlan_id & 0x0FFF)

def create_bdpu_payload(root_id, cost, bridge_id):
    zero = 0
    return (
        zero.to_bytes(2, byteorder='big') +       # prot ID (2 bytes)
        zero.to_bytes(1, byteorder='big') +       # prot version ID (1 byte)
        zero.to_bytes(1, byteorder='big') +       # type (1 byte)
        zero.to_bytes(1, byteorder='big') +       # flags (1 byte)
        root_id.to_bytes(8, byteorder='big') +    # root ID (8 bytes)
        cost.to_bytes(4, byteorder='big') +       # cost (4 bytes)
        bridge_id.to_bytes(8, byteorder='big') +  # bridge ID (8 bytes)
        zero.to_bytes(2, byteorder='big') +       # port ID (2 bytes)
        zero.to_bytes(2, byteorder='big') +       # age (2 bytes)
        zero.to_bytes(2, byteorder='big') +       # max age (2 bytes)
        zero.to_bytes(2, byteorder='big') +       # hello time (2 bytes)
        zero.to_bytes(2, byteorder='big')         # forward delay (2 bytes)
    )

def create_bdpu_frame(src_mac, payload):
    # dest_mac is 01:80:C2:00:00:00
    dest_mac = bytes.fromhex('0180C2000000')
    llc_header = bytes.fromhex('424203')
    length = len(llc_header) + len(payload)
    return (
        dest_mac +
        src_mac +
        length.to_bytes(2, byteorder='big') +
        llc_header +
        payload
    )



def send_bdpu_every_sec():
    global own_bridge_id, root_bridge_id, cost, interfaces, root_port, port_state, mac_table, vlan
    while True:
        # TODO Send BDPU every second if necessary
        if own_bridge_id == root_bridge_id:
            src_mac = get_switch_mac()
            for port in interfaces:
                if vlan[get_interface_name(port)] == 'T':
                    payload = create_bdpu_payload(root_bridge_id, cost, own_bridge_id)
                    frame = create_bdpu_frame(src_mac, payload)
                    send_to_link(port, len(frame), frame)
                
        time.sleep(1)

# check unicast function
def is_unicast(mac_adr):
    mac_bytes = bytes(int(b, 16) for b in mac_adr.split(":"))
    return (mac_bytes[0] & 1) == 0

# add vlan function
def add_vlan(data, vlan_id):
    return data[:12] + create_vlan_tag(int(vlan_id)) + data[12:]

# remove vlan function
def delete_vlan(data):
    return data[:12] + data[16:]

# send vlan function
def send_vlan(dest_mac, input_trunk, input_port_name, data, length, vlan_id, interface):
    global own_bridge_id, root_bridge_id, cost, interfaces, root_port, port_state, mac_table, vlan
    # is the output port trunk?
    output_port_name = get_interface_name(interface)
    output_trunk = False
    if vlan[output_port_name] == "T":
        # trunk port
        output_trunk = True

    # packet throwing cases
    if input_trunk:
        # does the frame have a vlan tag?
        if (data[12] << 8) + data[13] != 0x8200:
            return
    
    if not output_trunk:
        # is the vlan the same as the output port?
        if input_trunk:
            if str(vlan_id) != vlan[output_port_name]:
                return
        else:
            if vlan[input_port_name] != vlan[output_port_name]:
                return
    
    # adding vlan header
    if not input_trunk:
        data = add_vlan(data, vlan[input_port_name])  
        length += 4

    # remove vlan header
    if not output_trunk:
        data = delete_vlan(data)
        length -= 4
    
    if port_state[interface] == LISTENING:
        send_to_link(interface, length, data)

def bdpu_extract_data(data):
    frame_root = int.from_bytes(data[22:30], byteorder='big')
    frame_cost = int.from_bytes(data[30:34], byteorder='big')
    frame_id = int.from_bytes(data[34:42], byteorder='big')
    
    return frame_root, frame_cost, frame_id

def handle_bdpu(data, interface):
    global own_bridge_id, root_bridge_id, cost, interfaces, root_port, port_state, mac_table, vlan
    frame_root, frame_cost, frame_id = bdpu_extract_data(data)

    if frame_root < root_bridge_id:
        # were we the root?
        former_root = False
        if root_bridge_id == own_bridge_id:
            former_root = True

        # updating the values
        root_bridge_id = frame_root
        cost = frame_cost + 10
        root_port = interface

        if former_root:
            # change all trunks to blocking, except root port
            for port in interfaces:
                if vlan[get_interface_name(port)] == 'T':
                    if port != root_port:
                        port_state[port] = BLOCKING
                    else: 
                        port_state[port] = LISTENING

        if port_state[root_port] == BLOCKING:
            port_state[root_port] = LISTENING
        
        # sending bdpu to all trunks
        for port in interfaces:
            if vlan[get_interface_name(port)] == 'T' and port != interface:
                payload = create_bdpu_payload(root_bridge_id, cost, own_bridge_id)
                frame = create_bdpu_frame(get_switch_mac(), payload)
                send_to_link(port, len(frame), frame)

    elif frame_root == root_bridge_id:
        if interface == root_port and frame_cost + 10 < cost:
            cost = frame_cost + 10
        elif frame_cost > cost:
            port_state[interface] = LISTENING

    elif frame_id == own_bridge_id:
        port_state[interface] = BLOCKING
    else:
        return
    
    if own_bridge_id == root_bridge_id and not former_root:
        for port in interfaces:
            port_state[port] = LISTENING

   

def main():
    global own_bridge_id, root_bridge_id, cost, interfaces, root_port, port_state, mac_table, vlan
    # init returns the max interface number. Our interfaces
    # are 0, 1, 2, ..., init_ret value + 1
    switch_id = sys.argv[1]

    # initializong the values
    cost = 0
    root_port = -1
    port_state = {}

    # defining mac table and vlan
    mac_table = {}
    vlan = {}

    # parsing config file
    config = open("configs/switch" + str(switch_id) + ".cfg", "r")

    # getting the vlan for each port
    lines = config.readlines()
    priority = int(lines[0])
    for line in lines[1:]:
        port, lan = line.split()
        vlan[port] = lan

    config.close()

    num_interfaces = wrapper.init(sys.argv[2:])
    interfaces = range(0, num_interfaces)

    print("# Starting switch with id {}".format(switch_id), flush=True)
    print("[INFO] Switch MAC", ':'.join(f'{b:02x}' for b in get_switch_mac()))

    # initializing STP
    for port in interfaces:
        if vlan[get_interface_name(port)] == 'T':
            port_state[port] = BLOCKING
        else:
            port_state[port] = LISTENING

    own_bridge_id = priority
    root_bridge_id = own_bridge_id

    if own_bridge_id == root_bridge_id:
        for port in interfaces:
            port_state[port] = LISTENING

    # Create and start a new thread that deals with sending BDPU
    t = threading.Thread(target=send_bdpu_every_sec)
    t.start()

    while True:
        # Note that data is of type bytes([...]).
        # b1 = bytes([72, 101, 108, 108, 111])  # "Hello"
        # b2 = bytes([32, 87, 111, 114, 108, 100])  # " World"
        # b3 = b1[0:2] + b[3:4].
        interface, data, length = recv_from_any_link()

        dest_mac, src_mac, ethertype, vlan_id = parse_ethernet_header(data)

        # Print the MAC src and MAC dst in human readable format
        dest_mac = ':'.join(f'{b:02x}' for b in dest_mac)
        src_mac = ':'.join(f'{b:02x}' for b in src_mac)

        # Note. Adding a VLAN tag can be as easy as
        # tagged_frame = data[0:12] + create_vlan_tag(10) + data[12:]

        print(f'Destination MAC: {dest_mac}')
        print(f'Source MAC: {src_mac}')
        print(f'EtherType: {ethertype}')

        print("Received frame of size {} on interface {}".format(length, interface), flush=True)

        # TODO: Implement forwarding with learning
        # bdpu frame or normal frame?
        if dest_mac == "01:80:c2:00:00:00":
            # it's a bdpu packet
            handle_bdpu(data, interface)
        else:
            input_port_name = get_interface_name(interface)
            input_trunk = False
            if vlan[input_port_name] == 'T':
                # trunk port
                input_trunk = True

            # forwarding
            if port_state[interface] == LISTENING:
                mac_table[src_mac] = interface

            if is_unicast(dest_mac):
                if dest_mac in mac_table:
                    send_vlan(dest_mac, input_trunk, input_port_name, data, length, vlan_id, mac_table[dest_mac])
                else:
                    for port in interfaces:
                        if port != interface:
                            send_vlan(dest_mac, input_trunk, input_port_name, data, length, vlan_id, port)
            else:
                for port in interfaces :
                    if port != interface:
                        send_vlan(dest_mac, input_trunk, input_port_name, data, length, vlan_id, port)

        # TODO: Implement VLAN support
        # TODO: Implement STP support

        # data is of type bytes.
        # send_to_link(i, length, data)

if __name__ == "__main__":
    main()
