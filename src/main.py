import sys
from app import MainWindow
from PyQt5.QtWidgets import QApplication

app = QApplication(sys.argv)

window = MainWindow()
window.show()

app.exec()