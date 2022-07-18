from collections import namedtuple
import time
import socket
import pyvisa
import numpy as np

Vector2 = namedtuple("Vector2", "x y")

"""
Result class to deal with error handling of device connections
"""
class Result:
    def __init__(self, msg:str, err:bool) -> None:
        self.msg = msg
        self.err = err

    def result(self):
        return self.msg

    def report(self, out: list):
        out.append(self.msg)

    """
    Reports msg to console if Result is an error
    """
    def expected(self, msg:str):
        if self.err == True:
            print(msg)
        return self
        
"""
"""
class LockIn:
    def __init__(self, ip: str, port: int):
        self.ip = ip
        self.port = port
        self.socket = None

    def connect(self) -> Result:
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.socket.connect((self.ip, self.port))
        except socket.error as e:
            self.socket = None
            return Result(msg=repr(e), err=True)
        else:
            return Result(msg="Connected", err=False)

    def send(self, msg: str) -> Result:
        if self.socket != None:
            try:
                self.socket.send(msg)
            except socket.error as e:
                return Result(msg=repr(e), err=True)
            else:
                return Result(msg=f"[{self.ip}] Sent {msg}", err=False)
    
    def recv(self, buffer: int) -> Result:
        if self.socket != None:
            try:
                result = self.socket.recv(buffer)
            except socket.error as e:
                return Result(msg=repr(e), err=True)
            else:
                return Result(msg=result, err=False)

    def reset(self) -> Result:
        result = self.socket.send('*CLS'.encode())
        time.sleep(3)
        return result

"""
Define AWG class to handle all communication with arbitrary waveform generator.
"""
class AWG:
    def __init__(self, id) -> None:
        self.id = id
        self.device : pyvisa.resources.USBInstrument = None
    
    def connect(self) -> Result:
        try:
            self.device = pyvisa.ResourceManager().open_resource(self.id)
        except ValueError as e:
            return Result(msg=repr(e), err=True)
        else:
            return Result(msg=f"[{self.id}] Connected", err=False)

    def write(self, msg:str) -> Result:
        if self.device != None:
            try:
                self.device.write(msg)
            except pyvisa.Error as e:
                return Result(msg=repr(e), err=True)
            else:
                return Result(msg=f"[{self.id}] Sent '{msg}'", err=False)

    def query(self, msg:str) -> Result:
        if self.device != None:
            try:
                result = self.device.query(msg)
            except pyvisa.Error as e:
                return Result(msg=repr(e), err=True)
            else:
                return Result(msg=result, err=False)

    def reset(self) -> Result:
        result = self.device.write('*RST')
        time.sleep(5)
        return result

    def wait(self) -> Result:
        return self.write('*WAI')

    def close(self) -> Result:
        if self.device != None:
            try:
                self.device.close()
            except pyvisa.Error as e:
                return Result(msg=repr(e), err=True)
            else:
                return Result(msg=f"[{self.id}] closed.", err=False)


    def open_channel(self, channel) -> Result:
        return self.write(f'OUTPut{channel} ON')

    def close_channel(self, channel) -> Result:
        return self.write(f'OUTPut{channel} OFF')

    """
    Sets amplitude for waveform on given channel
        amp: amplitude to set
        ch : arb channel
    """
    def set_amp(self, amp:float, ch:int, offset:int = 0):
        # Set amplitude
        msg = f'SOURce{ch}:VOLT {amp}'
        self.write(msg)

        # Set volt offset to 0
        msg = f'SOURce{ch}VOLT:OFFSET {offset}'
        self.write(msg)

    """
    Sends an arbitrary waveform to device.
        arb         : list of waveform points
        amp         : amplitude of waveform
        sample_rate : sample rate of the waveform
        name        : name of the waveform file
        channel     : channel of arbitrary waveform generator to send waveform
    """
    def send_arb_ch(self, arb:list, amp:float, sample_rate:float, name:str, channel:int) -> None:
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
        error = self.query('SYST:ERR?').result()

        if error[0:13] == '+0,"No error"':
            print('Waveform transfered without error. Instrument ready for use.')
        else:
            print('Error reported: ' + error)

    """
    Modulates the amplitude of the waveform on the specified channel of device by a square wave with frequency freq.
        freq    : modulation frequency
        channel : channel of arbitrary waveform generator to modulate
    """
    def modulate_ampitude(self, freq:float, channel:int) -> None:
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
        

    """
    Syncs all channels on device. By default, neither phase nor function data are synced.
        syncPhase : resets all phase generators on self.device
        syncFunc  : restarts arbitrary waveforms at first sample simultaneously
    """
    def sync_channels(self, syncPhase=False, syncFunc=False) -> None:
        if syncFunc:
            self.device.write('FUNC:ARB:SYNC') 
            self.device.write('*WAI')

        if syncPhase:
            self.device.write('SOURce:PHAS:SYNC') 
            self.device.write('*WAI')


    """
    Combines waveforms from two channels and feeds the result to out.
        out   : waveform on out is combined with waveform on feed and result is fed to out
        feed  : waveform on feed is used for combining but output doesn't change
    """
    def combine_channels(self, out:int, feed:int) -> None:
        self.device.write(f'SOURce{out}:COMBine:FEED CH{feed}')
        self.device.write('*WAI')



"""
Base STM class from which specific STM model classes inherit.
*** Only RHK R9 implemented ***
"""
class STM:
    def __init__(self, model:str, ip:str, port:int) -> None:
        self.model = model
        self.ip = ip
        self.port = port
        
        self._socket = None 
        self._buffer_size = 1024
        
    def connect(self) -> Result:
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self._socket.connect((self.ip, self.port))
            time.sleep(0.1)
        except socket.error as e:
            self.socket = None
            return Result(msg=repr(e), err=True)
        else:
            return Result(msg="Connected", err=True)
    
    def on_close(self) -> None:
        pass
    
    def set_bias(self) -> None:
        pass
    
    def set_position(self) -> None:
       pass 
    
    """
    Returns tip position in scan space as a vector
    """
    def get_position(self) -> Vector2:
        pass

"""
Implementation of RHK R9. Inherits from STM. 
NOTE: Not sure which variables/methods are specifc to RHK R9. Most implementation is done spefically in RHK_R9 for now.
"""
class RHK_R9(STM):
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
            
    """
    Sets STM tip control mode to tip_mode. (e.g. set_tip_control("freeze"), set_tip_control("unlimit"))
    """
    def set_tip_control(self, tip_mode:str):
        tip_mode = tip_mode.title()
        cmd = f'SetHWParameter, Z PI Controller 1, Tip Control, {tip_mode}\n'
        self._socket.send(cmd.encode())
        self._socket.recv(self._buffer_size)
        
    """
    Sets STM bias to bias
    """
    def set_bias(self, bias: float):
        cmd = f'SetSWParameter, STM Bias, Value, {bias}\n'
        self._socket.send(cmd.encode())
        self._socket.recv(self._buffer_size)
        time.sleep(3)
        try:
            self._socket.recv(self._buffer_size)
            self._socket.recv(self._buffer_size)
        except Exception as e:
            print(f"Got exception: {e}")
        
    """
    Returns the current tip position as a Vector2.
    TODO: What are the offset values relative to? The center of the scan window? global scan space?
    """
    def get_position(self) -> Vector2:
        cmd = 'GetSWParameter, Scan Area Window, X Offset'
        self._socket.send(cmd.encode())
        x_offset = self._socket.recv(self._buffer_size)
        
        cmd = 'GetSWParameter, Scan Area Window, Y Offset'
        self._socket.send(cmd.encode())
        y_offset = self._socket.recv(self._buffer_size)
        
        return Vector2(x=x_offset, y=y_offset)
