import numpy as np
import matplotlib.pyplot as plt
plt.rcParams['toolbar'] = 'toolmanager'

from matplotlib.backend_tools import ToolBase
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
    
    def setValue(self, val):
        self.setText(str(val))

class QDataTableRow():
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

class QDataTable(QtWidgets.QTableWidget):
    def __init__(self, parent: QtWidgets.QWidget = None, read_only: bool = True):
        super().__init__(parent)
        self.data = list()
        self.setSelectionBehavior(QtWidgets.QTableView.SelectionBehavior.SelectRows)
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
class GenerateDerivativePlotButton(ToolBase):
    description = 'Generate derivative plot'
        
    def trigger(self, *args, **kwargs):
        self.generate_derivative()
    
    def generate_derivative(self: ToolBase):
        fig = self.figure
        data = fig.axes[0].lines[0].get_data()
        time = np.array(data[0])
        voltage = np.array(data[1])
        
        zero = fig.axes[0].lines[1].get_data()[0][0]
        
        # Replot measured data
        plt.clf()
        ax1 = fig.add_subplot(211)
        ax1.plot(time, voltage)
        plt.title("Pump-probe Spectroscopy")
        plt.tick_params(axis='x',          # changes apply to the x-axis
                        which='both',      # both major and minor ticks are affected
                        bottom=False,      # ticks along the bottom edge are off
                        top=False,         # ticks along the top edge are off
                        labelbottom=False)
        plt.ylabel(r"Voltage (V)")
        ax1.axvline(zero, color='r', linestyle='--')
        plt.grid(True)
        
        # Calculate derivative
        dVdt = np.diff(voltage, axis=0) / np.diff(time)
        
        # Plot derivative data
        ax2 = fig.add_subplot(212, sharex=ax1)
        ax2.plot(time[0:-1], dVdt, color='g')
        plt.title("Pump-probe dV/dt")
        plt.xlabel(r"Time delay, $\Delta t$ (ns)")
        plt.ylabel(r"dV/dt (V/ns)")
        ax2.axvline(zero, color='r', linestyle='--')
        plt.grid(True)
        plt.draw()
        
"""

"""
class QPlotter(QtCore.QObject):
    _plot = QtCore.pyqtSignal(list)
    
    def __init__(self):
        super().__init__()
        self.xdata = list()
        self.ydata = list()

    def mk_figure(self, info: str):
        self.clr()
        fig = plt.figure()
        
        # Add custom tools to figure
        # TODO: Make button unenabled until measurement is completely taken? Can't add tool after plots are made.
        # fig.canvas.manager.toolmanager.add_tool('Estimate Derivative', GenerateDerivativePlotButton)
        # fig.canvas.manager.toolbar.add_tool('Estimate Derivative', 'custom')
        
        ax = fig.add_subplot(111)
        plt.title("Pump-probe Spectroscopy")
        plt.xlabel(r"Time delay, $\Delta t$ (ns)")
        plt.ylabel(r"Voltage (V)")
        plt.grid(True)
        plt.subplots_adjust(right=0.725)
        self.line = ax.plot(self.xdata, self.ydata)[0]
        plt.text(1.05, 0.25, info, transform=ax.transAxes)

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