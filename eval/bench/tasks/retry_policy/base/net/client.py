class TransientError(Exception):
    pass


def send(method, url, transport):
    return transport(method, url)


def fetch_with_retry(method, url, transport):
    return send(method, url, transport)
