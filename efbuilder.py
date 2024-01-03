from enum import Enum
import argparse
import os
import re
import xml.etree.ElementTree as ET

class Filetype(Enum):
    SCRATCHED = 0x00
    DELETED = 0x80
    SEQUENTIAL = 0x81
    PROGRAM = 0x82
    USER = 0x83
    RELATIVE = 0x84
    LOCKED_DELETED = 0xc0
    LOCKED_SEQUENTIAL = 0xc1
    LOCKED_PROGRAM = 0xc2
    LOCKED_USER = 0xc3
    LOCKED_RELATIVE = 0xc4
    UNSUPPORTED = 0x100

class EasyFlashCrt:

    def __init__(self, name):
        self.name = name
        self.banks = list()
        self.files = list()
        self.directory = bytearray()
        self.fsdata = bytearray()

    def addfile(self, file):
        self.files.append(file)

    @classmethod
    def from_manifest(cls, manifest):
        efcart = manifest.getroot()
        name = efcart.attrib['name']
        print("Cartname:", name)
        ef_crt = cls(name)

        fnboot = efcart.find('boot').attrib['filename']
        print("fnboot:", fnboot)
        with open(fnboot, 'rb') as f:
            data = f.read()
            print("bootlen:", len(data))
            if len(data) == 0x4002:
                ef_crt.boot = data[2:]
            elif len(data) == 0x4000:
                ef_crt.boot = data
            else:
                sys.exit('boot file needs to be of len 0x4000')
            ef_crt.banks.append(Bank(0x00, ef_crt.boot))

        for f in efcart.findall('EasyFS/file'):
            fname = f.attrib['filename']
            effs_name = f.attrib['name']
            fflags = f.attrib['flags']
            add_start_addr = f.attrib.get('add_start')
            if add_start_addr != None:
                add_start_addr = int(add_start_addr, 0)
            print(fname)
            with open(fname, 'rb') as f:
                data = f.read()
            print("filesize:", len(data))
            cbmfile = Cbmfile(effs_name, data, start = add_start_addr)
            ef_crt.addfile(cbmfile)

        print("Adding Rombanks")
        for f in efcart.findall('BankData/rombank'):
            fname = f.attrib['filename']
            bank = int(f.attrib['bank'],0)
            print(fname, bank)
            with open(fname, 'rb') as f:
                data = f.read()
                print("datalen:", len(data))
                if len(data) == 0x4002:
                    bankdata = data[2:]
                elif len(data) == 0x4000:
                    bankdata = data
                else:
                    sys.exit('rombank file needs to be of len 0x4000')
                ef_crt.banks.append(Bank(bank, bankdata))
     

        return ef_crt

    def export(self, filename):
        self.make_easyfs()
        bank0org = self.banks[0].data
        self.banks[0].data = bytearray(bank0org)
        self.banks[0].data[0x2000:0x2000+len(self.directory)] = self.directory

        fsbank = 1
        fsdatalen = len(self.fsdata)
        fsdataoffset = 0
        while fsdatalen > 0:
            bankdata = bytearray(self.fsdata[fsdataoffset:fsdataoffset + 0x4000])
            banklen = len(bankdata)
            self.banks.append(Bank(fsbank, bankdata.ljust(0x4000,b'\xff')))
            print("fsbank:", fsbank, "len:", banklen)
            fsdatalen -= banklen
            fsbank += 1
            fsdataoffset += 0x4000

        #sorted(self.banks, key=lambda bank: bank.bank_id)
        self.banks.sort(key=lambda bank: bank.bank_id)

        with open(filename, 'wb') as f:
            # write cartridge header
            f.write("C64 CARTRIDGE   ".encode('ascii'))
            f.write((0x40).to_bytes(4, byteorder = 'big'))
            f.write(bytearray([0x01, 0x00]))                # version 1.0 (hi, low)
            f.write((32).to_bytes(2, byteorder = 'big'))    # crt type
            f.write(bytearray([1,0]))                       # ultimax mode
            f.write(bytearray([0,0,0,0,0,0]))               # reserved
            f.write(self.name.ljust(32,chr(0))[:32].encode('ascii'))
            for bank in self.banks:
                for area in range(2):
                    print("bank:", bank.bank_id, "area:", area)
                    f.write("CHIP".encode('ascii'))                 # chip header
                    f.write((0x2010).to_bytes(4, byteorder = 'big'))# total packet length
                    f.write((2).to_bytes(2, byteorder = 'big'))     # chip type (flash)
                    f.write(bank.bank_id.to_bytes(2, byteorder = 'big')) # bank id
                    f.write((0x8000 + area*0x2000).to_bytes(2, byteorder = 'big')) # start address
                    f.write((0x2000).to_bytes(2, byteorder = 'big')) # rom image size in bytes
                    f.write(bank.data[area*0x2000:(area+1)*0x2000])
        print(self.files)
            

    def make_easyfs(self):
        fsoffset = 0
        self.directory = bytearray()
        for f in self.files:
            print("adding file: ", f.name, "@", f.address)
            fulldata = bytearray()
            if f.start != None:
                fulldata.extend(f.start.to_bytes(2, byteorder='little', signed=False))
            fulldata.extend(f.data)
            print("fsoffset", fsoffset)
            print("filesize:", len(fulldata))

            self.fsdata.extend(fulldata)
            print("EasyFS size:", len(self.fsdata))
            #self.directory.extend(f.direntry())
            #print("size dir:", len(self.directory))
            self.directory.extend(f.name.ljust(16,chr(0))[:16].encode('ascii'))
            self.directory.append(1)     # flags
            bank = fsoffset // 0x4000 + 1
            offset = fsoffset % 0x4000
            self.directory.extend(bank.to_bytes(2, byteorder='little', signed=False))
            self.directory.extend(offset.to_bytes(2, byteorder='little', signed=False))
            self.directory.extend(len(fulldata).to_bytes(3, byteorder='little', signed=False))

            print("dir:",self.directory)
            fsoffset += len(fulldata)
 

class Bank:

    def __init__(self, bank_id, data):
        self.bank_id = bank_id
        self.data = data

class Cbmfile:
    """
    This class represents a file for use with a Commodore 8 bit machine.
    It may be subclassed by specialized classes, i.e. cartridge file, disk file, tape file
    """

    def __init__(self, name = 'newfile', data = b'', filetype = Filetype.PROGRAM, start = None):
        self.name = name            #: file name
        self.data = data            #: binary file data
        self.filetype = filetype    #: file type
        self.start = start          #: start address (to be added), or None
        #self.crc = zlib.crc32(self.data) & 0xffffffff
        #self.hashid = hashlib.sha256(self.data).hexdigest()
        self.address = int.from_bytes(data[:2], byteorder='little', signed=False)

    def __str__(self):
        return self.name

    def save(self, filepath):
        with open(filepath, "wb") as f:
            f.write(self.data)

    def direntry(self):
        entry = bytearray()
        entry.extend(self.name.ljust(16,chr(0))[:16].encode('ascii'))
        entry.append(1)     # flags
        print("entry:",entry)
        return entry


def parse_arguments():
    parser = argparse.ArgumentParser(description='EasyFlash cartridge builder')
    parser.add_argument('manifest')
#    parser.add_argument('output')
    parser.add_argument('--directory', '-d', action=argparse.BooleanOptionalAction, help = "input and output are directories")
    args = parser.parse_args()
    return args


if __name__ == "__main__":
    args = parse_arguments()
    print(args)

    tree = ET.parse(args.manifest)
    print(tree)
    ef_crt = EasyFlashCrt.from_manifest(tree)
    fn_outputfile = tree.getroot().attrib['outputfile']
    print("outfile:", fn_outputfile)
    ef_crt.export(fn_outputfile)

