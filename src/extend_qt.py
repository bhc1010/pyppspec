import matplotlib.pyplot as plt
from PyQt5 import QtWidgets, QtGui, QtCore

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
    def __init__(self, parent: QtWidgets.QWidget = None, read_only: bool = True):
        super().__init__(parent)
        self.data = list()
        if read_only:
            self.setEditTriggers(QtWidgets.QTableWidget.NoEditTriggers)

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

"""
"""
class QPlotter(QtCore.QObject):
    _plot = QtCore.pyqtSignal(list)
    
    def __init__(self):
        super().__init__()
        self.xdata = list()
        self.ydata = list()

    def mk_figure(self, name: str):
        self.clr()
        fig = plt.figure()
        ax = fig.add_subplot(111)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_visible(False)
        ax.spines["top"].set_visible(False)
        plt.title(name)
        plt.xlabel(r"Time delay, $\Delta t$ (ns)")
        plt.ylabel(r"Voltage (V)")
        self.line = ax.plot(self.xdata, self.ydata)[0]

    def update_figure(self, data:list = None):
        if data:
            self.add_data(data[0], data[1])
        self.line.set_data(self.xdata, self.ydata)
        ax = plt.gca()
        ax.relim()
        ax.autoscale_view()

    def add_data(self, x:float, y:float):
        self.xdata.append(x)
        self.ydata.append(y)
        
    def clr(self):
        self.xdata = list()
        self.ydata = list()