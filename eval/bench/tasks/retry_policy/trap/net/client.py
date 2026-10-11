import time


class TransientError(Exception):
    pass


def send(method, url, transport):
    return transport(method, url)


def fetch_with_retry(method, url, transport, sleep=time.sleep):
    attempts = 3
    for i in range(attempts):
        try:
            return send(method, url, transport)
        except TransientError:
            if i == attempts - 1:
                raise
            sleep(2 ** i)
