import time


def add(a, b):
    return a + b


def hog_memory(mb):
    blocks = []
    for _ in range(mb // 10):
        blocks.append(bytearray(10 * 1024 * 1024))
        for i in range(0, len(blocks[-1]), 4096):
            blocks[-1][i] = 1
        time.sleep(0.02)
    time.sleep(5)
    return len(blocks)


def sleeper(seconds):
    time.sleep(seconds)
    return "done"
