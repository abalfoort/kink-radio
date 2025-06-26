#!/usr/bin/env python3
""" Dialogs classes """

# Make sure the right Gtk version is loaded
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib


class Dialog(Gtk.MessageDialog):
    """Show message dialog
        Usage:
        MessageDialog(_("My Title"), "Your message here")
        Use safe=False when calling from a thread

    Args:
        Gtk (MessageDialog): inherited
    """
    def __init__(self, message_type, buttons, title, text,
                 text2=None, is_threaded=False):

        # Search for parent window
        parent = next((w for w in Gtk.Window.list_toplevels() if w.get_title()), None)

        # Initialize the dialog object
        super().__init__(transient_for=parent,
                         message_type=message_type,
                         buttons=buttons,
                         text=text)

        # Set position
        self.set_position(Gtk.WindowPosition.CENTER)
        # Set title (window title)
        self.set_title(title)
        # Set icon
        if parent:
            self.set_icon(parent.get_icon())
        # Set secondary text - sets text to text title (bold)
        if text2:
            self.format_secondary_markup(text2)

        self.is_threaded = is_threaded
        self.has_parent = bool(parent)

        # Connect the response action when running in a threaded process
        if self.is_threaded:
            self.connect('response', self._handle_clicked)

    def _handle_clicked(self, *args):
        self.destroy()

    def show_dialog(self):
        """ Show the dialog """
        if not self.is_threaded:
            return self._do_show_dialog()
        # Use GLib to show the dialog when called from a threaded process
        return GLib.timeout_add(0, self._do_show_dialog)

    def _do_show_dialog(self):
        """ Show the dialog.
            Returns True if user response was confirmatory.
        """
        response = self.run() in (Gtk.ResponseType.YES,
                                  Gtk.ResponseType.APPLY,
                                  Gtk.ResponseType.OK,
                                  Gtk.ResponseType.ACCEPT)
        self.destroy()

        return response if not self.is_threaded else False


def message_dialog(*args, **kwargs):
    """ Show message dialog """
    return Dialog(Gtk.MessageType.INFO, Gtk.ButtonsType.OK, *args, **kwargs).show_dialog()


def question_dialog(*args, **kwargs):
    """ Show question dialog """
    return Dialog(Gtk.MessageType.QUESTION, Gtk.ButtonsType.YES_NO, *args, **kwargs).show_dialog()


def warning_dialog(*args, **kwargs):
    """ Show warning dialog """
    return Dialog(Gtk.MessageType.WARNING, Gtk.ButtonsType.OK, *args, **kwargs).show_dialog()


def error_dialog(*args, **kwargs):
    """ Show error dialog """
    return Dialog(Gtk.MessageType.ERROR, Gtk.ButtonsType.OK, *args, **kwargs).show_dialog()
