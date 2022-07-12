from os import listxattr
import sys
from app import MainWindow
from PyQt5.QtWidgets import QApplication

def main(argv: list):
    app = QApplication(argv)

    window = MainWindow()
    window.show()

    app.exec()

if __name__ == "__main__":
    main(sys.argv)