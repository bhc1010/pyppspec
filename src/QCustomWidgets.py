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

class QDataTableRow():
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

class QDataTable(QtWidgets.QTableWidget):
    def __init__(self, parent: QtWidgets.QWidget = None):
        super().__init__(parent)
        self.data = list()

    def add_item(self, row: QDataTableRow, data=None):
        # if no optional data is given, then let new data be QDataTableRow dict 
        if data == None:
            data = row.__dict__
        # add new data to table's data array
        self.data.append(data)
        # add QDataTableRow object to table
        row_idx = len(self.data) - 1
        if row_idx + 1 > self.rowCount():
            self.insertRow(row_idx)
        for col_idx, key in enumerate(row.__dict__.keys()):
            self.setItem(row_idx, col_idx, QtWidgets.QTableWidgetItem(row.__dict__[key]))
