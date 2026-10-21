import socket


class ConnectionService:
    def is_connected(self, host="8.8.8.8", port=53, timeout=3) -> bool:
        try:
            # create_connection usa timeout local; setdefaulttimeout afetaria o app inteiro
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False
