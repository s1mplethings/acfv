from PyQt5.QtCore import QThread, pyqtSignal

class AgentWorker(QThread):
    finished = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, backend, query: str, thread_id: str = "gui"):
        super().__init__()
        self.backend = backend
        self.query = query
        self.thread_id = thread_id

    def run(self):
        try:
            ans = self.backend.ask(self.query, thread_id=self.thread_id)
            self.finished.emit(ans)
        except Exception as e:
            self.failed.emit(str(e))
