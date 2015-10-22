class PortiaException(Exception):
    pass


class JsonProtocolException(PortiaException):
    def __init__(self, message, command, reference_id):
        super(JsonProtocolException, self).__init__(message)
        self.message = message
        self.command = command
        self.reference_id = reference_id
