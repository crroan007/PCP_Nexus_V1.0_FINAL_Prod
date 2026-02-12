import socket
import uuid
import json

class Telemetry:
    """
    Gathers Node Identity for Distributed Tracking.
    """
    @staticmethod
    def get_node_info():
        try:
            hostname = socket.gethostname()
            ip_address = socket.gethostbyname(hostname)
            mac_address = ':'.join(['{:02x}'.format((uuid.getnode() >> ele) & 0xff)
                                  for ele in range(0,8*6,8)][::-1])
            return {
                "hostname": hostname,
                "ip": ip_address,
                "mac": mac_address,
                "version": "1.0.0" # Should be read from config/const
            }
        except Exception as e:
            return {"error": str(e), "hostname": "UNKNOWN"}

    @staticmethod
    def get_node_id():
        """Returns a unique string for this running instance (e.g. Hostname)"""
        return socket.gethostname()
