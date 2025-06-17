#!/usr/bin/env python3 -OO

""" Initialize KinkPlaying class """
# -OO: Turn on basic optimizations.  Given twice, causes docstrings to be discarded.

import sys
import signal
import traceback
import gettext
from kink import KinkPlaying
from dialogs import error_dialog

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

_ = gettext.translation('kink-playing', fallback=True).gettext

def uncaught_excepthook(*args):
    sys.__excepthook__(*args)
    if not __debug__:
        details = '\n'.join(traceback.format_exception(*args)).replace('<', '').replace('>', '')
        title = _('Unexpected error')
        msg = _('Kink Playing has failed with the following unexpected error.' \
                'Please submit a bug report!')
        error_dialog(title, f"<b>{msg}</b>", f"<tt>{details}</tt>", None, True, 'solydxk')

    sys.exit(1)

sys.excepthook = uncaught_excepthook

def main():
    """Main function initiating KinkPlaying class"""
    KinkPlaying()
    #signal.signal(signal.SIGINT, signal.SIG_DFL)
    Gtk.main()

if __name__ == '__main__':
    main()
