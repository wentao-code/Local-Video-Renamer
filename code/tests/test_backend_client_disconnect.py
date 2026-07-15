import unittest

from app.backend.server import make_handler


class _Service:
    pass


class _DisconnectingWriter:
    def write(self, _payload):
        raise BrokenPipeError('client disconnected')


class _OSErrorWriter:
    def write(self, _payload):
        raise OSError('socket closed')


class _HandlerStub:
    wfile = _DisconnectingWriter()

    def send_response(self, _status):
        return None

    def send_header(self, _name, _value):
        return None

    def end_headers(self):
        return None


class BackendClientDisconnectTest(unittest.TestCase):
    def test_send_json_ignores_client_disconnect(self):
        handler_class = make_handler(_Service())
        handler_class._send_json(_HandlerStub(), {'ok': True})

    def test_send_json_ignores_generic_socket_oserror(self):
        handler_class = make_handler(_Service())
        stub = _HandlerStub()
        stub.wfile = _OSErrorWriter()
        handler_class._send_json(stub, {'ok': True})


if __name__ == '__main__':
    unittest.main()
