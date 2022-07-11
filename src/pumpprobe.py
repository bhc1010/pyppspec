import time
import numpy as np
import matplotlib.pyplot as plt
from device import LockIn, AWG
from dataclasses import dataclass
from typing import Tuple

"""
Defines an immutable dataclass called Pulse to hold amplitude, width, edge, and time spread (pulse length) data for a specific pulse
"""
@dataclass(frozen=True)
class Pulse:
    amp: float
    width: float
    edge: float
    time_spread: float

"""
Defines an immutable dataclass PumpProbeExperiment to hold pump and probe pulse data about a specific experiement.
"""
@dataclass(frozen=True)
class PumpProbeExperiment:
    pump: Pulse
    probe: Pulse
    phase_range: float
    samples: int
    lockin_freq: int

"""
Defines a mutable dataclass PumpProbeConfig to hold semi-constant (globally used for all experiments but can be mutated) pump-probe configuration data
"""
@dataclass
class PumpProbeConfig:
    lockin_ip: str
    lockin_port: int
    lockin_freq: int
    awg_id: str
    sample_rate: float

"""
Defines a PumpProbe class that connects and holds references to devices, experimental settings, and runs pump-probe experiments.
"""
class PumpProbe:
    def __init__(self, config:PumpProbeConfig = None):
        self.config = config
        self.lockin : LockIn = None
        self.awg : AWG = None

    def init_lockin(self):
        if self.lockin != None:
            self.lockin.send('IE 2'.encode()).expected(f"Lockin reference mode not set.")  #set reference mode to external front panel
            time.sleep(0.2)
            self.lockin.send('IMODE 0'.encode()).expected("Lockin current mode not set.")  #current mode off-input voltage only
            time.sleep(0.2)
            self.lockin.send('VMODE 1'.encode()).expected("Lockin input not set.")  #A input only
            time.sleep(0.2)
            self.lockin.send('SEN 20'.encode()).expected("Lockin sensitivity not set.")  #sensitivity 10 mV
            time.sleep(0.2)
            self.lockin.send('ACGAIN 5'.encode()).expected("Lockin gain not set.")  #set gain, 6 = 36 dB. dB = 6 * n
            time.sleep(0.2)
            # self.lockin.send('AUTOMATIC 0'.encode())  #set AC gain to automatic control
            self.lockin.send('AQN'.encode()).expected("Lockin auto-phase not set.")  #auto-phase
            time.sleep(0.2)
            # self.lockin.send('TC 10'.encode())  #set filter time constant control to 20 ms
            # self.lockin.send('FLOAT 1'.encode())  #'float input connector shell using 1kOhm to ground' need to read more
            # time.sleep(0.1)
            self.lockin.send('LF 0'.encode()).expected("Lockin line frequency rejection filter not turned off")  #'turn off line frequency rejection filter
            time.sleep(0.2)

            self.lockin.reset()

    def make_experiment(self, time_spread: float, pump_amp: float, pump_width:float, pump_edge:float, probe_amp:float, probe_width:float, probe_edge:float, 
                        phase_range:float, samples:int, lockin_freq:int) -> PumpProbeExperiment:
        pump = Pulse(amp=pump_amp, width=pump_width, edge=pump_edge, time_spread=time_spread)
        probe = Pulse(amp=probe_amp, width=probe_width, edge=probe_edge, time_spread=time_spread)
        return PumpProbeExperiment(pump=pump, probe=probe, phase_range=phase_range, samples=samples, lockin_freq=lockin_freq)

    """
    Returns a list of waveform points for a pulse. Minimum rise time, minimum pulse width, sample rate, and minimum arb length are hard coded from KeySight 33600A specs.
        pulse : reference to Pulse object 
            => width       : width of the pulse in seconds
            => rise_time   : width of rising and falling edge of pulse in seconds 
            => time_spread : period of the waveform
    """
    def create_pulse(pulse: Pulse) -> list:
        width = pulse.width
        rise_time = pulse.edge
        time_spread = pulse.time_spread

        min_rise_time = 4e-9 #
        min_width = 4e-9 #
        sample_rate = 1e9 #
        min_arb_length = 32 #
        
        rising_edge = np.linspace(0, 1, max(round(min_rise_time*sample_rate), round(rise_time*sample_rate))).tolist()
        falling_edge = list(reversed(rising_edge))
        if width > min_width:
            pulse = rising_edge + np.ones(max(round(min_width * sample_rate), round(width*sample_rate))).tolist() + falling_edge
        else:
            pulse = rising_edge + falling_edge
        
        if len(pulse) < max(min_arb_length, time_spread*sample_rate):
            padding = round(time_spread*sample_rate) - len(pulse)
            pulse = pulse + np.zeros(max(min_arb_length, padding)).tolist()

        return pulse

    """
    Runs a pump-probe experiment by sweeping the phase of one of the pulses.
        exp : PumpProbeExperiment to run
    """
    def run(self, exp:PumpProbeExperiment, repeat:bool) -> Tuple[list, list]:
        time_spread = exp.probe.time_spread
        phase_range = exp.phase_range
        sweep_channel = 2
        sample_rate = self.config.sample_rate

        if not repeat:
            # Reset both devices
            self.awg.reset()
            self.lockin.reset()
            # Create arb for each pulse
            pump_arb: list = self.create_pulse(exp.pump)
            probe_arb: list = self.create_pulse(exp.probe)
            # Send arbs to awg
            self.awg.send_arb_ch(pump_arb, exp.pump.amp.value(), self.pp.config.sample_rate, 'Pump', 1)
            self.awg.send_arb_ch(probe_arb, exp.probe.amp.value(), self.pp.config.sample_rate, 'Probe', 2)
            # Modulate channel 2 amplitude
            self.awg.modulate_ampitude(self.pp.config.lockin_freq, 2)
            # Sync channel arbs
            self.awg.sync_channels(syncFunc=True)
            # Combine channels
            self.awg.combine_channels(out=1, feed=2)

        phase_range = np.linspace(-exp.phase_range, exp.phase_range, exp.samples)

        data = list()
        dt = list()
        fig = plt.figure()
        ax = fig.add_subplot(111)
        line = ax.plot(dt, data)[0]
        plt.show()

        for i in range(len(phase_range)):
            dt.append(phase_range[i] * (time_spread / 360) * sample_rate)
            self.awg.write(f'SOURce{sweep_channel}:PHASe:ARB {phase_range[i]}').expected("AWG phase not set.")
            self.awg.wait().expected("AWG not waiting to set phase.")
            if i == 0:
                self.lockIn.send('X.'.encode()).expected("Initial buffering message not sent.")
                time.sleep(0.2)
                self.lockIn.recv(1024).expected("Initial buffering message not received.")
            time.sleep(0.01)
            self.lockIn.send('X.'.encode()).expected("Request for X value not sent to Lockin")
            X = self.lockIn.recv(1024).expected("X value not recieved from Lockin")
            if X.err == False:
                X = X.result().decode()
            X = X.split()[0]
            X = float(X)
            data.append(X)
            line.set_data(dt, data)
            ax.relim()
            ax.autoscale_view()
            # fig.canvas.draw_idle()

        # phase_range = np.linspace(-180, 180, 400)
        # for phase in phase_range:
        #     x.append(phase)
        #     y.append(np.sin(np.deg2rad(phase)))
        #     line.set_data(x, y)
        #     ax.relim()
        #     ax.autoscale_view()
        #     fig.canvas.draw_idle()
        #     fig.canvas.flush_events()

        # plt.show()
        
        return (data, dt)