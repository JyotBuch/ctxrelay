import time


class TransientError(Exception):
    pass


def send(method, url, transport):
    return transport(method, url)


def fetch_with_retry(method, url, transport, sleep=time.sleep):
    return send(method, url, transport)
