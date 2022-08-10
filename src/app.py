import os, traceback
from xml import dom

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from PyQt5 import QtCore, QtGui, QtWidgets
from extend_qt import QDataTable, QDataTableRow, QPlotter
from pump_probe import Procedure, PumpProbe, PumpProbeConfig, PumpProbeExperiment, Pulse, Channel
from scientific_spinbox import ScienDSpinBox
from datetime import datetime

plt.ion()

class PumpProbeWorker(QtCore.QThread):
    _progress = QtCore.pyqtSignal(str)
    _finished = QtCore.pyqtSignal()
    _queue_signal = QtCore.pyqtSignal(QtGui.QColor)
    _lockin_status = QtCore.pyqtSignal(str)
    _awg_status = QtCore.pyqtSignal(str)
    _stm_status = QtCore.pyqtSignal(str)
    _make_figure = QtCore.pyqtSignal(str)

    def __init__(self, pump_probe:PumpProbe, queue: QDataTable, plotter: QPlotter) -> None:
        super().__init__(parent=None)
        self.pump_probe = pump_probe
        self.queue = queue
        self.plotter = plotter

    def stop_early(self):
        self._running_pp = False

    def connect_device(self, device, signal, name):
        self._progress.emit(f"[{name}] Connecting...")
        signal.emit("Connecting...")
        result = device.connect().expected(f"[{name}] Could not connect:")
        self._progress.emit(f"[{name}] {result.msg}")
        if result.err:
            signal.emit("Disconnected")
        else:
            signal.emit("Connected")
        return result
    
    def save_data(self, exp, data):
        dt, volt_data = data
        # Save measurement data
        out = pd.DataFrame({'Voltage': volt_data, 'Time Delay': dt})
        path = os.path.join(self.pump_probe.config.save_path, exp.name)
        if not os.path.isdir(path):
            os.mkdir(path)
        out.to_csv(os.path.join(path, exp.name), index=False)

        # Save measurement figure
        meta = exp.generate_meta()
        plt.savefig(f"{os.path.join(path, exp.name)}.png", metadata=meta)
        
        # Save RHK position info
        with open(os.path.join(path,  "meta.toml"), 'w') as file:
            toml = exp.generate_toml()
            file.write(toml)

    """
    Run pump probe experiment for each experiment in the queue until empty or 'Stop queue' button is pressed.
    """
    def run(self):
        self._running_pp = False
        self._new_arb = True

        ## Check if devices are connected
        lockin_result = self.connect_device(self.pump_probe.lockin, self._lockin_status, "Lock-in")
        awg_result = self.connect_device(self.pump_probe.awg, self._awg_status, "AWG")
        stm_result = self.connect_device(self.pump_probe.stm, self._stm_status, self.pump_probe.config.stm_model)
        
        # Report any errors with connecting.
        for name, result in zip(["STM", "Lock-in", "AWG"], [stm_result, lockin_result, awg_result]):
            if result.err:
                self._progress.emit(f"[ERROR] {name} did not connect. Please ensure {name} is able to communicate with local user.")
                self._finished.emit()
                return

        # Check if experiment queue is empty
        if self.queue.rowCount() == 0:
            self._progress.emit("[ERROR] Experiment queue is empty. Please fill queue with at least one experiment.")
            self._finished.emit()
            return

        # Run pump-probe for each experiment in queue until queue is empty of 'Stop queue' button is pressed.
        self._running_pp = True

        # While the queue is not empty and pump-probe is still set to run (running_pp is set to False by clicking 'Stop queue')
        while(len(self.queue.data) != 0 and self._running_pp):
            self._queue_signal.emit(QtGui.QColor(QtCore.Qt.green))
            
            experiments : list = self.queue.data[0]
            
            # Run pump-probe experiment. If not a repeated pulse, send new pulse data to AWG
            for exp in experiments:
                exp.name = str(datetime.now().strftime("%Y%m%d %H-%M-%S"))
                
                try:
                    prev_exp = self.pump_probe.prev_exp
                except:
                    prev_exp = None 
                    
                if prev_exp:
                    if exp.pump.edge != prev_exp.pump.edge or exp.pump.width != prev_exp.pump.width:
                        self._new_arb = True
                    elif exp.probe.edge != prev_exp.probe.edge and exp.probe.width != prev_exp.probe.width:
                        self._new_arb = True
                    elif exp.pump.time_spread != prev_exp.pump.time_spread:
                        self._new_arb = True
                    else:
                        self._new_arb = False

                # Make new figure 
                self._make_figure.emit(exp.generate_toml())
                
                # Get tip position
                exp.stm_coords = self.pump_probe.stm.get_position()
                try:
                    self._progress.emit("Running pump-probe experiment.")
                    dt, volt_data = self.pump_probe.run(exp=exp, new_arb=self._new_arb, plotter=self.plotter)
                except Exception as e:
                    traceback.print_exc()
                    msg = f"[ERROR] {e}. "
                    if "'send'" in repr(e):
                        msg += " 'send' is a Lock-in method. Is the Lock-in connected properly?"
                    elif "'write'" in repr(e):
                        msg += " 'write' is an AWG method. Is the AWG connected properly?"
                    self._progress.emit(msg)
                    self._queue_signal.emit(QtGui.QColor(QtCore.Qt.red))
                    self._running_pp = False
                    self._finished.emit()
                    return
                
                # Add zero line to plot
                zero = (2*exp.pump.edge + exp.pump.width) * self.pump_probe.config.sample_rate
                plt.axvline(zero, color = 'r', linestyle='--')
                
                # Save data
                self.save_data(exp, (dt, volt_data))
                
                # Check if next experiment in queue is a repeat arb
                self.pump_probe.prev_exp = exp
            
            # Remove experiment from queue data and top row
            del self.queue.data[0]
            self.queue.removeRow(0)
        # Close thread
        self._progress.emit("QThread finished. Pump-probe experiment(s) stopped.")
        self._finished.emit()

class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, settings: QtCore.QSettings) -> None:
        super().__init__()
        self.settings = settings
        
        self.setWindowTitle("Settings")
        self.setMinimumSize(450, 225)
        self.layout = QtWidgets.QFormLayout(self)
        self.labels = list()
        self.keys = list()
        for i, key in enumerate(self.settings.allKeys()):
            self.labels.append(QtWidgets.QLabel(self))
            self.keys.append(QtWidgets.QLineEdit(self))
            self.layout.setWidget(i, QtWidgets.QFormLayout.LabelRole, self.labels[-1])
            self.layout.setWidget(i, QtWidgets.QFormLayout.FieldRole, self.keys[-1])
            self.labels[-1].setText(key)
            self.keys[-1].setText(self.settings.value(key))
        self.accept_btn = QtWidgets.QPushButton(self)
        self.accept_btn.setText("Accept")
        self.layout.setWidget(len(self.labels), QtWidgets.QFormLayout.SpanningRole, self.accept_btn)
        
        self.accept_btn.clicked.connect(self.on_exit)
        
    def on_exit(self):
        for i, label in enumerate(self.labels):
            self.settings.setValue(label.text(), self.keys[i].text())
            
        self.accept()

"""
"""
class MainWindow(QtWidgets.QMainWindow):
    _hook = QtCore.pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setupUi()
        default_config = dict(stm_model="RHK R9", 
                              lockin_ip = "169.254.11.17", lockin_port=50_000, lockin_freq = 1007,
                              awg_id='USB0::0x0957::0x5707::MY53805152::INSTR', 
                              sample_rate=1e9, save_path="")
        
        # Setup PumpProbeConfig
        self.settings = QtCore.QSettings('HollenLab', 'pump-probe')
        if not self.settings.contains('save_path'):
            for key, value in default_config.items():
                self.settings.setValue(key, value)
        
        config = dict()
        for key in self.settings.allKeys():
            config[key] = self.settings.value(key, type=type(default_config[key]))
            print(f"{key} : {self.settings.value(key)} - {type(default_config[key])}")
    
        
        self.PumpProbe = PumpProbe(PumpProbeConfig(**config))
        self.PumpProbe.plotter = QPlotter()
        self.retranslateUi()
        self.procedure_dict = {'procedure' : 'Time delay', 'procedure_channel' : 'Probe',
                               'procedure_start' : 0.0, 'procedure_end' : 0.0,
                               'fixed_time_delay' : 0.0, 'sweep_parameter' : 'None', 'sweep_channel' : 'Pump',
                               'sweep_start' : 0.0, 'sweep_end' : 0.0, 'sweep_step' : 0.0}
    """
    """
    def setupUi(self):
        self.setFixedSize(1111, 751)

        self.centralwidget = QtWidgets.QWidget(self)
        
        # Procedure layout
        self.procedure_layout = QtWidgets.QWidget(self.centralwidget)
        self.procedure_layout.setGeometry(QtCore.QRect(10, 20, 251, 31))
        self.procedure_layout = QtWidgets.QHBoxLayout(self.procedure_layout)
        self.procedure_layout.setContentsMargins(0, 0, 0, 0)
        
        # Procedure selection
        self.procedure_label = QtWidgets.QLabel(self.centralwidget)
        self.procedure_layout.addWidget(self.procedure_label)
        self.procedure = QtWidgets.QComboBox(self.centralwidget)
        self.procedure.addItem("")
        self.procedure.addItem("")
        self.procedure.addItem("")
        self.procedure_layout.addWidget(self.procedure)
        self.procedure_layout.setStretch(1, 1)
        
        # Add procedure btn
        self.add_procedure_btn = QtWidgets.QPushButton(self.centralwidget)
        self.add_procedure_btn.setGeometry(QtCore.QRect(10, 600, 251, 41))
        
        # Remove procedure btn
        self.remove_procedure_btn = QtWidgets.QPushButton(self.centralwidget)
        self.remove_procedure_btn.setGeometry(QtCore.QRect(10, 650, 251, 41))
        
        # Run / stop procedures btn
        self.procedure_btn = QtWidgets.QPushButton(self.centralwidget)
        self.procedure_btn.setGeometry(QtCore.QRect(840, 640, 261, 51))

        # Table queue
        self.queue = QDataTable(self.centralwidget)
        self.queue.setGeometry(QtCore.QRect(280, 10, 821, 431))
        self.queue.setRowCount(1)
        self.queue.setColumnCount(8)
        self.queue.setHorizontalHeaderItem(0, QtWidgets.QTableWidgetItem())
        self.queue.setHorizontalHeaderItem(1, QtWidgets.QTableWidgetItem())
        self.queue.setHorizontalHeaderItem(2, QtWidgets.QTableWidgetItem())
        self.queue.setHorizontalHeaderItem(3, QtWidgets.QTableWidgetItem())
        self.queue.setHorizontalHeaderItem(4, QtWidgets.QTableWidgetItem())
        self.queue.setHorizontalHeaderItem(5, QtWidgets.QTableWidgetItem())
        self.queue.setHorizontalHeaderItem(6, QtWidgets.QTableWidgetItem())
        self.queue.setHorizontalHeaderItem(7, QtWidgets.QTableWidgetItem())
        self.queue.horizontalHeader().setVisible(True)
        self.queue.horizontalHeader().setCascadingSectionResizes(False)
        self.queue.verticalHeader().setVisible(True)
        
        # Pump pulse box
        self.pump_box = QtWidgets.QGroupBox(self.centralwidget)
        self.pump_box.setGeometry(QtCore.QRect(10, 70, 251, 131))

        # Pump pulse box layout
        self.pump_box_layout = QtWidgets.QWidget(self.pump_box)
        self.pump_box_layout.setGeometry(QtCore.QRect(9, 29, 231, 91))
        self.pump_box_layout = QtWidgets.QFormLayout(self.pump_box_layout)
        self.pump_box_layout.setContentsMargins(0, 0, 0, 0)

        # Pump amplitude
        self.pump_amp_label = QtWidgets.QLabel(self.pump_box)
        self.pump_box_layout.setWidget(0, QtWidgets.QFormLayout.LabelRole, self.pump_amp_label)
        self.pump_amp = ScienDSpinBox(parent=self.pump_box)
        self.pump_box_layout.setWidget(0, QtWidgets.QFormLayout.FieldRole, self.pump_amp)

        # Pump width
        self.pump_width_label = QtWidgets.QLabel(self.pump_box)
        self.pump_box_layout.setWidget(1, QtWidgets.QFormLayout.LabelRole, self.pump_width_label)
        self.pump_width = ScienDSpinBox(parent=self.pump_box)
        self.pump_box_layout.setWidget(1, QtWidgets.QFormLayout.FieldRole, self.pump_width)

        # Pump edge
        self.pump_edge_layout = QtWidgets.QLabel(self.pump_box)
        self.pump_box_layout.setWidget(2, QtWidgets.QFormLayout.LabelRole, self.pump_edge_layout)
        self.pump_edge = ScienDSpinBox(parent=self.pump_box)
        self.pump_box_layout.setWidget(2, QtWidgets.QFormLayout.FieldRole, self.pump_edge)

        # Probe pulse box
        self.probe_box = QtWidgets.QGroupBox(self.centralwidget)
        self.probe_box.setGeometry(QtCore.QRect(10, 220, 251, 131))

        # Probe pulse box layout
        self.probe_box_layout = QtWidgets.QWidget(self.probe_box)
        self.probe_box_layout.setGeometry(QtCore.QRect(9, 29, 231, 91))
        self.probe_box_layout = QtWidgets.QFormLayout(self.probe_box_layout)
        self.probe_box_layout.setContentsMargins(0, 0, 0, 0)

        # Probe amplitude
        self.probe_amp_label = QtWidgets.QLabel(self.probe_box)
        self.probe_box_layout.setWidget(0, QtWidgets.QFormLayout.LabelRole, self.probe_amp_label)
        self.probe_amp = ScienDSpinBox(parent=self.probe_box)
        self.probe_box_layout.setWidget(0, QtWidgets.QFormLayout.FieldRole, self.probe_amp)

        # Probe width
        self.probe_width_label = QtWidgets.QLabel(self.probe_box)
        self.probe_box_layout.setWidget(1, QtWidgets.QFormLayout.LabelRole, self.probe_width_label)
        self.probe_width = ScienDSpinBox(parent=self.probe_box)
        self.probe_box_layout.setWidget(1, QtWidgets.QFormLayout.FieldRole, self.probe_width)

        # Probe edge
        self.probe_edge_label = QtWidgets.QLabel(self.probe_box)
        self.probe_box_layout.setWidget(2, QtWidgets.QFormLayout.LabelRole, self.probe_edge_label)
        self.probe_edge = ScienDSpinBox(parent=self.probe_box)
        self.probe_box_layout.setWidget(2, QtWidgets.QFormLayout.FieldRole, self.probe_edge)

        # Procedure settings box
        self.procedure_settings_box = QtWidgets.QGroupBox(self.centralwidget)
        self.procedure_settings_box.setGeometry(QtCore.QRect(280, 450, 551, 241))
        
        # Time delay settings layout
        self.time_delay_procedure_settings_layout_outer = QtWidgets.QWidget(self.procedure_settings_box)
        self.time_delay_procedure_settings_layout_outer.setGeometry(QtCore.QRect(10, 30, 531, 201))
        self.time_delay_procedure_settings_layout = QtWidgets.QGridLayout(self.time_delay_procedure_settings_layout_outer)
        self.time_delay_procedure_settings_layout.setContentsMargins(0, 0, 0, 0)
        
        # Time spread
        self.time_spread_label = QtWidgets.QLabel(self.time_delay_procedure_settings_layout_outer)
        self.time_delay_procedure_settings_layout.addWidget(self.time_spread_label, 0, 0, 1, 1)
        self.time_spread = ScienDSpinBox(parent=self.time_delay_procedure_settings_layout_outer)
        self.time_delay_procedure_settings_layout.addWidget(self.time_spread, 0, 1, 1, 1)
        
        # Time delay sample size
        self.time_delay_sample_size_label = QtWidgets.QLabel(self.time_delay_procedure_settings_layout_outer)
        self.time_delay_procedure_settings_layout.addWidget(self.time_delay_sample_size_label, 1, 0, 1, 1)
        self.time_delay_sample_size = QtWidgets.QSpinBox(self.time_delay_procedure_settings_layout_outer)
        self.time_delay_sample_size.setMaximum(9999)
        self.time_delay_procedure_settings_layout.addWidget(self.time_delay_sample_size, 1, 1, 1, 1)
        
        # Time delay spacing
        self.spacer_x = QtWidgets.QLabel(self.time_delay_procedure_settings_layout_outer)
        self.spacer_x.setText("")
        self.time_delay_procedure_settings_layout.addWidget(self.spacer_x, 0, 2, 1, 1)
        self.spacer_x_2 = QtWidgets.QLabel(self.time_delay_procedure_settings_layout_outer)
        self.spacer_x_2.setText("")
        self.time_delay_procedure_settings_layout.addWidget(self.spacer_x_2, 0, 3, 1, 1)
        self.spacer_y = QtWidgets.QLabel(self.time_delay_procedure_settings_layout_outer)
        self.spacer_y.setText("")
        self.time_delay_procedure_settings_layout.addWidget(self.spacer_y, 2, 0, 1, 1)
        
        # Amplitude procedure settings layout
        self.amp_procedure_settings_layout_outer = QtWidgets.QWidget(self.procedure_settings_box)
        self.amp_procedure_settings_layout_outer.setGeometry(QtCore.QRect(10, 30, 531, 201))
        self.amp_procedure_settings_layout_outer.hide()
        self.amp_procedure_settings_layout = QtWidgets.QGridLayout(self.amp_procedure_settings_layout_outer)
        self.amp_procedure_settings_layout.setContentsMargins(0, 0, 0, 0)
        
        # Amp procedure channel
        self.amp_procedure_channel_label = QtWidgets.QLabel(self.amp_procedure_settings_layout_outer)
        self.amp_procedure_settings_layout.addWidget(self.amp_procedure_channel_label, 0, 0, 1, 1)
        self.amp_procedure_channel = QtWidgets.QComboBox(self.amp_procedure_settings_layout_outer)
        self.amp_procedure_channel.addItem("")
        self.amp_procedure_channel.addItem("")
        self.amp_procedure_settings_layout.addWidget(self.amp_procedure_channel, 0, 1, 1, 1)
        
        # Amp procedure start
        self.amp_procedure_start_label = QtWidgets.QLabel(self.amp_procedure_settings_layout_outer)
        self.amp_procedure_settings_layout.addWidget(self.amp_procedure_start_label, 1, 0, 1, 1)
        self.amp_procedure_start = ScienDSpinBox(parent=self.amp_procedure_settings_layout_outer)
        self.amp_procedure_settings_layout.addWidget(self.amp_procedure_start, 1, 1, 1, 1)        
        
        # Amp procedure end
        self.amp_procedure_end_label = QtWidgets.QLabel(self.amp_procedure_settings_layout_outer)
        self.amp_procedure_settings_layout.addWidget(self.amp_procedure_end_label, 2, 0, 1, 1)
        self.amp_procedure_end = ScienDSpinBox(parent=self.amp_procedure_settings_layout_outer)
        self.amp_procedure_settings_layout.addWidget(self.amp_procedure_end, 2, 1, 1, 1)
        
        # Amp procedure fixed time delay
        self.amp_procedure_fixed_time_delay_label = QtWidgets.QLabel(self.amp_procedure_settings_layout_outer)
        self.amp_procedure_settings_layout.addWidget(self.amp_procedure_fixed_time_delay_label, 3, 0, 1, 1)
        self.amp_procedure_fixed_time_delay = ScienDSpinBox(parent=self.amp_procedure_settings_layout_outer)
        self.amp_procedure_settings_layout.addWidget(self.amp_procedure_fixed_time_delay, 3, 1, 1, 1)
        
        
        # Amp procedure sample size
        self.amp_procedure_sample_size_label = QtWidgets.QLabel(self.amp_procedure_settings_layout_outer)
        self.amp_procedure_settings_layout.addWidget(self.amp_procedure_sample_size_label, 4, 0, 1, 1)
        self.amp_procedure_sample_size = QtWidgets.QSpinBox(self.amp_procedure_settings_layout_outer)
        self.amp_procedure_sample_size.setMaximum(9999)
        self.amp_procedure_settings_layout.addWidget(self.amp_procedure_sample_size, 4, 1, 1, 1)
        
        # Amp procedure spacing
        self.amp_procedure_spacing_x = QtWidgets.QLabel(self.amp_procedure_settings_layout_outer)
        self.amp_procedure_spacing_x.setText("")
        self.amp_procedure_settings_layout.addWidget(self.amp_procedure_spacing_x, 0, 2, 1, 1)
        self.amp_procedure_spacing_x_2 = QtWidgets.QLabel(self.amp_procedure_settings_layout_outer)
        self.amp_procedure_spacing_x_2.setText("")
        self.amp_procedure_settings_layout.addWidget(self.amp_procedure_spacing_x_2, 0, 3, 1, 1)
        self.amp_procedure_spacing_y = QtWidgets.QLabel(self.amp_procedure_settings_layout_outer)
        self.amp_procedure_spacing_y.setText("")
        self.amp_procedure_settings_layout.addWidget(self.amp_procedure_spacing_y, 5, 0, 1, 1)
        
        # Image procedure settings layout
        self.image_procedure_settings_layout_outer = QtWidgets.QWidget(self.procedure_settings_box)
        self.image_procedure_settings_layout_outer.setGeometry(QtCore.QRect(10, 30, 531, 201))
        self.image_procedure_settings_layout_outer.hide()
        self.image_procedure_settings_layout = QtWidgets.QGridLayout(self.image_procedure_settings_layout_outer)
        self.image_procedure_settings_layout.setContentsMargins(0, 0, 0, 0)
        # self.image_procedure_settings_layout.setHorizontalSpacing(24)
        
        # Image frames
        self.image_frames_label = QtWidgets.QLabel(self.image_procedure_settings_layout_outer)
        self.image_procedure_settings_layout.addWidget(self.image_frames_label, 0, 0, 1, 1)
        self.image_frames = QtWidgets.QSpinBox(self.image_procedure_settings_layout_outer)
        self.image_frames.setMaximum(1024)
        self.image_procedure_settings_layout.addWidget(self.image_frames, 0, 1, 1, 1)

        # Image lines per frame
        self.image_lines_label = QtWidgets.QLabel(self.image_procedure_settings_layout_outer)
        self.image_procedure_settings_layout.addWidget(self.image_lines_label, 1, 0, 1, 1)
        self.image_lines = QtWidgets.QSpinBox(self.image_procedure_settings_layout_outer)
        self.image_lines.setMaximum(1024)
        self.image_procedure_settings_layout.addWidget(self.image_lines, 1, 1, 1, 1)

        # Image Size
        self.image_size_label = QtWidgets.QLabel(self.image_procedure_settings_layout_outer)
        self.image_procedure_settings_layout.addWidget(self.image_size_label, 2, 0, 1, 1)
        self.image_size = ScienDSpinBox(parent=self.image_procedure_settings_layout_outer)
        self.image_procedure_settings_layout.addWidget(self.image_size, 2, 1, 1, 1)
        
        # Image X Offset
        self.image_x_offset_label = QtWidgets.QLabel(self.image_procedure_settings_layout_outer)
        self.image_procedure_settings_layout.addWidget(self.image_x_offset_label, 3, 0, 1, 1)
        self.image_x_offset = ScienDSpinBox(parent=self.image_procedure_settings_layout_outer)
        self.image_procedure_settings_layout.addWidget(self.image_x_offset, 3, 1, 1, 1)

        # Image Y Offset
        self.image_y_offset_label = QtWidgets.QLabel(self.image_procedure_settings_layout_outer)
        self.image_procedure_settings_layout.addWidget(self.image_y_offset_label, 4, 0, 1, 1)
        self.image_y_offset = ScienDSpinBox(parent=self.image_procedure_settings_layout_outer)
        self.image_procedure_settings_layout.addWidget(self.image_y_offset, 4, 1, 1, 1)

        # Image scane speed
        self.image_scan_speed_label = QtWidgets.QLabel(self.image_procedure_settings_layout_outer)
        self.image_procedure_settings_layout.addWidget(self.image_scan_speed_label, 5, 0, 1, 1)
        self.image_scan_speed = ScienDSpinBox(parent=self.image_procedure_settings_layout_outer)
        self.image_procedure_settings_layout.addWidget(self.image_scan_speed, 5, 1, 1, 1)

        # Image lines per second
        self.image_lines_per_second_label = QtWidgets.QLabel(self.image_procedure_settings_layout_outer)
        self.image_procedure_settings_layout.addWidget(self.image_lines_per_second_label, 6, 0, 1, 1)
        self.image_lines_per_second = ScienDSpinBox(parent=self.image_procedure_settings_layout_outer)
        self.image_lines_per_second.setEnabled(False)
        self.image_procedure_settings_layout.addWidget(self.image_lines_per_second, 6, 1, 1, 1)

        # Image procedure spacing
        self.spacer_x = QtWidgets.QLabel(self.image_procedure_settings_layout_outer)
        self.spacer_x.setText("")
        self.image_procedure_settings_layout.addWidget(self.spacer_x, 0, 2, 1, 1)
        self.spacer_x_2 = QtWidgets.QLabel(self.image_procedure_settings_layout_outer)
        self.spacer_x_2.setText("")
        self.image_procedure_settings_layout.addWidget(self.spacer_x_2, 0, 3, 1, 1)
        
        # Sweep box
        self.sweep_box = QtWidgets.QGroupBox(self.centralwidget)
        self.sweep_box.setGeometry(QtCore.QRect(10, 370, 251, 211))
        self.sweep_box.setCheckable(True)
        self.sweep_box.setChecked(False)
        
        # Sweep box vlayout
        self.sweep_box_vlayout_outer  = QtWidgets.QWidget(self.sweep_box)
        self.sweep_box_vlayout_outer.setGeometry(QtCore.QRect(10, 30, 233, 175))
        self.sweep_box_vlayout = QtWidgets.QVBoxLayout(self.sweep_box_vlayout_outer)
        self.sweep_box_vlayout.setContentsMargins(0, 0, 0, 0)
        
        # Sweep box layout
        self.sweep_box_layout = QtWidgets.QFormLayout()
        self.sweep_box_vlayout.addLayout(self.sweep_box_layout)
        
        # Sweep parameter
        self.sweep_parameter_label = QtWidgets.QLabel(self.sweep_box_vlayout_outer)
        self.sweep_box_layout.setWidget(0, QtWidgets.QFormLayout.LabelRole, self.sweep_parameter_label)
        self.sweep_parameter = QtWidgets.QComboBox(self.sweep_box)
        self.sweep_parameter.addItems(["" for _ in range(3)])
        self.sweep_box_layout.setWidget(0, QtWidgets.QFormLayout.FieldRole, self.sweep_parameter)
        
        # Sweep channel
        self.sweep_channel_label = QtWidgets.QLabel(self.sweep_box_vlayout_outer)
        self.sweep_box_layout.setWidget(1, QtWidgets.QFormLayout.LabelRole, self.sweep_channel_label)
        self.sweep_channel = QtWidgets.QComboBox(self.sweep_box_vlayout_outer)
        self.sweep_channel.addItems(["" for _ in range(3)])
        self.sweep_box_layout.setWidget(1, QtWidgets.QFormLayout.FieldRole, self.sweep_channel)
        
        # Sweep start
        self.sweep_start_label = QtWidgets.QLabel(self.sweep_box_vlayout_outer)
        self.sweep_box_layout.setWidget(2, QtWidgets.QFormLayout.LabelRole, self.sweep_start_label)
        self.sweep_start = ScienDSpinBox(parent=self.sweep_box_vlayout_outer)
        self.sweep_box_layout.setWidget(2, QtWidgets.QFormLayout.FieldRole, self.sweep_start)
        
        # Sweep end
        self.sweep_end_label = QtWidgets.QLabel(self.sweep_box_vlayout_outer)
        self.sweep_box_layout.setWidget(3, QtWidgets.QFormLayout.LabelRole, self.sweep_end_label)
        self.sweep_end = ScienDSpinBox(parent=self.sweep_box_vlayout_outer)
        self.sweep_box_layout.setWidget(3, QtWidgets.QFormLayout.FieldRole, self.sweep_end)
        
        # Sweep increment
        self.sweep_step_label = QtWidgets.QLabel(self.sweep_box_vlayout_outer)
        self.sweep_box_layout.setWidget(4, QtWidgets.QFormLayout.LabelRole, self.sweep_step_label)
        self.sweep_step = ScienDSpinBox(parent=self.sweep_box_vlayout_outer)
        self.sweep_box_layout.setWidget(4, QtWidgets.QFormLayout.FieldRole, self.sweep_step)
        
        # Overlay runs on same figure checkbox
        self.overlay_checkbox = QtWidgets.QCheckBox(self.sweep_box_vlayout_outer)
        self.sweep_box_vlayout.addWidget(self.overlay_checkbox)

        # Device status layout
        self.device_status_layout = QtWidgets.QWidget(self.centralwidget)
        self.device_status_layout.setGeometry(QtCore.QRect(840, 470, 261, 161))
        self.device_status_layout = QtWidgets.QFormLayout(self.device_status_layout)
        self.device_status_layout.setContentsMargins(0, 0, 0, 0)

        # Lock-in connection feedback
        self.lockin_status_label = QtWidgets.QLabel(self)
        self.device_status_layout.setWidget(4, QtWidgets.QFormLayout.LabelRole, self.lockin_status_label)
        self.lockin_status = QtWidgets.QLabel(self)
        self.device_status_layout.setWidget(4, QtWidgets.QFormLayout.FieldRole, self.lockin_status)

        # AWG connection feedback
        self.awg_status_label = QtWidgets.QLabel(self)
        self.device_status_layout.setWidget(5, QtWidgets.QFormLayout.LabelRole, self.awg_status_label)
        self.awg_status = QtWidgets.QLabel(self)
        self.device_status_layout.setWidget(5, QtWidgets.QFormLayout.FieldRole, self.awg_status)
        
        # STM connection feedback
        self.stm_status_label = QtWidgets.QLabel(self)
        self.device_status_layout.setWidget(6, QtWidgets.QFormLayout.LabelRole, self.stm_status_label)
        self.stm_status = QtWidgets.QLabel(self)
        self.device_status_layout.setWidget(6, QtWidgets.QFormLayout.FieldRole, self.stm_status)

        # Set central widget
        self.setCentralWidget(self.centralwidget)

        # Menu bar
        self.menubar = QtWidgets.QMenuBar(self)
        self.menubar.setGeometry(QtCore.QRect(0, 0, 552, 22))
        self.menu_file = QtWidgets.QMenu(self.menubar)
        self.setMenuBar(self.menubar)
        
        # Status bar
        self.statusbar = QtWidgets.QStatusBar(self)
        self.statusbar_divider = QtWidgets.QFrame(self.centralwidget)
        self.statusbar_divider.setGeometry(QtCore.QRect(0, 690, 1201, 20))
        self.statusbar_divider.setFrameShape(QtWidgets.QFrame.HLine)
        self.statusbar_divider.setFrameShadow(QtWidgets.QFrame.Sunken)
        self.setStatusBar(self.statusbar)
        
        # File menu actions
        self.action_set_save_path = QtWidgets.QAction(self)
        self.action_reset_connected_devices = QtWidgets.QAction(self)
        self.action_edit_settings = QtWidgets.QAction(self)
        self.menu_file.addAction(self.action_set_save_path)
        self.menu_file.addAction(self.action_reset_connected_devices)
        self.menu_file.addAction(self.action_edit_settings)
        self.menubar.addAction(self.menu_file.menuAction())

        self.init_connections()
        QtCore.QMetaObject.connectSlotsByName(self)

    """
    """
    def retranslateUi(self):
        self.setWindowTitle("All-Electronic Pump Probe Spectroscopy")
        
        self.procedure_label.setText("Procedure:")
        self.procedure.setItemText(0, "Time delay")
        self.procedure.setItemText(1, "Amplitude")
        self.procedure.setItemText(2, "Image")
        
        self.add_procedure_btn.setText("Add procedure")
        self.remove_procedure_btn.setText("Remove procedure")
        self.procedure_btn.setText("Run procedures")
        
        self.pump_box.setTitle("Pump")
        self.pump_amp_label.setText("Amplitude         ")
        self.pump_width_label.setText("Width")
        self.pump_edge_layout.setText("Edge")
        
        self.probe_box.setTitle("Probe")
        self.probe_amp_label.setText("Amplitude         ")
        self.probe_width_label.setText("Width")
        self.probe_edge_label.setText("Edge")

        self.procedure_settings_box.setTitle("Procedure settings")
        
        # Time delay procedure settings
        self.time_spread_label.setText("Time spread:")
        self.time_delay_sample_size_label.setText("Sample size:")
        
        # Amp procedure settings
        self.amp_procedure_channel_label.setText("Channel:")
        self.amp_procedure_channel.setItemText(0, "Probe")
        self.amp_procedure_channel.setItemText(1, "Pump")
        self.amp_procedure_start_label.setText("Amplitude start:")
        self.amp_procedure_end_label.setText("Amplitude end:")
        self.amp_procedure_fixed_time_delay_label.setText("Fixed time delay:")
        self.amp_procedure_sample_size_label.setText("Sample size:")
        
        # Image procedure settings
        self.image_frames_label.setText("Frames:")
        self.image_lines_label.setText("Lines per frame:")
        self.image_size_label.setText("Size:")
        self.image_x_offset_label.setText("X Offset:")
        self.image_y_offset_label.setText("Y Offset:")
        self.image_scan_speed_label.setText("Scan speed:")
        self.image_lines_per_second_label.setText("Lines per second:")
        
        self.sweep_box.setTitle("Sweep over multiple runs")
        self.sweep_parameter_label.setText("Sweep parameter")
        self.sweep_parameter.setItemText(0, "Amplitude")
        self.sweep_parameter.setItemText(1, "Width")
        self.sweep_parameter.setItemText(2, "Edge")
        self.sweep_channel_label.setText("Sweep channel")
        self.sweep_channel.setItemText(0, "Probe")
        self.sweep_channel.setItemText(1, "Pump")
        self.sweep_channel.setItemText(2, "Both")
        self.sweep_start_label.setText("Sweep start")
        self.sweep_end_label.setText("Sweep end")
        self.sweep_step_label.setText("Sweep step")
        self.overlay_checkbox.setText("Overlay runs on same figure")

        # Queue headers
        self.queue.horizontalHeaderItem(0).setText("Procedure")
        self.queue.horizontalHeaderItem(1).setText("Pump Amp")
        self.queue.horizontalHeaderItem(2).setText("Pump Width")
        self.queue.horizontalHeaderItem(3).setText("Pump Edge")
        self.queue.horizontalHeaderItem(4).setText("Probe Amp")
        self.queue.horizontalHeaderItem(5).setText("Probe Width")
        self.queue.horizontalHeaderItem(6).setText("Probe Edge")
        self.queue.horizontalHeaderItem(7).setText("Domain")

        # Defaults
        self.pump_amp.setValue(0.5)
        self.pump_amp.setSuffix('V')
        
        self.pump_width.setValue(10e-9)
        self.pump_width.setSuffix('s')
        
        self.pump_edge.setValue(3e-9)
        self.pump_edge.setSuffix('s')
        
        self.probe_amp.setValue(0.5)
        self.probe_amp.setSuffix('V')
        
        self.probe_width.setValue(10e-9)
        self.probe_width.setSuffix('s')

        self.probe_edge.setValue(3e-9)
        self.probe_edge.setSuffix('s')
        
        self.sweep_start.setValue(0.0)
        self.sweep_start.setSuffix('V')
        
        self.sweep_end.setValue(1.0)
        self.sweep_end.setSuffix('V')
        
        self.sweep_step.setValue(0.1)
        self.sweep_step.setSuffix('V')
        
        self.time_spread.setValue(100e-9)
        self.time_spread.setSuffix('s')
        
        self.time_delay_sample_size.setValue(500)
        
        self.amp_procedure_start.setValue(0.0)
        self.amp_procedure_start.setSuffix('V')
        
        self.amp_procedure_end.setValue(1.0)
        self.amp_procedure_end.setSuffix('V')
        
        self.amp_procedure_fixed_time_delay.setValue(10e-9)
        self.amp_procedure_fixed_time_delay.setSuffix('s')
        
        self.amp_procedure_sample_size.setValue(500)
        
        self.image_frames.setValue(512)
        self.image_lines.setValue(512)
        self.image_size.setValue(10e-9)
        self.image_size.setSuffix('m')
        self.image_x_offset.setValue(0.0)
        self.image_x_offset.setSuffix('m')
        self.image_x_offset.setMaximum(999e-6)
        self.image_x_offset.setMinimum(-999e-6)
        self.image_x_offset.setMinimalStep(0.01e-9)
        self.image_y_offset.setValue(0.0)
        self.image_y_offset.setSuffix('m')
        self.image_y_offset.setMaximum(999e-6)
        self.image_y_offset.setMinimum(-999e-6)
        self.image_y_offset.setMinimalStep(0.01e-9)
        self.image_scan_speed.setValue(10.0e-9)
        self.image_scan_speed.setSuffix('m/s')
        self.image_lines_per_second.setValue(self.image_scan_speed.value()/self.image_size.value())
        self.image_lines_per_second.setSuffix('lines/s')

        self.lockin_status_label.setText("Lock-in status: ")
        self.lockin_status.setText("Disconnected")
        self.awg_status_label.setText("AWG status: ")
        self.awg_status.setText("Disconnected")
        self.stm_status_label.setText(f"{self.PumpProbe.config.stm_model} status: ")
        self.stm_status.setText("Disconnected")
        self.menu_file.setTitle("File")
        self.action_set_save_path.setText("Set save path")
        self.action_reset_connected_devices.setText("Reset connected devices")
        self.action_edit_settings.setText("Edit settings")
    
    """
    """
    def init_connections(self):
        # Buttons
        self.procedure.activated.connect(self.set_procedure_settings)
        self.procedure_btn.clicked.connect(self.run_procedures)
        self.add_procedure_btn.clicked.connect(self.add_procedure)
        self.remove_procedure_btn.clicked.connect(self.remove_procedure)
        
        # Combobox activations
        self.amp_procedure_channel.activated.connect(self.amp_proc_ch_changed)
        self.sweep_parameter.activated.connect(self.sweep_param_changed)
        
        # Settings changed
        self.image_size.valueChanged.connect(self.update_image_lines_per_second)
        self.image_scan_speed.valueChanged.connect(self.update_image_lines_per_second)
        
        # Menu actions
        self.action_set_save_path.triggered.connect(self.set_save_path)
        self.action_reset_connected_devices.triggered.connect(self.reset_triggered)
        self.action_edit_settings.triggered.connect(self.edit_settings)
    
    """
    """ 
    def reset_triggered(self):
        if self.PumpProbe.lockin:
            self.PumpProbe.lockin.reset()
        if self.PumpProbe.awg:
            self.PumpProbe.awg.reset()

    """
    """
    def update_lockin_status(self, msg: str) -> None:
        self.lockin_status.setText(msg)

    """
    """
    def update_awg_status(self, msg: str) -> None:
        self.awg_status.setText(msg)
    
    """
    """    
    def update_stm_status(self, msg: str) -> None:
        self.stm_status.setText(msg)

    """
    """
    def update_queue_status(self, color: QtGui.QColor) -> None:
        for cell in range(self.queue.columnCount()):
            self.queue.item(0, cell).setBackground(color)
    
    """
    """    
    def report_progress(self, msg:str) -> None:
        print(f"{msg}")
        self.statusbar.showMessage(msg)

    """
    """
    def set_procedure_settings(self):
        self.time_delay_procedure_settings_layout_outer.hide()
        self.amp_procedure_settings_layout_outer.hide()
        self.image_procedure_settings_layout_outer.hide()
        match self.procedure.currentText():
            case "Time delay":
                self.time_delay_procedure_settings_layout_outer.setHidden(False)
                self.sweep_channel.setEnabled(True)
            case "Amplitude":
                self.amp_procedure_settings_layout_outer.setHidden(False)
                if self.amp_procedure_channel.currentText() == "Probe":
                    self.sweep_channel.setCurrentText("Pump")
                else:
                    self.sweep_channel.setCurrentText("Probe")
                self.sweep_channel.setEnabled(False)
            case "Image":
                self.image_procedure_settings_layout_outer.setHidden(False)
                self.sweep_channel.setEnabled(True)
            case _:
                pass
    
    def sweep_param_changed(self):
        """
        """
        if self.sweep_parameter.currentText() == 'Amplitude':
            self.set_sweep_suffix('V')
        else:
            self.set_sweep_suffix('s')                
     
    def set_sweep_suffix(self, suffix: str):
        self.sweep_start.setSuffix(suffix)
        self.sweep_end.setSuffix(suffix)
        self.sweep_step.setSuffix(suffix)
    
    """
    """
    def amp_proc_ch_changed(self):
        if self.amp_procedure_channel.currentText() == "Probe":
            self.sweep_channel.setCurrentText("Pump")
        else:
            self.sweep_channel.setCurrentText("Probe")

    def update_image_lines_per_second(self):
        self.image_lines_per_second.setValue(self.image_scan_speed.value() / self.image_size.value())

    def run_procedures(self):
        """
        Called when 'Run procedures' button is pressed. Handles running of pump-probe experiment on seperate QThread.
        """
        while self.PumpProbe.config.save_path == "":
            self.set_save_path()
        self.plotter = QPlotter()
        self.worker = PumpProbeWorker(self.PumpProbe, self.queue, self.plotter)

        self.worker.started.connect(lambda: self.report_progress("QThread started. Running pump-probe experiment(s)."))
        self.worker._progress.connect(self.report_progress)
        self.worker._lockin_status.connect(self.update_lockin_status)
        self.worker._awg_status.connect(self.update_awg_status)
        self.worker._stm_status.connect(self.update_stm_status)
        self.worker._queue_signal.connect(self.update_queue_status)
        self._hook.connect(lambda: self.worker.stop_early())

        # plotting
        self.worker._make_figure.connect(self.plotter.mk_figure)
        self.plotter._plot.connect(self.plotter.update_figure)


        self.procedure_btn.setText("Stop procedures")
        self.procedure_btn.clicked.disconnect()
        self.procedure_btn.clicked.connect(self.stop_procedures)

        self.worker._finished.connect(lambda: self.procedure_btn.setText("Run procedures"))
        self.worker._finished.connect(lambda: self.procedure_btn.setEnabled(True))
        self.worker._finished.connect(lambda: self.procedure_btn.clicked.disconnect())
        self.worker._finished.connect(lambda: self.procedure_btn.clicked.connect(self.run_procedures))
        
        self.worker.start()

    def stop_procedures(self):
        """
        Called when 'Stop procedures' button is pushed. Emits hook signal to stop queue after current experiment is finished.
        """
        self._hook.emit()
        self._hook.disconnect()
        self.procedure_btn.setEnabled(False)

    def get_experiment_dict(self) -> dict[str, str]:
        """
        Returns a dict containing all relevant experimental information to be displayed in the queue. Dictionary keys correspond to column titles.
        """
        exp_dict = {'procedure' : self.procedure.currentText(),
                'pump_amp': self.pump_amp.text(), 'pump_width': self.pump_width.text(), 'pump_edge': self.pump_edge.text(),
                'probe_amp': self.probe_amp.text(), 'probe_width': self.probe_width.text(), 'probe_edge': self.probe_edge.text(),
                'domain': ''}
        
        match exp_dict['procedure']:
            case "Time delay":
                bound = self.time_spread.textFromValue(self.time_spread.value()/2)
                exp_dict['domain'] = f'(-{bound}s, {bound}s)'
            case "Amplitude":
                exp_dict['domain'] = f'({self.amp_procedure_start.text()}, {self.amp_procedure_end.text()})'
                if self.amp_procedure_channel.currentText() == "Pump":
                    exp_dict['pump_amp'] = exp_dict['domain']
                else:
                    exp_dict['probe_amp'] = exp_dict['domain']
            case "Image":
                pass
            case _:
                pass                  
        
        sweep_param = self.sweep_parameter.currentText()
        sweep_ch = self.sweep_channel.currentText()
    
        domain_str = f'{{{self.sweep_start.text()}, {self.sweep_end.text()}}} : {self.sweep_step.text()}'
        
        if self.sweep_box.isChecked():
            if sweep_param == "Amplitude":
                if sweep_ch == "Pump":
                    exp_dict['pump_amp'] = domain_str
                elif sweep_ch == "Probe":
                    exp_dict['probe_amp'] = domain_str
                else:
                    exp_dict['pump_amp'] = domain_str
                    exp_dict['probe_amp'] = domain_str
            elif sweep_param == "Width":
                if sweep_ch == "Pump":
                    exp_dict['pump_width'] = domain_str
                elif sweep_ch == "Probe":
                    exp_dict['probe_width'] = domain_str
                else:
                    exp_dict['pump_width'] = domain_str
                    exp_dict['probe_width'] = domain_str
            elif sweep_param == "Edge":
                if sweep_ch == "Pump":
                    exp_dict['pump_edge'] = domain_str
                elif sweep_ch == "Probe":
                    exp_dict['probe_edge'] = domain_str
                else:
                    exp_dict['pump_edge'] = domain_str
                    exp_dict['probe_edge'] = domain_str                    
        
        return exp_dict

    def add_procedure(self):
        """
        Called when 'Add procedure' button is pressed. Creates a list of PumpProbeExperiments which gets passed to the queue via QDataTable.add_item().
        The row information is in the form of a QDataTableRow object which gets passed a dictionary from get_experiment_dict(). This allows the information 
        presented in the row be equivalent to what the user inputed (i.e. 100e-9 -> 100e-9 and not 100e-9 -> 1e-7). The new PumpProbeExperiment is instantiated
        with float values and added to the QDataTable's data array via QDataTable.add_item(..., data = PumpProbeExperiment(...))
        """    
        steps = 1
        experiments = list()
        procedure = self.get_selected_procedure()
        
        if self.sweep_box.isChecked():
            steps += int((self.sweep_end.value() - self.sweep_start.value()) // self.sweep_step.value())
            sweep_range = np.linspace(self.sweep_start.value(), self.sweep_end.value(), steps)
        
        sweep_param = self.sweep_parameter.currentText()
        sweep_ch = self.sweep_channel.currentText()
        
        for i in range(steps):
            pump_pulse = Pulse(self.pump_amp.value(), self.pump_width.value(), self.pump_edge.value(), 100e-9)
            probe_pulse = Pulse(self.probe_amp.value(), self.probe_width.value(), self.probe_edge.value(), 100e-9)
            if self.sweep_box.isChecked():
                if sweep_param == "Amplitude":
                    if sweep_ch == "Pump":
                        pump_pulse.amp = sweep_range[i]
                    elif sweep_ch == "Probe":
                        probe_pulse.amp = sweep_range[i]
                    else:
                        pump_pulse.amp = sweep_range[i]
                        probe_pulse.amp = sweep_range[i]
                elif sweep_param == "Width":
                    if sweep_ch == "Pump":
                        pump_pulse.width = sweep_range[i]
                    elif sweep_ch == "Probe":
                        probe_pulse.width = sweep_range[i]
                    else:
                        pump_pulse.width = sweep_range[i]
                        probe_pulse.width = sweep_range[i]
                elif sweep_param == "Edge":
                    if sweep_ch == "Pump":
                        pump_pulse.edge = sweep_range[i]
                    elif sweep_ch == "Probe":
                        probe_pulse.edge = sweep_range[i]
                    else:
                        pump_pulse.edge = sweep_range[i]
                        probe_pulse.edge = sweep_range[i]                        

            match self.procedure.currentText():
                case "Time delay":
                    samples = self.time_delay_sample_size.value()
                    domain = (-180, 180)
                    procedure_channel = Channel.PROBE
                case "Amplitude":
                    samples = self.amp_procedure_sample_size.value()
                    domain = (self.amp_procedure_start.value(), self.amp_procedure_end.value())
                    if self.amp_procedure_channel.currentText() == "Probe":
                        procedure_channel = Channel.PROBE
                        probe_pulse.amp = domain[0]
                    else:
                        procedure_channel = Channel.PUMP
                        pump_pulse.amp = domain[0]
                case "Image":
                    samples = self.image_frames.value()
                    procedure_channel = Channel.PROBE
                    domain = (-180, 180)
                    self.report_progress("Image functionality not implemented yet.")
                    return
                case _:
                    pass
                

            new_experiment = PumpProbeExperiment(procedure=procedure, procedure_channel=procedure_channel, pump=pump_pulse, probe=probe_pulse, domain=domain, samples=samples)
            experiments.append(new_experiment)
        print("Added to queue:")
        for exp in experiments:
            print(f'[ADDED] {exp}')
        self.queue.add_item(row = QDataTableRow(**self.get_experiment_dict()), data = experiments)

    """
    """
    def remove_procedure(self):
        rowIdx = self.queue.currentRow()
        if rowIdx >= 0:
            # Remove row from queue
            self.queue.removeRow(rowIdx)
            # Remove experiment from queue data
            self.statusbar.showMessage("Experiment removed from queue.")
            print("Experiment removed from queue:")
            for exp in self.queue.data[rowIdx]:
                print(f'[REMOVED] {exp}')
            del self.queue.data[rowIdx]

    """
    """
    def get_selected_procedure(self):
        match self.procedure.currentText():
            case "Time delay":
                return self.sweep_phase_procedure()
            case "Amplitude":
                return self.sweep_amp_procedure()
            case _:
                return None
    
    """
    """
    def set_save_path(self):
        save_path = QtWidgets.QFileDialog.getExistingDirectory(self, 'Set Save Path', self.PumpProbe.config.save_path)
        self.PumpProbe.config.save_path = save_path
        self.settings.setValue('save_path', save_path)
        self.report_progress(f"Save path set to {self.PumpProbe.config.save_path}")

    """
    Opens a dialog window with configuration options. Stores in QSettings object
    """        
    def edit_settings(self):
        settings_dialog = SettingsDialog(self.settings)
        if settings_dialog.exec_():
            self.report_progress("Settings updated.")
    
    """
    """
    def sweep_phase_procedure(self) -> Procedure:
        return Procedure(self.PumpProbe.awg.set_phase, conversion_factor=100e-9 / 360 * self.PumpProbe.config.sample_rate)
    
    """
    """
    def sweep_amp_procedure(self) -> Procedure:
        return Procedure(self.PumpProbe.awg.set_amp, conversion_factor=1.0)