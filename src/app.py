import matplotlib.pyplot as plt
from PyQt5 import QtCore, QtGui, QtWidgets
from pump_probe import PumpProbe, PumpProbeConfig, PumpProbeExperiment, Pulse
from device import LockIn, AWG, Result
from extend_qt import QDataTable, QDataTableRow, QNumericalLineEdit
plt.ion()

class PumpProbeWorker(QtCore.QThread):
    progress = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()
    queue_signal = QtCore.pyqtSignal(QtGui.QColor)
    lockin_status = QtCore.pyqtSignal(str)
    awg_status = QtCore.pyqtSignal(str)
    _plot = QtCore.pyqtSignal()

    def __init__(self, pump_probe:PumpProbe, queue: QDataTable) -> None:
        super().__init__(parent=None)
        self.pump_probe = pump_probe
        self.queue = queue
        self.running_pp = False
        self.repeat_arb = False

    def stop_early(self):
        self.running_pp = False

    def init_lockin(self):
        if self.pump_probe.lockin == None:
            self.progress.emit("[Lock-in] Initializing")
            self.pump_probe.lockin = LockIn(ip=self.pump_probe.config.lockin_ip, port=self.pump_probe.config.lockin_port)

    def init_awg(self):
        if self.pump_probe.awg == None:
            self.progress.emit("[AWG] Initializing")
            self.pump_probe.awg = AWG(id=self.pump_probe.config.awg_id)
    
    def connect_lockin(self) -> Result:
        self.progress.emit("[Lock-in] Connecting...")
        self.lockin_status.emit("Connecting...")
        result = self.pump_probe.lockin.connect().expected("[Lock-in] Could not connect:")
        self.progress.emit(f"[Lock-in] {result.msg}")
        if result.err == True:
            self.lockin_status.emit("Disconnected")
        else:
            self.lockin_status.emit("Connected")
        return result

    def connect_awg(self) -> Result:
        self.progress.emit("[AWG] Connecting...")
        self.awg_status.emit("Connecting...")
        result = self.pump_probe.awg.connect().expected("[AWG] Could not connect:")
        self.progress.emit(f"[AWG] {result.msg}")
        if result.err == True:
            self.awg_status.emit("Disconnected")
        else:
            self.awg_status.emit("Connected")
        return result

    """
    Run pump probe experiment for each experiment in the queue until empty or 'Stop queue' button is pressed.
    """
    def run(self):
        # Check if devices are initialized
        self.init_lockin()
        self.init_awg()
        ## Check if devices are connected
        lockin_result = self.connect_lockin()
        awg_result = self.connect_awg()

        if lockin_result.err:
            self.progress.emit("[ERROR] Lock-in did not connect. Please ensure Lock-in is able to communicate with local user.")
            self.finished.emit()
            return
                    
        if awg_result.err:
            self.progress.emit("[ERROR] AWG did not connect. Please ensure AWG is able to communicate with local user.")
            self.finished.emit()
            return

        # Check if experiment queue is empty
        if self.queue.rowCount() == 0:
            self.progress.emit("[ERROR] Experiment queue is empty. Please fill queue with at least one experiment.")
            self.finished.emit()
            return

        # Run pump-probe for each experiment in queue until queue is empty of 'Stop queue' button is pressed.
        self.running_pp = True
        # While the queue is not empty and pump-probe is still set to run (running_pp is set to False by clicking 'Stop queue')
        while(len(self.queue.data) != 0 and self.running_pp):
            self.queue_signal.emit(QtGui.QColor(QtCore.Qt.green))
            # Run pump-probe experiment. If not a repeated pulse, send new pulse data to AWG
            exp: PumpProbeExperiment = self.queue.data[0]
            try:
                self.progress.emit("Running pump-probe experiment.")
                self._plot.emit()
                volt_data, dt = self.pump_probe.run(exp=exp, repeat=self.repeat_arb)
            except Exception as e:
                msg = f"[ERROR] {e}. "
                if "'send'" in repr(e):
                    msg += " 'send' is a Lock-in method. Is the Lock-in connected properly?"
                elif "'write'" in repr(e):
                    msg += " 'write' is an AWG method. Is the AWG connected properly?"
                self.progress.emit(msg)
                self.queue_signal.emit(QtGui.QColor(QtCore.Qt.red))
                self.running_pp = False
            # Save measurement data
            
            # Check if next experiment in queue is a repeat arb

            # Remove experiment from queue data and top row
            del self.queue.data[0]
            self.queue.removeRow(0)
        # Close thread
        self.progress.emit("QThread finished. Pump-probe experiment(s) stopped.")
        self.finished.emit()

class MainWindow(QtWidgets.QMainWindow):
    hook = QtCore.pyqtSignal()

    def __init__(self):
        super().__init__()
        config = PumpProbeConfig(lockin_ip = "169.254.11.17", lockin_port=50_000, lockin_freq=1007, awg_id='USB0::0x0957::0x5707::MY53805152::INSTR', sample_rate=1e9, save_path="")
        self.PumpProbe = PumpProbe(config)
        self.experiments = list()
        self.setupUi()

    def setupUi(self):
        self.setObjectName("MainWindow")
        self.setFixedSize(997, 554)

        self.centralwidget = QtWidgets.QWidget(self)
        self.centralwidget.setObjectName("centralwidget")
        
        self.add_to_queue = QtWidgets.QPushButton(self.centralwidget)
        self.add_to_queue.setGeometry(QtCore.QRect(20, 460, 241, 41))
        self.add_to_queue.setObjectName("add_to_queue")

        self.queue_btn = QtWidgets.QPushButton(self.centralwidget)
        self.queue_btn.setGeometry(QtCore.QRect(730, 460, 241, 41))
        self.queue_btn.setObjectName("queue_btn")

        # Table queue
        self.queue = QDataTable(self.centralwidget)
        self.queue.setGeometry(QtCore.QRect(270, 30, 715, 411))
        self.queue.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.queue.setShowGrid(True)
        self.queue.setGridStyle(QtCore.Qt.SolidLine)
        self.queue.setCornerButtonEnabled(False)
        self.queue.setRowCount(1)
        self.queue.setColumnCount(7)
        self.queue.setObjectName("queue")
        self.queue.setHorizontalHeaderItem(0, QtWidgets.QTableWidgetItem())
        self.queue.setHorizontalHeaderItem(1, QtWidgets.QTableWidgetItem())
        self.queue.setHorizontalHeaderItem(2, QtWidgets.QTableWidgetItem())
        self.queue.setHorizontalHeaderItem(3, QtWidgets.QTableWidgetItem())
        self.queue.setHorizontalHeaderItem(4, QtWidgets.QTableWidgetItem())
        self.queue.setHorizontalHeaderItem(5, QtWidgets.QTableWidgetItem())
        self.queue.setHorizontalHeaderItem(6, QtWidgets.QTableWidgetItem())
        self.queue.horizontalHeader().setVisible(True)
        self.queue.horizontalHeader().setCascadingSectionResizes(False)
        self.queue.verticalHeader().setVisible(True)
        
        # Pump pulse  box
        self.pump_box = QtWidgets.QGroupBox(self.centralwidget)
        self.pump_box.setGeometry(QtCore.QRect(10, 10, 251, 131))
        self.pump_box.setObjectName("pump_box")

        # Pump pulse box layout
        self.pump_box_layout = QtWidgets.QWidget(self.pump_box)
        self.pump_box_layout.setGeometry(QtCore.QRect(9, 29, 231, 91))
        self.pump_box_layout.setObjectName("pump_box_layout")
        self.pump_box_layout = QtWidgets.QFormLayout(self.pump_box_layout)
        self.pump_box_layout.setContentsMargins(0, 0, 0, 0)
        self.pump_box_layout.setObjectName("pump_box_layout")

        # Pump amplitude
        self.pump_amp_label = QtWidgets.QLabel(self.pump_box)
        self.pump_amp_label.setObjectName("pump_amp_label")
        self.pump_box_layout.setWidget(0, QtWidgets.QFormLayout.LabelRole, self.pump_amp_label)
        self.pump_amp = QNumericalLineEdit(self.pump_box, QtGui.QDoubleValidator)
        self.pump_amp.setObjectName("pump_amp")
        self.pump_box_layout.setWidget(0, QtWidgets.QFormLayout.FieldRole, self.pump_amp)

        # Pump width
        self.pump_width_label = QtWidgets.QLabel(self.pump_box)
        self.pump_width_label.setObjectName("pump_width_label")
        self.pump_box_layout.setWidget(1, QtWidgets.QFormLayout.LabelRole, self.pump_width_label)
        self.pump_width = QNumericalLineEdit(self.pump_box, QtGui.QDoubleValidator)
        self.pump_width.setObjectName("pump_width")
        self.pump_box_layout.setWidget(1, QtWidgets.QFormLayout.FieldRole, self.pump_width)

        # Pump edge
        self.pump_edge_layout = QtWidgets.QLabel(self.pump_box)
        self.pump_edge_layout.setObjectName("pump_edge_layout")
        self.pump_box_layout.setWidget(2, QtWidgets.QFormLayout.LabelRole, self.pump_edge_layout)
        self.pump_edge = QNumericalLineEdit(self.pump_box, QtGui.QDoubleValidator)
        self.pump_edge.setObjectName("pump_edge")
        self.pump_box_layout.setWidget(2, QtWidgets.QFormLayout.FieldRole, self.pump_edge)

        # Probe pulse box
        self.probe_box = QtWidgets.QGroupBox(self.centralwidget)
        self.probe_box.setGeometry(QtCore.QRect(10, 150, 251, 131))
        self.probe_box.setObjectName("probe_box")

        # Probe pulse box layout
        self.probe_box_layout = QtWidgets.QWidget(self.probe_box)
        self.probe_box_layout.setGeometry(QtCore.QRect(9, 29, 231, 91))
        self.probe_box_layout.setObjectName("probe_box_layout")
        self.probe_box_layout = QtWidgets.QFormLayout(self.probe_box_layout)
        self.probe_box_layout.setContentsMargins(0, 0, 0, 0)
        self.probe_box_layout.setObjectName("probe_box_layout")

        # Probe amplitude
        self.probe_amp_label = QtWidgets.QLabel(self.probe_box)
        self.probe_amp_label.setObjectName("probe_amp_label")
        self.probe_box_layout.setWidget(0, QtWidgets.QFormLayout.LabelRole, self.probe_amp_label)
        self.probe_amp = QNumericalLineEdit(self.probe_box, QtGui.QDoubleValidator)
        self.probe_amp.setObjectName("probe_amp")
        self.probe_box_layout.setWidget(0, QtWidgets.QFormLayout.FieldRole, self.probe_amp)

        # Probe width
        self.probe_width_label = QtWidgets.QLabel(self.probe_box)
        self.probe_width_label.setObjectName("probe_width_label")
        self.probe_box_layout.setWidget(1, QtWidgets.QFormLayout.LabelRole, self.probe_width_label)
        self.probe_width = QNumericalLineEdit(self.probe_box, QtGui.QDoubleValidator)
        self.probe_width.setObjectName("probe_width")
        self.probe_box_layout.setWidget(1, QtWidgets.QFormLayout.FieldRole, self.probe_width)

        # Probe edge
        self.probe_edge_label = QtWidgets.QLabel(self.probe_box)
        self.probe_edge_label.setObjectName("probe_edge_label")
        self.probe_box_layout.setWidget(2, QtWidgets.QFormLayout.LabelRole, self.probe_edge_label)
        self.probe_edge = QNumericalLineEdit(self.probe_box, QtGui.QDoubleValidator)
        self.probe_edge.setObjectName("probe_edge")
        self.probe_box_layout.setWidget(2, QtWidgets.QFormLayout.FieldRole, self.probe_edge)

        # Layout for other settings
        self.etc_layout = QtWidgets.QWidget(self.centralwidget)
        self.etc_layout.setGeometry(QtCore.QRect(20, 290, 231, 134))
        self.etc_layout.setObjectName("etc_layout")
        self.etc_layout = QtWidgets.QFormLayout(self.etc_layout)
        self.etc_layout.setContentsMargins(0, 0, 0, 0)
        self.etc_layout.setObjectName("etc_layout")

        # Pulse length
        self.pulse_length_label = QtWidgets.QLabel(self)
        self.pulse_length_label.setObjectName("pulse_length_label")
        self.etc_layout.setWidget(0, QtWidgets.QFormLayout.LabelRole, self.pulse_length_label)
        self.pulse_length = QNumericalLineEdit(self, QtGui.QDoubleValidator)
        self.pulse_length.setObjectName("pulse_length")
        self.etc_layout.setWidget(0, QtWidgets.QFormLayout.FieldRole, self.pulse_length)

        # Lock-in IP
        self.lockin_ip_label = QtWidgets.QLabel(self)
        self.lockin_ip_label.setObjectName("lockin_ip_label")
        self.etc_layout.setWidget(1, QtWidgets.QFormLayout.LabelRole, self.lockin_ip_label)
        self.lockin_ip = QtWidgets.QLineEdit(self)
        self.lockin_ip.setObjectName("lockin_ip")
        self.etc_layout.setWidget(1, QtWidgets.QFormLayout.FieldRole, self.lockin_ip)

        # Lock-in Freq
        self.lockin_freq_label = QtWidgets.QLabel(self)
        self.lockin_freq_label.setObjectName("lockin_freq_label")
        self.etc_layout.setWidget(2, QtWidgets.QFormLayout.LabelRole, self.lockin_freq_label)
        self.lockin_freq = QNumericalLineEdit(self, QtGui.QDoubleValidator)
        self.lockin_freq.setObjectName("lockin_freq")
        self.etc_layout.setWidget(2, QtWidgets.QFormLayout.FieldRole, self.lockin_freq)

        # Lock-in connection feedback
        self.lockin_status_label = QtWidgets.QLabel(self)
        self.lockin_status_label.setObjectName("lockin_status_label")
        self.etc_layout.setWidget(3, QtWidgets.QFormLayout.LabelRole, self.lockin_status_label)
        self.lockin_status = QtWidgets.QLineEdit(self)
        self.lockin_status.setFrame(False)
        self.lockin_status.setStyleSheet("background : transparent")
        self.lockin_status.setObjectName("lockin_status")
        self.etc_layout.setWidget(3, QtWidgets.QFormLayout.FieldRole, self.lockin_status)

        # AWG connection feedback
        self.awg_status_label = QtWidgets.QLabel(self)
        self.awg_status_label.setObjectName("awg_status_label")
        self.etc_layout.setWidget(4, QtWidgets.QFormLayout.LabelRole, self.awg_status_label)
        self.awg_status = QtWidgets.QLineEdit(self)
        self.awg_status.setFrame(False)
        self.awg_status.setStyleSheet("background : transparent")
        self.awg_status.setObjectName("awg_status")
        self.etc_layout.setWidget(4, QtWidgets.QFormLayout.FieldRole, self.awg_status)

        # Set central widget
        self.setCentralWidget(self.centralwidget)

        # Menu bar
        self.menubar = QtWidgets.QMenuBar(self)
        self.menubar.setGeometry(QtCore.QRect(0, 0, 552, 22))
        self.menubar.setObjectName("menubar")
        self.menu_file = QtWidgets.QMenu(self.menubar)
        self.menu_file.setObjectName("menu_file")
        self.setMenuBar(self.menubar)
        
        # Status bar
        self.statusbar = QtWidgets.QStatusBar(self)
        self.statusbar.setObjectName("statusbar")
        self.statusbar_divider = QtWidgets.QFrame(self.centralwidget)
        self.statusbar_divider.setGeometry(QtCore.QRect(0, 500, 1201, 20))
        self.statusbar_divider.setFrameShape(QtWidgets.QFrame.HLine)
        self.statusbar_divider.setFrameShadow(QtWidgets.QFrame.Sunken)
        self.statusbar_divider.setObjectName("statusbar_divider")
        self.setStatusBar(self.statusbar)
        
        # File menu actions
        self.action_set_save_path = QtWidgets.QAction(self)
        self.action_set_save_path.setObjectName("action_set_save_path")
        self.action_reset_connected_devices = QtWidgets.QAction(self)
        self.action_reset_connected_devices.setObjectName("action_reset_connected_devices")
        self.menu_file.addAction(self.action_set_save_path)
        self.menu_file.addAction(self.action_reset_connected_devices)
        self.menubar.addAction(self.menu_file.menuAction())

        self.init_connections()
        self.retranslateUi()
        QtCore.QMetaObject.connectSlotsByName(self)

    def retranslateUi(self):
        _translate = QtCore.QCoreApplication.translate
        self.setWindowTitle("Pump Probe")
        self.add_to_queue.setText("Add to queue")
        self.queue_btn.setText("Start queue")
        self.pump_box.setTitle("Pump")
        self.pump_amp_label.setText("Amplitude (V)     ")
        self.pump_width_label.setText("Width (s)")
        self.pump_edge_layout.setText("Edge (s)")
        self.probe_box.setTitle("Probe")
        self.probe_amp_label.setText("Amplitude (V)     ")
        self.probe_width_label.setText("Width (s)")
        self.probe_edge_label.setText("Edge (s)")
        self.pulse_length_label.setText("Pulse Length (s)")
        self.lockin_ip_label.setText("Lock-in IP")
        self.lockin_ip.setText("169.254.11.17")

        # Queue headers
        self.queue.horizontalHeaderItem(0).setText("Pump Amp")
        self.queue.horizontalHeaderItem(1).setText("Pump Width")
        self.queue.horizontalHeaderItem(2).setText("Pump Edge")
        self.queue.horizontalHeaderItem(3).setText("Probe Amp")
        self.queue.horizontalHeaderItem(4).setText("Probe Width")
        self.queue.horizontalHeaderItem(5).setText("Probe Edge")
        self.queue.horizontalHeaderItem(6).setText("Time Spread")

        # Defaults
        self.pump_amp.setText("0.95")
        self.pump_width.setText("10e-9")
        self.pump_edge.setText("3e-9")
        self.probe_amp.setText("0.6")
        self.probe_width.setText("10e-9")
        self.probe_edge.setText("3e-9")
        self.pulse_length.setText("100e-9")
        self.lockin_freq.setText("1007")

        self.lockin_freq_label.setText("Lock-in Freq (Hz)")
        self.lockin_status_label.setText("Lock-in status: ")
        self.lockin_status.setText("Disconnected")
        self.awg_status_label.setText("AWG status: ")
        self.awg_status.setText("Disconnected")
        self.menu_file.setTitle("File")
        self.action_set_save_path.setText("Set save path")
        self.action_reset_connected_devices.setText("Reset connected devices")

    def init_connections(self):
        self.queue_btn.clicked.connect(self.start_queue_pushed)
        self.add_to_queue.clicked.connect(self.add_to_queue_pushed)
        self.lockin_ip.textChanged.connect(lambda ip=self.lockin_ip.text(): self.set_lockin_ip(ip=ip))
        self.action_set_save_path.triggered.connect(self.set_save_path)

    def set_lockin_ip(self, ip:str) -> None:
        self.PumpProbe.config.lockin_ip = ip

    def update_lockin_status(self, msg: str) -> None:
        self.lockin_status.setText(msg)

    def update_awg_status(self, msg: str) -> None:
        self.awg_status.setText(msg)

    def update_queue_status(self, color: QtGui.QColor) -> None:
        for cell in range(self.queue.columnCount()):
            self.queue.item(0, cell).setBackground(color)
        
    def report_progress(self, msg:str) -> None:
        print(f"{msg}")
        self.statusbar.showMessage(msg)

    def update_figure(self, _in: list) -> None:
        dt, data = _in
        self.line.set_data(dt, data)
        plt.gca().relim()
        plt.gca().autoscale_view()
        # plt.show()

    def mk_figure(self):
        fig = plt.figure()
        ax = fig.add_subplot(111)
        self.line = ax.plot(list(), list())[0]

    """
    Called when 'Start queue' button is pressed. Handles running of pump-probe experiment on seperate QThread.
    """
    def start_queue_pushed(self):
        while self.PumpProbe.config.save_path == "":
            self.PumpProbe.config.save_path = QtWidgets.QFileDialog.getExistingDirectory(self, 'Set Save Path', self.PumpProbe.config.save_path)

        self.worker = PumpProbeWorker(self.PumpProbe, self.queue)

        self.worker.started.connect(lambda: self.report_progress("QThread started. Running pump-probe experiment(s)."))
        self.worker.progress.connect(self.report_progress)
        self.worker.lockin_status.connect(self.update_lockin_status)
        self.worker.awg_status.connect(self.update_awg_status)
        self.worker.queue_signal.connect(self.update_queue_status)
        self.hook.connect(lambda: self.worker.stop_early())

        # plotting
        self.worker._plot.connect(self.mk_figure)
        self.PumpProbe._plot.connect(self.update_figure)

        self.worker.start()

        self.queue_btn.setText("Stop queue")
        self.queue_btn.clicked.disconnect()
        self.queue_btn.clicked.connect(self.stop_queue_pushed)

        self.worker.finished.connect(lambda: self.queue_btn.setText("Start queue"))
        self.worker.finished.connect(lambda: self.queue_btn.setEnabled(True))
        self.worker.finished.connect(lambda: self.queue_btn.clicked.disconnect())
        self.worker.finished.connect(lambda: self.queue_btn.clicked.connect(self.start_queue_pushed))

    """
    Called when 'Stop queue' button is pushed. Emits hook signal to stop queue after current experiment is finished.
    """
    def stop_queue_pushed(self):
        self.hook.emit()
        self.hook.disconnect()
        self.queue_btn.setEnabled(False)

    """
    Returns a dict containing all relevant experimental information to be displayed in the queue.
    TODO: should lock-in freq be included? (i.e. variable between experiments)
    """
    def get_experiment_dict(self) -> dict[str, str]:
        return {'pump_amp': self.pump_amp.text(), 'pump_width': self.pump_width.text(), 'pump_edge': self.pump_edge.text(),
                'probe_amp': self.probe_amp.text(), 'probe_width': self.probe_width.text(), 'probe_edge': self.probe_edge.text(),
                'pulse_length': self.pulse_length.text()}

    """
    Called when 'Add to queue' button is pressed. Creates two Pulse objects and a PumpProbeExperiment which gets passed to the queue via QDataTable.add_item().
    The row information is in the form of a QDataTableRow object which gets passed a dictionary from get_experiment_dict(). This allows the information 
    presented in the row be equivalent to what the user inputed (i.e. 100e-9 -> 100e-9 and not 100e-9 -> 1e-7). The new PumpProbeExperiment is instantiated
    with float values and added to the QDataTable's data array via QDataTable.add_item(..., data = PumpProbeExperiment(...))
    """
    def add_to_queue_pushed(self):
        pump_pulse = Pulse(self.pump_amp.value(), self.pump_width.value(), self.pump_edge.value(), self.pulse_length.value())
        probe_pulse = Pulse(self.probe_amp.value(), self.probe_width.value(), self.probe_edge.value(), self.pulse_length.value())
        new_experiment = PumpProbeExperiment(pump=pump_pulse, probe=probe_pulse, phase_range=180, samples=400, lockin_freq=self.lockin_freq.value())
        self.queue.add_item(row = QDataTableRow(**self.get_experiment_dict()), data = new_experiment)
        self.statusbar.showMessage(f"New experiment added to queue.")
        print(f"New experiment added to queue: {self.queue.data[-1]}")

    def set_save_path(self):
        save_path = QtWidgets.QFileDialog.getExistingDirectory(self, 'Set Save Path', self.PumpProbe.config.save_path)
        self.PumpProbe.config.save_path = save_path
        self.report_progress(f"Save path set to {self.PumpProbe.config.save_path}")
