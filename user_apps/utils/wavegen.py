#!/usr/bin/env python3

"""
Usage:

# 16 chans 32 bit +11.5 degrees phase offset per channel
./user_apps/utils/wavegen.py --nchan=16 --dsize=4 --phase=+11.5

# 8 chans 32 bit each channel scaled down by 0.125
./user_apps/utils/wavegen.py --nchan=8 --dsize=4 --scale=+1,-0.125

# 3 chans different wave functions on each
./user_apps/utils/wavegen.py --nchan=3 --wave=SINE:1/RAMP:2/SQUARE:3

#channels spaced apart in voltage + time
./user_apps/utils/wavegen.py --nchan=8 --dsize=2 --scale=+0.1 --voltage=10 --offset=+7:-7:-7,-2 --scale=0.05 --totallength=300000 --spos=+0,40000 --wavelength=10000

Accumulate Mode:
    +start:stop,value

Importing:

from user_apps.utils.wavegen import WaveGen

waveargs = {
    'nchan': 32,
    'wavelength': 1000,
}
waveform = WaveGen(**waveargs)
waveform.generate()
waveform.data


"""

import argparse
import numpy as np
import time
from matplotlib import pyplot as plt

class WaveGen():

    def __init__(
            self, 
            nchan=8, 
            cycles=1, 
            wavelength=20000,
            totallength=None,
            dsize=2, 
            wave='SINE:ALL', 
            phase=0, 
            scale=1,  
            crop=0, 
            spos=0,
            voltage=10,
            offset=0,
            **kwargs
        ):

        def tolist(var):
            if isinstance(var, list): return var
            return str(var).split(',')

        self.nchan = nchan
        self.cycles = cycles
        self.phase = tolist(phase)
        self.crop = tolist(crop)
        self.spos = tolist(spos)
        self.scale = tolist(scale)
        self.voltage = voltage
        self.offset = tolist(offset)

        self.wavelength = self.__init_wavelength(tolist(wavelength))
        self.totallength = totallength if totallength else self.wavelength
        self.datalength = self.totallength * nchan

        #print(f"wavelength {self.wavelength} totallength {self.totallength} datalength {self.datalength}")

        self.dtype = self.__init_dtype(dsize)
        self.wave = self.__init_wave(wave)
     
        self.filename = f"{self.nchan}CH.{self.dlen}B.{self.totallength}.{self.cycles}CYCL"

        self.ptr = {}
        self.last = {}
        self.range = {}

    def __init_wavelength(self, wavelength):
        self.wavelengths = wavelength
        return int(wavelength[0]) * self.cycles
    
    def __init_wave(self, wave):
        wave_funcs = {
            'SINE': self.__gen_sine,
            'RAMP': self.__gen_ramp,
            'SQUARE': self.__gen_square,
            'NULL': self.__gen_null,
        }
        wave_map = {}
        for value in wave.split('/'):
            selector, channels = value.split(':')
            wave_map.update({chan: wave_funcs[selector] for chan in self.get_channels(channels)})
        return wave_map

    def get_channels(self, chans):
        if chans.upper() == 'ALL': return list(range(1, self.nchan + 1))
        if chans.upper() == 'ODD': return list(range(1, self.nchan + 1, 2))
        if chans.upper() == 'EVEN': return list(range(2, self.nchan + 1, 2))
        channels = []
        for chan in chans.split(','):
            if '-' in chan:
                chan = list(map(int, chan.split('-')))
                channels.extend(list(range(chan[0], chan[1] + 1)))
                continue
            channels.append(int(chan))
        return channels

    def __init_dtype(self, dsize):
        if dsize in [2, 16]:
            dtype = np.int16
            self.dlen = 2
        elif dsize in [4, 32]:
            dtype = np.int32
            self.dlen = 4
        else:
            raise ValueError(f"dsize is invalid '{dsize}'")
        self.max_value = np.iinfo(dtype).max
        return dtype
        
    def generate(self, hush=False):

        if not hush:
            print(f"Generating {self.nchan} Chans @ {self.dlen}Bytes * {self.totallength} Samples")

        self.data = np.zeros(self.datalength, dtype=self.dtype)
        self.view = self.data.reshape(-1, self.nchan).T
        for chan in range(self.nchan):
            
            gen_wave = self.__get_wave(chan + 1)
            if not gen_wave: continue
            scale = self.__get_scale()
            wavelength = self.__get_wavelength()
            phase = self.__get_phase()
            crop = self.__get_crop()
            spos = self.__get_spos()
            offset = self.__get_offset()

            d0 = min(0 + spos, self.totallength)
            d1 = min(d0 + wavelength - crop, self.totallength)

            w0 = 0
            w1 = d1 - d0 

            if not hush:
                print(f"CH {chan + 1} {gen_wave.__name__} offset[{offset}] phase[{phase}] spos[{spos}] scale[{scale}] wavelength[{wavelength}] crop[{crop}]")

            self.data[chan::self.nchan][d0:d1] = (gen_wave(wavelength, phase) * (self.max_value * scale) ).astype(self.dtype)[w0:w1]
            self.data[chan::self.nchan] += offset

    def __get_wave(self, chan):
        if chan in self.wave:
            return self.wave[chan]
        return None
    
    def normalize(self, n):
        if n == 0: return 0
        m = n % 1
        return 1 if m == 0 else round(m, 3)
    
    def __cycler_generic(self, arr, key):
        if key not in self.ptr:
            self.ptr[key] = 0
            self.last[key] = 0

        accumulate = (str(arr[0])[0] == "+")
        value = arr[self.ptr[key] % len(arr)]
        if not accumulate:
            #normal mode
            self.ptr[key] += 1
            return float(value)
        #accumulate mode
        if key not in self.range:
            self.range[key] = (arr[0].lstrip('+').split(":") + [None])[:2]
            value = self.range[key][0]

        if value[0] == "+":
            self.ptr[key] += 1
            value = arr[self.ptr[key] % len(arr)]

        if self.range[key][1]:
            lower = float(min(self.range[key]))
            upper = float(max(self.range[key]))
            temp = float(self.last[key] + float(value))
            if temp < lower or temp >= upper:
                self.last[key] = float(self.range[key][0])
                return self.last[key]

        value = self.last[key] + float(value)
        self.ptr[key] += 1
        self.last[key] = value
        return value
    
    def __get_scale(self):
        return self.normalize(self.__cycler_generic(self.scale, "scale"))

    def __get_crop(self):
        return int(self.__cycler_generic(self.crop, "crop"))
    
    def __get_wavelength(self):
        return int(self.__cycler_generic(self.wavelengths, "wave")) * self.cycles

    def __get_phase(self):
        return np.deg2rad(self.__cycler_generic(self.phase, "phase"))
    
    def __get_spos(self):
        return int(self.__cycler_generic(self.spos, "spos"))
    
    def __get_offset(self):
        return int((self.__cycler_generic(self.offset, "offset") / self.voltage) * self.max_value)
    
    def __gen_sine(self, wavelength, phase):
        return np.sin(np.linspace(-phase, -phase + (self.cycles * 2) * np.pi, wavelength))
    
    def __gen_ramp(self, wavelength, phase):
        return np.mod(np.linspace(0, self.cycles, wavelength) + phase, 1)
    
    def __gen_square(self, wavelength, phase):
        return np.sign(self.__gen_sine(wavelength, phase))
    
    def __gen_null(self, wavelength, phase):
        return np.zeros(self.wavelength, dtype=self.dtype)
    
    def plot(self, voltage = None):
        print(f'Plotting')
        voltage = voltage if voltage != None else self.voltage
        view = (self.data.astype(np.float32) / self.max_value) * voltage

        for chan in range(self.nchan):
            plt.plot(view[chan::self.nchan], label=f"CH{chan + 1}")

        plt.title(self.filename)
        plt.xlabel("Samples")
        plt.ylabel("Voltage")
        plt.legend()
        plt.show()

    def save(self, save):
        id = int(time.time()) if save == "1" else save
        filename = f"{self.filename}.{id}.dat"
        self.data.tofile(filename)
        print(f"wave data saved to {filename}")


def run_main(args):
    wave = WaveGen(**vars(args))
    wave.generate(args.hush)

    if args.plot:
        wave.plot()

    if args.save:
        wave.save(args.save)

def comma_list(arg):
    return arg.split(',')

def get_parser():    
    parser = argparse.ArgumentParser(description="Waveform generator helper")

    parser.add_argument('--nchan', default=8, type=int, help="total channels")
    parser.add_argument('--cycles', default=1, type=int, help="cycles in waveform")
    parser.add_argument('--wavelength', default=[20000], type=comma_list, help="wavelength in samples")
    parser.add_argument('--totallength', default=None, type=int, help="total channel length override")
    parser.add_argument('--dsize', default=2, type=int, help="data size 2,16 or 4,32")
    parser.add_argument('--voltage', default=10, type=int, help="Max voltage")

    parser.add_argument('--wave', default="SINE:ALL", help="wave func and targeted channels (SINE:1,2,3,4/RAMP:5,6,7,8)")

    parser.add_argument('--scale', default=[1], type=comma_list, help="scale waveforms (-0.125 or 1,0.8,0.6)")
    parser.add_argument('--phase', default=[0], type=comma_list, help="phase value in degrees (45 or +45 or 45,90,135, 180)")
    parser.add_argument('--offset', default=[0],  type=comma_list, help="voltage offset")
    parser.add_argument('--spos', default=[0], type=comma_list, help="start position to insert waveform")
    parser.add_argument('--crop', default=[0], type=comma_list,  help="crop waveform by x samples") 

    parser.add_argument('--plot', default=1, type=int, help="Plot data")
    parser.add_argument('--save', default=None, help="Save (0: disable, 1: enabled or id string)")
    parser.add_argument('--hush', default=0, type=int, help="hush output")
    return parser

if __name__ == '__main__':
    run_main(get_parser().parse_args())

