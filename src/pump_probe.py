import os, time
import numpy as np
from devices import STM, LockIn, AWG, Vector2
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
Defines an mutable dataclass PumpProbeExperiment to hold pump and probe pulse data about a specific experiement.
    NOTE: Needs to be mutable so that stm_coords can be set when experiment is run and not when object is added to queue
"""
@dataclass()
class PumpProbeExperiment:
    pump: Pulse
    probe: Pulse
    phase_range: float
    samples: int
    lockin_freq: int
    stm_coords: Vector2 = Vector2(0,0)
    name: str = ""
    
    def generate_meta(self):
        return {'Title': self.name,
                'Author': os.environ.get('USERNAME'),
                'Description': f"An STM pump-probe measurement. Settings: {repr(self)}",
                'Creation Time': self.name,
                'Software': "ppspectroscopy",
                'Comment': ""}
    
    def generate_toml(self) -> str:
        out =  f"[Date]\n{self.name}\n"
        out += f"[Position]\nx: {self.stm_coords.x}\ny: {self.stm_coords.y}\n"
        out += f"[Pump]\namp: {self.pump.amp}\nwidth: {self.pump.width}\nedge: {self.pump.edge}\n"
        out += f"[Probe]\namp: {self.probe.amp}\nwidth: {self.probe.width}\nedge: {self.probe.edge}\n"
        out += f"[Settings]\npulse length: {self.probe.time_spread}\nsamples: {self.samples}\nlock-in freq: {self.lockin_freq}\n"
        return out
    
"""
Defines a mutable dataclass PumpProbeConfig to hold semi-constant (globally used for all experiments but can be mutated) pump-probe configuration data
"""
@dataclass
class PumpProbeConfig:
    stm_model: str
    lockin_ip: str
    lockin_port: int
    awg_id: str
    sample_rate: float
    save_path: str = ""

"""
Defines a PumpProbe class that connects and holds references to devices, experimental settings, and runs pump-probe experiments.
"""
class PumpProbe():
    def __init__(self, config:PumpProbeConfig = None):
        super().__init__()
        self.config = config
        self.stm: STM = None
        self.lockin: LockIn = None
        self.awg: AWG = None

    def create_experiment(self, time_spread: float, pump_amp: float, pump_width:float, pump_edge:float, probe_amp:float, probe_width:float, probe_edge:float, 
                        phase_range:float, samples:int, lockin_freq:int) -> PumpProbeExperiment:
        pump = Pulse(amp=pump_amp, width=pump_width, edge=pump_edge, time_spread=time_spread)
        probe = Pulse(amp=probe_amp, width=probe_width, edge=probe_edge, time_spread=time_spread)
        coords = self.stm.get_position()
        return PumpProbeExperiment(pump=pump, probe=probe, phase_range=phase_range, samples=samples, lockin_freq=lockin_freq, stm_coords=coords)

    """
    Returns a list of waveform points for a pulse. Minimum rise time, minimum pulse width, sample rate, and minimum arb length are hard coded from KeySight 33600A specs.
        pulse : reference to Pulse object 
            => width       : width of the pulse in seconds
            => rise_time   : width of rising and falling edge of pulse in seconds 
            => time_spread : period of the waveform
    """
    def create_arb(self, pulse: Pulse) -> list:
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
    def run(self, exp:PumpProbeExperiment, new_arb:bool, plotter=None) -> Tuple[list, list]:
        time_spread = exp.probe.time_spread
        phase_range = exp.phase_range
        sweep_channel = 1
        sample_rate = self.config.sample_rate

        if new_arb:
            # Reset both devices
            self.awg.reset()
            self.lockin.reset()
            self.lockin.default()
            # Create arb for each pulse
            pump_arb: list = self.create_arb(exp.pump)
            probe_arb: list = self.create_arb(exp.probe)
            # Send arbs to awg
            self.awg.send_arb_ch(pump_arb, exp.pump.amp, self.config.sample_rate, 'Pump', 1)
            self.awg.send_arb_ch(probe_arb, exp.probe.amp, self.config.sample_rate, 'Probe', 2)
            # Modulate channel 2 amplitude
            self.awg.modulate_ampitude(exp.lockin_freq, 2)
            # Combine channels
            self.awg.combine_channels(out=1, feed=2)
            # Sync channel arbs
            self.awg.sync_channels(syncFunc=True)
        else:
            self.awg.set_amp(exp.pump.amp, 1)
            self.awg.set_amp(exp.probe.amp, 2)

        phase_range = np.linspace(-exp.phase_range, exp.phase_range, exp.samples)

        data = list()
        dt = list()

        # Set STM tip to freeze
        self.stm.set_tip_control("freeze")
        time.sleep(1)
        
        """TODO: have bias a setting in the experiment?"""
        # Set STM bias to minimum
        prev_bias = self.stm.get_bias()
        self.stm.set_bias(0.01)
        time.sleep(1) # Time delay added due to lack of understanding of STM bandwidth

        # Open channel 1 on AWG
        self.awg.open_channel(1)
        
        # For each phase in phase_range, set phase on AWG sweep channel and measure output from lockin. If a plotter object is given to
        #   PumpProbe.run() then emit the latest data.
        for i in range(len(phase_range)):
            t = phase_range[i] * (time_spread / 360)
            offset = 2 * exp.pump.edge + exp.pump.width
            dt.append((t - offset) * sample_rate)
            self.awg.write(f'SOURce{sweep_channel}:PHASe:ARB {phase_range[i]}').expected("AWG phase not set.")
            self.awg.wait().expected("AWG not waiting to set phase.")
            if i == 0:
                self.lockin.send('X.'.encode()).expected("Initial buffering message not sent.")
                time.sleep(0.2)
                self.lockin.recv(1024).expected("Initial buffering message not received.")
            time.sleep(0.01)
            self.lockin.send('X.'.encode()).expected("Request for X value not sent to Lockin")
            X = self.lockin.recv(1024).expected("X value not recieved from Lockin")
            if X.err == False:
                X = X.result().decode()
            X = X.split()[0]
            X = float(X)
            data.append(X)
            # If a plotter object is given (with a pyqtSignal _plot), then emit latest data
            if plotter and plotter._plot:
                plotter._plot.emit([dt[-1], data[-1]])
        
        # Close channel 1 on AWG
        self.awg.close_channel(1)
        time.sleep(1)
        
        # Set bias to default
        self.stm.set_bias(prev_bias)
        
        # Set tip to unlimit
        # NOTE: Commenting out so that the tip height is constant across runs. Tip must be manually put back into unlimit mode
        # time.sleep(1)
        # self.stm.set_tip_control("unlimit")
        
        return (dt, data)