#!/usr/local/bin/python2.7

####
## ublox startup configuration
## ---------------------------
## Jorge Schrauwen 2019
##
## FreeBSD package required:
## - py27-serial
####

## import
# NOTE: standard libraries
import os
import sys
import struct
import shlex
import subprocess
from time import sleep

# NOTE: local libraries
sys.path.append(os.path.join(os.path.dirname(__file__), 'lib'))
import ublox
from ublox import UBlox, UBloxMessage

## methodes
def simple_exec(cmd, shell=False):
    """Execute command and return True or False"""
    if not isinstance(cmd, list):
        cmd = shlex.split(cmd)

    devnull = open(os.devnull, "w")
    popen = subprocess.Popen(
        cmd, stdout=devnull, stderr=devnull, shell=shell, universal_newlines=True
    )

    return popen.wait() == 0

def _get_config(gps, cls, msg, payload=''):
    cfg_tries = 0
    gps.configure_poll(cls, msg, payload)
    while cfg_tries <= 25:
        cfg_tries += 1
        cfg_msg = gps.receive_message_noerror()
        if cfg_msg and cfg_msg.msg_type() == (cls, msg):
            return cfg_msg
        elif cfg_msg.msg_type() == (ublox.CLASS_ACK, ublox.MSG_ACK_NACK):
            return None

    return None

def _set_config(gps, cfg, verify=True):
    res_tries = 0
    gps.send(cfg)
    while res_tries <= 25:
        res_tries += 1
        res = gps.receive_message_noerror()
        res.unpack()
        if res:
            res.unpack()
            if res.msg_type() == (ublox.CLASS_ACK, ublox.MSG_ACK_ACK):
                cfg_class, cfg_msg = cfg.msg_type()
                if (cfg_class, cfg_msg) != (ublox.CLASS_CFG, ublox.MSG_CFG_MSG):
                    # NOTE: UBX-CFG-*
                    cfg_new = _get_config(gps, cfg_class, cfg_msg)
                else:
                    # NOTE: UBX-CFG-MSG is special
                    cfg_new = _get_config(gps, cfg_class, cfg_msg, struct.pack('<BB', 0xf0, cfg.msgId))
                cfg_new.unpack()
                return str(cfg) == str(cfg_new)
            elif res and res.msg_type() == (ublox.CLASS_ACK, ublox.MSG_ACK_NACK):
                return False

    return False

## main
if __name__ == '__main__':
    if simple_exec("/etc/rc.d/ntpd status"):
        sys.stdout.write("[>>] Stopping NTPd ...")
        res_stop = simple_exec("/etc/rc.d/ntpd stop")
        sys.stdout.write("\r[OK]\n" if res_stop else "\r[!!]\n")

    # NOTE: symlink to make ntpd happy
    devfs_cfg = "/etc/devfs.conf"
    dev_mapping = [
        ("pps0", "gpiopps0", None),
        ("gps0", "cuau0", 9600),
        ("gps1", "cuaU0", 4800),
    ]
    for dst, src, baudrate in dev_mapping:
        sys.stdout.write("[>>] Configuring devfs for {} ...".format(dst))

        dev_setup = False
        if os.path.exists(os.path.join("/dev", dst)):
            dev_setup = True
        elif os.path.exists(os.path.join("/dev", src)):
            with open(devfs_cfg, "r") as devfs_fd:
                for line in devfs_fd:
                    line = line.strip()
                    if line.startswith("link") or line.startswith("#link"):
                        (link, link_src, link_dst) = line.split("\t")
                        if link_dst == dst:
                            dev_setup = True
                            break
            if not dev_setup:
                with open(devfs_cfg, "a") as devfs_fd:
                    devfs_fd.write("link\t{}\t{}\n".format(src, dst))
                dev_setup = simple_exec("/etc/rc.d/devfs restart")

        sys.stdout.write("\r[OK]\n" if dev_setup else "\r[!!]\n")

        # NOTE: skip non gpsX devices
        if not dst.startswith("gps"):
            continue

        # NOTE: connect to gps
        gps = UBlox(os.path.join("/dev", dst), baudrate=baudrate, timeout=1)

        # NOTE: read hwVersion
        hwver = _get_config(gps, ublox.CLASS_MON, ublox.MSG_MON_VER)
        hwver.unpack()
        hwver = int(hwver.hwVersion[3])
        sys.stdout.write("[II] {} is running hwVersion {}\n".format(dst, hwver))

        # NOTE: configure PMS
        if hwver >= 8:
            sys.stdout.write("[>>] Configuring PMS for {} ...".format(dst))
            cfg_pms = _get_config(gps, ublox.CLASS_CFG, ublox.MSG_CFG_PMS)
            if cfg_pms:
                cfg_pms.unpack()
                cfg_pms.powerSetupValue = ublox.POWER_FULL
                cfg_pms.pack()
                res_pms = _set_config(gps, cfg_pms)
            sys.stdout.write("\r[OK]\n" if cfg_pms and res_pms else "\r[!!]\n")

        # NOTE: configure NAV5
        sys.stdout.write("[>>] Configuring NAV5 for {} ...".format(dst))
        cfg_nav5 = _get_config(gps, ublox.CLASS_CFG, ublox.MSG_CFG_NAV5)
        if cfg_nav5:
            cfg_nav5.unpack()
            cfg_nav5.dynModel = ublox.DYNAMIC_MODEL_STATIONARY
            cfg_nav5.pack()
            res_nav5 = _set_config(gps, cfg_nav5)
        sys.stdout.write("\r[OK]\n" if cfg_nav5 and res_nav5 else "\r[!!]\n")
        gps.set_preferred_dynamic_model(ublox.DYNAMIC_MODEL_STATIONARY)

        # NOTE: configure SBAS
        sys.stdout.write("[>>] Configuring SBAS for {} ...".format(dst))
        cfg_sbas = _get_config(gps, ublox.CLASS_CFG, ublox.MSG_CFG_SBAS)
        if cfg_sbas:
            cfg_sbas.unpack()
            cfg_sbas.mode = 1
            cfg_sbas.usage = 6
            cfg_sbas.maxSBAS = 3
            cfg_sbas.scanmode1 = 2129
            cfg_sbas.scanmode2 = 0
            cfg_sbas.pack()
            res_sbas = _set_config(gps, cfg_sbas)
        sys.stdout.write("\r[OK]\n" if cfg_sbas and res_sbas else "\r[!!]\n")

        # NOTE: configure GNSS
        if hwver >= 8:
            sys.stdout.write("[>>] Configuring GNSS for {} ...".format(dst))
            cfg_gnss = _get_config(gps, ublox.CLASS_CFG, ublox.MSG_CFG_GNSS)
            if cfg_gnss:
                cfg_gnss.unpack()
                cfg_gnss.flags0 = 16842753 # NOTE: enable GPS
                cfg_gnss.flags1 = 16842753 # NOTE: enable SBAS
                cfg_gnss.flags2 = 16842753 # NOTE: enable Galileo
                cfg_gnss.flags3 = 16842752 # NOTE: disable BeiDou
                cfg_gnss.flags4 = 50397184 # NOTE: disable IMES
                cfg_gnss.flags5 = 83951616 # NOTE: disable QZSS
                cfg_gnss.flags6 = 16842753 # NOTE: enable GLONAS
                cfg_gnss.pack()
                res_gnss = _set_config(gps, cfg_gnss)
            sys.stdout.write("\r[OK]\n" if cfg_gnss and res_gnss else "\r[!!]\n")

        # NOTE: configure TP5
        #sys.stdout.write("[>>] Configuring TP5 for {} ...".format(dst))
        #cfg_tp5 = _get_config(gps, ublox.CLASS_CFG, ublox.MSG_CFG_TP5)
        #if cfg_tp5:
        #    cfg_tp5.unpack()
        #    cfg_tp5.freqPeriod = 1
        #    cfg_tp5.freqPeriodLock = 1
        #    cfg_tp5.flags = 127
        #    cfg_tp5.pack()
        #    res_tp5 = _set_config(gps, cfg_tp5)
        #sys.stdout.write("\r[OK]\n" if cfg_tp5 and res_tp5 else "\r[!!]\n")

        # NOTE: configure MSG
        cfg_nmea_opts = [
            ("NMEA_GGA", [1, 1, 0, 1, 1, 0]),
            ("NMEA_ZDA", [1, 1, 0, 1, 1, 0]),
            ("NMEA_GLL", [0, 0, 0, 0, 0, 0]),
            ("NMEA_GSA", [1, 0, 0, 0, 0, 0]),
            ("NMEA_GSV", [0, 0, 0, 0, 0, 0]),
            ("NMEA_RMC", [0, 0, 0, 0, 0, 0]),
            ("NMEA_VTG", [0, 0, 0, 0, 0, 0]),
            ("NMEA_GRS", [0, 0, 0, 0, 0, 0]),
            ("NMEA_GST", [0, 0, 0, 0, 0, 0]),
            ("NMEA_GBS", [0, 0, 0, 0, 0, 0]),
            ("NMEA_DTM", [0, 0, 0, 0, 0, 0]),
        ]
        cfg_nmea_opts.extend([
            ("NMEA_GNS", [1, 0, 0, 0, 0, 0]),
            ("NMEA_VLW", [0, 0, 0, 0, 0, 0]),
        ] if hwver >= 8 else [])
        cfg_nmea = _get_config(gps, ublox.CLASS_CFG, ublox.MSG_CFG_MSG,
                               struct.pack('<BB', 0xf0, ublox.MSG_CFG_MSG_NMEA_GGA))
        for (msgId, rates) in cfg_nmea_opts:
            sys.stdout.write("[>>] Configuring MSG_{} for {} ...".format(msgId, dst))
            cfg_nmea.unpack()
            cfg_nmea.msgId = eval("ublox.MSG_CFG_MSG_{}".format(msgId))
            cfg_nmea.rates = rates
            cfg_nmea.pack()
            res_nmea = _set_config(gps, cfg_nmea)
            sys.stdout.write("\r[OK]\n" if cfg_nmea and res_nmea else "\r[!!]\n")

        # NOTE: disconnect
        gps.close()

    # NOTE: start NTPd
    sys.stdout.write("[>>] Starting NTPd ...")
    res_start = simple_exec("/etc/rc.d/ntpd start")
    sys.stdout.write("\r[OK]\n" if res_start else "\r[!!]\n")
