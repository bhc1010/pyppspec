import time
import socket
import pyvisa
import numpy as np

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
class LockIn():
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
        time.sleep(8)
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
