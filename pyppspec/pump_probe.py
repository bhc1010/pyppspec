import os, time, logging
import numpy as np
from ppspectroscopy.devices import STM, LockIn, AWG, Vector2
from dataclasses import dataclass
from typing import Tuple, Callable, List
from enum import IntEnum, Enum
from datetime import datetime

class Channel(IntEnum):
    PROBE = 1
    PUMP = 2
    
class PumpProbeProcedureType(Enum):
    TIME_DELAY = 1
    AMPLITUDE = 2
    IMAGE = 3

@dataclass()
class Pulse:
    """
    Defines a mutable dataclass called Pulse to hold amplitude, width, edge, and time spread (pulse length) data for a specific pulse
    """
    amp: float
    width: float
    edge: float
    time_spread: float

@dataclass()
class PumpProbeExperiment:
    """
    Defines a mutable dataclass PumpProbeExperiment to hold pump and probe pulse data about a specific experiement.
        NOTE: Needs to be mutable so that stm_coords can be set when experiment is run and not when object is added to queue
    """
    pump: Pulse
    probe: Pulse
    domain: tuple
    samples: int
    fixed_time_delay: float = None
    stm_coords: Vector2 = Vector2(0,0)
    date: datetime = None
    
    def generate_meta(self) -> dict:
        return {'Author': os.environ.get('USERNAME'),
                'Description': f"An STM pump-probe measurement. Settings: {repr(self)}",
                'Creation Time': self.date,
                'Software': "ppspectroscopy",
                'Comment': ""}
    
    def generate_csv_head(self) -> List[str]:
        out =  []
        out.append(['[Date]', ''])
        out.append([f'{self.date}', ''])
        out.append(['[Position]' ,''])
        out.append(['x', f'{self.stm_coords.x}'])
        out.append(['y', f'{self.stm_coords.y}'])
        out.append(['[Pump]', ''])
        out.append(['amp', f'{self.pump.amp}'])
        out.append(['width',  f'{self.pump.width}'])
        out.append(['edge', f'{self.pump.edge}'])
        out.append(['[Probe]', ''])
        out.append(['amp', f'{self.probe.amp}'])
        out.append(['width',  f'{self.probe.width}'])
        out.append(['edge', f'{self.probe.edge}'])
        out.append(['[Settings]', ''])
        out.append(['domain', f'{self.domain}'])
        out.append(['samples', f'{self.samples}'])
        out.append(['fixed time delay', f'{self.fixed_time_delay}'])
        return out

@dataclass()
class PumpProbeProcedure:
    """
    Defines an mutable dataclass called Procedure to hold information about what function to run each step and what the conversion factor should be for the x-axis
    """
    proc_type: PumpProbeProcedureType
    call: Callable
    channel: Channel
    experiments: List[PumpProbeExperiment]
    conversion_factor: float
    
    def generate_domain_title(self) -> str:
        if self.proc_type == PumpProbeProcedureType.TIME_DELAY:
            domain_title = r'Time delay, $\Delta t$ (ns)'
        elif self.proc_type == PumpProbeProcedureType.AMPLITUDE:
            domain_title = f'{self.channel.name.title()} amplitude (V)'
        else:
            domain_title = ''
        return domain_title

@dataclass
class PumpProbeConfig:
    """
    Defines a mutable dataclass PumpProbeConfig to hold semi-constant (globally used for all experiments but can be mutated) pump-probe configuration data
    """
    stm_model: str
    lockin_ip: str
    lockin_port: int
    lockin_freq: float
    awg_id: str
    sample_rate: float
    save_path: str = ""

class PumpProbe():
    """
    Defines a PumpProbe class that holds references to devices, experimental settings, and runs pump-probe experiments.
    TODO: Refactor stm, lockin, and awg initialization from __init__ to class methods.
    """
    def __init__(self, stm: STM, config: PumpProbeConfig):
        super().__init__()
        self.config = config
        self.stm: STM = stm
        self.lockin: LockIn = LockIn(ip=config.lockin_ip, port=config.lockin_port)
        self.awg: AWG = AWG(id=config.awg_id)

    def create_arb(self, pulse: Pulse) -> list:
        """
        Returns a list of waveform points for a pulse. Minimum rise time, minimum pulse width, sample rate, and minimum arb length are hard coded from KeySight 33600A specs.
            pulse : reference to Pulse object 
                => width       : width of the pulse in seconds
                => rise_time   : width of rising and falling edge of pulse in seconds 
                => time_spread : period of the waveform
        """
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

    def run(self, procedure: PumpProbeProcedure, experiment_idx: int, new_arb: bool, logger:logging.Logger, plotter=None) -> Tuple[list, list]:
        """
        Runs a pump-probe experiment by sweeping the phase of one of the pulses.
            procedure      : PumpProbeProcedure currently running
            experiment_idx : index for PumpProbeExperiment to run
            new_arb        : bool to decide with new waveform information needs to be sent to AWG
            plotter        : optional ploting object to handle plotting
        """
        exp = procedure.experiments[experiment_idx]
        proc_start = exp.domain[0]
        proc_end = exp.domain[1]
        samples = exp.samples
        
        # Sending a new waveform to the AWG
        if new_arb:
            # Reset both devices
            logger.info('Resetting AWG')
            self.awg.reset()
            logger.info('Resetting Lock-In')
            self.lockin.reset()
            self.lockin.default(logger=logger)
            # Create arb for each pulse
            pump_arb: list = self.create_arb(exp.pump)
            probe_arb: list = self.create_arb(exp.probe)
            # Send arbs to awg
            logger.info('Sending new waveform to AWG')
            self.awg.send_arb_ch(arb=pump_arb, amp=exp.pump.amp, sample_rate=self.config.sample_rate, name='Pump', channel=Channel.PUMP)
            self.awg.send_arb_ch(arb=probe_arb, amp=exp.probe.amp, sample_rate=self.config.sample_rate, name='Probe', channel=Channel.PROBE)
            # Modulate channel 2 amplitude
            self.awg.modulate_ampitude(self.config.lockin_freq, channel=Channel.PROBE)
            # Combine channels
            self.awg.combine_channels(out=Channel.PROBE, feed=Channel.PUMP)
            # Sync channel arbs
            self.awg.sync_channels(syncFunc=True)
        else:
            self.awg.set_amp(exp.pump.amp, Channel.PUMP)
            self.awg.set_amp(exp.probe.amp, Channel.PROBE)

        if exp.fixed_time_delay:
            phi = (exp.fixed_time_delay + 2*exp.pump.edge + exp.pump.width) * self.config.sample_rate / 360
            self.awg.set_phase(phi, Channel.PROBE)

        proc_range = np.linspace(proc_start, proc_end, samples)
        
        data = list()
        x = list()

        # Set STM tip to freeze
        result = self.stm.set_tip_control("freeze").report(logger=logger)
        if result.err:
            return (x, data)
        
        time.sleep(1)
        
        """TODO: have bias a setting in the experiment?"""
        # Set STM bias to minimum
        prev_bias = self.stm.get_bias().value()
        bias_min = 0.01

        result = self.stm.set_bias(bias_min).report(logger=logger)
        while(result.err):
            result = self.stm.set_bias(bias_min).report(logger=logger)

        time.sleep(0.1)

        bias = self.stm.get_bias().report(logger=logger).value()
        while(type(bias) != float and bias != bias_min):
            bias = self.stm.get_bias().report(logger=logger).value()
        
        time.sleep(1) # Time delay added due to lack of understanding of STM bandwidth

        # Open channel 1 on AWG
        self.awg.open_channel(1).report(logger=logger)
        
        # For each phase in phase_range, set phase on AWG sweep channel and measure output from lockin. If a plotter object is given to
        #   PumpProbe.run() then emit the latest data.
        self.lockin.send('X.').expected("Initial buffering message not sent", logger)
        time.sleep(0.2)
        self.lockin.recv(1024).expected("Initial buffering message not received", logger)
        logger.info('Beginning pump-probe procedure')
        for spectra in range(num_spectra):
            for i in range(samples):
                # define x coordinate
                dx = proc_range[i] * procedure.conversion_factor
                x.append(dx)
                
                # Procedure done each dx
                procedure.call(proc_range[i], procedure.channel)
                time.sleep(0.01)

                # Read value from lock-in
                self.lockin.send('X.').expected("Request for X value not sent to Lockin", logger)
                y = self.lockin.recv(1024).expected("X value not recieved from Lockin", logger)
                if y.err == False:
                    y = y.value().decode()
                    y = y.split()[0]
                    y = float(y)
                else:
                    y = y.value()
                data.append(y)
                
                # If a plotter object is given (with a pyqtSignal _plot), then emit latest data
                if plotter and plotter._plot:
                    plotter._plot.emit([x[-1], data[-1]])
            if plotter:
                plotter._new_line.emit()
        
        # Close channel 1 on AWG
        self.awg.close_channel(1).report(logger=logger)
        time.sleep(1)
        
        """
        It's very important that the previous bias is set correctly before the tip control is set to unlimit, otherwise the tip may crash into the surface
        """
        result = self.stm.set_bias(prev_bias).report(logger=logger)
        while(result.err):
            result = self.stm.set_bias(prev_bias).report(logger=logger)

        time.sleep(0.1)

        bias = self.stm.get_bias().report(logger=logger).value()
        while(type(bias) != float and bias != prev_bias):
            bias = self.stm.get_bias().report(logger=logger).value()

        time.sleep(1)

        # Set tip to unlimit
        self.stm.set_tip_control("unlimit").report(logger=logger)
        time.sleep(1)
        
        return (x, data)