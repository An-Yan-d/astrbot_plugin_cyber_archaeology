from astrbot.api import logger as astrbot_logger
import os


class MyLogger:
    def __init__(self):
        astrbot_logger.info(f"Log file is at {os.getcwd()}")
        self.file = open(os.path.join("data","log.txt"), "w")

    def __del__(self):
        self.file.close()

    def info(self, content: str):
        astrbot_logger.info(content)
        self.file.writelines([f"[INFO] {content}\n\r"])
        self.file.flush()

    def error(self, content: str):
        astrbot_logger.error(content)
        self.file.writelines([f"[ERROR] {content}\n\r"])
        self.file.flush()

logger = MyLogger()