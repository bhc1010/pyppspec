from PyQt5 import QtWidgets, QtGui
from pumpprobe import PumpProbeExperiment

class QNumericalLineEdit(QtWidgets.QLineEdit):
    def __init__(self, parent: QtWidgets.QWidget, validator:QtGui.QValidator):
        super().__init__(parent)
        self.setValidator(validator())

    def value(self):
        val = self.text()
        if val == '':
            val = 0
        match self.validator():
            case QtGui.QIntValidator():
                return int(val)
            case QtGui.QDoubleValidator():
                return float(val)
            case _:
                return str(val)

class QDataTable(QtWidgets.QTableWidget):
    def __init__(self, parent: QtWidgets.QWidget = None):
        super().__init__(parent)
        self.data = list()

    def addItem(self, item: PumpProbeExperiment):
        self.data.append(item)
        idx = len(self.data) - 1
        if idx + 1 > self.rowCount():
            self.insertRow(idx)
        self.setItem(idx, 0, QtWidgets.QTableWidgetItem(item.pump.amp.text()))
        self.setItem(idx, 1, QtWidgets.QTableWidgetItem(item.pump.width.text()))
        self.setItem(idx, 2, QtWidgets.QTableWidgetItem(item.pump.edge.text()))
        self.setItem(idx, 3, QtWidgets.QTableWidgetItem(item.probe.amp.text()))
        self.setItem(idx, 4, QtWidgets.QTableWidgetItem(item.probe.width.text()))
        self.setItem(idx, 5, QtWidgets.QTableWidgetItem(item.probe.edge.text()))
        self.setItem(idx, 6, QtWidgets.QTableWidgetItem(item.probe.time_spread.text()))