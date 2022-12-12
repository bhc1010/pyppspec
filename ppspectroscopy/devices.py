import time
import socket
import pyvisa
import numpy as np
from collections import namedtuple
import logging

Vector2 = namedtuple("Vector2", "x y")

class Result:
    """
    Result class to deal with error handling and passing logging infomation to user
    """
    def __init__(self, err:bool, val=None, msg:str = None) -> None:
        self.err = err
        self.val = val
        self.msg = msg

    def value(self):
        return self.val

    def report(self, logger:logging.Logger):
        """
        Logs msg with proper logging level
        """
        if self.err:
            logger.error(self.msg)
        if not self.err:
            logger.info(self.msg)
        
        return self

    def expected(self, new_msg:str, logger:logging.Logger):
        """
        Logs new_msg if Result is an error
        """
        if self.err:
            logger.error(new_msg)

        return self

class LockIn:
    """
    LockIn class to interface with LockIn device. LockIn commands are defined in lockin_commands dictionary. This can be changed for easily implementing different instruments.
        ip   : lockin is setup to connect via ethernet, this is its ip address
        port : port number for python socket to connect from
    """
    def __init__(self, ip: str, port: int):
        self.ip = ip
        self.port = port
        self.socket = None
        self.connected = False
        self.sensitivity_dict = {'10e-3' : 20}

    def connect(self) -> Result:
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.socket.connect((self.ip, self.port))
            self.connected = True
        except socket.error as e:
            self.socket = None
            return Result(val=e, msg=repr(e), err=True)
        else:
            return Result(val=f"Connected with IP address {self.ip} on port {self.port}", err=False)

    def send(self, msg: str) -> Result:
        if self.socket != None:
            try:
                self.socket.send(msg.encode())
            except socket.error as e:
                return Result(val=e, msg=repr(e), err=True)
            else:
                return Result(msg=f"Successfully sent '{msg}' to {self.ip}", err=False)
        else:
            return Result(msg='Lock-In socket uninitiated.', err=True)
    
    def recv(self, buffer: int) -> Result:
        if self.socket != None:
            try:
                result = self.socket.recv(buffer)
            except socket.error as e:
                return Result(val=e, msg=repr(e), err=True)
            else:
                return Result(val=result, err=False)
        else:
            return Result(msg='Lock-In socket uninitiated.', err=True)

    def reset(self) -> Result:
        result = self.send('*CLS')
        time.sleep(3)
        return result
    
    def set_sensitivity(self, sensitivity):
        if self.socket != None:
            result = self.send(f'SEN {self.senstivity_dict[sensitivity]}')  #sensitivity 10 mV
            time.sleep(0.2)
        return result
    
    def default(self, logger:logging.Logger):
        if self.socket != None:
            self.send('IE 2').expected(f"Lockin reference mode not set.", logger)  #set reference mode to external front panel
            time.sleep(0.2)
            self.send('IMODE 0').expected("Lockin current mode not set.", logger)  #current mode off-input voltage only
            time.sleep(0.2)
            self.send('VMODE 1').expected("Lockin input not set.", logger)  #A input only
            time.sleep(0.2)
            self.send('SEN 22').expected("Lockin sensitivity not set.", logger)  #sensitivity 10 mV
            time.sleep(0.2)
            self.send('ACGAIN 5').expected("Lockin gain not set.", logger)  #set gain, 6 = 36 dB. dB = 6 * n
            time.sleep(0.2)
            self.send('AUTOMATIC 0')  #set AC gain to automatic control
            self.send('AQN').expected("Lockin auto-phase not set.", logger)  #auto-phase
            time.sleep(0.2)
            self.send('TC 10')  #set filter time constant control to 20 ms
            self.send('FLOAT 1')  #'float input connector shell using 1kOhm to ground' need to read more
            time.sleep(0.1)
            self.send('LF 0').expected("Lockin line frequency rejection filter not turned off", logger)  #'turn off line frequency rejection filter
            time.sleep(0.2)

class AWG:
    """
    Handles all communication with an arbitrary waveform generator via PyVisa.
    """
    def __init__(self, id) -> None:
        self.id = id
        self.device : pyvisa.resources.USBInstrument = None
        self.connected =  False
    
    def connect(self) -> Result:
        try:
            self.device = pyvisa.ResourceManager().open_resource(self.id)
            self.connected = True
        except pyvisa.errors.VisaIOError as e:
            return Result(val=e, msg=repr(e), err=True)
        else:
            return Result(val=f"Connected with VISA device {self.id}", err=False)

    def write(self, msg:str) -> Result:
        if self.device != None:
            try:
                self.device.write(msg)
            except pyvisa.Error as e:
                return Result(val=e, msg=repr(e), err=True)
            else:
                return Result(msg=f"Successfully sent '{msg}' to {self.id}", err=False)
        else:
            return Result(msg='AWG device uninitiated.', err=True)

    def query(self, msg:str) -> Result:
        if self.device != None:
            try:
                result = self.device.query(msg)
            except pyvisa.Error as e:
                return Result(val=e, msg=repr(e), err=True)
            else:
                return Result(val=result, err=False)
        else:
            return Result(msg='AWG device uninitiated.', err=True)

    def reset(self) -> Result:
        result = self.write('*RST')
        time.sleep(5)
        return result

    def wait(self) -> Result:
        return self.write('*WAI')

    def close(self) -> Result:
        if self.device != None:
            try:
                self.device.close()
            except pyvisa.Error as e:
                return Result(val=e, msg=repr(e), err=True)
            else:
                return Result(msg=f"VISA device {self.id} closed.", err=False)
        else:
            return Result(msg='AWG device uninitiated.', err=True)

    def open_channel(self, channel) -> Result:
        return self.write(f'OUTPut{channel} ON')

    def close_channel(self, channel) -> Result:
        return self.write(f'OUTPut{channel} OFF')

    def set_amp(self, amp:float, ch:int):
        """
        Sets amplitude for waveform on given channel
            amp: amplitude to set
            ch : arb channel
        """
        # Set amplitude
        msg = f'SOURce{ch}:VOLT {amp}'
        self.write(msg)
        self.wait()

        # Set volt offset
        msg = f'SOURce{ch}VOLT:OFFSET 0'
        self.write(msg)
        self.wait()
    
    def set_phase(self, phase:float, ch:int):
        """
        Sets phase for waveform on given channel
            phase : phase to set 
            ch    : arb channel
        """
        msg = f'SOURce{ch}:PHASe:ARB {phase}'
        self.write(msg)
        self.wait()
        
    def send_arb_ch(self, arb:list, amp:float, sample_rate:float, name:str, channel:int) -> Result:
        """
        Sends an arbitrary waveform to device.
            arb         : list of waveform points
            amp         : amplitude of waveform
            sample_rate : sample rate of the waveform
            name        : name of the waveform file
            channel     : channel of arbitrary waveform generator to send waveform
        """
        # Use single precision for waveform data
        arb = np.single(arb)

        # Scale waveform to [-1, 1]
        mx = max(abs(arb))
        arb = arb/mx

        # Define source name
        sName = f'SOURce{channel}:'
        
        # Clear volatile memory
        msg = sName + 'DATA:VOLatile:CLEar' 
        self.write(msg)

        # Configure instrument to accept binary waveform data from pc (Most computers use the least-significant byte (LSB) format; SWAP sets format to LSB)
        self.write('FORMat:BORDer SWAP')

        # Send header and waveform data to instrument in binary format
        # (currently using pyvisas built-in write_binary_values function. could be causing an error but waveform seems to be loading onto AWG just fine.)
        # arbBytes = str(len(arb) * 4)
        header = sName + 'DATA:ARBitrary ' + name + f',' #{len(arbBytes)}' + arbBytes
        self.device.write_binary_values(header, arb)
        
        # Wait until waveform is fully loaded onto instrument memory
        self.write('*WAI') 

        # Set current waveform to arb
        msg = sName + 'FUNCtion:ARBitrary ' + name 
        self.write(msg)
        msg = 'MMEM:STOR:DATA1 "INT:\\' + name + '.arb"'
        self.write(msg)

        # Set sample rate
        msg = sName + 'FUNCtion:ARBitrary:SRATe ' + str(sample_rate)
        self.write(msg)

        # Turn on arb function
        msg = sName + 'FUNCtion ARB'
        self.write(msg)


        # Set amplitude (V) with zero voltage offset
        self.set_amp(amp=amp, ch=channel)

        # Query instrument for errors
        error = self.query('SYST:ERR?').value()

        if error[0:13] == '+0,"No error"':
            result = Result(msg='Waveform transfered without error', err=False)
        else:
            result = Result(msg=error, err=True)

        return result

    def modulate_ampitude(self, freq:float, channel:int) -> None:
        """
        Modulates the amplitude of the waveform on the specified channel of device by a square wave with frequency freq.
            freq    : modulation frequency
            channel : channel of arbitrary waveform generator to modulate
        """
        # Define source name
        sName = f'SOURce{channel}:'

        # Set AM deviation to 100%
        msg = sName + 'AM:DEPT 100'
        self.device.write(msg)
        self.device.write('*WAI')

        # DSSC OFF: amplitude is zero in second cycle
        msg = sName + 'AM:DSSC OFF'
        self.device.write(msg)
        self.device.write('*WAI')

        # Set to internal modulation
        msg = sName + 'AM:SOURCE INT'
        self.device.write(msg)
        self.device.write('*WAI')

        # Set internal modulation to square 
        msg = sName + 'AM:INT:FUNC SQU'
        self.device.write(msg)
        self.device.write('*WAI')

        # Set modulation frequency 
        msg = sName + f'AM:INT:FREQ {freq}'
        self.device.write(msg)
        self.device.write('*WAI')

        # Turn modulation on 
        msg = sName + 'AM:STATE ON'
        self.device.write(msg)
        self.device.write('*WAI')
        
        # Set internal modulation to square 
        msg = f'OUTP:SYNC:SOURCE CH{channel}'
        self.device.write(msg)
        self.device.write('*WAI')
        
    def sync_channels(self, syncPhase=False, syncFunc=False) -> None:
        """
        Syncs all channels on device. By default, neither phase nor function data are synced.
            syncPhase : resets all phase generators on self.device
            syncFunc  : restarts arbitrary waveforms at first sample simultaneously
        """
        if syncFunc:
            self.device.write('FUNC:ARB:SYNC') 
            self.device.write('*WAI')

        if syncPhase:
            self.device.write('SOURce:PHAS:SYNC') 
            self.device.write('*WAI')


    def combine_channels(self, out:int, feed:int) -> None:
        """
        Combines waveforms from two channels and feeds the result to out.
            out   : waveform on out is combined with waveform on feed and result is fed to out
            feed  : waveform on feed is used for combining but output doesn't change
        """
        self.device.write(f'SOURce{out}:COMBine:FEED CH{feed}')
        self.device.write('*WAI')


class STM:
    """
    Base STM class from which specific STM model classes inherit.
    """
    def __init__(self, model:str, ip:str, port:int) -> None:
        self.model = model
        self.ip = ip
        self.port = port
        self.connected = False
        
        self._socket = None 
        self._buffer_size = 1024
        
    def connect(self) -> Result:
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self._socket.connect((self.ip, self.port))
            self.connected = True
        except socket.error as e:
            self.socket = None
            return Result(val=e, msg=repr(e), err=True)
        else:
            return Result(val="Connected", err=False)
    
    def send(self, msg: str) -> Result:
        if self._socket != None:
            try:
                # self.recv(self._buffer_size)
                self._socket.send(msg.encode())
                time.sleep(0.01)
            except socket.error as e:
                return Result(val=e, msg=repr(e), err=True)
            else:
                return Result(msg=f"Succesfully sent '{msg}' to {self.ip}", err=False)
        else:
            return Result(msg='STM socket uninitiated.', err=True)

    def recv(self, buffer: int) -> Result:
        if self._socket != None:
            try:
                result = self._socket.recv(buffer)
            except socket.error as e:
                return Result(val=e, msg=repr(e), err=True)
            else:
                return Result(val=result, err=False)
        else:
            return Result(msg='STM socket uninitiated.', err=True)

    def on_close(self) -> None:
        pass
    
    def set_bias(self) -> Result:
        pass

    def get_bias(self) -> float:
        pass
    
    def set_position(self) -> Result:
       pass 
    
    def get_position(self) -> Vector2:
        """
        Returns tip position in scan space as a vector
        """
        pass

class RHK_R9(STM):
    """
    Implementation of RHK R9. Inherits from STM. 
    TODO?: make stm command dict to use only STM class. Other instruments could then be implemented by changing only the exact external commands the STM
    """
    def __init__(self, ip: str = '127.0.0.1', port:int = 12600):
        super().__init__("RHK R9", ip, port)
        self.outgoingQueue = None
        self.cancel = False
        self.courseX = 0
        self.courseY = 0

    def on_close(self):
        if self._socket is not None:
            self._socket.shutdown(2)
            self._socket.close()

    def set_bias(self, bias: float) -> Result:
        """
        Sets STM bias to bias
        """
        cmd = f'SetSWParameter, STM Bias, Value, {bias}\n'
        self.send(cmd)
        result = self.recv(self._buffer_size)

        if 'Done' in str(result.value()):
            result = Result(msg=f'STM bias set to {bias} V', err=False)
        else:
            result = Result(msg=f'Bias not set, STM returned message: {result.value()}', err=True)

        return result
            
    def set_tip_control(self, tip_mode:str):
        """
        Sets STM tip control mode to tip_mode. (e.g. set_tip_control("freeze"), set_tip_control("unlimit"))
        """
        tip_mode = tip_mode.title()
        cmd = f'SetHWParameter, Z PI Controller 1, Tip Control, {tip_mode}\n'
        self.send(cmd)
        result = self.recv(self._buffer_size)

        if 'Done' in str(result.value()):
            result = Result(msg=f'STM tip control set to {tip_mode}', err=False)
        else:
            result = Result(msg=f'Tip control not set, STM returned error: {result.value()}', err=True)

        return result
        
    def set_tip_position(self, x: float, y: float) -> None:
        """
        Set the STM tip to (x, y) in scan coordinates
        """
        results = list()

        cmd = f'SetSWParameter, Scan Area Window, Tip X in scan coordinates, {x}\n'
        self.send(cmd)
        results.append(self.recv(self._buffer_size))
        
        cmd = f'SetSWParameter, Scan Area Window, Tip Y in scan coordinates, {x}\n'
        self.send(cmd)
        results.append(self.recv(self._buffer_size))

        cmd = f'StartProcedure, Move Tip'
        self.send(cmd)
        results.append(self.recv(self._buffer_size))

        errs = []
        for result in results:
            if 'Done' not in str(result.value()):
                errs.append(True)
            else:
                errs.append(False)

        if any(errs):
            result = Result(msg=f'Tip position not set, STM returned:\n\t\t\t For x coordinate: {results[0].value()}\n\t\t\t For y coordinate: {results[1].value()}', err=True)
        else:
            result = Result(msg=f'Tip position set to {(x, y)}')
        return result

    def get_bias(self) -> Result:
        """
        Returns current STM bias
        """
        cmd = f'GetSWParameter, STM Bias, Value\n'
        self.send(cmd)
        bias = self._socket.recv(self._buffer_size)
        try:
            return Result(val=float(bias), msg=f'stm.get_bias() returned {bias}', err=False)
        except ValueError:
            return Result(val=bias, msg=f'stm.get_bias() returned {bias}', err=True)
            
    def get_tip_position(self) -> Result:
        """
        Returns the current tip position as a Vector2.
        """
        cmd = 'GetSWParameter, Scan Area Window, Tip X in scan coordinates\n'
        self.send(cmd)
        x = self.recv(self._buffer_size).value()
        
        cmd = 'GetSWParameter, Scan Area Window, Tip Y in scan coordinates\n'
        self.send(cmd)
        y = self.recv(self._buffer_size).value()
        try:
            tip_position = Vector2(x=float(x), y=float(y))
            return Result(val=tip_position, msg=f'stm.get_tip_position() return {tip_position}', err=False)
        except:
            tip_position = Vector2(x=x, y=y)
            return Result(val=tip_position, msg=f'stm.get_tip_position() return {tip_position}', err=True)
    
    # Define general methods

    def start_procedure(self, procedure_name: str):
        """
        """
        cmd = f'StartProcedure, {procedure_name}'
        self.send(cmd)
        return self.recv(self._buffer_size)

    def single_image(self, lines: int, size: float, x_offset: float, y_offset: float, scan_speed: float) -> Result:
        # Put tip in starting position
        start_pos = Vector2(x_offset + size/2, y_offset + size/2)
        self.set_tip_position(start_pos.x, start_pos.y)
        # Begin image loop#
        for line in range(lines):
            # Begin line loop #
            for pt in range(lines):
                # Take pump-probe spec
                pass
                # Move tip over to next position

            # End line loop #
            # When end of line reached, turn around and get data for reverse current
            # When one line (back and forth) is finished, move tip down 
        # End image loop #